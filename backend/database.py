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
    from backend.models import Account, Conversation, Message, Settings, Campaign, CampaignTarget, PromptTemplate, DoNotContact, Contact, ContactBatch, RuntimeEvent, WarmingProfile, AccountWarming, WarmingAction, WarmingChannelPool  # noqa
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
        ("accounts", "connection_state TEXT DEFAULT 'offline'"),
        ("accounts", "proxy_state TEXT DEFAULT 'unknown'"),
        ("accounts", "session_state TEXT DEFAULT 'missing'"),
        ("accounts", "eligibility_state TEXT DEFAULT 'blocked_auth'"),
        ("accounts", "last_error_code TEXT"),
        ("accounts", "last_error_message TEXT"),
        ("accounts", "last_error_at TIMESTAMP"),
        ("accounts", "last_proxy_check_at TIMESTAMP"),
        ("accounts", "last_connect_at TIMESTAMP"),
        ("accounts", "last_seen_online_at TIMESTAMP"),
        ("accounts", "quarantine_until TIMESTAMP"),
        ("accounts", "warmup_level INTEGER DEFAULT 0"),
        ("accounts", "session_source TEXT"),
        ("accounts", "proxy_last_rtt_ms INTEGER"),
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
        ("campaign_targets", "account_id INTEGER"),
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
        # device fingerprint fields on accounts
        ("accounts", "device_model TEXT"),
        ("accounts", "system_version TEXT"),
        ("accounts", "app_version TEXT"),
        ("accounts", "lang_code TEXT"),
        # warming gate on campaigns
        ("campaigns", "min_health_score INTEGER DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for table, col_def in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
                conn.commit()
            except Exception:
                conn.rollback()  # PostgreSQL requires rollback after error before next statement

    # For PostgreSQL: convert legacy INTEGER boolean columns to proper BOOLEAN type.
    # Safe to re-run because we first inspect the current column type.
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
                    data_type = conn.execute(
                        text(
                            """
                            SELECT data_type
                            FROM information_schema.columns
                            WHERE table_name = :table AND column_name = :column
                            """
                        ),
                        {"table": table, "column": col},
                    ).scalar()
                    if data_type in {"integer", "smallint", "bigint"}:
                        conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {col} DROP DEFAULT"))
                        conn.execute(
                            text(
                                f"""
                                ALTER TABLE {table}
                                ALTER COLUMN {col} TYPE BOOLEAN
                                USING CASE
                                    WHEN {col} IS NULL THEN NULL
                                    WHEN {col} = 0 THEN FALSE
                                    ELSE TRUE
                                END
                                """
                            )
                        )
                        conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {col} SET DEFAULT FALSE"))
                        conn.commit()
                except Exception:
                    conn.rollback()

        text_cols = [
            ("accounts", "app_hash"),
            ("accounts", "proxy_pass"),
            ("settings", "openai_key"),
            ("settings", "anthropic_key"),
        ]
        with engine.connect() as conn:
            for table, col in text_cols:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE TEXT"))
                    conn.commit()
                except Exception:
                    conn.rollback()
