from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import llm, service
from .config import settings
from .db import ScenarioRow, SessionLocal, SessionRow, init_db
from .schemas import Scenario, ScenarioBrief, ScenarioCard, SessionResult, TurnIn, TurnOut
from .seeds import SEEDS


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        for sid, card in SEEDS.items():
            if db.get(ScenarioRow, sid) is None:
                db.add(ScenarioRow(id=sid, card=card.model_dump()))
        db.commit()
    yield


app = FastAPI(title="Арена переговоров", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"ok": True, "offline_mode": settings.offline_mode, "model": settings.llm_model}


@app.get("/api/scenarios", response_model=list[Scenario])
def list_scenarios(db=Depends(get_db)):
    return [Scenario(id=r.id, **r.card) for r in db.query(ScenarioRow).order_by(ScenarioRow.created_at)]


@app.post("/api/scenarios", response_model=Scenario)
def create_scenario(card: ScenarioCard, db=Depends(get_db)):
    row = ScenarioRow(id=uuid4().hex[:12], card=card.model_dump())
    db.add(row)
    db.commit()
    return Scenario(id=row.id, **row.card)


@app.put("/api/scenarios/{scenario_id}", response_model=Scenario)
def update_scenario(scenario_id: str, card: ScenarioCard, db=Depends(get_db)):
    row = db.get(ScenarioRow, scenario_id)
    if row is None:
        raise HTTPException(404, "Сценарий не найден")
    if row.card.get("locked_by_org"):
        raise HTTPException(403, "Модуль зафиксирован организацией")
    row.card = card.model_dump()
    db.commit()
    return Scenario(id=row.id, **row.card)


@app.post("/api/scenarios/generate", response_model=ScenarioCard)
def generate_scenario(brief: ScenarioBrief):
    if settings.offline_mode:
        raise HTTPException(503, "Генерация недоступна без LLM")
    try:
        return llm.generate_card(brief.description)
    except Exception as exc:
        raise HTTPException(502, f"LLM недоступна: {exc}") from exc


@app.post("/api/sessions")
def start_session(scenario_id: str, db=Depends(get_db)):
    sc = db.get(ScenarioRow, scenario_id)
    if sc is None:
        raise HTTPException(404, "Сценарий не найден")
    row = service.start(db, sc.id, ScenarioCard(**sc.card))
    return {"session_id": row.id, "opening": row.turns[0].text, "max_turns": row.card["max_turns"]}


def _session(db, session_id: str) -> SessionRow:
    row = db.get(SessionRow, session_id)
    if row is None:
        raise HTTPException(404, "Сессия не найдена")
    return row


@app.post("/api/sessions/{session_id}/turn", response_model=TurnOut)
def make_turn(session_id: str, payload: TurnIn, db=Depends(get_db)):
    row = _session(db, session_id)
    if row.status != "active":
        raise HTTPException(409, "Сессия уже завершена")
    return service.turn(db, row, payload.message)


@app.post("/api/sessions/{session_id}/finish")
def finish_session(session_id: str, db=Depends(get_db)):
    service.finish(db, _session(db, session_id))
    return {"ok": True}


@app.get("/api/sessions/{session_id}/result", response_model=SessionResult)
def session_result(session_id: str, db=Depends(get_db)):
    return service.result(db, _session(db, session_id))


@app.get("/api/sessions")
def list_sessions(db=Depends(get_db)):
    rows = db.query(SessionRow).order_by(SessionRow.created_at.desc()).limit(50)
    return [{"id": r.id, "scenario": r.card["name"], "status": r.status, "outcome": r.outcome, "turns": r.turn} for r in rows]


STATIC = Path(__file__).resolve().parent.parent / "static"
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        return FileResponse(STATIC / "index.html")
