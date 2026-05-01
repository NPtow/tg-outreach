from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base


class ProxyPool(Base):
    """Shared proxy pool. One proxy should be assigned to one account max."""
    __tablename__ = "proxy_pool"

    id = Column(Integer, primary_key=True)
    label = Column(String(100), nullable=True)        # optional name
    host = Column(String(100), nullable=False)
    port = Column(Integer, nullable=False)
    proxy_type = Column(String(10), default="SOCKS5")
    username = Column(String(100), nullable=True)
    password = Column(Text, nullable=True)
    proxy_state = Column(String(30), default="unknown")
    last_error_message = Column(Text, nullable=True)
    last_proxy_check_at = Column(DateTime, nullable=True)
    proxy_last_rtt_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Integration(Base):
    """OAuth/API credentials for external services such as Google Calendar."""
    __tablename__ = "integrations"

    id = Column(Integer, primary_key=True)
    provider = Column(String(50), unique=True, nullable=False)
    account_email = Column(String(200), nullable=True)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_type = Column(String(50), nullable=True)
    scope = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Project(Base):
    """Logical workspace. Campaign content is scoped; accounts/proxies remain reusable."""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(30), default="active")
    default_timezone = Column(String(50), default="Europe/Moscow")
    default_calendar_email = Column(String(200), nullable=True)
    dify_dataset_id = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    accounts = relationship("ProjectAccount", back_populates="project")
    proxies = relationship("ProjectProxy", back_populates="project")


class ProjectAccount(Base):
    """Reusable account linked into a project without copying credentials."""
    __tablename__ = "project_accounts"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    role = Column(String(50), default="outreach")
    is_default = Column(Boolean, default=False)
    daily_limit_override = Column(Integer, nullable=True)
    auto_reply_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="accounts")
    account = relationship("Account")


class ProjectProxy(Base):
    """Reusable proxy linked into a project without owning the proxy globally."""
    __tablename__ = "project_proxies"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    proxy_id = Column(Integer, ForeignKey("proxy_pool.id"), nullable=False, index=True)
    role = Column(String(50), default="default")
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="proxies")
    proxy = relationship("ProxyPool")


class PromptTemplate(Base):
    """Reusable GPT prompt presets. Assigned per-account or per-campaign."""
    __tablename__ = "prompt_templates"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(300), nullable=True)
    system_prompt = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentPipeline(Base):
    """Reusable auto-reply pipeline. n8n is the first external runner type."""
    __tablename__ = "agent_pipelines"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    name = Column(String(120), nullable=False)
    description = Column(String(500), nullable=True)
    type = Column(String(40), nullable=False, default="n8n_webhook")
    status = Column(String(30), nullable=False, default="draft")  # draft | active | archived
    config_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    versions = relationship("AgentPipelineVersion", back_populates="pipeline")


class AgentPipelineVersion(Base):
    __tablename__ = "agent_pipeline_versions"

    id = Column(Integer, primary_key=True)
    pipeline_id = Column(Integer, ForeignKey("agent_pipelines.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    config_json = Column(Text, nullable=False, default="{}")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(100), nullable=True)

    pipeline = relationship("AgentPipeline", back_populates="versions")


class DoNotContact(Base):
    """Global blacklist. Contacts here are never messaged."""
    __tablename__ = "do_not_contact"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), nullable=True, index=True)
    tg_user_id = Column(String(50), nullable=True, index=True)
    reason = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), unique=True, nullable=False)
    app_id = Column(String(50), nullable=False)
    app_hash = Column(Text, nullable=False)
    session_file = Column(String(200))
    session_string = Column(Text, nullable=True)
    is_active = Column(Boolean, default=False)
    auto_reply = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    proxy_host = Column(String(100), nullable=True)
    proxy_port = Column(Integer, nullable=True)
    proxy_type = Column(String(10), nullable=True)
    proxy_user = Column(String(100), nullable=True)
    proxy_pass = Column(Text, nullable=True)
    needs_reauth = Column(Boolean, default=False)  # True when Telegram invalidated the session
    tdata_blob = Column(Text, nullable=True)        # base64-encoded tdata .zip — master credential for auto-recovery
    connection_state = Column(String(30), default="offline")
    proxy_state = Column(String(30), default="unknown")
    session_state = Column(String(30), default="missing")
    eligibility_state = Column(String(30), default="blocked_runtime")
    last_error_code = Column(String(50), nullable=True)
    last_error_message = Column(Text, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    last_proxy_check_at = Column(DateTime, nullable=True)
    last_connect_at = Column(DateTime, nullable=True)
    last_seen_online_at = Column(DateTime, nullable=True)
    session_source = Column(String(30), nullable=True)
    proxy_last_rtt_ms = Column(Integer, nullable=True)
    # Custom prompt for this account (overrides campaign and global prompts)
    prompt_template_id = Column(Integer, ForeignKey("prompt_templates.id"), nullable=True)
    agent_pipeline_id = Column(Integer, ForeignKey("agent_pipelines.id"), nullable=True)
    # Device fingerprint — generated once, immutable. Makes client look like real Telegram Desktop.
    device_model = Column(String(100), nullable=True)
    system_version = Column(String(100), nullable=True)
    app_version = Column(String(50), nullable=True)
    lang_code = Column(String(10), nullable=True)

    conversations = relationship("Conversation", back_populates="account")
    prompt_template = relationship("PromptTemplate", foreign_keys=[prompt_template_id])
    agent_pipeline = relationship("AgentPipeline", foreign_keys=[agent_pipeline_id])


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    tg_user_id = Column(String(50), nullable=False)
    tg_username = Column(String(100))
    tg_first_name = Column(String(100))
    tg_last_name = Column(String(100))
    status = Column(String(20), default="active")  # active | paused | done
    last_message = Column(Text)
    last_message_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Outreach tracking
    source_campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    unread_count = Column(Integer, default=0)
    is_hot = Column(Boolean, default=False)  # flagged by hot_keywords

    account = relationship("Account", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at")
    source_campaign = relationship("Campaign", foreign_keys=[source_campaign_id])


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(10), nullable=False)  # user | assistant
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")


class ScheduledMeeting(Base):
    """Calendar/Zoom meeting booked for a Telegram conversation."""
    __tablename__ = "scheduled_meetings"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    status = Column(String(30), default="scheduled")
    scheduled_start = Column(DateTime, nullable=False)
    scheduled_end = Column(DateTime, nullable=False)
    timezone = Column(String(50), default="Europe/Moscow")
    calendar_event_id = Column(String(200), nullable=True)
    calendar_html_link = Column(Text, nullable=True)
    calendar_add_url = Column(Text, nullable=True)
    zoom_meeting_id = Column(String(100), nullable=True)
    zoom_join_url = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class AgentRun(Base):
    """Inspectable trace for agent decisions, sandbox replays, and evals."""
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True, index=True)
    run_type = Column(String(50), nullable=False)
    model = Column(String(100), nullable=True)
    input_json = Column(Text, nullable=False)
    output_json = Column(Text, nullable=True)
    status = Column(String(30), default="succeeded")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class ScenarioCard(Base):
    """Reusable conversation scenario mined from real chats or created manually."""
    __tablename__ = "scenario_cards"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    intent = Column(String(100), nullable=False)
    trigger_summary = Column(Text, nullable=False)
    recommended_reply = Column(Text, nullable=False)
    avoid_reply = Column(Text, nullable=True)
    tags = Column(String(300), nullable=True)
    status = Column(String(30), default="draft")
    source_conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    dify_document_id = Column(String(100), nullable=True)
    dify_sync_status = Column(String(30), nullable=True)
    dify_sync_error = Column(Text, nullable=True)
    dify_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ContactBatch(Base):
    """Group of contacts imported together (one CSV upload = one batch)."""
    __tablename__ = "contact_batches"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)  # filename or custom label
    created_at = Column(DateTime, default=datetime.utcnow)

    contacts = relationship("Contact", back_populates="batch")


class Contact(Base):
    """Reusable contact library. Import once, use in multiple campaigns."""
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    username = Column(String(100), nullable=False, index=True)
    display_name = Column(String(100), nullable=True)   # {first_name}
    company = Column(String(200), nullable=True)        # {company}
    role = Column(String(200), nullable=True)           # {role}
    custom_note = Column(Text, nullable=True)           # {note}
    tags = Column(String(300), nullable=True)           # comma-separated tags
    created_at = Column(DateTime, default=datetime.utcnow)
    batch_id = Column(Integer, ForeignKey("contact_batches.id"), nullable=True)

    batch = relationship("ContactBatch", back_populates="contacts")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    account_ids = Column(Text, nullable=True)  # JSON list e.g. "[1,2,3]"; if set, overrides account_id
    messages = Column(Text, nullable=False)  # JSON list of variants
    delay_min = Column(Integer, default=30)
    delay_max = Column(Integer, default=90)
    daily_limit = Column(Integer, default=20)
    send_hour_from = Column(Integer, default=9)
    send_hour_to = Column(Integer, default=21)
    send_window_enabled = Column(Boolean, default=False)
    status = Column(String(20), default="draft")  # draft|running|paused|done
    created_at = Column(DateTime, default=datetime.utcnow)
    # Campaign prompt for auto-replies when the account has no prompt
    prompt_template_id = Column(Integer, ForeignKey("prompt_templates.id"), nullable=True)
    agent_pipeline_id = Column(Integer, ForeignKey("agent_pipelines.id"), nullable=True)
    # Stop conditions
    stop_on_reply = Column(Boolean, default=False)   # pause auto-reply when person responds
    stop_keywords = Column(Text, nullable=True)      # comma-separated: "нет,отписка,стоп"
    hot_keywords = Column(Text, nullable=True)       # comma-separated: "интересно,расскажи"
    max_messages = Column(Integer, nullable=True)    # max GPT replies per conversation
    targets = relationship("CampaignTarget", back_populates="campaign")
    prompt_template = relationship("PromptTemplate", foreign_keys=[prompt_template_id])
    agent_pipeline = relationship("AgentPipeline", foreign_keys=[agent_pipeline_id])


class CampaignTarget(Base):
    __tablename__ = "campaign_targets"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    username = Column(String(100), nullable=False)
    display_name = Column(String(100), nullable=True)   # {first_name}
    company = Column(String(200), nullable=True)        # {company}
    role = Column(String(200), nullable=True)           # {role}
    custom_note = Column(Text, nullable=True)           # {note}
    status = Column(String(20), default="pending")      # pending|sent|failed|skipped
    sent_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)

    campaign = relationship("Campaign", back_populates="targets")


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, default=1)
    provider = Column(String(20), default="openai")    # openai|anthropic|ollama|lmstudio
    openai_key = Column(Text, default="")
    anthropic_key = Column(Text, default="")
    base_url = Column(String(300), default="")         # for ollama/lmstudio
    model = Column(String(50), default="gpt-4o-mini")
    system_prompt = Column(Text, default="Ты вежливый менеджер по продажам. Отвечай кратко и по делу.")
    auto_reply_enabled = Column(Boolean, default=True)
    context_messages = Column(Integer, default=10)
    google_client_id = Column(Text, default="")
    google_client_secret = Column(Text, default="")
    google_redirect_uri = Column(Text, default="")
    google_oauth_state_secret = Column(Text, default="")
    google_calendar_email = Column(Text, default="")
    zoom_account_id = Column(Text, default="")
    zoom_client_id = Column(Text, default="")
    zoom_client_secret = Column(Text, default="")
    zoom_host_email = Column(Text, default="")


class RuntimeEvent(Base):
    __tablename__ = "runtime_events"

    id = Column(Integer, primary_key=True)
    event_type = Column(String(50), nullable=False, default="runtime")
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
