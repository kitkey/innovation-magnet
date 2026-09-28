"""Генерация карточки сценария по описанию пользователя.

Инструкция модели собрана из блоков: общие правила и по блоку на каждое поле карточки (что это, откуда брать,
формат, типичные ошибки, хороший и плохой пример). Из тех же блоков берутся описания полей схемы, которую
Instructor отдаёт модели, поэтому инструкция и схема не расходятся.

Модель заполняет только содержательные поля. Служебные (аватар, фиксация организацией, наставления и подсказки
автора) в схему не входят, идентификаторов в ней нет. После ответа карточка проходит проверку: безопасные ошибки
чинятся (перевёрнутая зона, регистр реплики, лишние поля), остальные возвращаются модели с объяснением,
а если она не справилась, пользователь получает понятную причину вместо испорченной карточки.
"""
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .schemas import DOMAIN_ICONS, ScenarioCard, TargetZone


@dataclass(frozen=True)
class Block:
    key: str
    title: str
    short: str
    body: str
    good: str = ""
    bad: str = ""

    def render(self) -> str:
        parts = [f"## {self.key} — {self.title}", self.body]
        if self.good:
            parts.append(f"Хорошо: {self.good}")
        if self.bad:
            parts.append(f"Плохо: {self.bad}")
        return "\n".join(parts)


INTRO = """Ты собираешь карточку учебного сценария переговоров для тренажёра. Пользователь описал свою ситуацию своими словами; \
по карточке тренажёр разыграет разговор: собеседника играет модель, игрок — сам пользователь.

Общие правила:
- Игрок — это автор описания. «Вы» в карточке — всегда игрок, собеседник — вторая сторона разговора.
- Все тексты по-русски, конкретно, с числами и фактами из описания. Не пиши общих слов вроде «добиться выгодных условий».
- Чего нет в описании, дополни правдоподобно и в духе ситуации: причину позиции собеседника, его интересы, альтернативы сторон. \
Не придумывай факты, которые спорят с описанием.
- Если описание противоречиво (например, две разные цены), выбери один вариант и в конце context одной фразой скажи, что выбрано и почему.
- Все поля обязательны, кроме opponent_name, если имя нельзя подобрать. Верни только поля схемы."""

ZONE_RULES = """## target_zone — целевая зона, самое важное поле
Тренажёр торгуется по одному числу. Сначала определи, что это за число, и в какую сторону оно лучше для игрока: player_wants.
- unit: предмет торга и единица через запятую, предмет первым. «аренда квартиры в месяц, тыс. руб.», «срок сдачи презентации, рабочих дней», \
«рост цены поставки, %», «скидка на партию, %», «сколько экранов делает Дима, экранов». Без запятой и без единицы нельзя. \
Плохо: «руб.», «цена», «%», «зарплата, 150».
- user_start: первое число, которое игрок назовёт вслух. Оно лучше для игрока, чем вся зона, или равно её лучшему краю. \nСмелее его цели, но в пределах разумного. Частая ошибка: поставить в user_start предел игрока («максимум 32», «минимум 5») — \nпредел это худший край зоны, а не старт.
- opponent_start: с чего начинает собеседник, его первое требование или предложение из описания.
- zone_min и zone_max: диапазон, в котором сделка для игрока хорошая. Край зоны, худший для игрока, — его граница: \
хуже неё лучше уйти к альтернативе. Лучший край — реалистичный хороший итог.
- Порядок чисел строгий. Если player_wants = more (игроку лучше больше: зарплата, срок, бюджет, цена продажи): \
opponent_start < zone_min <= zone_max <= user_start. Если player_wants = less (игроку лучше меньше: цена покупки, \
рост цены, срок исполнения для заказчика, аренда для арендатора): user_start <= zone_min <= zone_max < opponent_start.
- Зона всегда между стартами и не включает старт собеседника: иначе торговаться не о чем. Старт игрока может совпасть с лучшим краем зоны.
- Все пять чисел в одной единице из unit. Если в описании «180 тысяч», а unit в тыс. руб., пиши 180, а не 180000.
- Не путай предмет торга с количеством товара: в «скидка на 12 станков» торгуются о скидке в %, 12 — объём заказа, он идёт в context.
- Если в описании нет какого-то числа, выведи его из остальных: старт игрока чуть смелее его цели, граница зоны — там, \
где альтернатива игрока становится выгоднее.
Пример, player_wants = less: игрок заказывает сайт, студия просит 180 тыс., игрок рассчитывал на 120 и готов максимум на 150. \
unit «стоимость сайта, тыс. руб.», user_start 120, zone_min 130, zone_max 150, opponent_start 180.
Пример, player_wants = more: директор даёт на обучение команды 50 тыс., нужно 90, без 70 курс не собрать. \
unit «бюджет на обучение команды, тыс. руб.», user_start 90, zone_min 70, zone_max 85, opponent_start 50.
Плохо: user_start 50 и opponent_start 90 во втором примере (перепутаны стороны); зона 50–90 (включает старт собеседника); \
user_start 12 при торге о скидке в %, если 12 — это число заказанных станков."""

FIELDS: list[Block] = [
    Block("title", "название сценария",
          "короткое название ситуации, 3–7 слов, не имя человека",
          "Короткое название, по которому сценарий найдут в списке: предмет разговора и с кем. Не имя собеседника и не название поля.",
          "«Цена сайта со студией», «Бюджет на обучение с директором»",
          "«Иван Петров», «Переговоры», «Сценарий 1»"),
    Block("domain", "сфера",
          "сфера жизни или работы, 1–3 слова",
          "Область, к которой относится ситуация: «Закупки», «Работа в команде», «Аренда жилья», «Трудоустройство», «Учёба».",
          "«Закупки»", "«переговоры о цене» (это тема, а не сфера)"),
    Block("domain_icon", "значок группы",
          "значок сферы из списка: " + ", ".join(DOMAIN_ICONS),
          "Значок, под которым сценарий попадёт в группу на главной. Одно имя из списка: procurement — закупки и поставщики, "
          "team — работа в команде, руководитель, коллеги; project — проекты и заказчики, фриланс; residents — резиденты, аренда площадей "
          "для бизнеса; career — карьера, оффер, зарплата; sales — продажи, магазин; service — клиентский сервис, поддержка, жалобы; "
          "finance — финансы, бюджет, банк; legal — юристы, договоры; logistics — логистика, доставка, склад; production — производство; "
          "it — IT и разработка; hr — найм и кадры; marketing — маркетинг и реклама; government — госорганы; startup — стартап, инвесторы; "
          "everyday — быт, соседи, аренда жилья, учёба. Выбирай по сфере, а не по словам в тексте.",
          "domain «Аренда жилья» → everyday", "придумывать своё имя значка"),
    Block("topic", "тема",
          "о чём разговор, одно предложение",
          "Одно предложение: о чём конкретно торгуются и почему именно сейчас.",
          "«Студия оценила сайт в 180 тыс. руб., а в бюджете 120»", "«переговоры о цене»"),
    Block("user_role", "роль игрока",
          "кто игрок в этой ситуации, с уточнением",
          "Должность или положение игрока из описания, с уточнением, где он работает или кем приходится собеседнику.",
          "«Маркетолог сети из пяти автомоек, отвечает за новый сайт»", "«сотрудник», «я»"),
    Block("user_goal", "цель игрока",
          "чего игрок хочет добиться, с числами торга и запасными вариантами",
          "Что игрок хочет получить, с числами из target_zone: к чему стремится, ниже или выше чего не соглашается, "
          "чем готов расплатиться за уступку (объём, предоплата, пересмотр через полгода).",
          "«Уложить сайт в 130–150 тыс. руб. вместо 180; в обмен можно отказаться от блога или сдвинуть срок на месяц»",
          "«договориться о цене», «получить скидку»"),
    Block("opponent_role", "роль собеседника",
          "кто собеседник, с уточнением",
          "Кто вторая сторона: должность и организация или отношение к игроку.",
          "«Руководитель веб-студии», «Начальник отдела продаж»", "«поставщик», «HR» без уточнения"),
    Block("opponent_name", "имя собеседника",
          "вымышленные имя и фамилия собеседника; пол совпадает с voice; не имя известного человека",
          "Имя и фамилия, как человека называют в разговоре. Вымышленные, русские, если описание не говорит иного. "
          "Если в описании есть имя собеседника (например, Дима), оставь его и добавь фамилию. Пол имени совпадает с voice. "
          "Не имена знаменитостей и не штампы вроде «Иван Петров», «Иван Иванов».",
          "«Марина Лаптева», «Дмитрий Клёнов»", "«Иван Петров», «Коммерческий директор»"),
    Block("voice", "голос собеседника",
          "female или male, по полу собеседника",
          "Пол собеседника: female или male. Если в описании «хозяйка», «она», «руководительница» — female. "
          "Если пол не ясен, выбери любой и подбери имя того же пола."),
    Block("opponent_goal", "цель собеседника",
          "чего собеседник хочет, с его числом",
          "Чего добивается собеседник и почему, с его стартовым числом.",
          "«Получить 180 тыс. руб.: студия считает 90 часов по 2 000 руб.»","«получить максимальную прибыль»"),
    Block("opponent_hidden_interests", "скрытые интересы собеседника",
          "2–3 конкретных интереса, о которых собеседник не говорит сам",
          "То, что собеседник не говорит сам, но раскроет, если игрок правильно спросит: реальная причина, "
          "ограничение, на чём можно договориться. Каждый интерес — конкретный факт, не повтор его цели.",
          "«боится потерять крупного клиента перед сезоном», «ему важнее предоплата, чем цена: кассовый разрыв»",
          "повтор opponent_goal; «сохранить отношения» без конкретики"),
    Block("user_batna", "альтернатива игрока",
          "что игрок сделает, если не договорятся; с числами",
          "Что будет у игрока без соглашения: другой поставщик, другой оффер, переезд, жалоба преподавателю. "
          "С числами и минусами из описания. Это действие, а не число торга.",
          "«Заказать сайт у фрилансера за 110 тыс. руб., но без гарантий по сроку и поддержки»",
          "«15%», «договориться о цене»"),
    Block("opponent_batna", "альтернатива собеседника",
          "что собеседник сделает, если не договорятся",
          "Что будет у собеседника без соглашения: найдёт другого клиента, отдаст задачу коллеге, сдаст квартиру дороже. "
          "Дополни правдоподобно, если в описании нет.",
          "«Ждать другого заказа, хотя два дизайнера студии сейчас без загрузки»", "«3%», «180 тыс.»"),
    Block("context", "контекст",
          "3–6 предложений от второго лица: кто игрок, что произошло, откуда числа, что будет без соглашения",
          "Ситуация для игрока, от второго лица («Вы…»): кто он, что произошло, почему разговор сейчас, откуда взялись числа "
          "из target_zone (бюджет, рынок, расчёт), что будет без соглашения. Перескажи описание своими словами, а не копируй его "
          "и не пиши от первого лица «я», «мы».",
          "«Вы отвечаете за маркетинг сети из пяти автомоек. Студия оценила новый сайт в 180 тыс. руб.: 90 часов по 2 000. "
          "Директор выделил 120, до 150 вы готовы дойти, если сайт заработает до сезона…»",
          "копия описания с «я хочу…»; контекст без чисел"),
    Block("mandatory_details", "обязательные детали",
          "2–4 факта, которые игрок должен произнести в разговоре",
          "Короткие фразы, 2–6 слов каждая: факты и условия, которые хороший переговорщик обязательно назовёт в этом разговоре. "
          "Тренажёр проверяет, прозвучали ли они.",
          "«запуск до начала сезона», «блог во второй версии»", "«скидка», «цена», «сайт»; целые предложения из описания"),
    Block("opening", "первая реплика собеседника",
          "первая фраза собеседника вслух, 2–3 предложения, со стартовым числом opponent_start цифрами; без названия должности",
          "Что собеседник говорит первым, как живой человек в своём характере. Обозначает суть вопроса и свою стартовую позицию: "
          "число opponent_start цифрами и словами разговора, а не «моя стартовая позиция». Не называет свою должность, "
          "не представляется, не раскрывает скрытые интересы, не говорит за игрока. Начинается с заглавной буквы.",
          "«Смету я вам отправил: 180 тысяч, и это без запаса. Дешевле можно, но тогда давайте решать, что выкидываем.»",
          "«Я руководитель студии…»; «Моя стартовая позиция 180»; реплика без числа; реплика со словами, которые должен сказать игрок"),
    Block("method", "метод, который тренируем",
          "spin, harvard, batna или free",
          "batna — у игрока есть конкретная альтернатива и важно не согласиться на худшее (закупки, офферы, аренда). "
          "spin — игрок убеждает собеседника, который не видит проблемы или считает цену завышенной (продажа, защита сметы). "
          "harvard — важны отношения и интересы обеих сторон, нужен взаимовыгодный вариант (руководитель, команда, соседи). "
          "free — ни один метод явно не подходит."),
    Block("style", "стиль собеседника",
          "hard, cooperative, avoiding, pressing или emotional",
          "По описанию характера собеседника. hard — стоит на своём, уступает редко. cooperative — готов искать решение. "
          "avoiding — уходит от разговора, ссылается на занятость. pressing — давит сроками и ультиматумами. "
          "emotional — вспыльчив, обижается. Нет описания — hard для деловых сделок, cooperative для коллег."),
    Block("tone", "тон реплик",
          "neutral, friendly, strict или skeptical",
          "Как собеседник говорит: neutral, friendly (дружелюбно), strict (строго, по-деловому), skeptical (с недоверием)."),
    Block("difficulty", "сложность",
          "easy, medium или hard",
          "easy — собеседник заинтересован договориться и уступает до лучшего края зоны. medium — обычный случай. "
          "hard — у собеседника сильная альтернатива или жёсткий характер, уступает только до границы зоны. Нет данных — medium."),
    Block("max_turns", "лимит ходов",
          "число ходов игрока, от 6 до 14, обычно 10",
          "Сколько реплик у игрока. 8 для простого торга по одному числу, 10 обычно, 12–14 если надо выяснить много интересов."),
]

FOOTER = """Перед ответом проверь себя: title — не имя; unit с запятой; порядок пяти чисел соответствует player_wants; \
зона не включает opponent_start; opening содержит opponent_start цифрами и не называет должность; context от второго лица \
и объясняет, откуда числа; coach_tips и hints не заполняй — их пишет автор сценария."""

SHORT = {b.key: b.short for b in FIELDS}


def system_prompt() -> str:
    return "\n\n".join([INTRO, ZONE_RULES, *(b.render() for b in FIELDS), FOOTER])


ENUM_RU = {
    "difficulty": {"лёгкая": "easy", "легкая": "easy", "средняя": "medium", "сложная": "hard", "трудная": "hard"},
    "tone": {"нейтральный": "neutral", "дружелюбный": "friendly", "строгий": "strict", "скептичный": "skeptical", "скептический": "skeptical"},
    "style": {"жёсткий": "hard", "жесткий": "hard", "сотрудничающий": "cooperative", "уклоняющийся": "avoiding", "давящий": "pressing",
              "эмоциональный": "emotional", "competitive": "hard", "collaborative": "cooperative"},
    "method": {"свободный": "free", "гарвардский": "harvard", "none": "free"},
    "voice": {"женский": "female", "мужской": "male", "woman": "female", "man": "male"},
}
FIELD_RU = {"title": "название", "domain": "сфера", "topic": "тема", "user_role": "ваша роль", "user_goal": "ваша цель",
            "opponent_role": "роль собеседника", "opponent_goal": "цель собеседника", "target_zone": "целевая зона",
            "context": "контекст", "unit": "предмет и единица торга", "player_wants": "направление торга"}


class GeneratedZone(BaseModel):
    player_wants: Literal["more", "less"] = Field(description="more — игроку лучше большее число, less — меньшее")
    unit: str = Field(description="предмет торга и единица через запятую, предмет первым: «аренда в месяц, тыс. руб.»")
    user_start: float = Field(description="с чего игрок открывает торг, в единице unit")
    zone_min: float = Field(description="меньший край целевой зоны игрока")
    zone_max: float = Field(description="больший край целевой зоны игрока")
    opponent_start: float = Field(description="первое требование собеседника, в единице unit")

    @model_validator(mode="after")
    def _check(self):
        self.unit = self.unit.strip().strip(",").strip()
        if not self.unit or not re.search(r"[^\W\d_]|%", self.unit):
            raise ValueError("unit пустой: напиши предмет торга и единицу через запятую, например «аренда в месяц, тыс. руб.»")
        if "," not in self.unit:
            raise ValueError(f"unit «{self.unit}» без запятой: нужен предмет торга и единица через запятую, например «скидка на партию, %»")
        if self.zone_min > self.zone_max:
            self.zone_min, self.zone_max = self.zone_max, self.zone_min
        u, o, lo, hi = self.user_start, self.opponent_start, self.zone_min, self.zone_max
        if u == o:
            raise ValueError(f"user_start и opponent_start равны ({u:g}): стороны должны начинать с разных чисел")
        if self.player_wants == "more" and u < o:
            raise ValueError(f"player_wants = more, значит user_start должен быть больше opponent_start, а сейчас {u:g} и {o:g}: "
                             "проверь, не перепутаны ли стороны или направление")
        if self.player_wants == "less" and u > o:
            raise ValueError(f"player_wants = less, значит user_start должен быть меньше opponent_start, а сейчас {u:g} и {o:g}: "
                             "проверь, не перепутаны ли стороны или направление")
        more = self.player_wants == "more"
        best = hi if more else lo
        if (u < best) if more else (u > best):
            # частая ошибка модели: старт игрока ставит на его предел, внутрь зоны; открывается он с лучшего края зоны
            self.user_start = u = best
        if (lo <= o) if more else (hi >= o):
            if (hi <= o) if more else (lo >= o):
                raise ValueError(f"целевая зона {lo:g}–{hi:g} выходит за стартовые позиции {min(u, o):g} и {max(u, o):g}: "
                                 "она лежит за стартом собеседника, а должна быть между стартами")
            raise ValueError(f"целевая зона {lo:g}–{hi:g} включает старт собеседника {o:g}: граница зоны должна быть лучше для игрока, "
                             "чем старт собеседника")
        return self

    def to_zone(self) -> TargetZone:
        return TargetZone(unit=self.unit, user_start=self.user_start, zone_min=self.zone_min, zone_max=self.zone_max, opponent_start=self.opponent_start)


class GeneratedCard(BaseModel):
    """Схема для модели. Имена полей говорящие (title вместо name), служебных полей и идентификаторов нет."""
    title: str = Field(min_length=1, description=SHORT["title"])
    domain: str = Field(min_length=1, description=SHORT["domain"])
    domain_icon: str = Field(default="", description=SHORT["domain_icon"])
    topic: str = Field(min_length=1, description=SHORT["topic"])
    user_role: str = Field(min_length=1, description=SHORT["user_role"])
    user_goal: str = Field(min_length=1, description=SHORT["user_goal"])
    opponent_role: str = Field(min_length=1, description=SHORT["opponent_role"])
    opponent_name: str = Field(default="", description=SHORT["opponent_name"])
    voice: Literal["female", "male"] = Field(default="female", description=SHORT["voice"])
    opponent_goal: str = Field(min_length=1, description=SHORT["opponent_goal"])
    opponent_hidden_interests: list[str] = Field(default_factory=list, description=SHORT["opponent_hidden_interests"])
    user_batna: str = Field(default="", description=SHORT["user_batna"])
    opponent_batna: str = Field(default="", description=SHORT["opponent_batna"])
    target_zone: GeneratedZone = Field(description="целевая зона: одно число торга, направление и пять чисел в одной единице")
    context: str = Field(min_length=1, description=SHORT["context"])
    mandatory_details: list[str] = Field(default_factory=list, description=SHORT["mandatory_details"])
    opening: str = Field(default="", description=SHORT["opening"])
    method: Literal["spin", "harvard", "batna", "free"] = Field(default="free", description=SHORT["method"])
    style: Literal["hard", "cooperative", "avoiding", "pressing", "emotional"] = Field(default="hard", description=SHORT["style"])
    tone: Literal["neutral", "friendly", "strict", "skeptical"] = Field(default="neutral", description=SHORT["tone"])
    difficulty: Literal["easy", "medium", "hard"] = Field(default="medium", description=SHORT["difficulty"])
    max_turns: int = Field(default=10, description=SHORT["max_turns"])

    @field_validator("difficulty", "tone", "style", "method", "voice", mode="before")
    @classmethod
    def _enum_ru(cls, v, info):
        if isinstance(v, str):
            s = v.strip().lower()
            return ENUM_RU[info.field_name].get(s, s)
        return v

    @field_validator("domain_icon", mode="before")
    @classmethod
    def _icon(cls, v):
        """Незнакомый значок не повод проваливать генерацию: пусто значит «подобрать по сфере»."""
        v = str(v or "").strip().lower()
        return v if v in DOMAIN_ICONS else ""

    @field_validator("opponent_hidden_interests", "mandatory_details", mode="before")
    @classmethod
    def _list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v = re.split(r"[\n;]+", v)
        out: list[str] = []
        for x in v:
            x = str(x).strip(" .•-«»\"")
            if x and x.lower() not in {y.lower() for y in out}:
                out.append(x)
        return out

    @field_validator("max_turns", mode="before")
    @classmethod
    def _turns(cls, v):
        try:
            return max(6, min(14, int(float(v))))
        except (TypeError, ValueError):
            return 10


def _numbers(text: str) -> list[float]:
    """Числа из реплики: «35 000», «12,5», «35 тысяч» → 35000, 12.5, 35."""
    joined = re.sub(r"(?<=\d)[\s  ](?=\d{3}\b)", "", text)
    return [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", joined)]


def _says_number(text: str, value: float) -> bool:
    return any(abs(n - v) < 1e-6 for n in _numbers(text) for v in (value, value * 1000, value / 1000))


class CardGenError(ValueError):
    """Модель так и не собрала корректную карточку; текст ошибки показывается пользователю."""


def fix_opening(text: str, card: GeneratedCard) -> str:
    """Реплику без стартового числа собеседника или с подписью должности не берём: пустая реплика
    допустима, в начале сессии тренажёр напишет её сам по стартовой позиции."""
    t = text.strip().strip("«»\"").strip()
    for n in sorted({card.opponent_role.strip(), card.opponent_name.strip()} - {""}, key=len, reverse=True):
        if t.lower().startswith(n.lower()) and t[len(n):].lstrip()[:1] in (":", "—", "-"):
            t = t[len(n):].lstrip()[1:].lstrip()
    if not t or not _says_number(t, card.target_zone.opponent_start) or re.search(r"стартов\w* позици", t, re.I):
        return ""
    return t[0].upper() + t[1:]


def to_card(g: GeneratedCard) -> ScenarioCard:
    """Карточка для сохранения: служебные поля пустые, мелкие огрехи модели поправлены."""
    name = g.opponent_name.strip()
    title = g.title.strip()
    if name and title.lower() == name.lower():
        title = g.topic.strip()[:80]
    if name.lower() == g.opponent_role.strip().lower() or len(name.split()) > 4:
        name = ""
    return ScenarioCard(
        name=title, domain=g.domain.strip(), domain_icon=g.domain_icon or None, topic=g.topic.strip(), difficulty=g.difficulty, tone=g.tone, method=g.method, style=g.style,
        user_role=g.user_role.strip(), user_goal=g.user_goal.strip(), opponent_role=g.opponent_role.strip(), opponent_name=name[:80],
        opponent_goal=g.opponent_goal.strip(), opponent_hidden_interests=g.opponent_hidden_interests[:5],
        opponent_batna=g.opponent_batna.strip(), user_batna=g.user_batna.strip(), target_zone=g.target_zone.to_zone(),
        mandatory_details=g.mandatory_details[:5], context=g.context.strip(), opening=fix_opening(g.opening, g)[:1500],
        max_turns=g.max_turns, voice=g.voice,
    )


def explain(exc: BaseException) -> str:
    """Последняя ошибка проверки карточки — по-человечески, для сообщения пользователю."""
    attempts = getattr(exc, "failed_attempts", None) or []
    last = attempts[-1].exception if attempts else exc
    if isinstance(last, ValidationError):
        msgs = []
        for e in last.errors():
            field = next((FIELD_RU[str(p)] for p in reversed(e["loc"]) if str(p) in FIELD_RU), "")
            if e["type"] == "missing":
                msgs.append(f"не заполнено поле «{field or e['loc'][-1]}»")
            else:
                msgs.append(e["msg"].removeprefix("Value error, "))
        text = "; ".join(dict.fromkeys(msgs))
    else:
        text = str(last)
    return ("Карточка не собралась: " + text + ". Уточните в описании, о каком числе торг, с чего начинаете вы, "
            "с чего начинает собеседник и на что вы готовы согласиться, или заполните поля вручную.")
