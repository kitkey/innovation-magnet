from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import llm, service
from .accounts import current_user, router as accounts_router
from .config import settings
from .db import ScenarioRow, SessionLocal, SessionRow, UserRow, get_db, init_db
from .schemas import RewindIn, Scenario, ScenarioBrief, ScenarioCard, SessionResult, TurnIn, TurnOut
from .seeds import SEEDS


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        for sid, card in SEEDS.items():
            row = db.get(ScenarioRow, sid)
            if row is None:
                db.add(ScenarioRow(id=sid, card=card.model_dump()))
            elif not row.card.get("locked_by_org"):
                row.card = card.model_dump()
        db.commit()
    yield


app = FastAPI(title="Арена переговоров", version="0.1.0", lifespan=lifespan)
app.include_router(accounts_router)


@app.get("/api/health")
def health():
    return {"ok": True, "offline_mode": settings.offline_mode, "model": settings.llm_model}


def _is_admin(token: str | None) -> bool:
    return bool(settings.admin_token) and token == settings.admin_token


def _is_org_admin(user: UserRow | None) -> bool:
    return user is not None and user.role == "org_admin" and bool(user.org_id)


def _check_lock_rights(card: ScenarioCard, token: str | None, user: UserRow | None) -> None:
    if card.locked_by_org and settings.admin_token and not _is_admin(token) and not _is_org_admin(user):
        raise HTTPException(403, "Фиксировать сценарий может только администратор")


def _owner_org(card: ScenarioCard, user: UserRow | None, current: str | None = None) -> str | None:
    """Зафиксированный сценарий принадлежит организации того, кто его зафиксировал; запасной admin-токен владельца не меняет."""
    if not card.locked_by_org:
        return None
    return current or (user.org_id if _is_org_admin(user) else None)


def _out(row: ScenarioRow) -> Scenario:
    return Scenario(id=row.id, org_id=row.org_id, **row.card)


@app.get("/api/scenarios", response_model=list[Scenario])
def list_scenarios(db=Depends(get_db)):
    out = []
    for r in db.query(ScenarioRow).order_by(ScenarioRow.created_at):
        try:
            out.append(_out(r))
        except ValidationError:
            continue
    return out


@app.post("/api/scenarios", response_model=Scenario)
def create_scenario(card: ScenarioCard, db=Depends(get_db), x_admin_token: str | None = Header(default=None), user: UserRow | None = Depends(current_user)):
    _check_lock_rights(card, x_admin_token, user)
    row = ScenarioRow(id=uuid4().hex[:12], card=card.model_dump(), org_id=_owner_org(card, user))
    db.add(row)
    db.commit()
    return _out(row)


@app.put("/api/scenarios/{scenario_id}", response_model=Scenario)
def update_scenario(scenario_id: str, card: ScenarioCard, db=Depends(get_db), x_admin_token: str | None = Header(default=None), user: UserRow | None = Depends(current_user)):
    row = db.get(ScenarioRow, scenario_id)
    if row is None:
        raise HTTPException(404, "Сценарий не найден")
    own_admin = _is_org_admin(user) and row.org_id is not None and row.org_id == user.org_id
    if row.card.get("locked_by_org") and not _is_admin(x_admin_token) and not own_admin:
        raise HTTPException(403, "Модуль зафиксирован организацией, менять его может только администратор")
    _check_lock_rights(card, x_admin_token, user)
    row.card = card.model_dump()
    row.org_id = _owner_org(card, user, row.org_id)
    db.commit()
    return _out(row)


@app.post("/api/scenarios/generate", response_model=ScenarioCard)
def generate_scenario(brief: ScenarioBrief):
    if settings.offline_mode:
        raise HTTPException(503, "Генерация недоступна без LLM")
    try:
        return llm.generate_card(brief.description)
    except Exception as exc:
        raise HTTPException(502, f"LLM недоступна: {exc}") from exc


@app.post("/api/sessions")
def start_session(scenario_id: str, db=Depends(get_db), user: UserRow | None = Depends(current_user)):
    sc = db.get(ScenarioRow, scenario_id)
    if sc is None:
        raise HTTPException(404, "Сценарий не найден")
    row = service.start(db, sc.id, ScenarioCard(**sc.card), user.id if user else None)
    return {"session_id": row.id, "opening": row.turns[0].text, "max_turns": row.card["max_turns"]}


def _session(db, session_id: str, user: UserRow | None) -> SessionRow:
    """Сессию пользователя видит только он сам; гостевые сессии открыты по ссылке, как раньше."""
    row = db.get(SessionRow, session_id)
    if row is None or (row.user_id is not None and (user is None or user.id != row.user_id)):
        raise HTTPException(404, "Сессия не найдена")
    return row


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, db=Depends(get_db), user: UserRow | None = Depends(current_user)):
    return service.view(_session(db, session_id, user))


@app.post("/api/sessions/{session_id}/turn", response_model=TurnOut)
def make_turn(session_id: str, payload: TurnIn, db=Depends(get_db), user: UserRow | None = Depends(current_user)):
    with service.lock(session_id):
        try:
            return service.turn(db, _session(db, session_id, user), payload.message)
        except service.SessionClosed:
            raise HTTPException(409, "Сессия уже завершена") from None


@app.post("/api/sessions/{session_id}/finish")
def finish_session(session_id: str, db=Depends(get_db), user: UserRow | None = Depends(current_user)):
    with service.lock(session_id):
        service.finish(db, _session(db, session_id, user))
    return {"ok": True}


@app.post("/api/sessions/{session_id}/rewind")
def rewind_session(session_id: str, payload: RewindIn, db=Depends(get_db), user: UserRow | None = Depends(current_user)):
    with service.lock(session_id):
        try:
            row = service.rewind(db, _session(db, session_id, user), payload.turn)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return service.view(row)


@app.get("/api/sessions/{session_id}/result", response_model=SessionResult)
def session_result(session_id: str, db=Depends(get_db), user: UserRow | None = Depends(current_user)):
    return service.result(db, _session(db, session_id, user))


@app.get("/api/sessions")
def list_sessions(db=Depends(get_db), user: UserRow | None = Depends(current_user)):
    """Вошедший видит свои сессии, гость — только гостевые."""
    q = db.query(SessionRow).filter(SessionRow.user_id == user.id) if user else db.query(SessionRow).filter(SessionRow.user_id.is_(None))
    rows = q.order_by(SessionRow.created_at.desc()).limit(50)
    return [{"id": r.id, "scenario": r.card["name"], "status": r.status, "outcome": r.outcome, "turns": r.turn} for r in rows]


STATIC = Path(__file__).resolve().parent.parent / "static"
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        return FileResponse(STATIC / "index.html")
