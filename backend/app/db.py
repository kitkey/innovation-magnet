from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ScenarioRow(Base):
    __tablename__ = "scenarios"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    card: Mapped[dict] = mapped_column(JSON)
    org_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OrgRow(Base):
    __tablename__ = "orgs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    invite_code: Mapped[str] = mapped_column(String(16), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    login: Mapped[str] = mapped_column(String(32), unique=True)
    pw_hash: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(80))
    org_id: Mapped[str | None] = mapped_column(ForeignKey("orgs.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="member")
    public_in_leaderboard: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuthTokenRow(Base):
    __tablename__ = "auth_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id"))
    card: Mapped[dict] = mapped_column(JSON)
    state: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="active")
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agreed_value: Mapped[float | None] = mapped_column(nullable=True)
    turn: Mapped[int] = mapped_column(Integer, default=0)
    judge: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    turns: Mapped[list["TurnRow"]] = relationship(back_populates="session", order_by="TurnRow.id")


class TurnRow(Base):
    __tablename__ = "turns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    session: Mapped[SessionRow] = relationship(back_populates="turns")


ADDED_COLUMNS = {"sessions": {"user_id": "VARCHAR(32)"}, "scenarios": {"org_id": "VARCHAR(32)"}}


def init_db(bind=None) -> None:
    """Миграций нет: новые таблицы создаёт create_all, новые колонки в старых таблицах добавляем ALTER TABLE, если их нет."""
    bind = bind or engine
    Base.metadata.create_all(bind)
    insp = inspect(bind)
    with bind.begin() as conn:
        for table, cols in ADDED_COLUMNS.items():
            have = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
