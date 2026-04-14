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
    from backend.models import Account, Conversation, Message, Settings, Campaign, CampaignTarget, PromptTemplate, DoNotContact, Contact, ContactBatch  # noqa
    Base.metadata.create_all(bind=engine)

    # Add new columns to existing tables (safe to re-run — errors for existing columns are swallowed)
    # Works for both SQLite and PostgreSQL.
    new_cols = [
        # accounts
        ("accounts", "session_string TEXT"),
        ("accounts", "needs_reauth INTEGER DEFAULT 0"),
        ("accounts", "tdata_blob TEXT"),
        ("accounts", "proxy_host TEXT"),
        ("accounts", "proxy_port INTEGER"),
        ("accounts", "proxy_type TEXT"),
        ("accounts", "proxy_user TEXT"),
        ("accounts", "proxy_pass TEXT"),
        ("accounts", "prompt_template_id INTEGER"),
        # campaigns
        ("campaigns", "account_ids TEXT"),
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
        # contacts
        ("contacts", "batch_id INTEGER"),
        # campaigns
        ("campaigns", "send_window_enabled INTEGER DEFAULT 0"),
        # settings
        ("settings", "provider TEXT DEFAULT 'openai'"),
        ("settings", "anthropic_key TEXT DEFAULT ''"),
        ("settings", "base_url TEXT DEFAULT ''"),
    ]
    with engine.connect() as conn:
        for table, col_def in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
                conn.commit()
            except Exception:
                conn.rollback()  # PostgreSQL requires rollback after error before next statement

    # For PostgreSQL: convert INTEGER boolean columns to proper BOOLEAN type.
    # These were originally added via ADD COLUMN ... INTEGER, causing comparison errors.
    # Safe to re-run — ALTER on already-BOOLEAN column will fail silently.
    if not DATABASE_URL.startswith("sqlite"):
        bool_cols = [
            ("conversations", "is_hot"),
            ("campaigns", "send_window_enabled"),
            ("campaigns", "stop_on_reply"),
            ("accounts", "auto_reply"),
            ("accounts", "needs_reauth"),
            ("settings", "auto_reply_enabled"),
        ]
        with engine.connect() as conn:
            for table, col in bool_cols:
                try:
                    conn.execute(text(
                        f"ALTER TABLE {table} ALTER COLUMN {col} TYPE BOOLEAN USING {col}::boolean"
                    ))
                    conn.commit()
                except Exception:
                    conn.rollback()
