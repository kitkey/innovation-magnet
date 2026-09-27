"""Очки сессий и рейтинг для лидерборда и кабинета организации.

Очко сессии = средняя оценка судьи по осям метода × множитель сложности + бонус за соглашение в целевой зоне.
Рейтинг пользователя = среднее по его лучшим TOP_N сессиям за период: сессии разной сложности сравниваются через множитель,
а число попыток не даёт преимущества само по себе.
"""
from datetime import datetime, timedelta, timezone

from .config import settings
from .db import SessionRow
from .engine import offline
from .schemas import MoveAnalysis, ScenarioCard

DIFFICULTY_MULT = {"easy": 0.8, "medium": 1.0, "hard": 1.25}
ZONE_BONUS = 10
TOP_N = 5
PERIODS = {"week": timedelta(days=7), "month": timedelta(days=30), "all": None}


def session_score(axes: dict[str, int] | None, difficulty: str, outcome: str | None) -> float | None:
    if not axes:
        return None
    base = sum(axes.values()) / len(axes)
    return round(base * DIFFICULTY_MULT[difficulty] + (ZONE_BONUS if outcome == "agreement_in_zone" else 0), 1)


def user_rating(scores: list[float]) -> float | None:
    best = sorted(scores, reverse=True)[:TOP_N]
    return round(sum(best) / len(best), 1) if best else None


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def since(period: str) -> datetime | None:
    delta = PERIODS[period]
    return datetime.now(timezone.utc) - delta if delta else None


def in_period(row: SessionRow, start: datetime | None) -> bool:
    return start is None or aware(row.created_at) >= start


def judge_axes(row: SessionRow) -> dict[str, int] | None:
    """Оценки судьи: сохранённые от LLM или разбор по правилам при тех же условиях, что и на экране результата."""
    if row.judge:
        return row.judge["axes"]
    user_turns = [t for t in row.turns if t.role == "user"]
    if row.status != "finished" or not user_turns:
        return None
    early_end = row.outcome in ("agreement_in_zone", "agreement_out_of_zone", "breakdown")
    if len(user_turns) < settings.incomplete_session_min_turns and not early_end:
        return None
    card = ScenarioCard(**row.card)
    return offline.judge_offline(card, [(t.text, MoveAnalysis(**t.analysis)) for t in user_turns]).axes


def duration_seconds(row: SessionRow) -> float:
    if len(row.turns) < 2:
        return 0.0
    return max(0.0, (aware(row.turns[-1].created_at) - aware(row.turns[0].created_at)).total_seconds())


def score_of(row: SessionRow) -> float | None:
    return session_score(judge_axes(row), row.card.get("difficulty", "medium"), row.outcome)


def member_stats(rows: list[SessionRow]) -> dict:
    axes_sum: dict[str, list[int]] = {}
    finished = [r for r in rows if r.status == "finished"]
    for r in rows:
        for k, v in (judge_axes(r) or {}).items():
            axes_sum.setdefault(k, []).append(v)
    scores = [s for s in map(score_of, rows) if s is not None]
    return {
        "sessions": len(rows),
        "training_minutes": round(sum(map(duration_seconds, rows)) / 60, 1),
        "axes": {k: round(sum(v) / len(v), 1) for k, v in axes_sum.items()},
        "in_zone_share": round(sum(r.outcome == "agreement_in_zone" for r in finished) / len(finished), 2) if finished else None,
        "rating": user_rating(scores),
    }
