import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app import scoring
from app.db import init_db
from app.main import app

from test_accounts import GOOD, play, register

WEAK = GOOD[:1] + ["Это не обсуждается.", "Делайте как хотите"]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def team(client, n=3, name="Сезонная"):
    """Администратор и n-1 участников в новой организации."""
    ha, admin = register(client, "Админ")
    code = client.post("/api/orgs", json={"name": name}, headers=ha).json()["invite_code"]
    people = [(ha, admin)]
    for i in range(n - 1):
        h, u = register(client, f"Участник {i + 1}")
        client.post("/api/orgs/join", json={"code": code}, headers=h)
        people.append((h, u))
    return people


def board(client, h, period="all"):
    r = client.get("/api/leaderboard", params={"scope": "org", "period": period}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def close(client, h, **kw):
    return client.post("/api/orgs/me/season/close", json={"award": False, "reset": False} | kw, headers=h)


@pytest.mark.parametrize("slots, gold, silver, expected", [
    (10, 0.2, 0.3, (2, 3, 5)),
    (0, 0.2, 0.3, (0, 0, 0)),
    (1, 0.2, 0.3, (1, 0, 0)),
    (3, 0.5, 0.5, (2, 1, 0)),
    (5, 0, 0, (0, 0, 5)),
    (4, 0.1, 0, (1, 0, 3)),
    (7, 0.25, 0.25, (2, 2, 3)),
    (1, 0, 1, (0, 1, 0)),
    (2, 1, 0, (2, 0, 0)),
])
def test_medal_split(slots, gold, silver, expected):
    split = scoring.medal_split(slots, gold, silver)
    assert (split["gold"], split["silver"], split["bronze"]) == expected
    assert sum(split.values()) == slots


def test_medal_for_place():
    split = {"gold": 1, "silver": 2, "bronze": 1}
    assert [scoring.medal_for_place(i, split) for i in range(5)] == ["gold", "silver", "silver", "bronze", None]
    assert scoring.medal_for_place(0, scoring.medal_split(0, 0.2, 0.3)) is None


def test_place_medals_scale_to_participants():
    assert scoring.place_medals(2, 10, 0.2, 0.3) == ["gold", "silver"]
    assert scoring.place_medals(12, 10, 0.2, 0.3) == ["gold"] * 2 + ["silver"] * 3 + ["bronze"] * 5 + [None] * 2
    assert scoring.place_medals(3, 0, 0.2, 0.3) == [None] * 3
    assert scoring.place_medals(0, 10, 0.2, 0.3) == []


def test_season_rights(client):
    (ha, _), (hm, _) = team(client, 2)
    hx, _ = register(client, "Чужой админ")
    client.post("/api/orgs", json={"name": "Чужая"}, headers=hx)
    hg, _ = register(client, "Без организации")
    body = {"medal_slots": 3, "gold_share": 0.3, "silver_share": 0.3}
    for h, code in ((hm, 403), (hg, 403), ({}, 401)):
        assert client.get("/api/orgs/me/season", headers=h).status_code == code
        assert client.put("/api/orgs/me/medals", json=body, headers=h).status_code == code
        assert close(client, h, award=True).status_code == code
    assert client.get("/api/profile/medals").status_code == 401
    play(client, hm)
    # чужой администратор меняет только свою организацию
    assert client.put("/api/orgs/me/medals", json=body | {"medal_slots": 0}, headers=hx).status_code == 200
    assert close(client, hx, award=True).status_code == 409
    assert board(client, hm)["medal_rule"]["slots"] == 10
    assert client.put("/api/orgs/me/medals", json=body | {"gold_share": 0.6, "silver_share": 0.5}, headers=ha).status_code == 422
    assert client.put("/api/orgs/me/medals", json=body | {"medal_slots": -1}, headers=ha).status_code == 422
    assert close(client, ha).status_code == 422
    state = client.put("/api/orgs/me/medals", json=body, headers=ha).json()
    assert state["medal_rule"]["split"] == {"gold": 1, "silver": 1, "bronze": 1}


def test_live_leaderboard_shows_medals(client):
    (ha, _), (h1, _), (h2, _) = team(client, 3)
    play(client, ha)
    play(client, h1, moves=WEAK)
    play(client, h2, moves=["Это не обсуждается.", "Делайте как хотите", "Мне всё равно."])
    client.put("/api/orgs/me/medals", json={"medal_slots": 2, "gold_share": 0.5, "silver_share": 0.5}, headers=ha)
    b = board(client, h1)
    assert b["season"]["name"] == "Сезон 1" and b["season"]["started_at"]
    assert b["medal_rule"]["split"] == {"gold": 1, "silver": 1, "bronze": 0}
    assert [r["medal"] for r in b["rows"]] == ["gold", "silver", None]
    assert b["rows"][0]["rating"] > b["rows"][1]["rating"] > b["rows"][2]["rating"]
    assert all(r["medals"] == {"gold": 0, "silver": 0, "bronze": 0} for r in b["rows"])
    client.put("/api/orgs/me/medals", json={"medal_slots": 0, "gold_share": 0.5, "silver_share": 0.5}, headers=ha)
    assert [r["medal"] for r in board(client, h1)["rows"]] == [None, None, None]
    glob = client.get("/api/leaderboard", params={"scope": "global"}).json()
    assert all(r["medal"] is None for r in glob["rows"]) and "season" not in glob


def test_award_without_reset_keeps_season_and_blocks_repeat(client):
    (ha, admin), (hm, member) = team(client, 2, "Только медали")
    play(client, ha)
    play(client, hm, moves=WEAK)
    season = client.get("/api/orgs/me/season", headers=ha).json()["season"]
    r = close(client, ha, award=True)
    assert r.status_code == 200, r.text
    out = r.json()
    assert [a["medal"] for a in out["awarded"]] == ["gold", "silver"] and [a["rank"] for a in out["awarded"]] == [1, 2]
    assert out["season"]["id"] == season["id"] and out["season"]["awarded"]
    assert out["history"][0]["medals"] == {"gold": 1, "silver": 1, "bronze": 0}
    assert close(client, ha, award=True).status_code == 409
    assert close(client, ha, award=True, reset=True).status_code == 409
    assert client.get("/api/orgs/me/season", headers=ha).json()["season"]["id"] == season["id"]
    b = board(client, hm)
    assert len(b["rows"]) == 2
    assert sorted(sum(r["medals"].values()) for r in b["rows"]) == [1, 1]
    medals = client.get("/api/profile/medals", headers=hm).json()
    assert len(medals) == 1 and medals[0]["season_name"] == "Сезон 1" and medals[0]["org_name"] == "Только медали"
    assert medals[0]["medal"] in ("gold", "silver") and medals[0]["rating"] > 0 and medals[0]["awarded_at"]
    # после выдачи сезон можно сбросить без медалей
    after = close(client, ha, reset=True, next_name="Весна").json()
    assert after["season"]["name"] == "Весна" and not after["season"]["awarded"]
    assert after["history"][0]["name"] == "Сезон 1" and after["history"][0]["ended_at"]


def test_reset_without_award(client):
    (ha, _), (hm, _) = team(client, 2, "Только сброс")
    play(client, hm)
    out = close(client, ha, reset=True).json()
    assert out["awarded"] == [] and out["season"]["name"] == "Сезон 2"
    assert out["history"][0]["name"] == "Сезон 1" and out["history"][0]["medals"] == {"gold": 0, "silver": 0, "bronze": 0}
    assert board(client, hm)["rows"] == []
    assert client.get("/api/profile/medals", headers=hm).json() == []


def test_award_and_reset_and_rating_counts_new_sessions_only(client):
    (ha, _), (hm, member) = team(client, 2, "Полный цикл")
    play(client, hm)
    play(client, hm)
    out = close(client, ha, award=True, reset=True, next_name="Осень-2026").json()
    assert [a["display_name"] for a in out["awarded"]] == ["Участник 1"]
    assert out["season"]["name"] == "Осень-2026"
    assert out["history"][0]["medals"]["gold"] == 1
    assert board(client, hm)["rows"] == []
    stats = client.get("/api/orgs/me/stats", params={"period": "all"}, headers=ha).json()
    assert stats["season"]["name"] == "Осень-2026"
    assert next(m for m in stats["members"] if m["id"] == member["id"])["sessions"] == 0
    assert close(client, ha, award=True).status_code == 409  # в новом сезоне пока некого награждать

    play(client, hm, moves=WEAK)
    rows = board(client, hm)["rows"]
    assert len(rows) == 1 and rows[0]["sessions"] == 1 and rows[0]["medals"]["gold"] == 1
    assert next(m for m in client.get("/api/orgs/me/stats", params={"period": "all"}, headers=ha).json()["members"] if m["id"] == member["id"])["sessions"] == 1
    assert close(client, ha, award=True).json()["awarded"][0]["medal"] == "gold"
    medals = client.get("/api/profile/medals", headers=hm).json()
    assert [m["season_name"] for m in medals] == ["Осень-2026", "Сезон 1"]
    # медали остаются у человека после выхода из организации
    client.post("/api/orgs/me/leave", headers=hm)
    assert len(client.get("/api/profile/medals", headers=hm).json()) == 2


def test_migration_adds_medal_columns_to_old_orgs():
    path = tempfile.mkdtemp(prefix="arena-old-orgs-")
    eng = create_engine(f"sqlite:///{path}/old.db")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE orgs (id VARCHAR(32) PRIMARY KEY, name VARCHAR(120), invite_code VARCHAR(16) UNIQUE, created_at DATETIME)"))
        c.execute(text("INSERT INTO orgs VALUES ('o1', 'Старая', 'ABCD1234', '2026-09-01 10:00:00')"))
    init_db(eng)
    init_db(eng)
    insp = inspect(eng)
    assert {"medal_slots", "gold_share", "silver_share"} <= {c["name"] for c in insp.get_columns("orgs")}
    assert {"seasons", "medals"} <= set(insp.get_table_names())
    with eng.connect() as c:
        assert c.execute(text("SELECT medal_slots, gold_share, silver_share FROM orgs")).all() == [(10, 0.2, 0.3)]
    eng.dispose()
