"""Сессия переговоров: ход пользователя → разметка → счётчики → ответ собеседника → исход; разбор после диалога."""
import logging
import re
import threading
from contextlib import contextmanager
from difflib import SequenceMatcher
from uuid import uuid4

from . import llm, voice
from .config import settings
from .db import SessionRow, TurnRow
from .engine import offline, rules
from .schemas import JudgeReport, MoveAnalysis, OpponentState, ScenarioCard, SessionResult, TurnOut

log = logging.getLogger(__name__)

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class SessionClosed(Exception):
    pass


@contextmanager
def lock(session_id: str):
    """Один ход или завершение сессии за раз: параллельные запросы к одной сессии выстраиваются в очередь."""
    with _locks_guard:
        lk = _locks.setdefault(session_id, threading.Lock())
    with lk:
        yield


def _history(row: SessionRow) -> list[dict]:
    return [{"role": "user" if t.role == "user" else "assistant", "content": t.text} for t in row.turns]


def _use_llm() -> bool:
    return not settings.offline_mode


def _template_opening(card: ScenarioCard) -> str:
    """Запасная первая реплика: без должности собеседника, с темой и стартовой позицией."""
    z = card.target_zone
    topic = card.topic.strip().rstrip(".")
    lead = f"Давайте обсудим: {topic[:1].lower()}{topic[1:]}." if topic else "Давайте к делу."
    pos = z.fmt(z.opponent_start).rstrip(".")
    what = f"{z.subject[:1].upper()}{z.subject[1:]} — я исхожу из {pos}." if z.subject else f"Я исхожу из {pos}."
    return f"{lead} {what} Что скажете?"


def opening_ok(card: ScenarioCard, text: str) -> bool:
    """Первая реплика называет стартовую позицию собеседника и не обещает больше неё."""
    z = card.target_zone
    found = offline.values(card, text)
    if any(rules.better_for_user(card, v, z.opponent_start) for v in found):
        return False
    return z.opponent_start == 0 or any(abs(v - z.opponent_start) < 1e-9 for v in found)


def _opening(card: ScenarioCard) -> str:
    """Первая реплика: из карточки; иначе одна реплика LLM в образе; иначе шаблон."""
    if card.opening.strip():
        return card.opening.strip()
    if _use_llm():
        try:
            text = llm.opening_line(card)
            if text and opening_ok(card, text):
                return text
            log.warning("opening_line rejected: %s", text)
        except Exception as exc:
            log.warning("opening_line fallback: %s", exc)
    return _template_opening(card)


def start(db, scenario_id: str, card: ScenarioCard, user_id: str | None = None) -> SessionRow:
    state = rules.initial_state(card)
    row = SessionRow(id=uuid4().hex, scenario_id=scenario_id, card=card.model_dump(), state=state.model_dump(), user_id=user_id)
    row.turns.append(TurnRow(role="opponent", text=_opening(card)))
    db.add(row)
    db.commit()
    return row


def _guard_reply(card: ScenarioCard, state: OpponentState, reply: str, message: str = "") -> bool:
    """Собеседник не может назвать значение лучше для пользователя, чем его текущая позиция: уступки решают правила.
    Число из реплики пользователя собеседник может повторить, чтобы отказаться от него, если тут же называет свою позицию."""
    found = offline.values(card, reply)
    echoed = set(offline.values(card, message)) if any(abs(v - state.position) < 1e-9 for v in found) else set()
    return not any(rules.better_for_user(card, v, state.position) and v not in echoed for v in found)


def turn(db, row: SessionRow, message: str, audio_url: str | None = None) -> TurnOut:
    if row.status != "active":
        raise SessionClosed
    card = ScenarioCard(**row.card)
    state = OpponentState(**row.state)
    history = _history(row)

    move: MoveAnalysis
    if _use_llm():
        try:
            move = llm.analyze_move(card, history, message)
            move.mentioned_details = [d for d in move.mentioned_details if d in card.mandatory_details]
            if move.proposed_value is not None and not rules.is_plausible(card, move.proposed_value):
                move.proposed_value = None
        except Exception as exc:  # LLM недоступна: переходим на правила, демо не ломается
            log.warning("analyze_move fallback: %s", exc)
            move = offline.analyze(card, message)
    else:
        move = offline.analyze(card, message)

    state, conceded = rules.apply_move(card, state, move)
    row.turn += 1
    outcome, value = rules.decide_outcome(card, state, move, row.turn)

    if outcome in ("agreement_in_zone", "agreement_out_of_zone"):
        reply = f"Договорились: {card.target_zone.fmt(value)}. Фиксируем."
    elif outcome == "walk_away":
        reply = "Понимаю. На этих условиях договориться не получается, расходимся без соглашения."
    elif outcome == "breakdown":
        reply = "В таком тоне я разговор продолжать не готов. На этом закончим."
    elif outcome == "turn_limit":
        reply = "Время вышло, к соглашению мы не пришли."
    elif _use_llm():
        try:
            reply = llm.opponent_reply(card, state, move, conceded, history, message)
            if not _guard_reply(card, state, reply, message):
                log.warning("opponent_reply named a value past position %s: %s", state.position, reply)
                reply = offline.reply(card, state, move, conceded)
        except Exception as exc:
            log.warning("opponent_reply fallback: %s", exc)
            reply = offline.reply(card, state, move, conceded)
    else:
        reply = offline.reply(card, state, move, conceded)

    row.turns.append(TurnRow(role="user", text=message, analysis=move.model_dump(), audio_url=audio_url))
    row.turns.append(TurnRow(role="opponent", text=reply))
    row.state = state.model_dump()
    if outcome:
        row.status, row.outcome, row.agreed_value = "finished", outcome, value
    db.commit()
    return TurnOut(turn=row.turn, opponent_message=reply, status=row.status, outcome=outcome, analysis=move, state=state, mood=voice.mood_for(card, state, outcome))


def finish(db, row: SessionRow) -> None:
    if row.status == "active":
        row.status, row.outcome = "finished", "user_finished"
        db.commit()


def rewind(db, row: SessionRow, keep: int) -> SessionRow:
    """Новая сессия того же сценария с первыми keep ходами; состояние пересчитывается правилами по сохранённой разметке, без LLM."""
    card = ScenarioCard(**row.card)
    pairs, turns = [], row.turns[1:]
    for i, t in enumerate(turns):
        if t.role == "user":
            pairs.append((t, turns[i + 1] if i + 1 < len(turns) else None))
    if keep > len(pairs):
        raise ValueError(f"В сессии только {len(pairs)} ходов")
    if keep == len(pairs) and row.outcome not in (None, "user_finished"):
        raise ValueError("Этот ход завершил переговоры, переиграйте с более раннего")
    state = rules.initial_state(card)
    new = SessionRow(id=uuid4().hex, scenario_id=row.scenario_id, card=row.card, state=state.model_dump(), turn=keep, user_id=row.user_id)
    new.turns.append(TurnRow(role="opponent", text=row.turns[0].text))
    for user, opp in pairs[:keep]:
        state, _ = rules.apply_move(card, state, MoveAnalysis(**user.analysis))
        new.turns.append(TurnRow(role="user", text=user.text, analysis=user.analysis, audio_url=user.audio_url))
        if opp is not None:
            new.turns.append(TurnRow(role="opponent", text=opp.text))
    new.state = state.model_dump()
    db.add(new)
    db.commit()
    return new


def view(row: SessionRow) -> dict:
    card = ScenarioCard(**row.card)
    diff = rules.DIFFICULTY[card.difficulty]
    return {
        "id": row.id, "scenario_id": row.scenario_id, "card": row.card, "status": row.status, "outcome": row.outcome,
        "turn": row.turn, "max_turns": card.max_turns, "state": row.state, "mood": voice.mood_for(card, OpponentState(**row.state), row.outcome),
        "thresholds": {"concede": diff["concede_threshold"], "breakdown_irritation": diff["breakdown_irritation"], "breakdown_trust": -6},
        "messages": [{"role": t.role, "text": t.text, "labels": (t.analysis or {}).get("labels", []), "audio_url": t.audio_url} for t in row.turns],
    }


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower().replace("ё", "е"))).strip()


def quote_found(quote: str, texts: list[str]) -> bool:
    q = _norm(quote)
    if len(q) < 3:
        return False
    for t in map(_norm, texts):
        if q in t:
            return True
        m = SequenceMatcher(None, q, t, autojunk=False).find_longest_match(0, len(q), 0, len(t))
        if m.size >= 0.8 * len(q):
            return True
    return False


def sanitize_judge(card: ScenarioCard, report: JudgeReport, user_texts: list[str], fallback: JudgeReport) -> JudgeReport:
    """Оси строго из метода, выдуманные цитаты выкидываем; если не осталось ни одного момента, берём моменты правил."""
    axes = {a: report.axes.get(a, fallback.axes[a]) for a in rules.METHOD_AXES[card.method]}
    moments = [m for m in report.key_moments if quote_found(m.quote, user_texts)] or fallback.key_moments
    return JudgeReport(axes=axes, key_moments=moments[:3], next_scenario_hint=report.next_scenario_hint or fallback.next_scenario_hint)


def walk_away_verdict(card: ScenarioCard, position: float) -> tuple[bool, str]:
    """Верно ли пользователь вышел к альтернативе: позиция собеседника на момент выхода против худшего края целевой зоны."""
    fmt, edge = card.target_zone.fmt, rules.zone_boundary(card)
    if rules.walk_away_justified(card, position):
        return True, (f"Верное решение: собеседник стоял на {fmt(position)}, это хуже границы целевой зоны ({fmt(edge)}), "
                      f"выгодной сделки не было и альтернатива лучше: {card.user_batna}.")
    return False, (f"Выход преждевременный: собеседник уже стоял на {fmt(position)}, это не хуже границы целевой зоны "
                   f"({fmt(edge)}), сделка была не хуже вашей альтернативы.")


def result(db, row: SessionRow) -> SessionResult:
    card = ScenarioCard(**row.card)
    user_turns = [t for t in row.turns if t.role == "user"]
    incomplete = len(user_turns) < settings.incomplete_session_min_turns
    covered = sorted({d for t in user_turns for d in (t.analysis or {}).get("mentioned_details", []) if d in card.mandatory_details})
    missed = [d for d in card.mandatory_details if d not in covered]
    z = card.target_zone
    in_zone = shift = None
    if row.agreed_value is not None:
        in_zone = z.zone_min <= row.agreed_value <= z.zone_max
        shift = row.agreed_value - z.user_start

    justified = note = None
    if row.outcome == "walk_away":
        justified, note = walk_away_verdict(card, OpponentState(**row.state).position)

    judge, source = (JudgeReport(**row.judge), "llm") if row.judge else (None, None)
    early_end = row.outcome in rules.EARLY_END
    if judge is None and row.status == "finished" and user_turns and (not incomplete or early_end):
        turns = [(t.text, MoveAnalysis(**t.analysis)) for t in user_turns]
        fallback = offline.judge_offline(card, turns)
        judge, source = fallback, "rules"
        if _use_llm() and not incomplete:
            try:
                marked = [{"role": t.role, "text": t.text, "labels": (t.analysis or {}).get("labels", [])} for t in row.turns]
                judge = sanitize_judge(card, llm.judge(card, marked, note or ""), [t.text for t in user_turns], fallback)
                source = "llm"
                row.judge = judge.model_dump()
                db.commit()
            except Exception as exc:
                log.warning("judge unavailable, rules report instead: %s", exc)

    return SessionResult(
        session_id=row.id, status=row.status, outcome=row.outcome, incomplete=incomplete,
        final_position=row.agreed_value, in_zone=in_zone, position_shift=shift,
        details_covered=covered, details_missed=missed, judge=judge, judge_source=source,
        walk_away_justified=justified, walk_away_note=note,
    )
