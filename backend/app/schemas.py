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


class TargetZone(BaseModel):
    unit: str = Field(min_length=1, description="предмет торга и единица через запятую, предмет первым: «стоимость доработки, тыс. руб.», "
                      "«срок сдачи, рабочих дней», «рост цены поставки, %»; все четыре числа зоны — в этой единице")
    user_start: float = Field(description="первое число, которое называет игрок; лучше для него, чем вся целевая зона, или равно её лучшему краю")
    zone_min: float = Field(description="меньший край целевой зоны: диапазона, где сделка для игрока хорошая; лежит между стартами сторон")
    zone_max: float = Field(description="больший край целевой зоны; худший для игрока край зоны — его граница, дальше выгоднее альтернатива")
    opponent_start: float = Field(description="первое требование собеседника; направление «лучше для игрока» задаёт порядок: "
                                  "игроку лучше большее число, если user_start больше opponent_start, и меньшее — если меньше")

    @model_validator(mode="after")
    def _consistent(self):
        if self.zone_min > self.zone_max:
            raise ValueError("Начало целевой зоны больше её конца")
        if self.user_start == self.opponent_start:
            raise ValueError("Стартовые позиции сторон совпадают, торговаться не о чем")
        low, high = sorted((self.user_start, self.opponent_start))
        if not low <= self.zone_min <= self.zone_max <= high:
            raise ValueError("Целевая зона должна лежать между стартовыми позициями сторон")
        return self

    @property
    def subject(self) -> str:
        """Что означает число: часть единицы до последней запятой («стоимость доработки»), пусто, если не указано."""
        return self.unit.rsplit(",", 1)[0].strip() if "," in self.unit else ""

    @property
    def short_unit(self) -> str:
        """Единица без предмета: «тыс. руб.», «рабочих дней», «%»."""
        return self.unit.rsplit(",", 1)[1].strip() or self.unit if "," in self.unit else self.unit

    def fmt(self, value: float) -> str:
        return f"{value:g}%" if self.short_unit == "%" else f"{value:g} {self.short_unit}"


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
    proposed_value: float | None = Field(default=None, description="значение, которое пользователь предложил в единицах торга, если назвал")


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
