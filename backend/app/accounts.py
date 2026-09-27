"""Аккаунты, организации, кабинет и лидерборд. Без входа тренажёр работает в гостевом режиме, как раньше."""
import hashlib
import hmac
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from . import scoring
from .db import AuthTokenRow, OrgRow, SessionRow, UserRow, get_db

router = APIRouter(prefix="/api")

PBKDF2_ROUNDS = 200_000


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


def _period(period: str) -> str:
    if period not in scoring.PERIODS:
        raise HTTPException(422, "Период: week, month или all")
    return period


def _sessions_by_user(db, user_ids: list[str], period: str) -> dict[str, list[SessionRow]]:
    start = scoring.since(period)
    out: dict[str, list[SessionRow]] = {uid: [] for uid in user_ids}
    if user_ids:
        for r in db.query(SessionRow).filter(SessionRow.user_id.in_(user_ids)):
            if scoring.in_period(r, start):
                out[r.user_id].append(r)
    return out


@router.get("/orgs/me/stats")
def org_stats(period: str = "month", user: UserRow = Depends(require_org_admin), db=Depends(get_db)):
    members = db.query(UserRow).filter_by(org_id=user.org_id).order_by(UserRow.created_at).all()
    by_user = _sessions_by_user(db, [m.id for m in members], _period(period))
    return {
        "org": org_out(db.get(OrgRow, user.org_id), user), "period": period,
        "members": [{"id": m.id, "login": m.login, "display_name": m.display_name, "role": m.role, **scoring.member_stats(by_user[m.id])} for m in members],
    }


@router.get("/leaderboard")
def leaderboard(scope: str = "org", period: str = "month", user: UserRow | None = Depends(current_user), db=Depends(get_db)):
    if scope == "org":
        if user is None or not user.org_id:
            raise HTTPException(403, "Лидерборд организации доступен её участникам")
        people = db.query(UserRow).filter_by(org_id=user.org_id).all()
    elif scope == "global":
        people = db.query(UserRow).filter_by(public_in_leaderboard=True).all()
    else:
        raise HTTPException(422, "Лидерборд: org или global")
    by_user = _sessions_by_user(db, [p.id for p in people], _period(period))
    orgs = {o.id: o.name for o in db.query(OrgRow).filter(OrgRow.id.in_({p.org_id for p in people if p.org_id}))}
    rows = []
    for p in people:
        scores = [s for s in map(scoring.score_of, by_user[p.id]) if s is not None]
        rating = scoring.user_rating(scores)
        if rating is not None:
            rows.append({"display_name": p.display_name, "org_name": orgs.get(p.org_id), "rating": rating, "sessions": len(scores), "me": user is not None and p.id == user.id})
    rows.sort(key=lambda r: -r["rating"])
    return {"scope": scope, "period": period, "top_n": scoring.TOP_N, "rows": rows}
