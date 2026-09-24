"""Сессия переговоров: ход пользователя → разметка → счётчики → ответ собеседника → исход; разбор после диалога."""
import logging
from uuid import uuid4

from . import llm
from .config import settings
from .db import SessionRow, TurnRow
from .engine import offline, rules
from .schemas import JudgeReport, MoveAnalysis, OpponentState, ScenarioCard, SessionResult, TurnOut

log = logging.getLogger(__name__)


def _history(row: SessionRow) -> list[dict]:
    return [{"role": "user" if t.role == "user" else "assistant", "content": t.text} for t in row.turns]


def _use_llm() -> bool:
    return not settings.offline_mode


def start(db, scenario_id: str, card: ScenarioCard) -> SessionRow:
    state = rules.initial_state(card)
    row = SessionRow(id=uuid4().hex, scenario_id=scenario_id, card=card.model_dump(), state=state.model_dump())
    opening = f"{card.opponent_role}. Слушаю вас. Моё предложение: {state.position:g} {card.target_zone.unit}."
    row.turns.append(TurnRow(role="opponent", text=opening))
    db.add(row)
    db.commit()
    return row


def turn(db, row: SessionRow, message: str) -> TurnOut:
    card = ScenarioCard(**row.card)
    state = OpponentState(**row.state)
    history = _history(row)

    move: MoveAnalysis
    if _use_llm():
        try:
            move = llm.analyze_move(card, history, message)
        except Exception as exc:  # LLM недоступна: переходим на правила, демо не ломается
            log.warning("analyze_move fallback: %s", exc)
            move = offline.analyze(card, message)
    else:
        move = offline.analyze(card, message)

    state, conceded = rules.apply_move(card, state, move)
    row.turn += 1
    outcome, value = rules.decide_outcome(card, state, move, row.turn)

    if outcome in ("agreement_in_zone", "agreement_out_of_zone"):
        reply = f"Договорились: {value:g} {card.target_zone.unit}. Фиксируем."
    elif outcome == "breakdown":
        reply = "В таком тоне я разговор продолжать не готов. На этом закончим."
    elif outcome == "turn_limit":
        reply = "Время вышло, к соглашению мы не пришли."
    elif _use_llm():
        try:
            reply = llm.opponent_reply(card, state, move, conceded, history, message)
        except Exception as exc:
            log.warning("opponent_reply fallback: %s", exc)
            reply = offline.reply(card, state, move, conceded)
    else:
        reply = offline.reply(card, state, move, conceded)

    row.turns.append(TurnRow(role="user", text=message, analysis=move.model_dump()))
    row.turns.append(TurnRow(role="opponent", text=reply))
    row.state = state.model_dump()
    if outcome:
        row.status, row.outcome, row.agreed_value = "finished", outcome, value
    db.commit()
    return TurnOut(turn=row.turn, opponent_message=reply, status=row.status, outcome=outcome, analysis=move, state=state)


def finish(db, row: SessionRow) -> None:
    if row.status == "active":
        row.status, row.outcome = "finished", "user_finished"
        db.commit()


def result(db, row: SessionRow) -> SessionResult:
    card = ScenarioCard(**row.card)
    user_turns = [t for t in row.turns if t.role == "user"]
    incomplete = len(user_turns) < settings.incomplete_session_min_turns
    covered = sorted({d for t in user_turns for d in (t.analysis or {}).get("mentioned_details", [])})
    missed = [d for d in card.mandatory_details if d not in covered]
    z = card.target_zone
    in_zone = shift = None
    if row.agreed_value is not None:
        in_zone = z.zone_min <= row.agreed_value <= z.zone_max
        shift = row.agreed_value - z.user_start

    judge = JudgeReport(**row.judge) if row.judge else None
    if not incomplete and row.status == "finished" and judge is None and _use_llm():
        try:
            judge = llm.judge(card, _history(row))
            row.judge = judge.model_dump()
            db.commit()
        except Exception as exc:
            log.warning("judge unavailable: %s", exc)

    return SessionResult(
        session_id=row.id, status=row.status, outcome=row.outcome, incomplete=incomplete,
        final_position=row.agreed_value, in_zone=in_zone, position_shift=shift,
        details_covered=covered, details_missed=missed, judge=judge,
    )
