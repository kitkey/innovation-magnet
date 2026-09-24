import os

os.environ["OFFLINE_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_arena.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.engine import rules  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas import MoveAnalysis  # noqa: E402
from app.seeds import SEEDS  # noqa: E402

CARD = SEEDS["deadline-with-manager"]


def run(moves):
    state = rules.initial_state(CARD)
    outcomes = []
    for i, m in enumerate(moves, 1):
        state, _ = rules.apply_move(CARD, state, m)
        outcomes.append(rules.decide_outcome(CARD, state, m, i))
    return state, outcomes


def test_same_moves_same_outcome():
    moves = [MoveAnalysis(labels=["interest_question", "empathy"]), MoveAnalysis(labels=["objective_criterion"]),
             MoveAnalysis(labels=["concrete_offer"], proposed_value=8)]
    assert run(moves) == run(moves)


def test_pressure_leads_to_breakdown():
    _, outcomes = run([MoveAnalysis(labels=["pressure", "personal_attack"])] * 3)
    assert ("breakdown", None) in outcomes


def test_interests_unlock_concession_and_agreement_in_zone():
    moves = [MoveAnalysis(labels=["interest_question", "empathy"]), MoveAnalysis(labels=["objective_criterion", "option_generation"]),
             MoveAnalysis(labels=["spin_need_payoff", "objective_criterion"]), MoveAnalysis(labels=["concrete_offer"], proposed_value=8)]
    state, outcomes = run(moves)
    assert state.position > CARD.target_zone.opponent_start
    assert outcomes[-1] == ("agreement_in_zone", 8)


def test_api_offline_full_session():
    with TestClient(app) as client:
        assert len(client.get("/api/scenarios").json()) >= 2
        sid = client.post("/api/sessions", params={"scenario_id": "deadline-with-manager"}).json()["session_id"]
        for msg in ["Понимаю вашу позицию. Что для вас важно в этом отчёте?", "Данные от смежного отдела приходят с опозданием, это стандарт по регламенту.",
                    "А если сделать предварительную версию к совещанию?"]:
            r = client.post(f"/api/sessions/{sid}/turn", json={"message": msg})
            assert r.status_code == 200
        client.post(f"/api/sessions/{sid}/finish")
        res = client.get(f"/api/sessions/{sid}/result").json()
        assert res["incomplete"] is False
        assert "данные от смежного отдела приходят с опозданием" in res["details_covered"]
