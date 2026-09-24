"""Запасной режим без LLM: разметка хода и ответы собеседника по правилам.

Маркеры и шаблоны ответов взяты из прототипа Артемия и переложены на разметку MoveAnalysis.
"""
import re

from ..schemas import MoveAnalysis, OpponentState, ScenarioCard

MARKERS = {
    "interest_question": ("что для вас", "что важно", "почему", "при каких условиях", "что мешает", "какие риски", "что нужно"),
    "objective_criterion": ("рынок", "рыночн", "стандарт", "норматив", "как у других", "данные", "статистик"),
    "option_generation": ("вариант", "можно так", "а если", "альтернатив"),
    "concession": ("уступ", "компромисс", "навстречу", "в обмен", "при условии"),
    "empathy": ("понимаю", "ценю", "вашу позицию", "слышу", "учитываю"),
    "argument": ("потому что", "расчет", "расчёт", "результат", "экономия", "выгода"),
    "pressure": ("иначе", "последнее предложение", "требую", "не обсуждается", "только так", "никаких"),
    "personal_attack": ("вы не понимаете", "некомпетент", "бред", "глупо"),
}
OFFER_MARKERS = ("предлагаю", "готов", "готовы", "давайте", "зафиксируем", "договоримся")
NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


def analyze(card: ScenarioCard, message: str) -> MoveAnalysis:
    low = message.lower()
    labels = [label for label, words in MARKERS.items() if any(w in low for w in words)]
    if "?" in message and "interest_question" not in labels:
        labels.append("interest_question")
    numbers = [float(n.replace(",", ".")) for n in NUMBER.findall(message)]
    proposed = numbers[0] if numbers else None
    if proposed is not None and any(w in low for w in OFFER_MARKERS):
        labels.append("concrete_offer")
    mentioned = [d for d in card.mandatory_details if any(tok in low for tok in d.lower().split() if len(tok) > 4)]
    if mentioned:
        labels.append("mandatory_detail")
    if not labels:
        labels.append("vague")
    return MoveAnalysis(labels=labels, mentioned_details=mentioned, proposed_value=proposed)


def reply(card: ScenarioCard, state: OpponentState, move: MoveAnalysis, conceded: bool) -> str:
    unit = card.target_zone.unit
    if "pressure" in move.labels or "personal_attack" in move.labels:
        return "Давление не помогает. Объясните, что ваши условия дают моей стороне."
    if conceded:
        return f"Хорошо, готов сдвинуться: {state.position:g} {unit}. Дальше нужны веские причины."
    if "interest_question" in move.labels and card.opponent_hidden_interests and state.trust >= 1:
        return f"Если честно, для меня важно другое: {card.opponent_hidden_interests[0]}."
    if "concrete_offer" in move.labels:
        return f"Пока могу предложить {state.position:g} {unit}. Обоснуйте, почему ваш вариант справедлив."
    if "objective_criterion" in move.labels or "argument" in move.labels:
        return "Аргумент понятен. Как он переводится в конкретное предложение?"
    return "Позиция пока общая. Дайте конкретное предложение или спросите, что важно для меня."
