from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), unique=True, nullable=False)
    app_id = Column(String(50), nullable=False)
    app_hash = Column(String(100), nullable=False)
    session_file = Column(String(200))
    session_string = Column(Text, nullable=True)  # Telethon StringSession for cloud
    is_active = Column(Boolean, default=False)
    auto_reply = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    proxy_host = Column(String(100), nullable=True)
    proxy_port = Column(Integer, nullable=True)
    proxy_type = Column(String(10), nullable=True)  # HTTP | SOCKS5
    proxy_user = Column(String(100), nullable=True)
    proxy_pass = Column(String(100), nullable=True)

    conversations = relationship("Conversation", back_populates="account")


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

    account = relationship("Account", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(10), nullable=False)  # user | assistant
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    messages = Column(Text, nullable=False)  # JSON list of variants
    delay_min = Column(Integer, default=30)
    delay_max = Column(Integer, default=90)
    daily_limit = Column(Integer, default=20)
    status = Column(String(20), default="draft")  # draft|running|paused|done
    created_at = Column(DateTime, default=datetime.utcnow)

    targets = relationship("CampaignTarget", back_populates="campaign")


class CampaignTarget(Base):
    __tablename__ = "campaign_targets"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    username = Column(String(100), nullable=False)
    status = Column(String(20), default="pending")  # pending|sent|failed
    sent_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)

    campaign = relationship("Campaign", back_populates="targets")


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, default=1)
    openai_key = Column(String(200), default="")
    model = Column(String(50), default="gpt-4o-mini")
    system_prompt = Column(Text, default="Ты вежливый менеджер по продажам. Отвечай кратко и по делу.")
    auto_reply_enabled = Column(Boolean, default=True)
    context_messages = Column(Integer, default=10)
