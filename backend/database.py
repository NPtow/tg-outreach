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
    from backend.models import Account, Conversation, Message, Settings, Campaign, CampaignTarget, PromptTemplate, AgentPipeline, AgentPipelineVersion, AgentRuntimeConfigRegistry, DoNotContact, Contact, ContactBatch, RuntimeEvent, ProxyPool, Integration, ScheduledMeeting, AgentRun, ScenarioCard, Project, ProjectAccount, ProjectProxy  # noqa
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
        ("accounts", "agent_pipeline_id INTEGER"),
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
        ("accounts", "session_source TEXT"),
        ("accounts", "proxy_last_rtt_ms INTEGER"),
        # campaigns
        ("campaigns", "project_id INTEGER"),
        ("campaigns", "account_ids TEXT"),
        ("campaigns", "send_hour_from INTEGER DEFAULT 9"),
        ("campaigns", "send_hour_to INTEGER DEFAULT 21"),
        ("campaigns", "prompt_template_id INTEGER"),
        ("campaigns", "agent_pipeline_id INTEGER"),
        ("campaigns", "stop_on_reply INTEGER DEFAULT 0"),
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
        ("conversations", "project_id INTEGER"),
        ("conversations", "source_campaign_id INTEGER"),
        ("conversations", "unread_count INTEGER DEFAULT 0"),
        ("conversations", "is_hot INTEGER DEFAULT 0"),
        # contacts
        ("contact_batches", "project_id INTEGER"),
        ("contacts", "project_id INTEGER"),
        ("contacts", "batch_id INTEGER"),
        # prompts, pipelines, scenario/eval traces
        ("prompt_templates", "project_id INTEGER"),
        ("agent_pipelines", "project_id INTEGER"),
        ("agent_runs", "project_id INTEGER"),
        ("scenario_cards", "project_id INTEGER"),
        # campaigns
        ("campaigns", "send_window_enabled INTEGER DEFAULT 0"),
        # settings
        ("settings", "provider TEXT DEFAULT 'openai'"),
        ("settings", "anthropic_key TEXT DEFAULT ''"),
        ("settings", "base_url TEXT DEFAULT ''"),
        ("settings", "google_client_id TEXT DEFAULT ''"),
        ("settings", "google_client_secret TEXT DEFAULT ''"),
        ("settings", "google_redirect_uri TEXT DEFAULT ''"),
        ("settings", "google_oauth_state_secret TEXT DEFAULT ''"),
        ("settings", "google_calendar_email TEXT DEFAULT ''"),
        ("settings", "zoom_account_id TEXT DEFAULT ''"),
        ("settings", "zoom_client_id TEXT DEFAULT ''"),
        ("settings", "zoom_client_secret TEXT DEFAULT ''"),
        ("settings", "zoom_host_email TEXT DEFAULT ''"),
        # device fingerprint fields on accounts
        ("accounts", "device_model TEXT"),
        ("accounts", "system_version TEXT"),
        ("accounts", "app_version TEXT"),
        ("accounts", "lang_code TEXT"),
        # proxy pool health
        ("proxy_pool", "proxy_state TEXT DEFAULT 'unknown'"),
        ("proxy_pool", "last_error_message TEXT"),
        ("proxy_pool", "last_proxy_check_at TIMESTAMP"),
        ("proxy_pool", "proxy_last_rtt_ms INTEGER"),
        # Dify knowledge sync for scenario cards
        ("scenario_cards", "dify_document_id TEXT"),
        ("scenario_cards", "dify_sync_status TEXT"),
        ("scenario_cards", "dify_sync_error TEXT"),
        ("scenario_cards", "dify_synced_at TIMESTAMP"),
        # meeting links
        ("scheduled_meetings", "project_id INTEGER"),
        ("scheduled_meetings", "calendar_add_url TEXT"),
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
            ("settings", "google_client_id"),
            ("settings", "google_client_secret"),
            ("settings", "google_redirect_uri"),
            ("settings", "google_oauth_state_secret"),
            ("settings", "google_calendar_email"),
            ("settings", "zoom_account_id"),
            ("settings", "zoom_client_id"),
            ("settings", "zoom_client_secret"),
            ("settings", "zoom_host_email"),
        ]
        with engine.connect() as conn:
            for table, col in text_cols:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE TEXT"))
                    conn.commit()
                except Exception:
                    conn.rollback()

    from backend.projects import assign_existing_rows_to_default_project

    db = SessionLocal()
    try:
        assign_existing_rows_to_default_project(db)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
