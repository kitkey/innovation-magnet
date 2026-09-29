import re
from typing import Literal, get_args

from pydantic import BaseModel, Field, field_validator, model_validator

Difficulty = Literal["easy", "medium", "hard"]
Tone = Literal["neutral", "friendly", "strict", "skeptical"]
Method = Literal["spin", "harvard", "batna", "free"]
Style = Literal["hard", "cooperative", "avoiding", "pressing", "emotional"]
MoveLabel = Literal[
    "interest_question",
    "spin_situation",
    "spin_problem",
    "spin_implication",
    "spin_need_payoff",
    "objective_criterion",
    "option_generation",
    "concrete_offer",
    "concession",
    "empathy",
    "argument",
    "mandatory_detail",
    "pressure",
    "personal_attack",
    "vague",
    "accept",
    "manipulation",
    "batna_reference",
    "boundary",
    "conditional_trade",
    "walk_away",
]
Mood = Literal["neutral", "happy", "angry", "sad", "disgust", "skeptic"]
AVATAR_URL = r"^/(uploads/avatars|avatars)/[A-Za-z0-9_.\-]+\.glb$"
Outcome = Literal["agreement_in_zone", "agreement_out_of_zone", "walk_away", "breakdown", "turn_limit", "user_finished"]
DomainIcon = Literal["procurement", "team", "project", "residents", "career", "sales", "service", "finance", "legal",
                     "logistics", "production", "it", "hr", "marketing", "government", "startup", "everyday"]
DOMAIN_ICONS = get_args(DomainIcon)


OPTIONS_MIN, OPTIONS_MAX = 2, 8


class TargetZone(BaseModel):
    """Целевая зона. Два вида: числом (options пуст, позиции в единице unit) и шкалой вариантов (options заданы,
    позиции — номера вариантов с нуля, 0 — лучший для игрока)."""
    unit: str = Field(min_length=1, description="предмет торга и единица через запятую, предмет первым: «стоимость доработки, тыс. руб.», "
                      "«срок сдачи, рабочих дней», «рост цены поставки, %»; все четыре числа зоны — в этой единице. "
                      "Для шкалы вариантов — предмет торга словами: «пункт о допработах при срыве срока»")
    user_start: float = Field(description="первое число, которое называет игрок; лучше для него, чем вся целевая зона, или равно её лучшему краю")
    zone_min: float = Field(description="меньший край целевой зоны: диапазона, где сделка для игрока хорошая; лежит между стартами сторон")
    zone_max: float = Field(description="больший край целевой зоны; худший для игрока край зоны — его граница, дальше выгоднее альтернатива")
    opponent_start: float = Field(description="первое требование собеседника; направление «лучше для игрока» задаёт порядок: "
                                  "игроку лучше большее число, если user_start больше opponent_start, и меньшее — если меньше")
    options: list[str] = Field(default_factory=list, description="шкала вариантов, когда торг не о числе: 2–8 формулировок от лучшего для игрока "
                               "к худшему; тогда user_start, zone_min, zone_max, opponent_start — номера вариантов с нуля")

    @field_validator("options", mode="before")
    @classmethod
    def _clean_options(cls, v):
        return [re.sub(r"\s+", " ", str(x)).strip() for x in v or [] if str(x or "").strip()]

    @model_validator(mode="after")
    def _consistent(self):
        if self.options:
            self._check_options()
        if self.zone_min > self.zone_max:
            raise ValueError("Начало целевой зоны больше её конца")
        if self.user_start == self.opponent_start:
            raise ValueError("Стартовые позиции сторон совпадают, торговаться не о чем")
        low, high = sorted((self.user_start, self.opponent_start))
        if not low <= self.zone_min <= self.zone_max <= high:
            raise ValueError("Целевая зона должна лежать между стартовыми позициями сторон")
        return self

    def _check_options(self) -> None:
        n = len(self.options)
        if not OPTIONS_MIN <= n <= OPTIONS_MAX:
            raise ValueError(f"Вариантов должно быть от {OPTIONS_MIN} до {OPTIONS_MAX}, сейчас {n}")
        if len({o.lower() for o in self.options}) < n:
            raise ValueError("Два варианта совпадают: у каждого должна быть своя формулировка")
        if any(len(o) > 200 for o in self.options):
            raise ValueError("Вариант длиннее 200 знаков: сформулируйте короче")
        for name, ru in (("user_start", "Ваш старт"), ("zone_min", "Начало зоны"), ("zone_max", "Конец зоны"), ("opponent_start", "Старт собеседника")):
            v = getattr(self, name)
            if v != int(v) or not 0 <= v < n:
                raise ValueError(f"{ru}: нужен один из вариантов, от 1 до {n}")
        if self.user_start > self.opponent_start:
            raise ValueError("Варианты идут от лучшего для вас к худшему: ваш старт должен стоять в списке выше старта собеседника")

    @property
    def ordinal(self) -> bool:
        return bool(self.options)

    @property
    def subject(self) -> str:
        """Предмет торга: часть единицы до последней запятой («стоимость доработки»), пусто, если не указано; у шкалы вариантов — весь unit."""
        if self.ordinal:
            return self.unit.strip()
        return self.unit.rsplit(",", 1)[0].strip() if "," in self.unit else ""

    @property
    def short_unit(self) -> str:
        """Единица без предмета: «тыс. руб.», «рабочих дней», «%»; у шкалы вариантов единицы нет."""
        if self.ordinal:
            return ""
        return self.unit.rsplit(",", 1)[1].strip() or self.unit if "," in self.unit else self.unit

    def index(self, value: float) -> int:
        """Номер варианта (с нуля) для позиции на шкале вариантов."""
        return max(0, min(len(self.options) - 1, int(round(value))))

    def option(self, value: float) -> str:
        return self.options[self.index(value)]

    def fmt(self, value: float) -> str:
        if self.ordinal:
            return f"«{self.option(value)}»"
        n = f"{value:g}".replace(".", ",")
        return f"{n}%" if self.short_unit == "%" else f"{n} {self.short_unit}"

    def fmt_at(self, value: float) -> str:
        """«на 10%» или «на варианте «…»»: для фраз вида «собеседник стоял …»."""
        return f"на варианте {self.fmt(value)}" if self.ordinal else f"на {self.fmt(value)}"

    def numbered(self) -> str:
        """Варианты списком с номерами от 1: для промптов модели."""
        return "; ".join(f"{i}) {o}" for i, o in enumerate(self.options, 1))

    def describe(self) -> str:
        """Старт игрока и целевая зона словами: для судьи и разметки."""
        if not self.ordinal:
            return f"старт пользователя {self.user_start:g}, целевая зона {self.zone_min:g}–{self.zone_max:g}"
        zone = (f"вариант {self.index(self.zone_min) + 1}" if self.zone_min == self.zone_max
                else f"варианты {self.index(self.zone_min) + 1}–{self.index(self.zone_max) + 1}")
        return (f"варианты от лучшего для пользователя к худшему: {self.numbered()}; старт пользователя — вариант {self.index(self.user_start) + 1}, "
                f"целевая зона — {zone}, старт собеседника — вариант {self.index(self.opponent_start) + 1}")


MOVE_LABELS = set(get_args(MoveLabel))
HINT_WHEN = re.compile(r"^(label:(?P<label>[a-z_]+)|missing:(?P<missing>[a-z_]+)@(?P<at>\d{1,2})|irritation_high|trust_low|readiness_high|turns_left:(?P<left>\d{1,2}))$")


class Hint(BaseModel):
    """Подсказка маскота по ходу диалога: условие и текст. Условия считаются на сервере по разметке ходов и счётчикам, без LLM."""
    when: str = Field(description="label:<метка> | missing:<метка>@<ход> | irritation_high | trust_low | readiness_high | turns_left:<N>")
    text: str = Field(min_length=1, max_length=300)

    @field_validator("when")
    @classmethod
    def _when(cls, v: str) -> str:
        v = v.strip()
        m = HINT_WHEN.match(v)
        if not m:
            raise ValueError(f"Неизвестное условие подсказки: {v}")
        label = m.group("label") or m.group("missing")
        if label and label not in MOVE_LABELS:
            raise ValueError(f"Неизвестная метка хода в условии подсказки: {label}")
        return v


class HintOut(BaseModel):
    text: str
    source: Literal["org", "author", "standard"]


class ScenarioCard(BaseModel):
    name: str = Field(min_length=1, description="название сценария в списке: предмет разговора и с кем, 3–7 слов; не имя собеседника")
    domain: str = Field(description="сфера: «Закупки», «Работа в команде», «Аренда жилья»")
    domain_icon: DomainIcon | None = Field(default=None, description="значок группы на главной; пусто — подбирается по словам сферы")
    topic: str = Field(description="о чём торг и почему сейчас, одно предложение")
    difficulty: Difficulty = "medium"
    tone: Tone = "neutral"
    method: Method = "free"
    style: Style = "hard"
    user_role: str = Field(min_length=1, description="кто игрок в этой ситуации")
    user_goal: str = Field(min_length=1, description="чего игрок хочет, с числами целевой зоны и тем, чем готов расплатиться за уступку")
    opponent_role: str = Field(min_length=1, description="кто собеседник: должность и организация или отношение к игроку")
    opponent_name: str = Field(default="", max_length=80, description="вымышленные имя и фамилия собеседника, пол совпадает с голосом voice; "
                               "не имя реального известного человека")
    opponent_goal: str = Field(min_length=1, description="чего добивается собеседник и почему, с его стартовым числом")
    opponent_hidden_interests: list[str] = Field(description="конкретные причины и ограничения собеседника, которые он раскрывает, только если о них спросили")
    opponent_batna: str = Field(description="что собеседник сделает без соглашения")
    user_batna: str = Field(description="что игрок сделает без соглашения: другой поставщик, другой оффер; действие, а не число торга")
    target_zone: TargetZone
    mandatory_details: list[str] = Field(description="2–4 коротких факта, которые игрок должен произнести; тренажёр проверяет, прозвучали ли они")
    context: str = Field(description="ситуация для игрока от второго лица: что произошло, откуда взялись числа зоны, что будет без соглашения")
    opening: str = Field(default="", max_length=1500, description="первая реплика собеседника вслух: суть вопроса и число target_zone.opponent_start цифрами, "
                         "словами живого человека в характере его стиля; не представляется и не называет должность; пусто — реплику напишет тренажёр")
    max_turns: int = Field(default=10, ge=3, le=30, description="сколько реплик у игрока; обычно 10")
    locked_by_org: bool = False
    voice: Literal["female", "male"] = Field(default="female", description="голос собеседника в режиме 3D и голос")
    avatar_url: str | None = Field(default=None, pattern=AVATAR_URL, description="GLB-аватар собеседника; при генерации карточки не заполняй")
    coach_tips: list[str] = Field(default_factory=list, max_length=8, description="наставления игроку перед стартом от автора сценария; при генерации карточки оставь пустым")
    hints: list[Hint] = Field(default_factory=list, max_length=20, description="подсказки по условиям от автора сценария; при генерации карточки оставь пустым")

    @field_validator("coach_tips", mode="before")
    @classmethod
    def _tips(cls, v):
        return [t.strip()[:300] for t in v or [] if isinstance(t, str) and t.strip()]

    @field_validator("domain_icon", mode="before")
    @classmethod
    def _empty_icon(cls, v):
        return v or None

    @field_validator("avatar_url", mode="before")
    @classmethod
    def _empty_avatar(cls, v):
        return v or None


class Scenario(ScenarioCard):
    id: str
    org_id: str | None = None
    builtin: bool = False
    can_edit: bool = False
    edit_key: str | None = Field(default=None, description="ключ правки сценария, созданного без входа; выдаётся один раз")


class ScenarioBrief(BaseModel):
    description: str = Field(min_length=10, max_length=3000)


class MoveAnalysis(BaseModel):
    labels: list[MoveLabel]
    mentioned_details: list[str] = Field(default_factory=list, description="какие обязательные детали из карточки пользователь озвучил в этой реплике")
    proposed_value: float | None = Field(default=None, description="значение, которое пользователь предложил в единицах торга, если назвал; "
                                          "при шкале вариантов — номер варианта")


class OpponentState(BaseModel):
    trust: int = 0
    readiness: int = 0
    irritation: int = 0
    position: float = 0.0


class TurnIn(BaseModel):
    message: str = Field(min_length=1, max_length=2500)


class TurnOut(BaseModel):
    turn: int
    opponent_message: str
    status: Literal["active", "finished"]
    outcome: Outcome | None = None
    analysis: MoveAnalysis
    state: OpponentState
    mood: Mood = "neutral"
    hints: list[HintOut] = Field(default_factory=list, description="подсказки маскота, сработавшие на этом ходу")


class VoiceTurnOut(TurnOut):
    recognized: str
    audio_url: str | None = None


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    emotion: Mood = "neutral"
    voice: Literal["female", "male"] = "female"


class KeyMoment(BaseModel):
    quote: str
    problem: str
    better: str


class JudgeReport(BaseModel):
    axes: dict[str, int] = Field(description="ось метода -> оценка 0..100")
    key_moments: list[KeyMoment] = Field(min_length=1, max_length=3)
    next_scenario_hint: str

    @field_validator("axes")
    @classmethod
    def _clamp(cls, v: dict[str, int]) -> dict[str, int]:
        return {k: max(0, min(100, int(x))) for k, x in v.items()}


class SessionResult(BaseModel):
    session_id: str
    status: str
    outcome: Outcome | None
    incomplete: bool
    final_position: float | None
    in_zone: bool | None
    position_shift: float | None
    walk_away_justified: bool | None = Field(default=None, description="при выходе к альтернативе: позиция собеседника была хуже границы целевой зоны")
    walk_away_note: str | None = None
    details_covered: list[str]
    details_missed: list[str]
    judge: JudgeReport | None
    judge_source: Literal["llm", "rules"] | None = None


class RewindIn(BaseModel):
    turn: int = Field(ge=0)
