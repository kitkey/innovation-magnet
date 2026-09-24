from typing import Literal

from pydantic import BaseModel, Field

Difficulty = Literal["easy", "medium", "hard"]
Tone = Literal["neutral", "friendly", "strict", "skeptical"]
Method = Literal["spin", "harvard", "free"]
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
]
Outcome = Literal["agreement_in_zone", "agreement_out_of_zone", "breakdown", "turn_limit", "user_finished"]


class TargetZone(BaseModel):
    unit: str = Field(description="единица торга: дни, проценты, рубли, число задач")
    user_start: float
    zone_min: float
    zone_max: float
    opponent_start: float


class ScenarioCard(BaseModel):
    name: str
    domain: str
    topic: str
    difficulty: Difficulty = "medium"
    tone: Tone = "neutral"
    method: Method = "free"
    style: Style = "hard"
    user_role: str
    user_goal: str
    opponent_role: str
    opponent_goal: str
    opponent_hidden_interests: list[str]
    opponent_batna: str
    user_batna: str
    target_zone: TargetZone
    mandatory_details: list[str]
    context: str
    max_turns: int = Field(default=10, ge=3, le=30)
    locked_by_org: bool = False


class Scenario(ScenarioCard):
    id: str


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


class KeyMoment(BaseModel):
    quote: str
    problem: str
    better: str


class JudgeReport(BaseModel):
    axes: dict[str, int] = Field(description="ось метода -> оценка 0..100")
    key_moments: list[KeyMoment] = Field(max_length=3)
    next_scenario_hint: str


class SessionResult(BaseModel):
    session_id: str
    status: str
    outcome: Outcome | None
    incomplete: bool
    final_position: float | None
    in_zone: bool | None
    position_shift: float | None
    details_covered: list[str]
    details_missed: list[str]
    judge: JudgeReport | None
