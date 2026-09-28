import hashlib
import hmac
import mimetypes
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import llm, scoring, service, voice
from .accounts import WRITE_LOCK, current_user, router as accounts_router
from .config import settings
from .db import ScenarioRow, SessionLocal, SessionRow, UserRow, get_db, init_db
from .engine import rules
from .schemas import OpponentState, RewindIn, Scenario, ScenarioBrief, ScenarioCard, SessionResult, TtsIn, TurnIn, TurnOut, VoiceTurnOut
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


def _is_org_admin(user: UserRow | None, org_id: str | None = None) -> bool:
    return user is not None and user.role == "org_admin" and bool(user.org_id) and (org_id is None or user.org_id == org_id)


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _can_edit(row: ScenarioRow, token: str | None, user: UserRow | None, edit_key: str | None) -> bool:
    """Встроенные сценарии правит только владелец запасного токена, остальные сохраняют копию.
    Зафиксированный — администратор его организации. Открытый — автор, администратор его организации или гость с ключом правки."""
    if _is_admin(token):
        return True
    if row.id in SEEDS:
        return False
    if row.card.get("locked_by_org"):
        return _is_org_admin(user, row.org_id)
    if user is not None and row.owner_id == user.id:
        return True
    if row.org_id and _is_org_admin(user, row.org_id):
        return True
    return row.owner_id is None and bool(row.edit_key) and bool(edit_key) and hmac.compare_digest(row.edit_key, _key_hash(edit_key))


def _check_lock_rights(card: ScenarioCard, token: str | None, user: UserRow | None) -> None:
    if card.locked_by_org and not _is_admin(token) and not _is_org_admin(user):
        raise HTTPException(403, "Фиксировать сценарий может только администратор организации")


def _out(row: ScenarioRow, token: str | None = None, user: UserRow | None = None, edit_key: str | None = None) -> Scenario:
    return Scenario(id=row.id, org_id=row.org_id, builtin=row.id in SEEDS, can_edit=_can_edit(row, token, user, edit_key), **row.card)


def _can_see(row: ScenarioRow, token: str | None, user: UserRow | None, known: set[str]) -> bool:
    """В списке: встроенные, свои, сценарии своей организации и сценарии, созданные этим браузером без входа (их id он передаёт сам)."""
    if _is_admin(token) or row.id in SEEDS:
        return True
    if user is not None and (row.owner_id == user.id or (row.org_id and row.org_id == user.org_id)):
        return True
    return row.owner_id is None and bool(row.edit_key) and row.id in known


@app.get("/api/scenarios", response_model=list[Scenario])
def list_scenarios(ids: str = "", db=Depends(get_db), x_admin_token: str | None = Header(default=None), user: UserRow | None = Depends(current_user)):
    known = {i for i in ids.split(",") if i}
    out = []
    for r in db.query(ScenarioRow).order_by(ScenarioRow.created_at):
        if not _can_see(r, x_admin_token, user, known):
            continue
        try:
            out.append(_out(r, x_admin_token, user))
        except ValidationError:
            continue
    return out


@app.post("/api/scenarios", response_model=Scenario)
def create_scenario(card: ScenarioCard, db=Depends(get_db), x_admin_token: str | None = Header(default=None), user: UserRow | None = Depends(current_user)):
    _check_lock_rights(card, x_admin_token, user)
    key = None if user else secrets.token_urlsafe(24)
    row = ScenarioRow(id=uuid4().hex[:12], card=card.model_dump(), org_id=user.org_id if user else None,
                      owner_id=user.id if user else None, edit_key=_key_hash(key) if key else None)
    db.add(row)
    db.commit()
    return _out(row, x_admin_token, user, key).model_copy(update={"edit_key": key})


@app.put("/api/scenarios/{scenario_id}", response_model=Scenario)
def update_scenario(scenario_id: str, card: ScenarioCard, db=Depends(get_db), x_admin_token: str | None = Header(default=None),
                    x_edit_key: str | None = Header(default=None), user: UserRow | None = Depends(current_user)):
    with WRITE_LOCK:
        row = db.get(ScenarioRow, scenario_id)
        if row is None:
            raise HTTPException(404, "Сценарий не найден")
        db.refresh(row)
        if not _can_edit(row, x_admin_token, user, x_edit_key):
            if row.id in SEEDS:
                raise HTTPException(403, "Встроенный сценарий не меняется: сохраните свою копию")
            if row.card.get("locked_by_org"):
                raise HTTPException(403, "Модуль зафиксирован организацией, менять его может только её администратор")
            raise HTTPException(403, "Менять сценарий может только автор или администратор его организации")
        _check_lock_rights(card, x_admin_token, user)
        if card.locked_by_org and not row.card.get("locked_by_org") and _is_org_admin(user):
            row.org_id = user.org_id
        row.card = card.model_dump()
        db.commit()
        return _out(row, x_admin_token, user, x_edit_key)


@app.post("/api/scenarios/generate", response_model=ScenarioCard)
def generate_scenario(brief: ScenarioBrief):
    if settings.offline_mode:
        raise HTTPException(503, "Генерация недоступна без LLM")
    try:
        return llm.generate_card(brief.description).model_copy(update={"avatar_url": None})
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


@app.post("/api/sessions/{session_id}/voice", response_model=VoiceTurnOut)
def voice_turn(session_id: str, audio: UploadFile = File(...), db=Depends(get_db), user: UserRow | None = Depends(current_user)):
    """Голосовая реплика: запись → распознавание → обычный ход. Распознанный текст уходит в разметку, как если бы его напечатали."""
    row = _session(db, session_id, user)
    if row.status != "active":
        raise HTTPException(409, "Сессия уже завершена")
    if not voice.stt_ready():
        raise HTTPException(503, voice.NOT_CONFIGURED)
    data = audio.file.read(voice.MAX_AUDIO_BYTES + 1)
    try:
        prepared, ext = voice.prepare_audio(data)
        text = voice.recognize(prepared)
    except voice.VoiceError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    if not text:
        raise HTTPException(422, "Речь не распознана: запишите ещё раз или напишите текстом")
    url = voice.save_voice(data, ext)
    with service.lock(session_id):
        try:
            out = service.turn(db, _session(db, session_id, user), text[:2500], audio_url=url)
        except service.SessionClosed:
            raise HTTPException(409, "Сессия уже завершена") from None
    return VoiceTurnOut(**out.model_dump(), recognized=text, audio_url=url)


@app.get("/api/voice/status")
def voice_status():
    return voice.status()


@app.post("/api/tts")
def tts(payload: TtsIn):
    """Озвучка реплики собеседника: WAV в base64 и тайминги слов для липсинка. Без ключей 503, фронт тогда двигает губы беззвучно."""
    try:
        return voice.synthesize(payload.text, payload.emotion, payload.voice)
    except voice.VoiceError as exc:
        raise HTTPException(exc.status, exc.message) from exc


@app.post("/api/avatars")
def upload_avatar(file: UploadFile = File(...)):
    """Свой GLB-аватар для сценария: расширение, сигнатура glTF 2.0, лимит размера, узлы скелета. Ссылку кладут в avatar_url карточки."""
    data = file.file.read(settings.avatar_max_mb * 1024 * 1024 + 1)
    try:
        return voice.save_avatar(data, file.filename or "")
    except voice.VoiceError as exc:
        raise HTTPException(exc.status, exc.message) from exc


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
def list_sessions(ids: str = "", db=Depends(get_db), user: UserRow | None = Depends(current_user)):
    """Вошедший видит свои сессии. Общего списка гостевых сессий нет: гость получает только те, id которых знает сам (браузер хранит их локально)."""
    if user:
        q = db.query(SessionRow).filter(SessionRow.user_id == user.id)
    else:
        known = [i for i in ids.split(",") if i][:50]
        q = db.query(SessionRow).filter(SessionRow.user_id.is_(None), SessionRow.id.in_(known))
    rows = q.order_by(SessionRow.created_at.desc()).limit(50)
    return [{"id": r.id, "scenario": r.card["name"], "scenario_id": r.scenario_id, "status": r.status, "outcome": r.outcome, "turns": r.turn,
             "created_at": r.created_at.isoformat() if r.created_at else None, "score": _score(r)} for r in rows]


def _score(r: SessionRow) -> float | None:
    """Очко сессии для списка: только если судья уже разобрал её."""
    if not r.judge:
        return None
    card = ScenarioCard(**r.card)
    ok = r.outcome == "walk_away" and rules.walk_away_justified(card, OpponentState(**r.state).position)
    return scoring.session_score(r.judge.get("axes"), card.difficulty, r.outcome, ok)


mimetypes.add_type("model/gltf-binary", ".glb")
UPLOADS = voice.uploads_dir()
UPLOADS.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")

STATIC = Path(__file__).resolve().parent.parent / "static"
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        """Файлы из корня сборки (модель аватара и т. п.) отдаём как есть, остальные пути — страница приложения."""
        f = (STATIC / path).resolve()
        if path and f.is_file() and STATIC.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(STATIC / "index.html")
