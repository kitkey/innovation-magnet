import pytest
from fastapi.testclient import TestClient

from app import scoring, service
from app.db import SessionLocal, SessionRow
from app.engine import offline, rules
from app.main import app
from app.schemas import MoveAnalysis, OpponentState
from app.seeds import SEEDS

SUPPLIER = SEEDS["supplier-price-batna"]
OFFER = SEEDS["salary-offer-batna"]
DEADLINE = SEEDS["deadline-with-manager"]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def labels(card, text):
    return offline.analyze(card, text).labels


def test_batna_labels_offline():
    assert "batna_reference" in labels(SUPPLIER, "У нас есть резервный поставщик с ростом цены 4%.")
    assert "boundary" in labels(SUPPLIER, "Рост выше 4% мы не можем согласовать, это наш предел.")
    assert "conditional_trade" in labels(SUPPLIER, "Если вы фиксируете 2%, мы дадим гарантированный объём на 12 месяцев.")
    assert "walk_away" in labels(SUPPLIER, "Спасибо, мы откажемся от сделки и переходим к резервному поставщику.")


def test_not_ready_is_not_an_offer():
    move = offline.analyze(SUPPLIER, "Не готов принять рост больше 4%.")
    assert "boundary" in move.labels
    assert "concrete_offer" not in move.labels
    assert "concrete_offer" in labels(SUPPLIER, "Готов принять рост 3%.")


def test_conditional_threat_is_not_walk_away():
    move = offline.analyze(SUPPLIER, "Иначе выберем другого поставщика, это не обсуждается.")
    assert "walk_away" not in move.labels
    assert {"batna_reference", "pressure"} <= set(move.labels)
    assert "walk_away" not in labels(SUPPLIER, "Если не снизите цену, мы откажемся от сделки.")


def test_batna_reference_as_threat_lowers_trust():
    calm, _ = rules.apply_move(SUPPLIER, rules.initial_state(SUPPLIER), MoveAnalysis(labels=["batna_reference"]))
    threat, _ = rules.apply_move(SUPPLIER, rules.initial_state(SUPPLIER), MoveAnalysis(labels=["batna_reference", "pressure"]))
    assert calm.readiness > 0 and calm.trust == 0
    base, _ = rules.apply_move(SUPPLIER, rules.initial_state(SUPPLIER), MoveAnalysis(labels=["pressure"]))
    assert threat.trust < base.trust and threat.readiness == base.readiness


def test_conditional_trade_and_boundary_raise_readiness():
    state, _ = rules.apply_move(SUPPLIER, rules.initial_state(SUPPLIER), MoveAnalysis(labels=["boundary", "conditional_trade"]))
    assert state.readiness >= 3


def test_walk_away_when_no_good_deal():
    state = OpponentState(position=6.5, readiness=10, trust=2)
    new, conceded = rules.apply_move(SUPPLIER, state, MoveAnalysis(labels=["walk_away", "batna_reference"]))
    assert not conceded and new.position == 6.5
    assert rules.decide_outcome(SUPPLIER, new, MoveAnalysis(labels=["walk_away"]), 3) == ("walk_away", None)
    ok, note = service.walk_away_verdict(SUPPLIER, new.position)
    assert ok and "Верное решение" in note
    assert rules.walk_away_justified(OFFER, 4) and not rules.walk_away_justified(OFFER, 8)


def test_walk_away_when_deal_was_good():
    ok, note = service.walk_away_verdict(SUPPLIER, 3)
    assert not ok and "преждевременный" in note
    assert not rules.walk_away_justified(SUPPLIER, 4)


def test_walk_away_bonus_only_when_justified():
    axes = {"a": 60, "b": 80}
    assert scoring.session_score(axes, "medium", "walk_away", True) == 80
    assert scoring.session_score(axes, "medium", "walk_away", False) == 70
    assert scoring.session_score(axes, "medium", "walk_away") == 70


def test_batna_axes_offline():
    texts = ["Что для вас важнее: маржа или гарантированный объём?",
             "У нас есть резервный поставщик с ростом 4%, но мы предпочли бы остаться с вами.",
             "Наш предел — рост не выше 4%. Если вы фиксируете 2%, мы готовы дать объём на год."]
    report = offline.judge_offline(SUPPLIER, [(t, offline.analyze(SUPPLIER, t)) for t in texts])
    assert list(report.axes) == rules.METHOD_AXES["batna"]
    assert report.axes["сравнение с альтернативой"] == 100
    assert report.axes["защита границы"] == 100
    assert report.axes["обмен условиями"] == 100
    threat = "Иначе выберем другого поставщика, это не обсуждается."
    bad = offline.judge_offline(SUPPLIER, [(t, offline.analyze(SUPPLIER, t)) for t in texts + [threat]])
    assert bad.axes["сравнение с альтернативой"] == 85
    assert bad.key_moments[0].quote == threat


def test_other_methods_keep_their_axes():
    report = offline.judge_offline(DEADLINE, [("Что для вас важно?", offline.analyze(DEADLINE, "Что для вас важно?"))])
    assert list(report.axes) == rules.METHOD_AXES["harvard"]


@pytest.mark.parametrize("sid,messages", [
    ("supplier-price-batna", ["Понимаю рост затрат. Что для вас важнее: маржа на единице или гарантированный объём на год?",
                              "У нас есть резервный поставщик с ростом цены 4%, но мы предпочли бы остаться с вами.",
                              "Наш предел — не выше, чем у резервного поставщика. Если вы фиксируете рост 2% и сроки отгрузки, мы готовы дать гарантированный объём на 12 месяцев.",
                              "Рыночные данные показывают рост цен в отрасли на 3%, поэтому при условии годового объёма предлагаю 3%.",
                              "Предлагаю зафиксировать 3% и сроки отгрузки."]),
    ("salary-offer-batna", ["Что для вас важно при закрытии позиции и какие ограничения по бюджету?",
                            "У меня есть другой оффер: фиксированная часть на 7% выше. Минимально приемлемо для меня не ниже этого уровня.",
                            "Если вы поднимаете оклад на 10% и даёте ранний пересмотр оклада, я готов выйти до конца месяца.",
                            "По рыночным данным аналитики на этом уровне получают больше, поэтому предлагаю 10% и sign-on бонус."]),
])
def test_batna_seeds_play_offline(client, sid, messages):
    assert sid in {s["id"] for s in client.get("/api/scenarios").json()}
    session = client.post("/api/sessions", params={"scenario_id": sid}).json()["session_id"]
    for msg in messages:
        r = client.post(f"/api/sessions/{session}/turn", json={"message": msg})
        assert r.status_code == 200
        if r.json()["status"] == "finished":
            break
    client.post(f"/api/sessions/{session}/finish")
    res = client.get(f"/api/sessions/{session}/result").json()
    assert res["judge_source"] == "rules"
    assert list(res["judge"]["axes"]) == rules.METHOD_AXES["batna"]
    assert res["judge"]["axes"]["сравнение с альтернативой"] == 100
    assert res["details_covered"]


def test_walk_away_session_offline(client):
    sid = client.post("/api/sessions", params={"scenario_id": "supplier-price-batna"}).json()["session_id"]
    client.post(f"/api/sessions/{sid}/turn", json={"message": "Что для вас важнее: маржа или гарантированный объём?"})
    r = client.post(f"/api/sessions/{sid}/turn", json={"message": "Рост 10% хуже нашей альтернативы. Мы откажемся от сделки и переходим к резервному поставщику."}).json()
    assert r["status"] == "finished" and r["outcome"] == "walk_away" and r["mood"] == "sad"
    res = client.get(f"/api/sessions/{sid}/result").json()
    assert res["outcome"] == "walk_away" and res["walk_away_justified"] is True
    assert res["final_position"] is None and res["judge"] is not None
    assert "10 % роста цены" in res["walk_away_note"]
    with SessionLocal() as db:
        row = db.get(SessionRow, sid)
        axes = scoring.judge_axes(row)
        assert scoring.score_of(row) == scoring.session_score(axes, "medium", "agreement_in_zone")
