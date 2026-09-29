"""Аккаунты, организации, кабинет и лидерборд. Без входа тренажёр работает в гостевом режиме, как раньше."""
import hashlib
import hmac
import secrets
import threading
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from . import scoring
from .db import AuthTokenRow, MedalRow, OrgRow, SeasonRow, SessionRow, UserRow, get_db

router = APIRouter(prefix="/api")

PBKDF2_ROUNDS = 200_000
WRITE_LOCK = threading.RLock()
"""Проверка прав и запись членства/сценариев одной критической секцией: без неё два одновременных запроса проходят проверку оба."""


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, digest = stored.split("$")
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
    except ValueError:
        return False
    return hmac.compare_digest(check, digest)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(authorization: str | None = Header(default=None), db=Depends(get_db)) -> UserRow | None:
    """Пользователь по Bearer-токену; без токена или с устаревшим токеном запрос идёт как гостевой."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    tok = db.get(AuthTokenRow, _token_hash(authorization[7:].strip()))
    return db.get(UserRow, tok.user_id) if tok else None


def require_user(user: UserRow | None = Depends(current_user)) -> UserRow:
    if user is None:
        raise HTTPException(401, "Нужно войти")
    return user


def require_org_admin(user: UserRow = Depends(require_user)) -> UserRow:
    if user.role != "org_admin" or not user.org_id:
        raise HTTPException(403, "Кабинет доступен только администратору организации")
    return user


class RegisterIn(BaseModel):
    login: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.\-]+$")
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=80)


class LoginIn(BaseModel):
    login: str
    password: str


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    public_in_leaderboard: bool | None = None


class OrgIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class JoinIn(BaseModel):
    code: str = Field(min_length=4, max_length=16)


class RoleIn(BaseModel):
    role: Literal["member", "org_admin"]


class MedalsIn(BaseModel):
    medal_slots: int = Field(ge=0, le=1000)
    gold_share: float = Field(ge=0, le=1)
    silver_share: float = Field(ge=0, le=1)


class SeasonCloseIn(BaseModel):
    award: bool
    reset: bool
    next_name: str = Field(default="", max_length=80)


def user_out(db, u: UserRow) -> dict:
    org = db.get(OrgRow, u.org_id) if u.org_id else None
    return {"id": u.id, "login": u.login, "display_name": u.display_name, "role": u.role, "org_id": u.org_id,
            "org_name": org.name if org else None, "public_in_leaderboard": u.public_in_leaderboard}


def _issue(db, u: UserRow) -> dict:
    token = secrets.token_urlsafe(32)
    db.add(AuthTokenRow(token_hash=_token_hash(token), user_id=u.id))
    db.commit()
    return {"token": token, "user": user_out(db, u)}


@router.post("/auth/register")
def register(payload: RegisterIn, db=Depends(get_db)):
    login = payload.login.lower()
    if db.query(UserRow).filter_by(login=login).first():
        raise HTTPException(409, "Такой логин уже занят")
    u = UserRow(id=uuid4().hex, login=login, pw_hash=hash_password(payload.password), display_name=payload.display_name.strip() or payload.login)
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Такой логин уже занят") from None
    return _issue(db, u)


@router.post("/auth/login")
def login(payload: LoginIn, db=Depends(get_db)):
    u = db.query(UserRow).filter_by(login=payload.login.strip().lower()).first()
    if u is None or not verify_password(payload.password, u.pw_hash):
        raise HTTPException(401, "Неверный логин или пароль")
    return _issue(db, u)


@router.post("/auth/logout")
def logout(authorization: str | None = Header(default=None), db=Depends(get_db)):
    if authorization and authorization.lower().startswith("bearer "):
        tok = db.get(AuthTokenRow, _token_hash(authorization[7:].strip()))
        if tok:
            db.delete(tok)
            db.commit()
    return {"ok": True}


@router.get("/auth/me")
def me(user: UserRow = Depends(require_user), db=Depends(get_db)):
    return user_out(db, user)


@router.patch("/profile")
def update_profile(payload: ProfileIn, user: UserRow = Depends(require_user), db=Depends(get_db)):
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip() or user.display_name
    if payload.public_in_leaderboard is not None:
        user.public_in_leaderboard = payload.public_in_leaderboard
    db.commit()
    return user_out(db, user)


def _new_code(db) -> str:
    while True:
        code = secrets.token_hex(4).upper()
        if not db.query(OrgRow).filter_by(invite_code=code).first():
            return code


def org_out(org: OrgRow, user: UserRow) -> dict:
    return {"id": org.id, "name": org.name, "invite_code": org.invite_code if user.role == "org_admin" else None}


@router.post("/orgs")
def create_org(payload: OrgIn, user: UserRow = Depends(require_user), db=Depends(get_db)):
    with WRITE_LOCK:
        db.refresh(user)
        if user.org_id:
            raise HTTPException(409, "Вы уже состоите в организации")
        org = OrgRow(id=uuid4().hex, name=payload.name.strip(), invite_code=_new_code(db))
        db.add(org)
        db.flush()
        user.org_id, user.role = org.id, "org_admin"
        db.commit()
    return org_out(org, user)


@router.post("/orgs/join")
def join_org(payload: JoinIn, user: UserRow = Depends(require_user), db=Depends(get_db)):
    with WRITE_LOCK:
        db.refresh(user)
        org = db.query(OrgRow).filter_by(invite_code=payload.code.strip().upper()).first()
        if org is None:
            raise HTTPException(404, "Код приглашения не найден")
        if user.org_id and user.org_id != org.id:
            raise HTTPException(409, "Вы уже состоите в другой организации")
        if user.org_id != org.id:
            user.org_id, user.role = org.id, "member"
            db.commit()
    return org_out(org, user)


@router.get("/orgs/me")
def my_org(user: UserRow = Depends(require_user), db=Depends(get_db)):
    if not user.org_id:
        raise HTTPException(404, "Вы не состоите в организации")
    return org_out(db.get(OrgRow, user.org_id), user)


@router.post("/orgs/me/invite")
def new_invite(user: UserRow = Depends(require_org_admin), db=Depends(get_db)):
    org = db.get(OrgRow, user.org_id)
    org.invite_code = _new_code(db)
    db.commit()
    return org_out(org, user)


def _member(db, admin: UserRow, user_id: str) -> UserRow:
    m = db.get(UserRow, user_id)
    if m is None or m.org_id != admin.org_id:
        raise HTTPException(404, "Участник не найден")
    return m


def _admin_count(db, org_id: str) -> int:
    return db.query(UserRow).filter_by(org_id=org_id, role="org_admin").count()


def member_out(m: UserRow) -> dict:
    return {"id": m.id, "login": m.login, "display_name": m.display_name, "role": m.role}


@router.patch("/orgs/me/members/{user_id}")
def set_member_role(user_id: str, payload: RoleIn, admin: UserRow = Depends(require_org_admin), db=Depends(get_db)):
    """Администратор назначает или снимает администратора. Последнего администратора снять нельзя, иначе кабинет останется без хозяина."""
    with WRITE_LOCK:
        m = _member(db, admin, user_id)
        if m.role == "org_admin" and payload.role == "member" and _admin_count(db, m.org_id) <= 1:
            raise HTTPException(409, "В организации должен остаться хотя бы один администратор")
        m.role = payload.role
        db.commit()
    return member_out(m)


@router.delete("/orgs/me/members/{user_id}")
def remove_member(user_id: str, admin: UserRow = Depends(require_org_admin), db=Depends(get_db)):
    with WRITE_LOCK:
        m = _member(db, admin, user_id)
        if m.id == admin.id:
            raise HTTPException(409, "Себя удалить нельзя: выйдите из организации в профиле")
        m.org_id, m.role = None, "member"
        db.commit()
    return {"ok": True}


@router.post("/orgs/me/leave")
def leave_org(user: UserRow = Depends(require_user), db=Depends(get_db)):
    """Выход из организации. Единственный администратор при других участниках сначала назначает преемника."""
    with WRITE_LOCK:
        db.refresh(user)
        if not user.org_id:
            raise HTTPException(404, "Вы не состоите в организации")
        others = db.query(UserRow).filter(UserRow.org_id == user.org_id, UserRow.id != user.id).count()
        if user.role == "org_admin" and others and _admin_count(db, user.org_id) <= 1:
            raise HTTPException(409, "Вы единственный администратор: сначала назначьте администратором другого участника")
        user.org_id, user.role = None, "member"
        db.commit()
    return user_out(db, user)


def _period(period: str) -> str:
    if period not in scoring.PERIODS:
        raise HTTPException(422, "Период: week, month или all")
    return period


def _sessions_by_user(db, user_ids: list[str], period: str, season_start: datetime | None = None) -> dict[str, list[SessionRow]]:
    """Сессии за период; для организации ещё и не раньше начала текущего сезона."""
    start = scoring.since(period)
    if season_start is not None:
        season_start = scoring.aware(season_start)
        start = season_start if start is None else max(start, season_start)
    out: dict[str, list[SessionRow]] = {uid: [] for uid in user_ids}
    if user_ids:
        for r in db.query(SessionRow).filter(SessionRow.user_id.in_(user_ids)):
            if scoring.in_period(r, start):
                out[r.user_id].append(r)
    return out


def _rank(people: list[UserRow], by_user: dict[str, list[SessionRow]]) -> list[tuple[UserRow, float, int]]:
    out = []
    for p in people:
        scores = [x for x in map(scoring.score_of, by_user[p.id]) if x is not None]
        rating = scoring.user_rating(scores)
        if rating is not None:
            out.append((p, rating, len(scores)))
    out.sort(key=lambda t: -t[1])
    return out


def current_season(db, org_id: str) -> SeasonRow:
    """Открытый сезон организации. У старой организации сезона нет: создаём «Сезон 1», в него идут все сессии."""
    with WRITE_LOCK:
        s = db.query(SeasonRow).filter_by(org_id=org_id, ended_at=None).order_by(SeasonRow.id.desc()).first()
        if s is None:
            s = SeasonRow(org_id=org_id, name="Сезон 1", started_at=None, awarded=False)
            db.add(s)
            db.commit()
        return s


def _iso(dt: datetime | None) -> str | None:
    return scoring.aware(dt).isoformat() if dt else None


def season_out(org: OrgRow, s: SeasonRow) -> dict:
    return {"id": s.id, "name": s.name, "started_at": _iso(s.started_at or org.created_at), "awarded": s.awarded}


def medal_rule(org: OrgRow) -> dict:
    return {"slots": org.medal_slots, "gold_share": org.gold_share, "silver_share": org.silver_share,
            "split": scoring.medal_split(org.medal_slots, org.gold_share, org.silver_share)}


def org_ranking(db, org: OrgRow, season: SeasonRow, period: str = "all") -> list[tuple[UserRow, float, int]]:
    """Участники организации с рейтингом за период внутри текущего сезона, по убыванию рейтинга."""
    people = db.query(UserRow).filter_by(org_id=org.id).order_by(UserRow.created_at).all()
    return _rank(people, _sessions_by_user(db, [p.id for p in people], period, season.started_at))


def medal_counts(db, user_ids: list[str]) -> dict[str, dict[str, int]]:
    out = {uid: dict.fromkeys(scoring.MEDALS, 0) for uid in user_ids}
    if user_ids:
        for m in db.query(MedalRow).filter(MedalRow.user_id.in_(user_ids)):
            out[m.user_id][m.medal] += 1
    return out


@router.get("/orgs/me/stats")
def org_stats(period: str = "month", user: UserRow = Depends(require_org_admin), db=Depends(get_db)):
    org = db.get(OrgRow, user.org_id)
    season = current_season(db, org.id)
    members = db.query(UserRow).filter_by(org_id=user.org_id).order_by(UserRow.created_at).all()
    by_user = _sessions_by_user(db, [m.id for m in members], _period(period), season.started_at)
    return {
        "org": org_out(org, user), "period": period, "season": season_out(org, season),
        "members": [{"id": m.id, "login": m.login, "display_name": m.display_name, "role": m.role, **scoring.member_stats(by_user[m.id])} for m in members],
    }


@router.get("/leaderboard")
def leaderboard(scope: str = "org", period: str = "month", user: UserRow | None = Depends(current_user), db=Depends(get_db)):
    """Организация: рейтинг внутри текущего сезона и медали, которые верхние места получили бы при закрытии сезона сейчас."""
    extra: dict = {}
    places: list[str | None] = []
    if scope == "org":
        if user is None or not user.org_id:
            raise HTTPException(403, "Лидерборд организации доступен её участникам")
        org = db.get(OrgRow, user.org_id)
        season = current_season(db, org.id)
        ranked = org_ranking(db, org, season, _period(period))
        orgs = {org.id: org.name}
        extra = {"season": season_out(org, season), "medal_rule": medal_rule(org)}
        places = scoring.place_medals(len(ranked), org.medal_slots, org.gold_share, org.silver_share)
    elif scope == "global":
        people = db.query(UserRow).filter_by(public_in_leaderboard=True).all()
        ranked = _rank(people, _sessions_by_user(db, [p.id for p in people], _period(period)))
        orgs = {o.id: o.name for o in db.query(OrgRow).filter(OrgRow.id.in_({p.org_id for p, _, _ in ranked if p.org_id}))}
    else:
        raise HTTPException(422, "Лидерборд: org или global")
    counts = medal_counts(db, [p.id for p, _, _ in ranked])
    rows = [{"display_name": p.display_name, "org_name": orgs.get(p.org_id), "rating": rating, "sessions": n, "me": user is not None and p.id == user.id,
             "medals": counts[p.id], "medal": places[i] if places else None}
            for i, (p, rating, n) in enumerate(ranked)]
    return {"scope": scope, "period": period, "top_n": scoring.TOP_N, "rows": rows, **extra}


def season_state(db, org: OrgRow) -> dict:
    season = current_season(db, org.id)
    history = []
    for s in db.query(SeasonRow).filter_by(org_id=org.id).order_by(SeasonRow.id.desc()):
        if s.ended_at is None and not s.awarded:
            continue
        given = dict.fromkeys(scoring.MEDALS, 0)
        for (medal,) in db.query(MedalRow.medal).filter_by(season_id=s.id):
            given[medal] += 1
        history.append({**season_out(org, s), "ended_at": _iso(s.ended_at), "medals": given})
    return {"season": season_out(org, season), "medal_rule": medal_rule(org), "history": history}


@router.get("/orgs/me/season")
def get_season(user: UserRow = Depends(require_org_admin), db=Depends(get_db)):
    return season_state(db, db.get(OrgRow, user.org_id))


@router.put("/orgs/me/medals")
def set_medals(payload: MedalsIn, user: UserRow = Depends(require_org_admin), db=Depends(get_db)):
    if payload.gold_share + payload.silver_share > 1 + 1e-9:
        raise HTTPException(422, "Доли золота и серебра в сумме не больше 100%")
    with WRITE_LOCK:
        org = db.get(OrgRow, user.org_id)
        org.medal_slots, org.gold_share, org.silver_share = payload.medal_slots, payload.gold_share, payload.silver_share
        db.commit()
    return season_state(db, org)


@router.post("/orgs/me/season/close")
def close_season(payload: SeasonCloseIn, user: UserRow = Depends(require_org_admin), db=Depends(get_db)):
    """Выдать медали по рейтингу сезона и/или начать новый сезон. Медали за один сезон выдаются один раз, старые сессии не удаляются."""
    if not payload.award and not payload.reset:
        raise HTTPException(422, "Выберите хотя бы одно: выдать медали или начать новый сезон")
    with WRITE_LOCK:
        org = db.get(OrgRow, user.org_id)
        db.refresh(org)
        season = current_season(db, org.id)
        db.refresh(season)
        awarded = []
        now = datetime.now(timezone.utc)
        if payload.award:
            if season.awarded:
                raise HTTPException(409, f"Медали за «{season.name}» уже выданы")
            if org.medal_slots <= 0:
                raise HTTPException(409, "Медали выключены: задайте число мест")
            ranked = org_ranking(db, org, season)
            if not ranked:
                raise HTTPException(409, "Некого награждать: в сезоне нет сессий с оценкой")
            places = scoring.place_medals(len(ranked), org.medal_slots, org.gold_share, org.silver_share)
            for i, ((p, rating, _), medal) in enumerate(zip(ranked, places)):
                if medal is None:
                    break
                db.add(MedalRow(user_id=p.id, org_id=org.id, org_name=org.name, season_id=season.id, season_name=season.name,
                                medal=medal, rank=i + 1, rating=rating, awarded_at=now))
                awarded.append({"display_name": p.display_name, "medal": medal, "rank": i + 1, "rating": rating})
            season.awarded = True
        if payload.reset:
            season.ended_at = now
            number = db.query(SeasonRow).filter_by(org_id=org.id).count() + 1
            db.add(SeasonRow(org_id=org.id, name=payload.next_name.strip() or f"Сезон {number}", started_at=now, awarded=False))
        db.commit()
        return {"awarded": awarded, **season_state(db, org)}


@router.get("/profile/medals")
def my_medals(user: UserRow = Depends(require_user), db=Depends(get_db)):
    rows = db.query(MedalRow).filter_by(user_id=user.id).order_by(MedalRow.awarded_at.desc(), MedalRow.id.desc()).all()
    return [{"medal": m.medal, "rank": m.rank, "rating": m.rating, "season_name": m.season_name, "org_name": m.org_name,
             "awarded_at": _iso(m.awarded_at)} for m in rows]
