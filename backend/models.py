from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
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
    app_hash = Column(String(100), nullable=False)
    session_file = Column(String(200))
    session_string = Column(Text, nullable=True)
    is_active = Column(Boolean, default=False)
    auto_reply = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    proxy_host = Column(String(100), nullable=True)
    proxy_port = Column(Integer, nullable=True)
    proxy_type = Column(String(10), nullable=True)
    proxy_user = Column(String(100), nullable=True)
    proxy_pass = Column(String(100), nullable=True)
    needs_reauth = Column(Boolean, default=False)  # True when Telegram invalidated the session
    # Custom prompt for this account (overrides global Settings.system_prompt)
    prompt_template_id = Column(Integer, ForeignKey("prompt_templates.id"), nullable=True)

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

    targets = relationship("CampaignTarget", back_populates="campaign")
    prompt_template = relationship("PromptTemplate", foreign_keys=[prompt_template_id])


class CampaignTarget(Base):
    __tablename__ = "campaign_targets"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
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
    openai_key = Column(String(200), default="")
    anthropic_key = Column(String(200), default="")
    base_url = Column(String(300), default="")         # for ollama/lmstudio
    model = Column(String(50), default="gpt-4o-mini")
    system_prompt = Column(Text, default="Ты вежливый менеджер по продажам. Отвечай кратко и по делу.")
    auto_reply_enabled = Column(Boolean, default=True)
    context_messages = Column(Integer, default=10)
