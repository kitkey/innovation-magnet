"""Страховки поверх разметки LLM. Слабая модель ставит метки, которых в реплике нет: вопрос о сроке становится предложением
с выдуманным числом, извинение — выходом из переговоров. Метки, от которых зависит исход сессии, здесь сверяются с текстом
реплики детерминированно:

1. Значение предложения берётся только из текста игрока: число (цифрами или прописью, с % или «процента») или вариант,
   который узнаёт распознаватель вариантов. Число, которого в реплике нет, обнуляется.
2. Вопрос (есть «?», а утверждений с предложением, согласием или выходом нет) не бывает предложением, согласием, уступкой,
   границей или выходом; ссылку на альтернативу и обмен условиями в вопросе оставляем, только если их видят маркеры.
3. accept остаётся, только если в утвердительном предложении есть явное согласие без оговорок («согласен», «договорились»,
   «по рукам»…); walk_away — только при явном выходе без условия («прекращаем переговоры», «переходим к резервному»…).
4. Предложение, которое закрыло бы сделку (не лучше для игрока, чем текущая позиция собеседника), требует явного
   «предлагаю / готовы / давайте» или согласия: иначе игрок просто повторил число собеседника.
5. Давление, которое видят маркеры, важнее «вопроса об интересах» или «обмена» от LLM; извинение без маркеров давления
   давлением не считается.
"""
import re
from difflib import SequenceMatcher

from ..schemas import MoveAnalysis, ScenarioCard
from . import offline, rules

THREATS = {"pressure", "personal_attack", "manipulation"}
NOT_IN_QUESTION = {"concrete_offer", "accept", "walk_away", "concession", "boundary"}
QUESTION_NEEDS_MARKER = {"batna_reference", "conditional_trade"}
SOFT_UNDER_PRESSURE = {"interest_question", "conditional_trade", "empathy", "concession"}
QUESTIONS = {"interest_question", "spin_situation", "spin_problem", "spin_implication", "spin_need_payoff"}

SENTENCE = re.compile(r"[^.!?…]+(?:[.!?…]+|$)")
ACCEPT = re.compile(
    r"(?<!не )(?<![а-яa-z])(согласен|согласна|согласны|соглашаюсь|соглашаемся|принимаю|принимаем|договорились|по рукам|"
    r"так и сделаем|так и поступим|так и запишем|решено|заметано|годится|идет|меня устраивает|нас устраивает|"
    r"это устраивает|устраивает|меня устроит|нас устроит|подходит|пусть будет так|подписываем|беру|берем)(?![а-яa-z])"
)
# «Речь идёт о…», «идёт работа» — не согласие: «идёт» считается, только если стоит в начале предложения или после «хорошо,»
IDET_OK = re.compile(r"(^|(хорошо|ладно|ок|окей|да)[,\s]+)идет(?![а-яa-z])")
ACCEPT_BUT = (" но ", ", но", "однако", "только если", "при условии", "если ", "если,")
WALK_AWAY = re.compile(
    r"(прекраща|прекрат|заканчива|законч|заверша|заверш|сворачива|сверн)\w*\s+(наши\s+|эти\s+)?(переговор|разговор|обсуждени)|"
    r"(уйд|уход|перейд|переход|переключ|обратимся|обращаемся|пойд|идем)\w*\s+(\w+\s+)?(к|на)\s+(друг|резерв|альтернатив|конкурент|следующ|втор)|"
    r"(отда|отдад|сда|сдад|переда)\w*\s+(\w+\s+)?(друг|следующ|втор)|"
    r"(выбира|выбер|выбра|принима|прим|бер|возьм|соглаша|соглаш)\w*\s+(\w+\s+)?(друг|альтернатив|резерв|втор)\w*\s*(оффер|предложени|поставщик|подрядчик|вариант|заказ|площадк|компани)|"
    r"(бер|возьм)\w*\s+(\w+\s+)?(заказ|оффер|предложени|контракт)\w*\s+(\w+\s+)?(друг|втор|конкурент)|"
    r"отказ\w*\s+от\s+(сделк|предложени|оффер|контракт|договор|переговор)|"
    r"(сделки|договора|соглашения)\s+не\s+будет|без\s+сделки|расходимся|на\s+этом\s+(все|закончим|остановимся)|"
    r"(не|нет смысла)\s+(будем|станем)\s+(заключать|подписывать|продолжать)"
)
WALK_CONDITIONAL = ("если", "иначе", "в случае", "либо", "или вы", "пока не", "до тех пор")
LATER = re.compile(r"(обсуд|созвон|встрет|вернемся|вернусь|подума|позже|завтра|на неделе|продолж)")
TRADE_WORDS = ("в обмен", "взамен", "при условии")
APOLOGY = ("извините", "извиняюсь", "простите", "прошу прощения", "погорячил", "не хотел вас задеть", "не хотела вас задеть",
           "был резок", "была резка", "прозвучало резко")

UNITS = {"ноль": 0, "один": 1, "одна": 1, "одно": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7,
         "восемь": 8, "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
         "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19}
TENS = {"двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90}
HUNDREDS = {"сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500, "шестьсот": 600, "семьсот": 700,
            "восемьсот": 800, "девятьсот": 900}
OBLIQUE = {"одного": 1, "одной": 1, "одному": 1, "одним": 1, "двух": 2, "двум": 2, "двумя": 2, "трех": 3, "трем": 3, "тремя": 3,
           "четырех": 4, "четырем": 4, "четырьмя": 4, "полтора": 1.5, "полутора": 1.5, "сорока": 40, "ста": 100}


def _word_values() -> dict[str, float]:
    out: dict[str, float] = {**UNITS, **TENS, **HUNDREDS, **OBLIQUE}
    for w, v in [*UNITS.items(), *TENS.items()]:
        if w.endswith("ь") and v >= 5:  # пять → пяти, пятью; двадцать → двадцати, двадцатью
            out.setdefault(w[:-1] + "и", v)
            out.setdefault(w[:-1] + "ью", v)
        if w.endswith("десят"):  # пятьдесят → пятидесяти
            out.setdefault(w.replace("ьдесят", "идесяти"), v)
    return out


WORD_VALUES = _word_values()
NUMBER_WORDS = re.compile(r"(?<![а-яa-z])(" + "|".join(sorted(WORD_VALUES, key=len, reverse=True)) + r")(?![а-яa-z])"
                          r"(?:\s+(" + "|".join(sorted((w for w, v in WORD_VALUES.items() if v < 10), key=len, reverse=True)) + r")(?![а-яa-z]))?")


def spell_digits(text: str, unit_stems: tuple[str, ...] = ("процент", "%", "тыс", "млн")) -> str:
    """Числа прописью — цифрами, если за ними идёт единица торга: «в два процента» → «в 2 процента»,
    «двадцать пять тысяч» → «25 тысяч». Без единицы («два варианта», «один вопрос») слова не трогаем."""
    low = text.lower().replace("ё", "е")

    def sub(m: re.Match) -> str:
        after = low[m.end():].lstrip()
        if not any(after.startswith(u) for u in unit_stems):
            return m.group(0)
        v = WORD_VALUES[m.group(1)]
        if m.group(2) and v >= 20 and v % 10 == 0:
            return _fmt(v + WORD_VALUES[m.group(2)])
        if m.group(2):
            return m.group(0)
        return _fmt(v)

    return NUMBER_WORDS.sub(sub, low)


def _fmt(v: float) -> str:
    return str(int(v)) if v == int(v) else str(v)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE.findall(text.replace("\n", ". ")) if s.strip(" .!?…")]


def _low(text: str) -> str:
    return text.lower().replace("ё", "е")


def named_values(card: ScenarioCard, text: str) -> list[float]:
    """Значения в единицах торга, которые игрок действительно назвал: числа цифрами и прописью или распознанный вариант."""
    if card.target_zone.ordinal:
        return offline.values(card, text)
    unit = card.target_zone.short_unit.lower().replace("ё", "е")
    stems = ("процент", "%", "тыс", "млн", *(w[:3] for w in re.findall(r"[а-яa-z]+", unit) if len(w) > 2))
    return offline.values(card, spell_digits(text, stems))


def value_named(card: ScenarioCard, text: str, value: float) -> bool:
    return any(abs(v - value) < 1e-6 for v in named_values(card, text))


def has_offer_statement(card: ScenarioCard, text: str) -> bool:
    """Есть утвердительное предложение с предложением, согласием, выходом или значением в единицах торга."""
    for s in sentences(text):
        if s.endswith("?"):
            continue
        low = _low(s)
        if offline.OFFER.search(low) or accept_in(low) or WALK_AWAY.search(low) or named_values(card, s):
            return True
    return False


def is_question(card: ScenarioCard, text: str) -> bool:
    return "?" in text and not has_offer_statement(card, text)


def accept_in(sentence_low: str) -> bool:
    m = ACCEPT.search(sentence_low)
    if not m:
        return False
    if m.group(1) == "идет" and not IDET_OK.search(sentence_low.strip()):
        return any(m2.group(1) != "идет" for m2 in ACCEPT.finditer(sentence_low))
    return True


def explicit_accept(text: str) -> bool:
    """Явное согласие без оговорок в утвердительном предложении: «Договорились», «По рукам: 10%», «Хорошо, согласен»."""
    for s in sentences(text):
        low = " " + _low(s)
        if s.endswith("?") or any(b in low for b in ACCEPT_BUT):
            continue
        if accept_in(low.strip()):
            return True
    return False


def explicit_walk_away(text: str) -> bool:
    """Явный выход без условия: «Прекращаем переговоры», «Переходим к резервному поставщику», «Тогда без сделки»."""
    for s in sentences(text):
        low = _low(s)
        if s.endswith("?") or any(c in low for c in WALK_CONDITIONAL):
            continue
        m = WALK_AWAY.search(low)
        if m and not re.search(r"(?<![а-яa-z])не\s+$", low[max(0, m.start() - 4):m.start()]):
            return True
    return False


def apology(text: str) -> bool:
    low = _low(text)
    return any(a in low for a in APOLOGY)


def reconcile(card: ScenarioCard, message: str, move: MoveAnalysis, position: float | None = None) -> MoveAnalysis:
    """Согласует разметку LLM с текстом реплики по правилам из описания модуля. position — текущая позиция собеседника.

    Метки делятся на три группы. Метки исхода (accept, walk_away, concrete_offer с закрывающим значением) требуют явных слов.
    Метки, которые Lite ставит почти всегда (batna_reference, conditional_trade, concession), требуют опоры в тексте:
    маркера, названной альтернативы игрока или значения. Метки, которые маркеры видят надёжно (давление, извинение,
    вопрос, предложение с «предлагаю» и числом, явный выход), добавляются, если LLM их пропустила.
    """
    labels = list(dict.fromkeys(move.labels))
    off = offline.analyze(card, message)
    marked = set(off.labels)
    question = is_question(card, message)
    low = _low(message)

    def drop(*names):
        for n in names:
            while n in labels:
                labels.remove(n)

    def add(name):
        if name not in labels:
            labels.append(name)

    walking = explicit_walk_away(message) and not question
    if "walk_away" in labels and not walking:
        drop("walk_away")
    if walking:
        add("walk_away")
    if "accept" in labels and not explicit_accept(message):
        drop("accept")
    if not question and not walking and explicit_accept(message) and not LATER.search(low):
        add("accept")  # «Хорошо, договорились» — согласие, даже если LLM его не увидела; «договорились созвониться» — нет
    if question:
        drop(*NOT_IN_QUESTION)
        drop(*(QUESTION_NEEDS_MARKER - marked))
        if not set(labels) & QUESTIONS:
            for lb in [lb for lb in off.labels if lb in QUESTIONS] or ["spin_situation"]:
                add(lb)
    if "batna_reference" in labels and not ("batna_reference" in marked or walking or names_user_batna(card, low)):
        drop("batna_reference")
    if "batna_reference" in marked and "batna_reference" not in labels and not question:
        add("batna_reference")
    if "conditional_trade" in labels and "conditional_trade" not in marked and "если" not in low:
        drop("conditional_trade")
    if not question and not walking and not marked & THREATS and (
            ("conditional_trade" in marked and (named_values(card, message) or any(w in low for w in TRADE_WORDS)))
            or (re.search(r"(?<![а-яa-z])если(?! не)", low) and named_values(card, message))):
        add("conditional_trade")  # «Если подпишете договор на пять лет, дадим скидку 3%»
    if "?" not in message:  # вопрос без вопроса: «Мы можем подключить мощность…» Lite размечает как вопрос о ситуации
        drop(*(QUESTIONS - marked))

    threat = marked & {"pressure", "personal_attack"}
    if threat and not set(labels) & THREATS:
        drop(*SOFT_UNDER_PRESSURE)
        for t in sorted(threat):
            add(t)
    elif apology(message) and not threat:
        drop("pressure", "personal_attack", "walk_away")
    if not threat and (apology(message) or "empathy" in marked):
        add("empathy")
    if "manipulation" in marked:
        add("manipulation")

    found = named_values(card, message)
    value = move.proposed_value
    if value is not None and not value_named(card, message, value):
        value = None
    if value is None and found and set(labels) & {"concrete_offer", "accept", "conditional_trade", "concession"}:
        value = found[0]
    if question:
        value = None
    if "concession" in labels and value is None and not marked & {"concession", "conditional_trade"}:
        drop("concession")
    offer_marker = bool(offline.OFFER.search(low)) or explicit_accept(message)
    if found and offline.OFFER.search(low) and not question and not walking:  # «Предлагаю скидку в два процента»
        add("concrete_offer")
        value = value if value is not None else found[0]
    if "concrete_offer" in labels:
        if value is None and not offer_marker:
            drop("concrete_offer")
        elif value is not None and position is not None and not rules.better_for_user(card, value, position)                 and not closing_offer(card, message, value):
            drop("concrete_offer")  # игрок повторил число собеседника, а не согласился на него

    details = [d for d in move.mentioned_details if d in card.mandatory_details and offline.detail_mentioned(d.replace("ё", "е"), low)]
    details += [d for d in off.mentioned_details if d not in details]
    drop("mandatory_detail", "vague")
    if details:
        labels.append("mandatory_detail")
    if not [lb for lb in labels if lb != "mandatory_detail"]:
        rest = [lb for lb in off.labels if lb not in labels and lb not in ("concrete_offer", "accept", "walk_away", "mandatory_detail")]
        labels = (rest or ["vague"]) + labels
    return MoveAnalysis(labels=labels, mentioned_details=details, proposed_value=value)


CLOSING_OFFER = re.compile(r"(?<!не )(?<![а-яa-z])(предлагаю|предлагаем|давайте|давай|зафиксируем|фиксируем|остановимся на|"
                           r"готов\w* (на|принять|согласиться|подписать|дать|пойти))")


def closing_offer(card: ScenarioCard, message: str, value: float) -> bool:
    """Предложение, которое закрыло бы сделку, засчитывается только при явном согласии или если в том же утвердительном
    предложении, где названо значение, стоит «предлагаю / давайте / готовы на»."""
    if explicit_accept(message):
        return True
    for s in sentences(message):
        if not s.endswith("?") and CLOSING_OFFER.search(_low(s)) and value_named(card, s, value):
            return True
    return False


def names_user_batna(card: ScenarioCard, low: str) -> bool:
    """Игрок своими словами назвал свою альтернативу из карточки: не меньше двух основ её слов."""
    return bool(card.user_batna.strip()) and offline.detail_mentioned(card.user_batna.lower().replace("ё", "е"), low)


ROLE_PREFIX = re.compile(r"(^|\n|\s)(пользователь|игрок|user|вы|я)\s*:", re.IGNORECASE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%]", " ", text.lower().replace("ё", "е"))).strip()


def _shared(a: str, b: str) -> int:
    return SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b)).size


def strip_player_voice(reply: str, player_lines: list[str]) -> str:
    """Убирает из ответа собеседника то, что сказал игрок: подпись «Пользователь:» и всё после неё, теги реплики
    и предложения, которые почти целиком повторяют реплику игрока (модель начинает ответ с его слов или говорит за него)."""
    text = re.sub(r"</?user_message>", " ", reply)
    m = ROLE_PREFIX.search(text)
    if m:
        text = text[:m.start()]
    players = [_norm(p) for p in player_lines if p.strip()]
    keep = []
    for s in sentences(text):
        ns = _norm(s)
        if len(ns) >= 15 and any(_shared(ns, p) >= max(15, 0.6 * len(ns)) for p in players):
            continue
        keep.append(s)
    return " ".join(keep).strip().strip("«»\"").strip()


FINALITY = re.compile(r"(последн\w* предложени|окончательн|не можем (опуститься |уступить |снизить )?(ниже|больше)|ниже не (можем|опуст)|это наш предел|дальше не (уступ|двига))", re.I)


def strip_repeats(reply: str, previous: list[str]) -> str:
    """Убирает из ответа собеседника предложения, которые почти дословно повторяют его прошлые реплики:
    слабая модель начинает каждый ответ одной и той же заготовкой."""
    prev = [_norm(p) for p in previous if p.strip()]
    keep = []
    for s in sentences(reply):
        ns = _norm(s)
        if len(ns) >= 20 and any(_shared(ns, p) >= 0.7 * len(ns) for p in prev):
            continue
        keep.append(s)
    return " ".join(keep).strip()


def claims_finality(reply: str) -> bool:
    """«Это наше последнее предложение» — позицию двигают правила, собеседник не объявляет предел сам."""
    return bool(FINALITY.search(reply))
