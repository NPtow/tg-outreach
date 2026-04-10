import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

_raw_url = os.getenv("DATABASE_URL", "sqlite:///./tg_outreach.db")
# Railway gives postgres:// but SQLAlchemy needs postgresql://
DATABASE_URL = _raw_url.replace("postgres://", "postgresql://", 1) if _raw_url.startswith("postgres://") else _raw_url

_kwargs = {"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, **_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from backend.models import Account, Conversation, Message, Settings, Campaign, CampaignTarget  # noqa
    Base.metadata.create_all(bind=engine)

    if not DATABASE_URL.startswith("sqlite"):
        return  # PostgreSQL handles schema via create_all

    # SQLite: add new columns if missing
    new_cols = [
        ("accounts", "session_string TEXT"),
        ("accounts", "proxy_host TEXT"),
        ("accounts", "proxy_port INTEGER"),
        ("accounts", "proxy_type TEXT"),
        ("accounts", "proxy_user TEXT"),
        ("accounts", "proxy_pass TEXT"),
    ]
    with engine.connect() as conn:
        for table, col_def in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
                conn.commit()
            except Exception:
                pass  # column already exists
