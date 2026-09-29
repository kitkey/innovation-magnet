from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.db import SessionLocal, SessionRow
from app.engine import hints, rules
from app.main import app
from app.schemas import Hint, MoveAnalysis, OpponentState, ScenarioCard
from app.seeds import SEEDS

SUPPLIER = SEEDS["supplier-price-batna"]
QUESTION = "Что для вас важнее: маржа на единице или гарантированный объём на год?"
PRESSURE = "Немедленно снижайте цену, это не обсуждается!"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def move(*labels):
    return MoveAnalysis(labels=list(labels))


def holds(when, labels=(), seen=(), state=None, turn=1, card=SUPPLIER):
    return hints.holds(card, when, move(*labels), set(seen) | set(labels), state or OpponentState(), turn)


def test_label_condition():
    assert holds("label:pressure", ["pressure", "batna_reference"])
    assert not holds("label:pressure", ["interest_question"], seen=["pressure"])


def test_missing_condition():
    assert not holds("missing:interest_question@3", turn=2)
    assert holds("missing:interest_question@3", turn=3)
    assert holds("missing:interest_question@3", turn=5)
    assert not holds("missing:interest_question@3", seen=["interest_question"], turn=3)


def test_counter_conditions_use_difficulty_thresholds():
    easy, hard = SUPPLIER.model_copy(update={"difficulty": "easy"}), SUPPLIER.model_copy(update={"difficulty": "hard"})
    assert hints.irritation_high(easy) == rules.DIFFICULTY["easy"]["breakdown_irritation"] - 2
    assert holds("irritation_high", state=OpponentState(irritation=3), card=hard)
    assert not holds("irritation_high", state=OpponentState(irritation=3), card=easy)
    assert holds("trust_low", state=OpponentState(trust=rules.BREAKDOWN_TRUST // 2))
    assert not holds("trust_low", state=OpponentState(trust=0))
    threshold = rules.DIFFICULTY[SUPPLIER.difficulty]["concede_threshold"]
    assert holds("readiness_high", state=OpponentState(readiness=threshold - 1))
    assert not holds("readiness_high", state=OpponentState(readiness=0))


def test_turns_left_condition():
    assert not holds("turns_left:2", turn=SUPPLIER.max_turns - 3)
    assert holds("turns_left:2", turn=SUPPLIER.max_turns - 2)


def test_hint_when_is_validated():
    assert Hint(when=" label:concession ", text="x").when == "label:concession"
    for bad in ["label:shouting", "missing:pressure", "sometimes", "turns_left:x"]:
        with pytest.raises(ValidationError):
            Hint(when=bad, text="Текст")


def test_standard_hints_are_valid_for_every_method():
    for method, items in hints.STANDARD_HINTS.items():
        assert 3 <= len(items) <= 4 and 2 <= len(hints.COACH_TIPS[method]) <= 3


def test_fire_once_and_at_most_two_per_turn():
    card = SUPPLIER.model_copy(update={"hints": [Hint(when="label:pressure", text="Своя про давление"),
                                                 Hint(when="label:pressure", text="Вторая своя")]})
    first = hints.fire(card, True, move("pressure"), {"pressure"}, OpponentState(), 1, [])
    assert [h.text for _, h in first] == ["Своя про давление", "Вторая своя"]
    assert {h.source for _, h in first} == {"org"}
    fired = [hid for hid, _ in first]
    second = hints.fire(card, True, move("pressure"), {"pressure"}, OpponentState(), 2, fired)
    assert [h.source for _, h in second] == ["standard"]
    fired += [hid for hid, _ in second]
    assert hints.fire(card, True, move("pressure"), {"pressure"}, OpponentState(), 3, fired) == []


def test_seeds_have_names_matching_voice():
    for card in SEEDS.values():
        first = card.opponent_name.split()[0]
        assert card.opponent_name and len(card.opponent_name.split()) == 2 and card.voice == ("female" if first[-1] in "ая" else "male")
        assert card.opponent_name.split()[1] not in card.opponent_role


def custom_card(**kw):
    data = SUPPLIER.model_dump() | {"name": f"Тест {uuid4().hex[:6]}", "coach_tips": ["Держите в голове объём на год"],
                                    "hints": [{"when": "label:concession", "text": "Уступка без обмена"}]}
    return data | kw


def test_coach_tips_and_hints_in_session(client):
    s = client.post("/api/scenarios", json=custom_card()).json()
    assert s["coach_tips"] == ["Держите в голове объём на год"] and s["hints"][0]["when"] == "label:concession"
    sid = client.post("/api/sessions", params={"scenario_id": s["id"]}).json()["session_id"]
    view = client.get(f"/api/sessions/{sid}").json()
    assert view["coach"][0] == {"text": "Держите в голове объём на год", "source": "author"}
    assert [c["source"] for c in view["coach"][1:]] == ["standard"] * len(hints.COACH_TIPS["batna"])

    r = client.post(f"/api/sessions/{sid}/turn", json={"message": PRESSURE}).json()
    assert r["hints"] == [{"text": hints.STANDARD_HINTS["batna"][0].text, "source": "standard"}]
    r = client.post(f"/api/sessions/{sid}/turn", json={"message": PRESSURE}).json()
    assert r["hints"] == []


def test_org_scenario_marks_hints_from_org(client):
    reg = client.post("/api/auth/register", json={"login": f"u{uuid4().hex[:10]}", "password": "secret123"}).json()
    headers = {"Authorization": f"Bearer {reg['token']}"}
    assert client.post("/api/orgs", json={"name": f"Орг {uuid4().hex[:6]}"}, headers=headers).status_code == 200
    s = client.post("/api/scenarios", json=custom_card(), headers=headers).json()
    assert s["org_id"]
    sid = client.post("/api/sessions", params={"scenario_id": s["id"]}, headers=headers).json()["session_id"]
    assert client.get(f"/api/sessions/{sid}", headers=headers).json()["coach"][0]["source"] == "org"


def test_rewind_recomputes_fired_hints(client):
    s = client.post("/api/scenarios", json=custom_card(hints=[])).json()
    sid = client.post("/api/sessions", params={"scenario_id": s["id"]}).json()["session_id"]
    client.post(f"/api/sessions/{sid}/turn", json={"message": QUESTION})
    r = client.post(f"/api/sessions/{sid}/turn", json={"message": PRESSURE}).json()
    assert [h["text"] for h in r["hints"]] == [hints.STANDARD_HINTS["batna"][0].text]

    back = client.post(f"/api/sessions/{sid}/rewind", json={"turn": 1}).json()
    with SessionLocal() as db:
        assert db.get(SessionRow, back["id"]).hints_fired == []
    r = client.post(f"/api/sessions/{back['id']}/turn", json={"message": PRESSURE}).json()
    assert [h["text"] for h in r["hints"]] == [hints.STANDARD_HINTS["batna"][0].text]

    again = client.post(f"/api/sessions/{back['id']}/rewind", json={"turn": 2}).json()
    with SessionLocal() as db:
        assert db.get(SessionRow, again["id"]).hints_fired == ["s0"]
    assert client.post(f"/api/sessions/{again['id']}/turn", json={"message": PRESSURE}).json()["hints"] == []


def test_generated_card_drops_hints():
    from app.cardgen import GeneratedCard, to_card
    data = custom_card()
    data |= {"title": data["name"], "target_zone": data["target_zone"] | {"player_wants": "less"}}
    card = to_card(GeneratedCard(**data))
    assert card.hints == [] and card.coach_tips == [] and card.avatar_url and "chibi" in card.avatar_url
    assert card.opponent_name == SUPPLIER.opponent_name


def test_llm_reply_speaker_prefix_is_stripped():
    from app.llm import strip_speaker
    assert strip_speaker(SUPPLIER, "Ольга Кравец: Цена растёт на 10%.") == "Цена растёт на 10%."
    assert strip_speaker(SUPPLIER, "Ольга — цена растёт.") == "цена растёт."
    assert strip_speaker(SUPPLIER, "Коммерческий директор поставщика гофроупаковки: нет.") == "нет."
    assert strip_speaker(SUPPLIER, "Цена растёт: картон подорожал.") == "Цена растёт: картон подорожал."
