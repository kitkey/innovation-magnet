"""Запасной режим без LLM: разметка хода, ответы собеседника и разбор по правилам.

Маркеры и шаблоны ответов взяты из прототипа Артемия и переложены на разметку MoveAnalysis.
"""
import math
import re

from ..schemas import JudgeReport, KeyMoment, MoveAnalysis, OpponentState, ScenarioCard, TargetZone
from . import rules

MARKERS = {
    "interest_question": ("что для вас", "для вас важн", "для вас критичн", "что вам важн", "что важно", "почему", "зачем",
                          "что мешает", "какие ограничени", "какие у вас ограничени", "что если", "а что, если", "чем обусловлен",
                          "чем вызван", "с чем связан", "при каких условиях", "на каких условиях", "какие риски", "что нужно",
                          "что вам нужно", "что вас устроит", "что вас устроило бы", "что для вас приемлем", "какие приоритет",
                          "какие у вас приоритет", "что стоит за", "какая у вас цель", "какие у вас цели", "что вы хотите получить"),
    "spin_situation": ("как сейчас", "как у вас", "как устроен", "сколько сейчас", "какой объём", "какой объем"),
    "spin_problem": ("проблем", "сложност", "трудност", "не устраивает", "что беспокоит"),
    "spin_implication": ("к чему привед", "чем грозит", "последстви", "во что обойд", "что будет, если"),
    "spin_need_payoff": ("если бы", "что это даст", "насколько полезно", "поможет ли", "было бы полезно"),
    "objective_criterion": ("рынок", "рыночн", "стандарт", "норматив", "как у других", "данные", "статистик"),
    "option_generation": ("вариант", "можно так", "а если", "альтернатив"),
    "concession": ("уступ", "компромисс", "навстречу", "в обмен", "при условии"),
    "empathy": ("понимаю", "ценю", "вашу позицию", "слышу", "учитываю"),
    "argument": ("потому что", "расчет", "расчёт", "результат", "экономия", "выгода"),
    "pressure": ("иначе", "последнее предложение", "требую", "не обсуждается", "только так", "никаких",
                 "нет вариантов", "вариантов нет", "без вариантов", "других вариантов нет", "без лишних разговоров",
                 "без разговоров", "хватит уже", "хватит тянуть", "хватит торговаться", "хватит болтать"),
    "personal_attack": ("вы не понимаете", "некомпетент", "бред", "глупо", "идиот", "дурак", "тупые", "тупой"),
    "manipulation": ("игнорируй все", "игнорируй предыдущ", "игнорируй инструкц", "игнорируйте все", "игнорируйте предыдущ",
                     "игнорируйте инструкц", "проигнорируй", "забудь все", "забудь предыдущ", "забудь инструкц", "забудь свои",
                     "забудьте все инструкц", "забудьте предыдущ", "забудьте инструкц", "твои инструкции", "свои инструкции",
                     "предыдущие инструкции", "системный промпт", "системное сообщение", "системные инструкции", "промпт",
                     "ты модель", "ты языковая модель", "ты бот", "ты ии", "ты нейросеть", "вы нейросеть", "выйди из роли",
                     "выйдите из роли", "просто согласись", "соглашайся"),
}
# Фразы, которые содержат маркер метки, но значат обратное: «без проблем» — не проблема, «не уступим» — не уступка.
# Перед поиском маркеров метки они вырезаются из текста.
EXCEPT = {
    "interest_question": ("вот почему", "вот зачем"),
    "spin_problem": ("без проблем", "нет проблем", "никаких проблем", "не проблема", "проблем нет"),
    "objective_criterion": ("нестандарт", "переданные", "заданные", "выданные", "изданные"),
    "option_generation": ("нет вариантов", "вариантов нет", "без вариантов", "не вариант", "нет альтернатив", "альтернатив нет"),
    "concession": ("не уступ", "никаких уступок", "без уступок", "никаких компромисс", "без компромисс", "не пойдем навстречу",
                   "не пойду навстречу", "не пойдем вам навстречу", "не пойду вам навстречу", "не можем пойти навстречу",
                   "не могу пойти навстречу"),
    "empathy": ("не понимаю", "непонимаю", "не слышу", "не ценю", "не учитываю"),
    "pressure": ("иначе говоря", "так или иначе", "или иначе", "никаких проблем", "никаких возражений"),
}
# Риторические и агрессивные вопросы и упрёки. Вопросительный знак в них не делает реплику вопросом об интересах:
# «Вы вообще понимаете, что делаете? Это несерьёзно.» — давление, а не выяснение.
# Границы слов через lookaround: у кириллицы с «ё» и дефисами так надёжнее, чем через границу слова.
RHETORIC = re.compile(
    r"несерьезн|не серьезн|вы серьезно|(?<![а-яa-z])вы что(?![а-яa-z-])|(?<![а-яa-z])ты что(?![а-яa-z-])|в своем уме|издеваете|издевательств|сколько можно|"
    r"смешн|не смешите|шутите|за дурак|за идиот|абсурд|нелеп|как вам не стыдно|кончайте|(?<![а-яa-z])хватит(?![а-яa-z-])(?! ли)|"
    r"(вы|ты) (вообще |хоть |хотя бы |вообще-то )понима|(вы|ты) (понимаете|понимаешь), что (делаете|делаешь|говорите|говоришь|несете|несешь)|"
    r"что вы себе позволяете|кто так делает|о чем вы вообще"
)
# Открытый вопрос без маркеров интересов и без упрёка — уточнение ситуации («Какой бюджет вы рассматриваете?»).
OPEN_QUESTION = re.compile(r"(?<![а-яa-z])(как|какой|какая|какое|какие|каким|каких|что|чем|когда|сколько|где|кто|откуда|ли)(?![а-яa-z])")
BATNA_MARKERS = {
    "batna_reference": ("альтернативн", "наша альтернатива", "моя альтернатива", "есть альтернатива", "запасной вариант",
                        "другой поставщик", "другого поставщика", "резервный поставщик", "резервного поставщика", "другой подрядчик",
                        "другого подрядчика", "конкурент", "другой оффер", "другое предложение", "если не договоримся",
                        "без соглашения", "вне сделки", "batna", "батна"),
    "boundary": ("минимум", "максимум", "предел", "границ", "ниже не", "выше не", "не выше", "не ниже", "не более", "не больше",
                 "не могу согласовать", "не можем согласовать", "не готов принять", "не готова принять", "не готовы принять",
                 "минимально приемлем", "максимально приемлем", "критическое условие"),
    "conditional_trade": ("если вы", "при условии", "в обмен", "тогда мы", "со своей стороны", "готовы в ответ", "готов в ответ",
                          "можем дать", "взамен"),
}
WALK_AWAY_MARKERS = ("откажемся от сделки", "отказываемся от сделки", "откажусь от предложения", "отказываюсь от предложения",
                     "откажемся от предложения", "откажусь от оффера", "выберем другого", "выбираем другого", "выберу другое",
                     "выбираю другое", "принимаю другой оффер", "перейдем к альтернатив", "переходим к альтернатив",
                     "переходим к резервному", "прекратим переговоры", "прекращаем переговоры", "не будем заключать",
                     "не сможем заключить", "лучше не заключать")
WALK_AWAY_CONDITIONAL = ("если", "иначе", "в случае", "?")
OFFER = re.compile(r"(?<!не )(предлагаю|готов|готовы|давайте|зафиксируем|договоримся)")
ACCEPT = re.compile(r"(?<!не )(согласен|согласна|согласны|принимаю|принимаем|по рукам|договорились|меня устраивает|нас устраивает)")
ACCEPT_SHORT = re.compile(r"^\s*(идёт|идет|по рукам)[\s,.!]")
BUT = (" но ", ", но", "однако", "только если", "при условии")
NUMBER = re.compile(r"(\d{1,3}(?:[  ]\d{3})+|\d+(?:[.,]\d+)?)\s*(%|процент\w*|тыс\w*\.?|млн\w*\.?|[a-zа-яё]+)?", re.IGNORECASE)
SCALE = {"тыс": 1e3, "млн": 1e6}
OTHER_UNITS = ("мвт", "квт", "руб", "кв", "м2", "дн", "день", "мес", "год", "лет", "час", "недел", "шт", "задач", "человек", "процент", "%")

LABELS_RU = {
    "pressure": "давление", "personal_attack": "переход на личности", "manipulation": "попытка манипуляции", "vague": "общая фраза без сути",
    "batna_threat": "ссылка на альтернативу как угроза",
}
BETTER = {
    "pressure": "Вместо ультиматума спросите, что важно для собеседника, и предложите вариант с обоснованием.",
    "personal_attack": "Отделите человека от проблемы: признайте его позицию и обсуждайте условия, а не личность.",
    "manipulation": "Работайте с интересами собеседника, а не с попыткой обойти его позицию.",
    "vague": "Назовите конкретное предложение в единицах торга и объясните, почему оно справедливо.",
    "batna_threat": "Назовите альтернативу спокойно, как точку сравнения, и предложите обмен: «если вы…, то мы…».",
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
    "сравнение с альтернативой": ({"batna_reference"}, None),
    "защита границы": ({"boundary", "walk_away"}, None),
    "обмен условиями": ({"conditional_trade", "concrete_offer"}, None),
    "исследование интересов": ({"interest_question", "spin_situation", "spin_problem", "spin_implication", "spin_need_payoff", "argument", "objective_criterion"}, None),
}
METHOD_RU = {"spin": "SPIN", "harvard": "Гарвардский", "batna": "BATNA", "free": "свободный"}
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
    "сравнение с альтернативой": "Сравните предложение со своей альтернативой вслух: чем сделка должна быть лучше неё.",
    "защита границы": "Обозначьте предел приемлемого до финальных уступок и не переходите его.",
    "обмен условиями": "Уступайте только в обмен: «если вы фиксируете…, то мы готовы…».",
    "исследование интересов": "Выясните интересы и ограничения собеседника вопросами и подкрепите позицию фактами.",
}
THREATS = {"pressure", "personal_attack", "manipulation"}


def _unit_scale(unit: str) -> float:
    low = unit.lower()
    return next((v for k, v in SCALE.items() if k in low), 1.0)


# Шкала вариантов: какой вариант назван в реплике. Сначала явный номер («вариант 2», «второй вариант»),
# потом ключевые слова формулировок. Слово весит тем больше, чем в меньшем числе вариантов оно встречается;
# слова из предмета торга и общие для всех вариантов не считаются. «Не больше 5 дней» и «5 дней» различаются
# по отрицанию перед словом. При равном весе выигрывает вариант, чьих слов названо больше в доле; полная ничья — не распознан.
OPTION_NUMBER = re.compile(r"(?:вариант\w*|№)\s*(?:номер\s*)?(\d)(?!\d)")
OPTION_ORDINAL = re.compile(r"(?<![а-яa-z])(перв|втор|трет|четв|пят|шест|седьм|восьм)\w*\s+вариант")
ORDINALS = {"перв": 1, "втор": 2, "трет": 3, "четв": 4, "пят": 5, "шест": 6, "седьм": 7, "восьм": 8}
NUM_WORDS = {"один": "1", "одного": "1", "одним": "1", "два": "2", "двух": "2", "двумя": "2", "три": "3", "трех": "3", "тремя": "3",
             "четыре": "4", "четырех": "4", "пять": "5", "пяти": "5", "пятью": "5", "шесть": "6", "шести": "6", "семь": "7", "семи": "7",
             "восемь": "8", "восьми": "8", "десять": "10", "десяти": "10"}
TERM = re.compile(r"[a-zа-я]+|\d+(?:\.\d+)?")
NEGATED = re.compile(r"(?<![а-яa-z])(не|без|никаких|никакого|никакой|нет)\s+$")
NO_WORD = re.compile(r"(?<![а-яa-z])нет(?![а-яa-z])")
REMOVAL = ("убра", "убер", "исключ", "вычерк", "удали", "удалит", "без пункт", "без этого пункт", "без такого пункт", "пункта нет",
           "пункта не будет", "не включа", "отказаться от пункт", "отказ от пункт", "пункт не нужен", "пункт лишн")


def _low(text: str) -> str:
    low = re.sub(r"(?<=\d),(?=\d)", ".", text.lower().replace("ё", "е"))
    return re.sub(r"[а-я]+", lambda m: NUM_WORDS.get(m.group(), m.group()), low)


def _terms(text: str) -> set[tuple[str, bool]]:
    """Основы слов длиной от четырёх букв и числа, с отметкой «стоит после не/без»."""
    low, out = _low(text), set()
    for m in TERM.finditer(low):
        w = m.group()
        if not w[0].isdigit():
            if len(w) < 4:
                continue
            w = w[:max(4, min(len(w) - 2, 6))]
        out.add((w, bool(NEGATED.search(low[max(0, m.start() - 12):m.start()]))))
    return out


def _occurrences(term: str, low: str):
    """Вхождения основы с начала слова («оплат» не находится в «предоплата») или числа целиком."""
    edge = r"(?<![\d.])" if term[0].isdigit() else r"(?<![а-яa-z0-9])"
    tail = r"(?![\d]|\.\d)" if term[0].isdigit() else ""
    return re.finditer(edge + re.escape(term) + tail, low)


def _has(term: str, low: str) -> bool:
    return next(_occurrences(term, low), None) is not None


def _found(term: str, neg: bool, low: str) -> bool:
    return any(bool(NEGATED.search(low[max(0, m.start() - 12):m.start()])) == neg for m in _occurrences(term, low))


def option_index(zone: TargetZone, text: str) -> int | None:
    """Номер варианта (с нуля), который назван в тексте, или None."""
    low = _low(text)
    m = OPTION_NUMBER.search(low)
    k = int(m.group(1)) if m else next((ORDINALS[o.group(1)] for o in OPTION_ORDINAL.finditer(low)), None)
    if k is not None and 1 <= k <= len(zone.options):
        return k - 1
    opts = [_low(o) for o in zone.options]
    subject = _low(zone.unit)
    scores = []
    for i, opt in enumerate(opts):
        score, hits, terms = 0.0, 0, 0
        for term, neg in _terms(zone.options[i]):
            share = sum(_has(term, o) for o in opts)
            if share == len(opts) or _has(term, subject):
                continue
            terms += 1
            if _found(term, neg, low):
                score, hits = score + 1 / share, hits + 1
        if NO_WORD.search(opt):
            terms += 1
            if any(r in low for r in REMOVAL):
                score, hits = score + 1 / sum(bool(NO_WORD.search(o)) for o in opts), hits + 1
        scores.append((round(score, 6), hits / terms if terms else 0.0))  # при равном весе выигрывает вариант, названный полнее
    best = max(scores)
    if best[0] <= 0 or scores.count(best) > 1:
        return None
    return scores.index(best)


def values(card: ScenarioCard, text: str) -> list[float]:
    """Все числа из текста, которые правдоподобны как значение в единицах торга; с совпадающей единицей идут первыми.
    На шкале вариантов — номер распознанного варианта."""
    if card.target_zone.ordinal:
        i = option_index(card.target_zone, text)
        return [] if i is None else [float(i)]
    unit = card.target_zone.short_unit.lower()
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


def _has_marker(label: str, words: tuple[str, ...], low: str) -> bool:
    for phrase in EXCEPT.get(label, ()):
        low = low.replace(phrase, " ")
    return any(w.replace("ё", "е") in low for w in words)


def analyze(card: ScenarioCard, message: str) -> MoveAnalysis:
    low = message.lower().replace("ё", "е")
    labels = [label for label, words in {**MARKERS, **BATNA_MARKERS}.items() if _has_marker(label, words, low)]
    if RHETORIC.search(low):
        labels = [lb for lb in labels if lb not in ("interest_question", "empathy")]
        if "pressure" not in labels:
            labels.append("pressure")
    elif "?" in message and not labels and OPEN_QUESTION.search(low):
        labels.append("spin_situation")
    if any(w.replace("ё", "е") in low for w in WALK_AWAY_MARKERS):
        if not any(c in low for c in WALK_AWAY_CONDITIONAL):
            labels.append("walk_away")
        elif "batna_reference" not in labels:  # «если не снизите, откажемся от сделки» — угроза альтернативой, а не выход
            labels.append("batna_reference")
    found = values(card, message)
    proposed = found[0] if found else None
    if proposed is not None and OFFER.search(low) and "walk_away" not in labels:
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
    pos = card.target_zone.fmt(state.position)
    at = card.target_zone.fmt_at(state.position)
    labels = set(move.labels)
    if "manipulation" in labels:
        return f"Давайте без этих приёмов. Моя позиция прежняя: {pos}."
    if "batna_reference" in labels and labels & THREATS:
        return "Ссылка на альтернативу звучит как ультиматум. Объясните границу спокойно и предложите обмен условиями."
    if "pressure" in labels or "personal_attack" in labels:
        return "Давление не помогает. Объясните, что ваши условия дают моей стороне."
    if conceded:
        return f"Хорошо, могу сдвинуться: {pos}. Дальше нужны веские причины."
    if "interest_question" in labels and card.opponent_hidden_interests and state.trust >= 1:
        return f"Если честно, для меня важно другое: {card.opponent_hidden_interests[0]}."
    if {"boundary", "conditional_trade"} <= labels:
        return f"Граница понятна, обмен выглядит предметно. Пока я {at}: что именно вы готовы зафиксировать со своей стороны?"
    if {"batna_reference", "boundary"} <= labels:
        return "Понимаю вашу альтернативу и предел. Что должно измениться в моём варианте, чтобы он стал для вас лучше альтернативы?"
    if "batna_reference" in labels:
        return "Альтернатива понятна. Какие условия сделали бы нашу сделку для вас предпочтительнее?"
    if "boundary" in labels:
        return "Вы обозначили предел. Предложите обмен, который позволит не перейти эту границу."
    if "conditional_trade" in labels:
        return f"Условный обмен конструктивен. Пока я {at}: какую ценность получает каждая сторона?"
    if "concrete_offer" in move.labels or "accept" in move.labels:
        return f"Пока могу предложить {pos}. Обоснуйте, почему ваш вариант справедлив."
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


def batna_axes(moves: list[MoveAnalysis]) -> dict[str, int]:
    """Оценка BATNA по счётчикам меток, как в прототипе Артемия: четыре компонента и штраф за давление.

    У Артемия компоненты по 25 из 100 и штраф до 25 от суммы; здесь каждая ось 0–100, поэтому веса умножены на 4,
    а штраф (15 за ход с давлением, не больше 25) снимается с каждой оси.
    """
    def count(labels: set[str]) -> int:
        return sum(bool(labels & set(m.labels)) for m in moves)

    questions = count({"interest_question", "spin_situation", "spin_problem", "spin_implication", "spin_need_payoff"})
    arguments = count({"argument", "objective_criterion"})
    raw = {
        "сравнение с альтернативой": 100 * count({"batna_reference"}),
        "защита границы": 100 * count({"boundary", "walk_away"}),
        "обмен условиями": 72 * count({"conditional_trade"}) + 28 * count({"concrete_offer"}),
        "исследование интересов": 48 * questions + 28 * arguments,
    }
    penalty = min(25, 15 * count(THREATS))
    return {axis: max(0, min(100, v) - penalty) for axis, v in raw.items()}


ORDINAL_WORDING = {
    "Назовите конкретное предложение в единицах торга и объясните, почему оно справедливо.":
        "Назовите конкретный вариант условия и объясните, почему он справедлив.",
    "Назовите конкретное значение в единицах торга.": "Назовите конкретный вариант условия.",
}


def _say(card: ScenarioCard, text: str) -> str:
    return ORDINAL_WORDING.get(text, text) if card.target_zone.ordinal else text


def judge_offline(card: ScenarioCard, turns: list[tuple[str, MoveAnalysis]]) -> JudgeReport:
    """Разбор по правилам: оценки осей метода из доли подходящих меток (у BATNA по счётчикам), ключевые моменты из проблемных ходов."""
    moves = [m for _, m in turns]
    if card.method == "batna":
        axes = batna_axes(moves)
    else:
        axes = {a: _axis_score(a, moves) for a in rules.METHOD_AXES[card.method]}
    weak = min(axes, key=axes.get)
    moments = []
    for text, m in turns:
        if "batna_reference" in m.labels and THREATS & set(m.labels) and len(moments) < 3:
            moments.append(KeyMoment(quote=text, problem=f"В реплике {LABELS_RU['batna_threat']}.", better=BETTER["batna_threat"]))
    for label in ("personal_attack", "manipulation", "pressure", "vague"):
        for text, m in turns:
            if label in m.labels and len(moments) < 3 and all(k.quote != text for k in moments):
                moments.append(KeyMoment(quote=text, problem=f"В реплике {LABELS_RU[label]}.", better=_say(card, BETTER[label])))
    if not moments:
        good, _ = AXIS_LABELS[weak]
        text = next((t for t, m in turns if not good & set(m.labels)), turns[0][0])
        moments.append(KeyMoment(quote=text, problem=f"Здесь не хватило приёма «{weak}».", better=_say(card, AXIS_TIPS[weak])))
    hint = f"Слабее всего ось «{weak}» ({axes[weak]}/100). {_say(card, AXIS_TIPS[weak])} Пройдите этот же сценарий ещё раз или возьмите сценарий с методом «{METHOD_RU[card.method]}» посложнее."
    return JudgeReport(axes=axes, key_moments=moments, next_scenario_hint=hint)
