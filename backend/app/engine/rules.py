"""Детерминированная механика собеседника: разметка хода двигает счётчики, счётчики решают об уступке и исходе.

LLM здесь не участвует. Одинаковые разметки ходов дают одинаковый исход, это требование воспроизводимости для жюри.
"""
from ..schemas import MoveAnalysis, OpponentState, Outcome, ScenarioCard

LABEL_EFFECTS = {
    "interest_question": {"trust": 1, "readiness": 2},
    "spin_situation": {"trust": 1, "readiness": 1},
    "spin_problem": {"trust": 1, "readiness": 2},
    "spin_implication": {"readiness": 2},
    "spin_need_payoff": {"readiness": 3},
    "objective_criterion": {"readiness": 3},
    "option_generation": {"trust": 1, "readiness": 2},
    "concrete_offer": {"readiness": 2},
    "concession": {"trust": 1, "readiness": 1},
    "empathy": {"trust": 2, "irritation": -1},
    "argument": {"readiness": 1},
    "mandatory_detail": {"trust": 1},
    "pressure": {"trust": -2, "irritation": 2},
    "personal_attack": {"trust": -3, "irritation": 3},
    "vague": {"irritation": 1},
    "manipulation": {"trust": -1, "irritation": 2},
}

STYLE_MULTIPLIERS = {
    "hard": {"trust": 0.5, "readiness": 0.8, "irritation": 1.0},
    "cooperative": {"trust": 1.5, "readiness": 1.2, "irritation": 0.7},
    "avoiding": {"trust": 1.0, "readiness": 0.6, "irritation": 0.8},
    "pressing": {"trust": 0.7, "readiness": 0.9, "irritation": 1.5},
    "emotional": {"trust": 1.3, "readiness": 1.0, "irritation": 2.0},
}

DIFFICULTY = {
    "easy": {"concede_threshold": 3, "breakdown_irritation": 9, "limit_share": 1.0},
    "medium": {"concede_threshold": 4, "breakdown_irritation": 7, "limit_share": 0.5},
    "hard": {"concede_threshold": 5, "breakdown_irritation": 5, "limit_share": 0.0},
}

CONCESSION_STEPS = 4

METHOD_AXES = {
    "spin": ["ситуационные вопросы", "проблемные вопросы", "извлекающие вопросы", "направляющие вопросы"],
    "harvard": ["люди отдельно от проблемы", "интересы, а не позиции", "варианты взаимной выгоды", "объективные критерии"],
    "free": ["выяснение интересов", "аргументация", "конкретные предложения", "контроль эмоций"],
}


def initial_state(card: ScenarioCard) -> OpponentState:
    return OpponentState(position=card.target_zone.opponent_start)


def _direction(card: ScenarioCard) -> int:
    z = card.target_zone
    return 1 if z.user_start > z.opponent_start else -1


def plausible_range(card: ScenarioCard) -> tuple[float, float]:
    """Какие значения вообще можно считать предложением в единицах торга: от половины меньшего края до полутора большего."""
    z = card.target_zone
    edges = [abs(v) for v in (z.user_start, z.zone_min, z.zone_max, z.opponent_start)]
    return 0.5 * min(edges), 1.5 * max(edges)


def is_plausible(card: ScenarioCard, value: float) -> bool:
    lo, hi = plausible_range(card)
    return lo <= value <= hi


def better_for_user(card: ScenarioCard, value: float, position: float) -> bool:
    return _direction(card) * (value - position) > 1e-9


def opponent_limit(card: ScenarioCard) -> float:
    """Докуда собеседник готов сдвинуться: от дальнего края зоны (hard) до ближнего к пользователю (easy)."""
    z = card.target_zone
    near, far = (z.zone_max, z.zone_min) if _direction(card) > 0 else (z.zone_min, z.zone_max)
    share = DIFFICULTY[card.difficulty]["limit_share"]
    return far + (near - far) * share


def apply_move(card: ScenarioCard, state: OpponentState, move: MoveAnalysis) -> tuple[OpponentState, bool]:
    """Возвращает новое состояние и флаг «собеседник уступил на этом ходу»."""
    mult = STYLE_MULTIPLIERS[card.style]
    s = state.model_copy()
    for label in move.labels:
        for counter, delta in LABEL_EFFECTS.get(label, {}).items():
            setattr(s, counter, getattr(s, counter) + round(delta * mult[counter]))
    s.irritation = max(0, s.irritation)

    conceded = False
    threshold = DIFFICULTY[card.difficulty]["concede_threshold"]
    limit = opponent_limit(card)
    step = abs(limit - card.target_zone.opponent_start) / CONCESSION_STEPS
    d = _direction(card)
    if s.readiness >= threshold and s.trust >= 0 and d * (limit - s.position) > 1e-9:
        s.position = min(s.position + step, limit) if d > 0 else max(s.position - step, limit)
        s.readiness -= threshold
        conceded = True
    return s, conceded


def decide_outcome(card: ScenarioCard, state: OpponentState, move: MoveAnalysis, turn: int) -> tuple[Outcome | None, float | None]:
    diff = DIFFICULTY[card.difficulty]
    if state.irritation >= diff["breakdown_irritation"] or state.trust <= -6:
        return "breakdown", None
    z = card.target_zone
    value = move.proposed_value if move.proposed_value is not None and is_plausible(card, move.proposed_value) else None
    if "manipulation" not in move.labels:
        if value is not None and ("concrete_offer" in move.labels or "accept" in move.labels) and not better_for_user(card, value, state.position):
            return ("agreement_in_zone" if z.zone_min <= value <= z.zone_max else "agreement_out_of_zone"), value
        if "accept" in move.labels and value is None:
            value = state.position
            return ("agreement_in_zone" if z.zone_min <= value <= z.zone_max else "agreement_out_of_zone"), value
    if turn >= card.max_turns:
        return "turn_limit", None
    return None, None
