from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Text, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base


class PromptTemplate(Base):
    """Reusable GPT prompt presets. Assigned per-account or per-campaign."""
    __tablename__ = "prompt_templates"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(String(300), nullable=True)
    system_prompt = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


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
    eligibility_state = Column(String(30), default="blocked_auth")
    last_error_code = Column(String(50), nullable=True)
    last_error_message = Column(Text, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    last_proxy_check_at = Column(DateTime, nullable=True)
    last_connect_at = Column(DateTime, nullable=True)
    last_seen_online_at = Column(DateTime, nullable=True)
    quarantine_until = Column(DateTime, nullable=True)
    warmup_level = Column(Integer, default=0)
    session_source = Column(String(30), nullable=True)
    proxy_last_rtt_ms = Column(Integer, nullable=True)
    # Custom prompt for this account (overrides global Settings.system_prompt)
    prompt_template_id = Column(Integer, ForeignKey("prompt_templates.id"), nullable=True)
    # Device fingerprint — generated once, immutable. Makes client look like real Telegram Desktop.
    device_model = Column(String(100), nullable=True)
    system_version = Column(String(100), nullable=True)
    app_version = Column(String(50), nullable=True)
    lang_code = Column(String(10), nullable=True)

    conversations = relationship("Conversation", back_populates="account")
    prompt_template = relationship("PromptTemplate", foreign_keys=[prompt_template_id])


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
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


class ContactBatch(Base):
    """Group of contacts imported together (one CSV upload = one batch)."""
    __tablename__ = "contact_batches"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)  # filename or custom label
    created_at = Column(DateTime, default=datetime.utcnow)

    contacts = relationship("Contact", back_populates="batch")


class Contact(Base):
    """Reusable contact library. Import once, use in multiple campaigns."""
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True)
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
    # Prompt override for auto-replies on this campaign's conversations
    prompt_template_id = Column(Integer, ForeignKey("prompt_templates.id"), nullable=True)
    # Stop conditions
    stop_on_reply = Column(Boolean, default=True)   # pause auto-reply when person responds
    stop_keywords = Column(Text, nullable=True)      # comma-separated: "нет,отписка,стоп"
    hot_keywords = Column(Text, nullable=True)       # comma-separated: "интересно,расскажи"
    max_messages = Column(Integer, nullable=True)    # max GPT replies per conversation
    # Warming gate: 0 = disabled, >0 = account health_score must reach this before sending
    min_health_score = Column(Integer, default=0)

    targets = relationship("CampaignTarget", back_populates="campaign")
    prompt_template = relationship("PromptTemplate", foreign_keys=[prompt_template_id])


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


class WarmingProfile(Base):
    """Template defining per-phase action quotas and phase durations."""
    __tablename__ = "warming_profiles"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(String(300), nullable=True)
    phase_1_days = Column(Integer, default=3)   # days in phase 1 (mutual msgs only)
    phase_2_days = Column(Integer, default=7)   # days in phase 2 (subscribe + react)
    # phase 3 runs until maintenance or forever
    phase_1_config = Column(Text, nullable=False)  # JSON: {online_sessions, mutual_messages, searches, dialog_reads}
    phase_2_config = Column(Text, nullable=False)  # JSON: + subscriptions_per_day, reactions_per_day
    phase_3_config = Column(Text, nullable=False)  # JSON: full activity
    maintenance_config = Column(Text, nullable=False)  # JSON: minimal keep-alive actions
    permanent_maintenance = Column(Boolean, default=False)  # True → after phase 3 stay in maintenance forever
    created_at = Column(DateTime, default=datetime.utcnow)

    warmings = relationship("AccountWarming", back_populates="profile")


class AccountWarming(Base):
    """Active warming task for one account."""
    __tablename__ = "account_warmings"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, unique=True)
    profile_id = Column(Integer, ForeignKey("warming_profiles.id"), nullable=False)
    status = Column(String(20), default="warming")  # warming | maintenance | paused | completed
    phase = Column(Integer, default=1)              # 1 | 2 | 3
    campaign_label = Column(String(100), nullable=True)   # A/B group tag e.g. "7day", "14day"
    started_at = Column(DateTime, default=datetime.utcnow)
    phase_started_at = Column(DateTime, default=datetime.utcnow)
    last_action_at = Column(DateTime, nullable=True)
    health_score = Column(Integer, default=0)        # 0–100
    subscribed_channels = Column(Text, default="[]") # JSON list[str]
    peer_account_ids = Column(Text, default="[]")    # JSON list[int] — accounts to mutual-msg with
    actions_today = Column(Integer, default=0)
    actions_today_date = Column(Date, nullable=True) # date of last reset
    total_actions = Column(Integer, default=0)
    ban_events = Column(Integer, default=0)          # flood/spam events counter

    profile = relationship("WarmingProfile", back_populates="warmings")
    actions = relationship("WarmingAction", back_populates="warming", order_by="WarmingAction.executed_at")


class WarmingAction(Base):
    """Log of every action taken during warming."""
    __tablename__ = "warming_actions"

    id = Column(Integer, primary_key=True)
    account_warming_id = Column(Integer, ForeignKey("account_warmings.id"), nullable=False)
    action_type = Column(String(30), nullable=False)  # online|offline|subscribe|react|msg_sent|msg_received|search|read_dialog
    target = Column(String(300), nullable=True)        # channel username, peer phone, search query
    result = Column(String(20), nullable=False)        # success|failed|flood_wait|skipped
    flood_wait_seconds = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)              # JSON extra info
    executed_at = Column(DateTime, default=datetime.utcnow)

    warming = relationship("AccountWarming", back_populates="actions")


class WarmingChannelPool(Base):
    """Pool of Telegram channels/groups used for warming subscriptions."""
    __tablename__ = "warming_channel_pool"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), nullable=False, unique=True)
    title = Column(String(200), nullable=True)
    niche = Column(String(50), nullable=True)     # tech|business|general|crypto|marketing|news|humor
    language = Column(String(10), default="ru")
    subscriber_count = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)
    added_at = Column(DateTime, default=datetime.utcnow)


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


class RuntimeEvent(Base):
    __tablename__ = "runtime_events"

    id = Column(Integer, primary_key=True)
    event_type = Column(String(50), nullable=False, default="runtime")
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
