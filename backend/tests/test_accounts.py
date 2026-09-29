import tempfile
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app import scoring
from app.accounts import hash_password, verify_password
from app.db import SessionLocal, SessionRow, init_db
from app.main import app
from app.seeds import SEEDS

GOOD = ["Понимаю вашу позицию. Что для вас важно в этом отчёте?", "Данные от смежного отдела приходят с опозданием, это стандарт по регламенту.",
        "А если сделать предварительную версию к совещанию?"]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def register(client, name="Иван"):
    r = client.post("/api/auth/register", json={"login": f"u{uuid4().hex[:10]}", "password": "secret123", "display_name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]


def play(client, headers, scenario="deadline-with-manager", moves=GOOD):
    sid = client.post("/api/sessions", params={"scenario_id": scenario}, headers=headers).json()["session_id"]
    for m in moves:
        client.post(f"/api/sessions/{sid}/turn", json={"message": m}, headers=headers)
    client.post(f"/api/sessions/{sid}/finish", headers=headers)
    return sid


def test_password_hash_roundtrip():
    h = hash_password("secret123")
    assert h.startswith("pbkdf2_sha256$") and "secret123" not in h
    assert verify_password("secret123", h) and not verify_password("secret124", h)
    assert not verify_password("x", "garbage")


def test_register_login_logout(client):
    login = f"u{uuid4().hex[:10]}"
    r = client.post("/api/auth/register", json={"login": login, "password": "secret123"})
    assert r.status_code == 200 and r.json()["user"]["display_name"] == login and r.json()["user"]["role"] == "member"
    assert client.post("/api/auth/register", json={"login": login.upper(), "password": "secret123"}).status_code == 409
    assert client.post("/api/auth/register", json={"login": "ab", "password": "secret123"}).status_code == 422
    assert client.post("/api/auth/login", json={"login": login, "password": "wrong"}).status_code == 401
    tok = client.post("/api/auth/login", json={"login": login, "password": "secret123"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/auth/me", headers=h).json()["login"] == login
    client.post("/api/auth/logout", headers=h)
    assert client.get("/api/auth/me", headers=h).status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_session_bound_to_user_and_history_is_private(client):
    h1, u1 = register(client)
    h2, _ = register(client)
    sid = play(client, h1)
    with SessionLocal() as db:
        assert db.get(SessionRow, sid).user_id == u1["id"]
    assert [s["id"] for s in client.get("/api/sessions", headers=h1).json()] == [sid]
    assert client.get("/api/sessions", headers=h2).json() == []
    assert sid not in [s["id"] for s in client.get("/api/sessions").json()]
    assert client.get(f"/api/sessions/{sid}", headers=h2).status_code == 404
    assert client.get(f"/api/sessions/{sid}/result").status_code == 404
    assert client.get(f"/api/sessions/{sid}/result", headers=h1).status_code == 200
    new = client.post(f"/api/sessions/{sid}/rewind", json={"turn": 1}, headers=h1).json()
    with SessionLocal() as db:
        assert db.get(SessionRow, new["id"]).user_id == u1["id"]


def test_guest_mode_unchanged(client):
    sid = play(client, {})
    with SessionLocal() as db:
        assert db.get(SessionRow, sid).user_id is None
    assert sid not in [s["id"] for s in client.get("/api/sessions").json()]
    assert [s["id"] for s in client.get("/api/sessions", params={"ids": f"{sid},nope"}).json()] == [sid]
    assert client.get(f"/api/sessions/{sid}/result").json()["judge_source"] == "rules"
    assert client.get(f"/api/sessions/{sid}", headers={"Authorization": "Bearer stale"}).status_code == 200


def test_org_invite_join_and_cabinet_rights(client):
    ha, _ = register(client, "Админ")
    hm, member = register(client, "Сотрудник")
    hx, _ = register(client, "Чужой")
    org = client.post("/api/orgs", json={"name": "Алабуга"}, headers=ha).json()
    assert org["invite_code"]
    assert client.get("/api/auth/me", headers=ha).json()["role"] == "org_admin"
    assert client.post("/api/orgs", json={"name": "Ещё одна"}, headers=ha).status_code == 409
    assert client.post("/api/orgs/join", json={"code": "NOPE0000"}, headers=hm).status_code == 404
    joined = client.post("/api/orgs/join", json={"code": org["invite_code"].lower()}, headers=hm).json()
    assert joined["name"] == "Алабуга" and joined["invite_code"] is None
    assert client.get("/api/auth/me", headers=hm).json()["org_name"] == "Алабуга"

    play(client, hm)
    stats = client.get("/api/orgs/me/stats", params={"period": "week"}, headers=ha).json()
    row = next(m for m in stats["members"] if m["id"] == member["id"])
    assert row["sessions"] == 1 and row["training_minutes"] >= 0 and row["axes"] and row["in_zone_share"] == 0 and row["rating"] is not None
    assert client.get("/api/orgs/me/stats", headers=hm).status_code == 403
    assert client.get("/api/orgs/me/stats", headers=hx).status_code == 403
    assert client.get("/api/orgs/me/stats").status_code == 401
    assert client.get("/api/orgs/me/stats", params={"period": "year"}, headers=ha).status_code == 422
    old = org["invite_code"]
    assert client.post("/api/orgs/me/invite", headers=ha).json()["invite_code"] != old
    assert client.post("/api/orgs/me/invite", headers=hm).status_code == 403


def test_locked_scenario_belongs_to_org(client):
    ha, _ = register(client)
    hm, _ = register(client)
    hb, _ = register(client)
    code = client.post("/api/orgs", json={"name": "Орг А"}, headers=ha).json()["invite_code"]
    client.post("/api/orgs/join", json={"code": code}, headers=hm)
    client.post("/api/orgs", json={"name": "Орг Б"}, headers=hb)
    card = SEEDS["split-with-colleague"].model_dump() | {"locked_by_org": True}
    assert client.post("/api/scenarios", json=card, headers=hm).status_code == 403
    sc = client.post("/api/scenarios", json=card, headers=ha).json()
    me = client.get("/api/auth/me", headers=ha).json()
    assert sc["org_id"] == me["org_id"]
    assert client.put(f"/api/scenarios/{sc['id']}", json=card, headers=hm).status_code == 403
    assert client.put(f"/api/scenarios/{sc['id']}", json=card, headers=hb).status_code == 403
    assert client.put(f"/api/scenarios/{sc['id']}", json=card | {"name": "Новое"}, headers=ha).json()["name"] == "Новое"
    r = client.put(f"/api/scenarios/{sc['id']}", json=card, headers={"X-Admin-Token": "test-admin"}).json()
    assert r["org_id"] == me["org_id"]


def test_score_formula():
    axes = {"a": 60, "b": 80}
    assert scoring.session_score(axes, "medium", "breakdown") == 70
    assert scoring.session_score(axes, "easy", None) == 56
    assert scoring.session_score(axes, "hard", "agreement_in_zone") == 97.5
    assert scoring.session_score(None, "hard", "agreement_in_zone") is None
    assert scoring.user_rating([10, 90, 80, 70, 60, 50, 100]) == 80
    assert scoring.user_rating([40]) == 40 and scoring.user_rating([]) is None


def test_leaderboard_org_and_global(client):
    ha, _ = register(client, "Лидер")
    hm, _ = register(client, "Скрытый")
    code = client.post("/api/orgs", json={"name": "Команда"}, headers=ha).json()["invite_code"]
    client.post("/api/orgs/join", json={"code": code}, headers=hm)
    play(client, ha)
    play(client, hm, moves=GOOD[:1] + ["Это не обсуждается.", "Делайте как хотите"])
    board = client.get("/api/leaderboard", params={"scope": "org", "period": "all"}, headers=hm).json()
    assert [r["display_name"] for r in board["rows"]] == ["Лидер", "Скрытый"] and board["rows"][1]["me"]
    names = lambda: [r["display_name"] for r in client.get("/api/leaderboard", params={"scope": "global"}).json()["rows"]]
    assert "Лидер" not in names()
    client.patch("/api/profile", json={"public_in_leaderboard": True}, headers=ha)
    assert "Лидер" in names() and "Скрытый" not in names()
    assert client.get("/api/leaderboard", params={"scope": "org"}).status_code == 403


def test_period_filter():
    with SessionLocal() as db:
        row = db.query(SessionRow).first()
        assert scoring.in_period(row, scoring.since("week"))
        assert not scoring.in_period(row, scoring.aware(row.created_at) + timedelta(seconds=1))
        assert scoring.in_period(row, scoring.since("all"))


def test_migration_adds_columns_to_old_schema():
    path = tempfile.mkdtemp(prefix="arena-old-")
    eng = create_engine(f"sqlite:///{path}/old.db")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE scenarios (id VARCHAR(64) PRIMARY KEY, card JSON, created_at DATETIME)"))
        c.execute(text("CREATE TABLE sessions (id VARCHAR(64) PRIMARY KEY, scenario_id VARCHAR(64) REFERENCES scenarios(id), card JSON, state JSON, "
                       "status VARCHAR(16), outcome VARCHAR(32), agreed_value FLOAT, turn INTEGER, judge JSON, created_at DATETIME)"))
        c.execute(text("INSERT INTO scenarios VALUES ('s1', '{}', '2026-09-01 10:00:00')"))
        c.execute(text("INSERT INTO sessions VALUES ('x1', 's1', '{}', '{}', 'finished', NULL, NULL, 3, NULL, '2026-09-01 10:00:00')"))
    init_db(eng)
    init_db(eng)
    insp = inspect(eng)
    assert "user_id" in {c["name"] for c in insp.get_columns("sessions")}
    assert "org_id" in {c["name"] for c in insp.get_columns("scenarios")}
    assert {"users", "orgs", "auth_tokens"} <= set(insp.get_table_names())
    with eng.connect() as c:
        assert c.execute(text("SELECT id, user_id FROM sessions")).all() == [("x1", None)]
    eng.dispose()


def test_member_roles_remove_and_leave(client):
    ha, admin = register(client, "Админ")
    hm, member = register(client, "Сотрудник")
    hx, stranger = register(client, "Чужой")
    code = client.post("/api/orgs", json={"name": "Роли"}, headers=ha).json()["invite_code"]
    client.post("/api/orgs/join", json={"code": code}, headers=hm)
    client.post("/api/orgs", json={"name": "Другая"}, headers=hx)
    url = f"/api/orgs/me/members/{member['id']}"
    assert client.patch(url, json={"role": "org_admin"}, headers=hm).status_code == 403
    assert client.patch(url, json={"role": "org_admin"}, headers=hx).status_code == 404
    assert client.patch(url, json={"role": "owner"}, headers=ha).status_code == 422
    assert client.patch(url, json={"role": "org_admin"}, headers=ha).json()["role"] == "org_admin"
    assert client.get("/api/orgs/me/stats", headers=hm).status_code == 200
    assert client.patch(f"/api/orgs/me/members/{admin['id']}", json={"role": "member"}, headers=hm).json()["role"] == "member"
    assert client.patch(url, json={"role": "member"}, headers=hm).status_code == 409
    assert client.post("/api/orgs/me/leave", headers=hm).status_code == 409
    assert client.delete(url, headers=hm).status_code == 409
    assert client.delete(f"/api/orgs/me/members/{stranger['id']}", headers=hm).status_code == 404
    assert client.delete(f"/api/orgs/me/members/{admin['id']}", headers=hm).json() == {"ok": True}
    me = client.get("/api/auth/me", headers=ha).json()
    assert me["org_id"] is None and me["role"] == "member"
    assert client.post("/api/orgs/me/leave", headers=hm).json()["org_id"] is None
    assert client.post("/api/orgs/me/leave", headers=hm).status_code == 404
    assert client.post("/api/orgs/me/leave").status_code == 401


def test_open_scenarios_belong_to_author(client):
    ha, _ = register(client)
    hm, _ = register(client)
    hb, _ = register(client)
    code = client.post("/api/orgs", json={"name": "Авторы А"}, headers=ha).json()["invite_code"]
    client.post("/api/orgs/join", json={"code": code}, headers=hm)
    client.post("/api/orgs", json={"name": "Авторы Б"}, headers=hb)
    card = SEEDS["split-with-colleague"].model_dump()
    seed = "deadline-with-manager"
    for h in ({}, hm, ha, hb):
        assert client.put(f"/api/scenarios/{seed}", json=SEEDS[seed].model_dump() | {"name": "Взлом"}, headers=h).status_code == 403
    assert next(s for s in client.get("/api/scenarios").json() if s["id"] == seed)["builtin"] is True

    own = client.post("/api/scenarios", json=card, headers=hm).json()
    assert own["can_edit"] and own["edit_key"] is None
    assert client.put(f"/api/scenarios/{own['id']}", json=card | {"name": "Моё"}, headers=hm).status_code == 200
    assert client.put(f"/api/scenarios/{own['id']}", json=card | {"name": "Админ"}, headers=ha).status_code == 200
    assert client.put(f"/api/scenarios/{own['id']}", json=card, headers={}).status_code == 403
    assert client.put(f"/api/scenarios/{own['id']}", json=card | {"locked_by_org": True}, headers=hb).status_code == 403
    assert client.put(f"/api/scenarios/{own['id']}", json=card | {"locked_by_org": True}, headers=hm).status_code == 403
    listed = {s["id"]: s for s in client.get("/api/scenarios", headers=hb).json()}
    assert own["id"] not in listed and listed[seed]["can_edit"] is False

    guest = client.post("/api/scenarios", json=card).json()
    key = guest["edit_key"]
    assert key and not client.get("/api/scenarios").json()[-1].get("edit_key")
    assert client.put(f"/api/scenarios/{guest['id']}", json=card).status_code == 403
    assert client.put(f"/api/scenarios/{guest['id']}", json=card, headers={"X-Edit-Key": "wrong"}).status_code == 403
    assert client.put(f"/api/scenarios/{guest['id']}", json=card, headers=hb).status_code == 403
    assert client.put(f"/api/scenarios/{guest['id']}", json=card | {"name": "Гость"}, headers={"X-Edit-Key": key}).json()["name"] == "Гость"
    assert client.put(f"/api/scenarios/{guest['id']}", json=card | {"locked_by_org": True}, headers={"X-Edit-Key": key}).status_code == 403


def test_scenario_list_is_scoped(client):
    ha, _ = register(client)
    hm, _ = register(client)
    hb, _ = register(client)
    code = client.post("/api/orgs", json={"name": "Видимость А"}, headers=ha).json()["invite_code"]
    client.post("/api/orgs/join", json={"code": code}, headers=hm)
    client.post("/api/orgs", json={"name": "Видимость Б"}, headers=hb)
    card = SEEDS["split-with-colleague"].model_dump()
    locked = client.post("/api/scenarios", json=card | {"locked_by_org": True}, headers=ha).json()["id"]
    own = client.post("/api/scenarios", json=card, headers=hm).json()["id"]
    guest = client.post("/api/scenarios", json=card).json()["id"]
    ids = lambda h, **p: {s["id"] for s in client.get("/api/scenarios", headers=h, params=p).json()}
    assert set(SEEDS) <= ids({}) and set(SEEDS) <= ids(hb)
    assert {locked, own} <= ids(hm) and {locked, own} <= ids(ha)
    assert not {locked, own, guest} & ids(hb)
    assert not {locked, own, guest} & ids({})
    assert guest in ids({}, ids=f"{guest},{locked}") and locked not in ids({}, ids=f"{guest},{locked}")
    assert {locked, own, guest} <= ids({"X-Admin-Token": "test-admin"})
