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
    from backend.models import Account, Conversation, Message, Settings, Campaign, CampaignTarget, PromptTemplate, DoNotContact  # noqa
    Base.metadata.create_all(bind=engine)

    if not DATABASE_URL.startswith("sqlite"):
        return  # PostgreSQL handles schema via create_all

    # SQLite: add new columns if missing (safe to re-run, errors are swallowed)
    new_cols = [
        # accounts
        ("accounts", "session_string TEXT"),
        ("accounts", "proxy_host TEXT"),
        ("accounts", "proxy_port INTEGER"),
        ("accounts", "proxy_type TEXT"),
        ("accounts", "proxy_user TEXT"),
        ("accounts", "proxy_pass TEXT"),
        ("accounts", "prompt_template_id INTEGER"),
        # campaigns
        ("campaigns", "send_hour_from INTEGER DEFAULT 9"),
        ("campaigns", "send_hour_to INTEGER DEFAULT 21"),
        ("campaigns", "prompt_template_id INTEGER"),
        ("campaigns", "stop_on_reply INTEGER DEFAULT 1"),
        ("campaigns", "stop_keywords TEXT"),
        ("campaigns", "hot_keywords TEXT"),
        ("campaigns", "max_messages INTEGER"),
        # campaign_targets
        ("campaign_targets", "display_name TEXT"),
        ("campaign_targets", "company TEXT"),
        ("campaign_targets", "role TEXT"),
        ("campaign_targets", "custom_note TEXT"),
        # conversations
        ("conversations", "source_campaign_id INTEGER"),
        ("conversations", "unread_count INTEGER DEFAULT 0"),
        ("conversations", "is_hot INTEGER DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for table, col_def in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
                conn.commit()
            except Exception:
                pass  # column already exists
