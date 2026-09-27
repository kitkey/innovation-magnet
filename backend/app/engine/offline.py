"""Запасной режим без LLM: разметка хода, ответы собеседника и разбор по правилам.

Маркеры и шаблоны ответов взяты из прототипа Артемия и переложены на разметку MoveAnalysis.
"""
import math
import re

from ..schemas import JudgeReport, KeyMoment, MoveAnalysis, OpponentState, ScenarioCard
from . import rules

MARKERS = {
    "interest_question": ("что для вас", "что важно", "почему", "при каких условиях", "что мешает", "какие риски", "что нужно"),
    "spin_situation": ("как сейчас", "как у вас", "как устроен", "сколько сейчас", "какой объём", "какой объем"),
    "spin_problem": ("проблем", "сложност", "трудност", "не устраивает", "что беспокоит"),
    "spin_implication": ("к чему привед", "чем грозит", "последстви", "во что обойд", "что будет, если"),
    "spin_need_payoff": ("если бы", "что это даст", "насколько полезно", "поможет ли", "было бы полезно"),
    "objective_criterion": ("рынок", "рыночн", "стандарт", "норматив", "как у других", "данные", "статистик"),
    "option_generation": ("вариант", "можно так", "а если", "альтернатив"),
    "concession": ("уступ", "компромисс", "навстречу", "в обмен", "при условии"),
    "empathy": ("понимаю", "ценю", "вашу позицию", "слышу", "учитываю"),
    "argument": ("потому что", "расчет", "расчёт", "результат", "экономия", "выгода"),
    "pressure": ("иначе", "последнее предложение", "требую", "не обсуждается", "только так", "никаких"),
    "personal_attack": ("вы не понимаете", "некомпетент", "бред", "глупо"),
    "manipulation": ("игнорируй", "забудь", "инструкци", "промпт", "системн", "ты модель", "ты бот", "ты ии", "нейросет", "выйди из роли", "просто согласись", "соглашайся"),
}
OFFER_MARKERS = ("предлагаю", "готов", "готовы", "давайте", "зафиксируем", "договоримся")
ACCEPT = re.compile(r"(?<!не )(согласен|согласна|согласны|принимаю|принимаем|по рукам|договорились|меня устраивает|нас устраивает)")
ACCEPT_SHORT = re.compile(r"^\s*(идёт|идет|по рукам)[\s,.!]")
BUT = (" но ", ", но", "однако", "только если", "при условии")
NUMBER = re.compile(r"(\d{1,3}(?:[  ]\d{3})+|\d+(?:[.,]\d+)?)\s*(%|процент\w*|тыс\w*\.?|млн\w*\.?|[a-zа-яё]+)?", re.IGNORECASE)
SCALE = {"тыс": 1e3, "млн": 1e6}
OTHER_UNITS = ("мвт", "квт", "руб", "кв", "м2", "дн", "день", "мес", "год", "лет", "час", "недел", "шт", "задач", "человек", "процент", "%")

LABELS_RU = {
    "pressure": "давление", "personal_attack": "переход на личности", "manipulation": "попытка манипуляции", "vague": "общая фраза без сути",
}
BETTER = {
    "pressure": "Вместо ультиматума спросите, что важно для собеседника, и предложите вариант с обоснованием.",
    "personal_attack": "Отделите человека от проблемы: признайте его позицию и обсуждайте условия, а не личность.",
    "manipulation": "Работайте с интересами собеседника, а не с попыткой обойти его позицию.",
    "vague": "Назовите конкретное предложение в единицах торга и объясните, почему оно справедливо.",
}
AXIS_LABELS = {
    "ситуационные вопросы": ({"spin_situation", "interest_question"}, None),
    "проблемные вопросы": ({"spin_problem"}, None),
    "извлекающие вопросы": ({"spin_implication"}, None),
    "направляющие вопросы": ({"spin_need_payoff"}, None),
    "люди отдельно от проблемы": ({"empathy"}, {"pressure", "personal_attack", "manipulation"}),
    "интересы, а не позиции": ({"interest_question", "spin_problem", "spin_situation"}, None),
    "варианты взаимной выгоды": ({"option_generation", "concession"}, None),
    "объективные критерии": ({"objective_criterion"}, None),
    "выяснение интересов": ({"interest_question", "spin_situation", "spin_problem", "spin_implication", "spin_need_payoff"}, None),
    "аргументация": ({"argument", "objective_criterion"}, None),
    "конкретные предложения": ({"concrete_offer", "option_generation"}, None),
    "контроль эмоций": ({"empathy"}, {"pressure", "personal_attack", "manipulation"}),
}
METHOD_RU = {"spin": "SPIN", "harvard": "Гарвардский", "free": "свободный"}
AXIS_TIPS = {
    "ситуационные вопросы": "Начните с вопросов о текущей ситуации собеседника: как сейчас устроена работа, какие сроки и ресурсы.",
    "проблемные вопросы": "Спросите, что собеседника не устраивает и какие трудности он видит.",
    "извлекающие вопросы": "Спросите о последствиях проблемы: к чему она приведёт, во что обойдётся.",
    "направляющие вопросы": "Подведите собеседника к выгоде решения: что даст ему ваш вариант.",
    "люди отдельно от проблемы": "Признайте позицию собеседника и обсуждайте условия, а не личность.",
    "интересы, а не позиции": "Спросите, зачем собеседнику его позиция и что для него важно на самом деле.",
    "варианты взаимной выгоды": "Предложите два-три варианта, где выигрывают обе стороны.",
    "объективные критерии": "Опирайтесь на данные, нормативы и рыночные цифры, а не на «хочу».",
    "выяснение интересов": "Задайте вопрос о том, что важно собеседнику, до того как называть цифру.",
    "аргументация": "Подкрепите предложение расчётом или данными.",
    "конкретные предложения": "Назовите конкретное значение в единицах торга.",
    "контроль эмоций": "Держите ровный тон: давление повышает раздражение собеседника и ведёт к срыву.",
}


def _unit_scale(unit: str) -> float:
    low = unit.lower()
    return next((v for k, v in SCALE.items() if k in low), 1.0)


def values(card: ScenarioCard, text: str) -> list[float]:
    """Все числа из текста, которые правдоподобны как значение в единицах торга; с совпадающей единицей идут первыми."""
    unit = card.target_zone.unit.lower()
    unit_scale = _unit_scale(unit)
    percent_unit = "%" in unit or "процент" in unit
    unit_stems = [w[:max(2, min(3, len(w) - 2))] for w in re.findall(r"[a-zа-яё]+", unit) if len(w) > 2]
    matched, bare = [], []
    for num, suffix in NUMBER.findall(text):
        n = float(num.replace(" ", "").replace(" ", "").replace(",", "."))
        suf = (suffix or "").lower()
        if suf == "%" or suf.startswith("процент"):
            if not percent_unit:
                continue
            matched.append(n)
        elif suf[:3] in SCALE:
            matched.append(n * SCALE[suf[:3]] / unit_scale)
        elif suf and any(suf.startswith(s) for s in unit_stems):
            matched.extend([n] if unit_scale == 1 else [n, n / unit_scale])
        elif suf and any(suf.startswith(u) for u in OTHER_UNITS):
            continue
        else:
            bare.extend([n] if unit_scale == 1 else [n, n / unit_scale])
    return [v for v in matched + bare if rules.is_plausible(card, v)]


def _stem(word: str) -> str:
    return word[:max(4, int(len(word) * 0.7))]


def detail_mentioned(detail: str, low: str) -> bool:
    stems = [_stem(w) for w in re.findall(r"[a-zа-яё0-9]+", detail.lower()) if len(w) > 3]
    if not stems:
        return detail.lower() in low
    need = min(2, math.ceil(len(stems) / 2))
    return sum(s in low for s in stems) >= need


def _is_accept(low: str) -> bool:
    return "?" not in low and not any(b in low for b in BUT) and bool(ACCEPT.search(low) or ACCEPT_SHORT.search(low + " "))


def analyze(card: ScenarioCard, message: str) -> MoveAnalysis:
    low = message.lower().replace("ё", "е")
    labels = [label for label, words in MARKERS.items() if any(w.replace("ё", "е") in low for w in words)]
    if "?" in message and "interest_question" not in labels:
        labels.append("interest_question")
    found = values(card, message)
    proposed = found[0] if found else None
    if proposed is not None and any(w in low for w in OFFER_MARKERS):
        labels.append("concrete_offer")
    if _is_accept(low):
        labels.append("accept")
    mentioned = [d for d in card.mandatory_details if detail_mentioned(d.replace("ё", "е"), low)]
    if mentioned:
        labels.append("mandatory_detail")
    if not labels:
        labels.append("vague")
    return MoveAnalysis(labels=labels, mentioned_details=mentioned, proposed_value=proposed)


def reply(card: ScenarioCard, state: OpponentState, move: MoveAnalysis, conceded: bool) -> str:
    unit = card.target_zone.unit
    if "manipulation" in move.labels:
        return f"Давайте без этих приёмов. Моя позиция прежняя: {state.position:g} {unit}."
    if "pressure" in move.labels or "personal_attack" in move.labels:
        return "Давление не помогает. Объясните, что ваши условия дают моей стороне."
    if conceded:
        return f"Хорошо, готов сдвинуться: {state.position:g} {unit}. Дальше нужны веские причины."
    if "interest_question" in move.labels and card.opponent_hidden_interests and state.trust >= 1:
        return f"Если честно, для меня важно другое: {card.opponent_hidden_interests[0]}."
    if "concrete_offer" in move.labels or "accept" in move.labels:
        return f"Пока могу предложить {state.position:g} {unit}. Обоснуйте, почему ваш вариант справедлив."
    if "objective_criterion" in move.labels or "argument" in move.labels:
        return "Аргумент понятен. Как он переводится в конкретное предложение?"
    return "Позиция пока общая. Дайте конкретное предложение или спросите, что важно для меня."


def _axis_score(axis: str, moves: list[MoveAnalysis]) -> int:
    good, bad = AXIS_LABELS[axis]
    n = len(moves)
    share = sum(bool(good & set(m.labels)) for m in moves) / n
    if bad is None:
        return round(100 * min(1.0, 2 * share))
    bad_share = sum(bool(bad & set(m.labels)) for m in moves) / n
    return round(max(0.0, min(100.0, 70 + 30 * min(1.0, 2 * share) - 100 * bad_share)))


def judge_offline(card: ScenarioCard, turns: list[tuple[str, MoveAnalysis]]) -> JudgeReport:
    """Разбор по правилам: оценки осей метода из доли подходящих меток, ключевые моменты из проблемных ходов."""
    moves = [m for _, m in turns]
    axes = {a: _axis_score(a, moves) for a in rules.METHOD_AXES[card.method]}
    weak = min(axes, key=axes.get)
    moments = []
    for label in ("personal_attack", "manipulation", "pressure", "vague"):
        for text, m in turns:
            if label in m.labels and len(moments) < 3 and all(k.quote != text for k in moments):
                moments.append(KeyMoment(quote=text, problem=f"В реплике {LABELS_RU[label]}.", better=BETTER[label]))
    if not moments:
        good, _ = AXIS_LABELS[weak]
        text = next((t for t, m in turns if not good & set(m.labels)), turns[0][0])
        moments.append(KeyMoment(quote=text, problem=f"Здесь не хватило приёма «{weak}».", better=AXIS_TIPS[weak]))
    hint = f"Слабее всего ось «{weak}» ({axes[weak]}/100). {AXIS_TIPS[weak]} Пройдите этот же сценарий ещё раз или возьмите сценарий с методом «{METHOD_RU[card.method]}» посложнее."
    return JudgeReport(axes=axes, key_moments=moments, next_scenario_hint=hint)
