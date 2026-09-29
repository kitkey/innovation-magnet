"""Маскот-наставник: наставления перед стартом и подсказки по условиям во время диалога.

Условия подсказок считаются по уже сохранённой разметке ходов и счётчикам собеседника, без вызовов LLM.
Каждая подсказка срабатывает не больше одного раза за сессию.
"""
from ..schemas import HINT_WHEN, Hint, HintOut, MoveAnalysis, OpponentState, ScenarioCard
from . import rules

MAX_PER_TURN = 2

COACH_TIPS = {
    "spin": [
        "Начните с двух-трёх вопросов о том, как у собеседника всё устроено сейчас, и не задерживайтесь на них: дальше спрашивайте, что у него не получается.",
        "Спросите, во что обойдётся проблема, если её не решить. Такой вопрос двигает собеседника сильнее любого аргумента.",
        "Своё предложение называйте, когда собеседник сам сказал, что ему нужно, и привяжите его к этим словам.",
    ],
    "harvard": [
        "За требованием собеседника обычно стоит интерес. Спросите, зачем ему именно это: интерес часто можно закрыть иначе.",
        "Предложите два-три варианта сразу, а не один. Из нескольких проще выбрать общий.",
        "Свою цифру подкрепляйте внешним критерием: регламентом, рыночной ценой, прошлыми сроками.",
    ],
    "batna": [
        "До первой реплики решите, где ваша граница: сделка хуже неё проигрывает вашей альтернативе.",
        "Упоминайте альтернативу спокойно, как факт для сравнения. Ультиматум злит и роняет доверие.",
        "Уступайте только в обмен: «если вы…, то мы…».",
    ],
    "free": [
        "Сначала выясните, что важно собеседнику, и только потом аргументируйте.",
        "Называйте цифры, сроки и условия. Общие слова раздражают.",
        "Если разговор накаляется, сбавьте тон: сорванные переговоры хуже медленных.",
    ],
}

STANDARD_HINTS = {
    "spin": [
        Hint(when="missing:spin_problem@3", text="Пока не было ни одного проблемного вопроса. Спросите, что у собеседника сейчас не получается."),
        Hint(when="label:pressure", text="Давление роняет доверие. Вместо него спросите, что будет, если оставить всё как есть."),
        Hint(when="missing:spin_need_payoff@5", text="Пора направляющий вопрос: пусть собеседник сам скажет, что ему даст ваше решение."),
        Hint(when="readiness_high", text="Собеседник почти готов уступить. Назовите конкретное предложение."),
    ],
    "harvard": [
        Hint(when="label:personal_attack", text="Спорьте с проблемой, а не с человеком. Вернитесь к интересам сторон."),
        Hint(when="missing:interest_question@3", text="Вы ещё не спросили, зачем собеседнику его позиция. Узнайте интерес за требованием."),
        Hint(when="missing:objective_criterion@5", text="Опирайтесь на критерий, который признают обе стороны: рынок, регламент, прошлый опыт."),
        Hint(when="trust_low", text="Доверие падает. Признайте ограничения собеседника, прежде чем спорить."),
    ],
    "batna": [
        Hint(when="label:pressure", text="Давление роняет доверие. Альтернативу называйте спокойно, как сравнение: «для нас это выгоднее, чем…»."),
        Hint(when="label:concession", text="Вы уступили без встречного условия. Просите что-то взамен: «если вы…, то мы…»."),
        Hint(when="missing:batna_reference@4", text="Вы ещё ни разу не сравнили сделку со своей альтернативой."),
        Hint(when="turns_left:2", text="Ходов почти не осталось. Если условия хуже альтернативы, выйти из переговоров нормально."),
    ],
    "free": [
        Hint(when="label:vague", text="Слишком общо. Назовите цифру, срок или условие."),
        Hint(when="irritation_high", text="Собеседник на грани. Сбавьте темп и признайте его позицию."),
        Hint(when="missing:concrete_offer@4", text="Конкретного предложения пока не было. Назовите своё число."),
        Hint(when="turns_left:2", text="Осталось два хода. Сформулируйте итоговое предложение."),
    ],
}


def irritation_high(card: ScenarioCard) -> int:
    """Раздражение, при котором до срыва остаётся два шага."""
    return rules.DIFFICULTY[card.difficulty]["breakdown_irritation"] - 2


TRUST_LOW = rules.BREAKDOWN_TRUST // 2


def readiness_high(card: ScenarioCard) -> int:
    """Готовность, при которой следующий удачный ход приводит к уступке."""
    return rules.DIFFICULTY[card.difficulty]["concede_threshold"] - 1


def holds(card: ScenarioCard, when: str, move: MoveAnalysis, seen: set[str], state: OpponentState, turn: int) -> bool:
    """Выполнено ли условие после хода turn: move — разметка этого хода, seen — все метки ходов 1..turn."""
    m = HINT_WHEN.match(when)
    if not m:
        return False
    if m.group("label"):
        return m.group("label") in move.labels
    if m.group("missing"):
        return turn >= int(m.group("at")) and m.group("missing") not in seen
    if m.group("left"):
        return card.max_turns - turn <= int(m.group("left"))
    if when == "irritation_high":
        return state.irritation >= irritation_high(card)
    if when == "trust_low":
        return state.trust <= TRUST_LOW
    if when == "readiness_high":
        return state.readiness >= readiness_high(card)
    return False


def catalog(card: ScenarioCard, from_org: bool) -> list[tuple[str, Hint, str]]:
    """Подсказки сессии с устойчивыми id: сначала свои из карточки, потом стандартные по методу."""
    own = "org" if from_org else "author"
    return [(f"c{i}", h, own) for i, h in enumerate(card.hints)] + [(f"s{i}", h, "standard") for i, h in enumerate(STANDARD_HINTS[card.method])]


def fire(card: ScenarioCard, from_org: bool, move: MoveAnalysis, seen: set[str], state: OpponentState, turn: int,
         fired: list[str]) -> list[tuple[str, HintOut]]:
    """Подсказки, которые срабатывают на этом ходу: условие выполнено и подсказка ещё не показывалась. Не больше двух за ход."""
    out = []
    for hid, hint, source in catalog(card, from_org):
        if hid in fired or not holds(card, hint.when, move, seen, state, turn):
            continue
        out.append((hid, HintOut(text=hint.text, source=source)))
        if len(out) == MAX_PER_TURN:
            break
    return out


def replay(card: ScenarioCard, from_org: bool, moves: list[MoveAnalysis]) -> list[str]:
    """Какие подсказки сработали бы за эти ходы: для отката пересчитываем по сохранённой разметке."""
    state, seen, fired = rules.initial_state(card), set(), []
    for turn, move in enumerate(moves, start=1):
        state, _ = rules.apply_move(card, state, move)
        seen |= set(move.labels)
        fired += [hid for hid, _ in fire(card, from_org, move, seen, state, turn, fired)]
    return fired


def coach(card: ScenarioCard, from_org: bool) -> list[HintOut]:
    """Наставления перед стартом: сначала от организации или автора сценария, потом стандартные по методу."""
    own = "org" if from_org else "author"
    return [HintOut(text=t, source=own) for t in card.coach_tips] + [HintOut(text=t, source="standard") for t in COACH_TIPS[card.method]]
