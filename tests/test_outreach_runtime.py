import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import get_db, Base
from backend.agent_runtime import record_agent_run
from backend.agent_policy import validate_agent_decision
from backend.evals import run_local_eval_cases
from backend.meeting_scheduler import (
    BOOK_MEETING_MARKER,
    append_meeting_booking_instructions,
    book_meeting_from_agent_payload,
    book_meeting_for_conversation,
    build_calendar_add_url,
    build_meeting_reply_text,
    extract_meeting_booking_intent,
    get_existing_scheduled_meeting,
)
from backend.models import Account, AgentPipeline, AgentRun, AgentRuntimeConfigRegistry, Campaign, CampaignTarget, Conversation, Message, Project, ProjectAccount, ProjectProxy, PromptTemplate, ProxyPool, ScenarioCard, ScheduledMeeting, Settings
from backend.n8n_agent import N8nAgentCallResult, N8nAgentDecision, N8nAgentRequest, call_n8n_agent
from backend.pipeline_runner import run_pipeline_for_auto_reply
from backend.routers import accounts as accounts_router
from backend.routers import bookings as bookings_router
from backend.routers import agent_pipelines as agent_pipelines_router
from backend.routers import agents as agents_router
from backend.routers import campaigns as campaigns_router
from backend.routers import conversations as conversations_router
from backend.routers import proxy_pool as proxy_pool_router
from backend.routers import projects as projects_router
from backend.routers import sandbox as sandbox_router
from backend.routers import scenarios as scenarios_router
from backend.dify_knowledge import build_scenario_dify_document, sync_scenarios_to_dify
from backend.scenarios import (
    active_scenarios_for_text,
    analyze_conversations_for_suggestions,
    group_scenarios,
    list_scenarios,
    mark_founder_research_pack_legacy,
    mine_scenario_from_conversation,
    seed_founder_research_pack,
    serialize_scenario,
)
from backend.sandbox import replay_conversation_n8n_sandbox, replay_conversation_sandbox
from backend.security import decrypt_value
from backend.google_calendar import build_calendar_event_description, build_google_auth_url, find_first_free_slot
from backend.zoom_meetings import build_zoom_meeting_payload, zoom_host_user
import backend.telegram_client as tg


class FakeCreatedTask:
    def __init__(self, *, done_value=False):
        self._done_value = done_value
        self.cancelled = False
        self.callbacks = []

    def done(self):
        return self._done_value

    def cancel(self):
        self.cancelled = True

    def add_done_callback(self, callback):
        self.callbacks.append(callback)


class FakeEvent:
    def __init__(self, *, sender, text, is_out=False, message_id=None, chat=None):
        self._sender = sender
        self.is_out = is_out
        self._chat = chat
        self.message = SimpleNamespace(text=text, id=message_id, out=is_out)

    async def get_sender(self):
        return self._sender

    async def get_chat(self):
        return self._chat


class FakeTypingAction:
    def __init__(self):
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *args):
        self.exited = True
        return None


class FakePresenceClient:
    def __init__(self):
        self.read_entities = []
        self.typing_actions = []

    async def send_read_acknowledge(self, entity):
        self.read_entities.append(entity)

    def action(self, entity, action_type):
        action = FakeTypingAction()
        self.typing_actions.append((entity, action_type, action))
        return action


class FakeManualSendClient:
    def __init__(self):
        self.sent = []
        self.resolved = []

    async def get_entity(self, username):
        self.resolved.append(username)
        return SimpleNamespace(id=6289865060, username=username)

    async def send_message(self, entity, text, **kwargs):
        self.sent.append((entity, text, kwargs))
        if isinstance(entity, int):
            raise ValueError("Could not find the input entity")
        return SimpleNamespace(id=1)




class FakeTaskState:
    def __init__(self, done_value):
        self._done_value = done_value

    def done(self):
        return self._done_value


class OutreachRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "test.db"
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        tg._clients.clear()
        tg._tasks.clear()
        if hasattr(tg, "_pending_auto_reply_tasks"):
            for task in tg._pending_auto_reply_tasks.values():
                if not task.done():
                    task.cancel()
            tg._pending_auto_reply_tasks.clear()
        self.engine.dispose()
        self.tempdir.cleanup()

    def _db(self):
        return self.Session()

    def test_telegram_client_inputs_are_normalized_before_telethon(self):
        account = Account(
            id=20,
            name="Ana",
            phone=573122997098,
            app_id=2040,
            app_hash=123456,
            auto_reply=True,
        )
        account.device_model = 777
        account.system_version = 888
        account.app_version = 999
        account.lang_code = 111
        account.proxy_host = 12345
        account.proxy_port = "8184"
        account.proxy_type = "SOCKS5"
        account.proxy_user = 222
        account.proxy_pass = 333

        proxy = tg._build_proxy(account)
        self.assertEqual(proxy["addr"], "12345")
        self.assertEqual(proxy["port"], 8184)
        self.assertEqual(proxy["username"], "222")
        self.assertEqual(proxy["password"], "333")

        with patch("backend.telegram_client.TelegramClient") as telegram_client:
            tg._make_fresh_client(account)

        args, kwargs = telegram_client.call_args
        self.assertEqual(args[1], 2040)
        self.assertEqual(args[2], tg.DEFAULT_API_HASH)
        self.assertEqual(kwargs["proxy"]["addr"], "12345")
        self.assertEqual(kwargs["device_model"], "777")
        self.assertEqual(kwargs["system_version"], "888")
        self.assertEqual(kwargs["app_version"], "999")
        self.assertEqual(kwargs["lang_code"], "111")

    def test_record_outreach_message_dedupes_by_telegram_message_id(self):
        with self._db() as db:
            conv = tg._ensure_outreach_conversation(
                db,
                account_id=1,
                tg_user_id="1001",
                tg_username="lead",
            )
            first = tg._record_outreach_message(
                db,
                conversation=conv,
                role="assistant",
                text="Первое",
                tg_message_id=555,
                is_outgoing=True,
            )
            second = tg._record_outreach_message(
                db,
                conversation=conv,
                role="assistant",
                text="Дубль",
                tg_message_id=555,
                is_outgoing=True,
            )
            db.commit()

            messages = db.query(Message).filter(Message.conversation_id == conv.id).all()
            self.assertEqual(first.id, second.id)
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].text, "Первое")

    def test_outgoing_message_is_assistant_and_not_unread(self):
        with self._db() as db:
            conv = tg._ensure_outreach_conversation(
                db,
                account_id=1,
                tg_user_id="1002",
                tg_username="lead2",
            )
            conv.unread_count = 3
            msg = tg._record_outreach_message(
                db,
                conversation=conv,
                role="assistant",
                text="Ответ из Nicegram",
                tg_message_id=777,
                is_outgoing=True,
            )
            conv.unread_count = 0
            db.commit()

            self.assertEqual(msg.role, "assistant")
            self.assertTrue(msg.is_outgoing)
            self.assertEqual(conv.unread_count, 0)

    def test_outgoing_telegram_event_is_persisted_without_auto_reply(self):
        with self._db() as db:
            db.add(Conversation(id=101, account_id=7, tg_user_id="1005", tg_username="lead5", unread_count=2))
            db.commit()

        event = FakeEvent(
            sender=SimpleNamespace(id=7),
            text="Ответ из Nicegram",
            is_out=True,
            message_id=900,
            chat=SimpleNamespace(id=1005, username="lead5", first_name="Lead", last_name=""),
        )
        with patch("backend.telegram_client.SessionLocal", self.Session):
            with patch("backend.telegram_client._schedule_auto_reply") as schedule:
                asyncio.run(tg._handle_message(7, event))

        schedule.assert_not_called()
        with self._db() as db:
            conv = db.query(Conversation).filter(Conversation.id == 101).first()
            messages = db.query(Message).filter(Message.conversation_id == 101).all()

        self.assertEqual(conv.unread_count, 0)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, "assistant")
        self.assertEqual(messages[0].text, "Ответ из Nicegram")
        self.assertEqual(messages[0].tg_message_id, 900)

    def test_should_refresh_profile_when_missing_or_old(self):
        conv = Conversation(account_id=1, tg_user_id="1003")
        self.assertTrue(tg._should_refresh_profile(conv))
        conv.tg_profile_updated_at = datetime.utcnow()
        self.assertFalse(tg._should_refresh_profile(conv))
        conv.tg_profile_updated_at = datetime.utcnow() - timedelta(days=8)
        self.assertTrue(tg._should_refresh_profile(conv))

    def test_apply_outbox_read_state_marks_assistant_messages_read(self):
        with self._db() as db:
            conv = tg._ensure_outreach_conversation(db, account_id=1, tg_user_id="1004")
            tg._record_outreach_message(
                db,
                conversation=conv,
                role="assistant",
                text="one",
                tg_message_id=10,
                is_outgoing=True,
            )
            tg._record_outreach_message(
                db,
                conversation=conv,
                role="assistant",
                text="two",
                tg_message_id=11,
                is_outgoing=True,
            )
            changed = tg._apply_read_state(db, conv, max_id=10, message_ids=[], inbox=False)
            db.commit()

            messages = db.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.tg_message_id).all()
            self.assertEqual(changed, 1)
            self.assertIsNotNone(messages[0].telegram_read_at)
            self.assertIsNone(messages[1].telegram_read_at)

    def test_apply_inbox_read_state_marks_user_messages_read_by_us(self):
        with self._db() as db:
            conv = tg._ensure_outreach_conversation(db, account_id=1, tg_user_id="1006")
            tg._record_outreach_message(
                db,
                conversation=conv,
                role="user",
                text="one",
                tg_message_id=20,
                is_outgoing=False,
            )
            changed = tg._apply_read_state(db, conv, max_id=20, message_ids=[], inbox=True)
            db.commit()

            message = db.query(Message).filter(Message.conversation_id == conv.id).first()
            self.assertEqual(changed, 1)
            self.assertIsNotNone(message.telegram_read_by_us_at)

    def test_message_read_state_serializer(self):
        outgoing = Message(role="assistant", text="x")
        self.assertEqual(conversations_router._message_read_state(outgoing), "sent")
        outgoing.telegram_read_at = datetime.utcnow()
        self.assertEqual(conversations_router._message_read_state(outgoing), "read")

        incoming = Message(role="user", text="x")
        self.assertEqual(conversations_router._message_read_state(incoming), "unread")
        incoming.telegram_read_by_us_at = datetime.utcnow()
        self.assertEqual(conversations_router._message_read_state(incoming), "read_by_us")

    def test_avatar_data_url_serializer(self):
        conv = Conversation(account_id=1, tg_user_id="1007", tg_photo_base64="abc", tg_photo_mime="image/jpeg")
        self.assertEqual(conversations_router._avatar_data_url(conv), "data:image/jpeg;base64,abc")

    def test_resolve_prompt_prefers_account_prompt_over_campaign_prompt(self):
        settings = Settings(system_prompt="global prompt")
        account_prompt = PromptTemplate(id=1, name="Account prompt", system_prompt="account prompt")
        campaign_prompt = PromptTemplate(id=2, name="Campaign prompt", system_prompt="campaign prompt")
        account = Account(
            name="Ana",
            phone="+573122997010",
            app_id="2040",
            app_hash="hash",
            prompt_template_id=account_prompt.id,
            prompt_template=account_prompt,
        )
        campaign = Campaign(
            name="Campaign",
            account_id=1,
            messages="[]",
            prompt_template_id=campaign_prompt.id,
            prompt_template=campaign_prompt,
        )

        self.assertEqual(tg._resolve_prompt(settings, account, campaign), "account prompt")

    def test_personalization_keeps_first_name_when_present(self):
        target = CampaignTarget(
            username="lead_user",
            display_name="Иван",
            company="Acme",
            role="CTO",
            custom_note="ProductConf",
        )

        text = tg._apply_personalization(
            "Привет, {first_name}! Ты из {company}, верно?",
            target,
        )

        self.assertEqual(text, "Привет, Иван! Ты из Acme, верно?")

    def test_personalization_uses_sending_account_as_agent_name(self):
        target = CampaignTarget(username="lead_user", display_name="Анна")
        account = Account(name="Никита", phone="+573122997011", app_id="2040", app_hash="hash")

        text = tg._apply_personalization(
            "Здравствуйте, {first_name}! Меня зовут {agent_name}.",
            target,
            account,
        )

        self.assertEqual(text, "Здравствуйте, Анна! Меня зовут Никита.")

    def test_personalization_preserves_message_paragraphs(self):
        target = CampaignTarget(username="lead_user", display_name="Анна")
        account = Account(name="Никита", phone="+573122997012", app_id="2040", app_hash="hash")

        text = tg._apply_personalization(
            "Здравствуйте, {first_name}!\n\nМеня зовут {agent_name}.",
            target,
            account,
        )

        self.assertEqual(text, "Здравствуйте, Анна!\n\nМеня зовут Никита.")

    def test_personalization_removes_dangling_first_name_punctuation_when_missing(self):
        target = CampaignTarget(username="lead_user", display_name=None)

        text = tg._apply_personalization(
            "Привет, {first_name}! Хотел обсудить вопрос.",
            target,
        )

        self.assertEqual(text, "Привет! Хотел обсудить вопрос.")

    def test_personalization_removes_english_dangling_first_name_punctuation_when_missing(self):
        target = CampaignTarget(username="lead_user", display_name=None)

        text = tg._apply_personalization(
            "Hi {first_name}, wanted to ask you something.",
            target,
        )

        self.assertEqual(text, "Hi wanted to ask you something.")

    def test_personalization_removes_leading_first_name_when_missing(self):
        target = CampaignTarget(username="lead_user", display_name=None)

        text = tg._apply_personalization("{first_name}, привет!", target)

        self.assertEqual(text, "Привет!")

    def test_campaign_is_running_requires_live_task(self):
        tg._campaign_tasks[7] = FakeTaskState(False)
        tg._campaign_tasks[8] = FakeTaskState(True)

        self.assertTrue(tg.campaign_is_running(7))
        self.assertFalse(tg.campaign_is_running(8))
        self.assertFalse(tg.campaign_is_running(9))

    def test_await_campaign_call_times_out_descriptively(self):
        async def never_returns():
            await asyncio.sleep(3600)

        with self.assertRaises(TimeoutError) as ctx:
            asyncio.run(
                tg._await_campaign_call(
                    campaign_id=9,
                    target_username="stuck_target",
                    stage="resolve",
                    coro=never_returns(),
                    timeout_s=0.01,
                )
            )

        self.assertIn("resolve timeout", str(ctx.exception))
        self.assertIn("@stuck_target", str(ctx.exception))

    def test_pause_campaign_after_worker_error_sets_status_paused(self):
        with self._db() as db:
            db.add(
                Campaign(
                    id=50,
                    name="Broken campaign",
                    account_id=1,
                    account_ids="[1]",
                    messages="[]",
                    status="running",
                )
            )
            db.commit()

        with patch("backend.telegram_client.SessionLocal", self.Session):
            tg._pause_campaign_after_worker_error(50, "boom")

        with self._db() as db:
            campaign = db.query(Campaign).filter(Campaign.id == 50).first()

        self.assertEqual(campaign.status, "paused")

    def test_auto_reply_delay_is_disabled_for_immediate_send(self):
        short = tg._auto_reply_delay_seconds(
            inbound_text="Что это?",
            reply_text="Коротко: это исследование.",
            task_type="clarification",
            jitter=0,
        )
        booking = tg._auto_reply_delay_seconds(
            inbound_text="Давайте завтра в 16:00",
            reply_text="Поставил встречу на завтра. Ссылка для добавления в календарь: https://calendar.google.com/calendar/render?action=TEMPLATE",
            task_type="booking",
            jitter=0,
        )
        long_inbound = tg._auto_reply_delay_seconds(
            inbound_text="а" * 800,
            reply_text="Коротко отвечаю по сути.",
            task_type="clarification",
            jitter=0,
        )

        self.assertEqual(short, 0.0)
        self.assertEqual(booking, 0.0)
        self.assertEqual(long_inbound, 0.0)

    def test_auto_reply_presence_marks_read_and_shows_typing(self):
        client = FakePresenceClient()
        tg._clients[77] = client

        with patch("backend.telegram_client.asyncio.sleep", AsyncMock()) as sleep:
            read_ok = asyncio.run(tg._mark_auto_reply_read(77, "477"))
            typing_ok = asyncio.run(tg._show_auto_reply_typing(77, "477", duration_s=3.5))

        self.assertTrue(read_ok)
        self.assertTrue(typing_ok)
        self.assertEqual(client.read_entities, [477])
        self.assertEqual(client.typing_actions[0][0], 477)
        self.assertEqual(client.typing_actions[0][1], "typing")
        self.assertTrue(client.typing_actions[0][2].entered)
        self.assertTrue(client.typing_actions[0][2].exited)
        sleep.assert_awaited_with(3.5)

    def test_google_oauth_url_uses_calendar_scopes_and_redirect(self):
        env = {
            "GOOGLE_CLIENT_ID": "client-id.apps.googleusercontent.com",
            "GOOGLE_CLIENT_SECRET": "client-secret",
            "GOOGLE_REDIRECT_URI": "http://127.0.0.1:8010/api/integrations/google/callback",
            "GOOGLE_OAUTH_STATE_SECRET": "state-secret",
        }
        with patch.dict(os.environ, env, clear=False):
            url = build_google_auth_url()

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "accounts.google.com")
        self.assertEqual(params["client_id"], ["client-id.apps.googleusercontent.com"])
        self.assertEqual(params["redirect_uri"], ["http://127.0.0.1:8010/api/integrations/google/callback"])
        self.assertEqual(params["response_type"], ["code"])
        self.assertEqual(params["access_type"], ["offline"])
        self.assertEqual(params["prompt"], ["consent"])
        scopes = set(params["scope"][0].split())
        self.assertIn("https://www.googleapis.com/auth/calendar.events", scopes)
        self.assertIn("https://www.googleapis.com/auth/calendar.readonly", scopes)
        self.assertTrue(params["state"][0])

    def test_find_first_free_slot_respects_busy_meetings_and_buffer(self):
        tz = ZoneInfo("Europe/Moscow")
        window_start = datetime(2026, 4, 25, 16, 0, tzinfo=tz)
        window_end = datetime(2026, 4, 25, 22, 0, tzinfo=tz)
        busy = [
            {"start": "2026-04-25T16:00:00+03:00", "end": "2026-04-25T16:30:00+03:00"},
            {"start": "2026-04-25T17:15:00+03:00", "end": "2026-04-25T17:45:00+03:00"},
        ]

        slot = find_first_free_slot(busy, window_start, window_end, duration_min=30, buffer_min=15)

        self.assertIsNotNone(slot)
        self.assertEqual(slot[0], datetime(2026, 4, 25, 16, 45, tzinfo=tz))
        self.assertEqual(slot[1], datetime(2026, 4, 25, 17, 15, tzinfo=tz))

    def test_zoom_meeting_payload_uses_safe_scheduled_defaults(self):
        tz = ZoneInfo("Europe/Moscow")
        start = datetime(2026, 4, 25, 21, 15, tzinfo=tz)

        payload = build_zoom_meeting_payload(
            start=start,
            duration_min=30,
            topic="TG Outreach test meeting",
            agenda="Тестовая встреча",
        )

        self.assertEqual(payload["topic"], "TG Outreach test meeting")
        self.assertEqual(payload["type"], 2)
        self.assertEqual(payload["start_time"], "2026-04-25T21:15:00+03:00")
        self.assertEqual(payload["duration"], 30)
        self.assertEqual(payload["timezone"], "Europe/Moscow")
        self.assertFalse(payload["settings"]["join_before_host"])
        self.assertTrue(payload["settings"]["waiting_room"])

    def test_zoom_host_user_prefers_configured_email(self):
        with patch.dict(os.environ, {"ZOOM_HOST_EMAIL": "host@example.com"}, clear=False):
            self.assertEqual(zoom_host_user(), "host@example.com")

    def test_calendar_description_includes_zoom_join_link(self):
        description = build_calendar_event_description(
            "Тестовая встреча.",
            {"id": 123456789, "join_url": "https://zoom.us/j/123456789"},
        )

        self.assertIn("Тестовая встреча.", description)
        self.assertIn("Zoom: https://zoom.us/j/123456789", description)
        self.assertIn("Zoom meeting ID: 123456789", description)

    def test_meeting_booking_prompt_adds_hidden_marker_instruction(self):
        prompt = append_meeting_booking_instructions("base prompt")

        self.assertIn("base prompt", prompt)
        self.assertIn(BOOK_MEETING_MARKER, prompt)
        self.assertIn("Do not show", prompt)

    def test_meeting_booking_marker_is_removed_from_user_reply(self):
        clean, wants_booking = extract_meeting_booking_intent(
            f"Да, давайте созвонимся.\\n{BOOK_MEETING_MARKER}"
        )

        self.assertTrue(wants_booking)
        self.assertEqual(clean, "Да, давайте созвонимся.")

    def test_existing_scheduled_meeting_prevents_duplicate_booking(self):
        start = datetime(2026, 4, 25, 21, 15, tzinfo=ZoneInfo("Europe/Moscow"))
        end = datetime(2026, 4, 25, 21, 45, tzinfo=ZoneInfo("Europe/Moscow"))
        with self._db() as db:
            db.add(Account(id=25, name="Ana", phone="+573122997125", app_id="2040", app_hash="hash"))
            db.add(Conversation(id=125, account_id=25, tg_user_id="425", tg_username="lead_user_25"))
            db.add(
                ScheduledMeeting(
                    conversation_id=125,
                    status="scheduled",
                    scheduled_start=start,
                    scheduled_end=end,
                    timezone="Europe/Moscow",
                    calendar_event_id="google-event-1",
                    calendar_html_link="https://calendar.google.com/event",
                    zoom_meeting_id="123456789",
                    zoom_join_url="https://zoom.us/j/123456789",
                )
            )
            db.commit()

            meeting = get_existing_scheduled_meeting(db, 125)

        self.assertIsNotNone(meeting)
        self.assertEqual(meeting.zoom_join_url, "https://zoom.us/j/123456789")

    def test_meeting_reply_text_prefers_calendar_event_link_over_zoom_link(self):
        start = datetime(2026, 4, 25, 21, 15, tzinfo=ZoneInfo("Europe/Moscow"))
        end = datetime(2026, 4, 25, 21, 45, tzinfo=ZoneInfo("Europe/Moscow"))

        text = build_meeting_reply_text(
            start,
            end,
            "https://zoom.us/j/123456789",
            "https://calendar.google.com/event",
        )

        self.assertIn("25.04.2026", text)
        self.assertIn("21:15-21:45 МСК", text)
        self.assertIn("Ссылка на событие", text)
        self.assertIn("https://calendar.google.com/event", text)
        self.assertNotIn("https://zoom.us/j/123456789", text)

    def test_meeting_reply_text_prefers_public_calendar_add_link(self):
        start = datetime(2026, 4, 25, 21, 15, tzinfo=ZoneInfo("Europe/Moscow"))
        end = datetime(2026, 4, 25, 21, 45, tzinfo=ZoneInfo("Europe/Moscow"))

        text = build_meeting_reply_text(
            start,
            end,
            "https://zoom.us/j/123456789",
            "https://calendar.google.com/event/internal",
            "https://calendar.google.com/calendar/render?action=TEMPLATE",
        )

        self.assertIn("Ссылка для добавления в календарь", text)
        self.assertIn("https://calendar.google.com/calendar/render?action=TEMPLATE", text)
        self.assertNotIn("https://calendar.google.com/event/internal", text)
        self.assertNotIn("https://zoom.us/j/123456789", text)

    def test_calendar_add_url_contains_event_details_and_zoom_link(self):
        start = datetime(2026, 4, 25, 21, 15, tzinfo=ZoneInfo("Europe/Moscow"))
        end = datetime(2026, 4, 25, 21, 45, tzinfo=ZoneInfo("Europe/Moscow"))

        url = build_calendar_add_url(
            start=start,
            end=end,
            title="Research interview",
            description="Обсуждаем найм.",
            zoom_join_url="https://zoom.us/j/123456789",
        )

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "calendar.google.com")
        self.assertEqual(params["action"], ["TEMPLATE"])
        self.assertEqual(params["ctz"], ["Europe/Moscow"])
        self.assertEqual(params["dates"], ["20260425T211500/20260425T214500"])
        self.assertIn("Research interview", params["text"][0])
        self.assertIn("https://zoom.us/j/123456789", params["details"][0])

    def test_meeting_reply_text_uses_zoom_link_when_calendar_link_is_missing(self):
        start = datetime(2026, 4, 25, 21, 15, tzinfo=ZoneInfo("Europe/Moscow"))
        end = datetime(2026, 4, 25, 21, 45, tzinfo=ZoneInfo("Europe/Moscow"))

        text = build_meeting_reply_text(start, end, "https://zoom.us/j/123456789")

        self.assertIn("25.04.2026", text)
        self.assertIn("21:15-21:45 МСК", text)
        self.assertIn("https://zoom.us/j/123456789", text)

    def test_book_meeting_for_conversation_creates_zoom_calendar_and_db_record(self):
        with self._db() as db:
            db.add(Account(id=26, name="Ana", phone="+573122997126", app_id="2040", app_hash="hash"))
            db.add(
                Conversation(
                    id=126,
                    account_id=26,
                    tg_user_id="426",
                    tg_username="lead_user_26",
                    tg_first_name="Lead",
                )
            )
            db.commit()

            with patch("backend.meeting_scheduler.find_next_available_slot", AsyncMock(return_value=(
                datetime(2026, 4, 25, 21, 15, tzinfo=ZoneInfo("Europe/Moscow")),
                datetime(2026, 4, 25, 21, 45, tzinfo=ZoneInfo("Europe/Moscow")),
            ))):
                with patch("backend.meeting_scheduler.create_zoom_meeting", AsyncMock(return_value={
                    "id": 123456789,
                    "join_url": "https://zoom.us/j/123456789",
                })) as zoom:
                    with patch("backend.meeting_scheduler.create_calendar_event", AsyncMock(return_value={
                        "id": "google-event-1",
                        "htmlLink": "https://calendar.google.com/event",
                    })) as calendar:
                        result = asyncio.run(book_meeting_for_conversation(db, 126))
                        second = asyncio.run(book_meeting_for_conversation(db, 126))

            stored = db.query(ScheduledMeeting).filter(ScheduledMeeting.conversation_id == 126).all()

        self.assertTrue(result["created"])
        self.assertFalse(second["created"])
        self.assertEqual(result["zoom_join_url"], "https://zoom.us/j/123456789")
        self.assertEqual(result["calendar_html_link"], "https://calendar.google.com/event")
        self.assertEqual(len(stored), 1)
        zoom.assert_awaited_once()
        calendar.assert_awaited_once()

    def test_book_meeting_from_agent_payload_supports_dry_run(self):
        with self._db() as db:
            db.add(Account(id=46, name="Ana", phone="+573122997146", app_id="2040", app_hash="hash"))
            db.add(Conversation(id=146, account_id=46, tg_user_id="446", tg_username="lead_user_46"))
            db.commit()

            with patch("backend.meeting_scheduler.create_zoom_meeting", AsyncMock()) as zoom:
                with patch("backend.meeting_scheduler.create_calendar_event", AsyncMock()) as calendar:
                    result = asyncio.run(book_meeting_from_agent_payload(
                        db,
                        conversation_id=146,
                        start_at="2026-04-30T19:00:00+03:00",
                        duration_min=30,
                        attendee_email="person@example.com",
                        dry_run=True,
                    ))

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["attendee_email"], "person@example.com")
        self.assertEqual(zoom.await_count, 0)
        self.assertEqual(calendar.await_count, 0)

    def test_book_meeting_from_agent_payload_without_email_returns_calendar_add_url(self):
        with self._db() as db:
            db.add(Account(id=48, name="Ana", phone="+573122997148", app_id="2040", app_hash="hash"))
            db.add(Conversation(id=148, account_id=48, tg_user_id="448", tg_username="lead_user_48"))
            db.commit()

            with patch("backend.meeting_scheduler.get_busy_intervals", AsyncMock(return_value=[])):
                with patch("backend.meeting_scheduler.create_zoom_meeting", AsyncMock(return_value={
                    "id": 123456789,
                    "join_url": "https://zoom.us/j/123456789",
                })):
                    with patch("backend.meeting_scheduler.zoom_configured", return_value=True):
                        with patch("backend.meeting_scheduler.create_calendar_event", AsyncMock(return_value={
                            "id": "google-event-no-email",
                            "htmlLink": "https://calendar.google.com/event/internal",
                        })) as calendar:
                            result = asyncio.run(book_meeting_from_agent_payload(
                                db,
                                conversation_id=148,
                                start_at="2026-04-30T19:00:00+03:00",
                                duration_min=30,
                                attendee_email="",
                            ))
            stored = db.query(ScheduledMeeting).filter(ScheduledMeeting.conversation_id == 148).first()

        self.assertTrue(result["ok"])
        self.assertEqual(result["attendee_email"], "")
        self.assertIn("calendar.google.com/calendar/render", result["calendar_add_url"])
        self.assertEqual(stored.calendar_add_url, result["calendar_add_url"])
        calendar.assert_awaited_once()
        self.assertIsNone(calendar.await_args.kwargs["attendee_email"])

    def test_bookings_create_endpoint_matches_n8n_contract(self):
        with self._db() as db:
            db.add(Account(id=47, name="Ana", phone="+573122997147", app_id="2040", app_hash="hash"))
            db.add(Conversation(id=147, account_id=47, tg_user_id="447", tg_username="lead_user_47"))
            db.commit()

        app = FastAPI()
        app.include_router(bookings_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            response = client.post("/api/bookings/create", json={
                "event_id": "test:booking",
                "conversation_id": 147,
                "account_id": 47,
                "start_at": "2026-04-30T19:00:00+03:00",
                "duration_minutes": 30,
                "attendee_email": "person@example.com",
                "dry_run": True,
            })
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["attendee_email"], "person@example.com")

    def test_generated_n8n_booking_reply_uses_calendar_event_link(self):
        workflow_path = Path(__file__).resolve().parents[2] / "artifacts" / "n8n" / "hr_discovery_multi_agent_booking_workflow.json"
        workflow = json.loads(workflow_path.read_text())
        merge_node = next(node for node in workflow["nodes"] if node["name"] == "Merge Booking Result")
        merge_code = merge_node["parameters"]["jsCode"]

        self.assertIn("calendar_add_url", merge_code)
        self.assertIn("Ссылка для добавления в календарь", merge_code)
        self.assertNotIn("Ссылка Zoom", merge_code)

    def test_generated_n8n_books_concrete_slot_without_requiring_email(self):
        workflow_path = Path(__file__).resolve().parents[2] / "artifacts" / "n8n" / "hr_discovery_multi_agent_booking_workflow.json"
        workflow = json.loads(workflow_path.read_text())
        prepare_code = next(node for node in workflow["nodes"] if node["name"] == "Prepare OpenAI Request")["parameters"]["jsCode"]
        parse_code = next(node for node in workflow["nodes"] if node["name"] == "Parse Decision")["parameters"]["jsCode"]

        self.assertIn("email не обязателен", prepare_code)
        self.assertIn("ops_action = \"create_booking\"", prepare_code)
        self.assertNotIn("const hasEmail", parse_code)
        self.assertNotIn("booking_missing_required_fields", parse_code)

    def test_generated_n8n_prompt_has_short_incremental_reply_rules(self):
        workflow_path = Path(__file__).resolve().parents[2] / "artifacts" / "n8n" / "hr_discovery_multi_agent_booking_workflow.json"
        workflow = json.loads(workflow_path.read_text())
        prepare_code = next(node for node in workflow["nodes"] if node["name"] == "Prepare OpenAI Request")["parameters"]["jsCode"]

        self.assertIn("Не повторяй уже сказанные мысли", prepare_code)
        self.assertIn("Если ответ повторяет предыдущий", prepare_code)
        self.assertIn("Вы имеете в виду", prepare_code)
        self.assertIn("last_messages", prepare_code)
        self.assertIn("scenario_cards", prepare_code)

    def test_generated_n8n_prompt_uses_dify_knowledge_cards(self):
        workflow_path = Path(__file__).resolve().parents[2] / "artifacts" / "n8n" / "hr_discovery_multi_agent_booking_workflow.json"
        workflow = json.loads(workflow_path.read_text())
        prepare_code = next(node for node in workflow["nodes"] if node["name"] == "Prepare OpenAI Request")["parameters"]["jsCode"]

        self.assertIn("knowledge_cards", prepare_code)
        self.assertIn("knowledgeCards", prepare_code)
        self.assertIn("Knowledge cards", prepare_code)
        self.assertIn("knowledge_cards важнее", prepare_code)

    def test_generated_n8n_prompt_includes_humanizer_rules(self):
        workflow_path = Path(__file__).resolve().parents[2] / "artifacts" / "n8n" / "hr_discovery_multi_agent_booking_workflow.json"
        workflow = json.loads(workflow_path.read_text())
        prepare_code = next(node for node in workflow["nodes"] if node["name"] == "Prepare OpenAI Request")["parameters"]["jsCode"]

        self.assertIn("Humanizer pass", prepare_code)
        self.assertIn("не звучит как AI", prepare_code)
        self.assertIn("не используй стерильную эмпатию", prepare_code)
        self.assertIn("не делай ответ идеально отполированным", prepare_code)
        self.assertIn("внутреннюю проверку не выводи", prepare_code)

    def test_schedule_conversation_meeting_endpoint_returns_reply_text(self):
        with self._db() as db:
            db.add(Account(id=27, name="Ana", phone="+573122997127", app_id="2040", app_hash="hash"))
            db.add(Conversation(id=127, account_id=27, tg_user_id="427", tg_username="lead_user_27"))
            db.commit()

        app = FastAPI()
        app.include_router(conversations_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            with patch("backend.routers.conversations.book_meeting_for_conversation", AsyncMock(return_value={
                "ok": True,
                "created": True,
                "reply_text": "Забронировал встречу на 25.04.2026, 21:15-21:45 МСК. Ссылка Zoom: https://zoom.us/j/123456789",
                "zoom_join_url": "https://zoom.us/j/123456789",
            })):
                response = client.post("/api/conversations/127/schedule-meeting")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["created"])
        self.assertIn("https://zoom.us/j/123456789", payload["reply_text"])

    def test_run_scheduled_auto_reply_books_meeting_when_ai_returns_marker(self):
        with self._db() as db:
            db.add(
                Account(
                    id=28,
                    name="Ana",
                    phone="+573122997128",
                    app_id="2040",
                    app_hash="hash",
                    auto_reply=True,
                )
            )
            db.add(Settings(id=1, provider="openai", auto_reply_enabled=True, openai_key="sk-test", model="gpt-4o-mini"))
            db.add(
                Conversation(
                    id=128,
                    account_id=28,
                    tg_user_id="428",
                    tg_username="lead_user_28",
                    tg_first_name="Lead",
                    status="active",
                )
            )
            db.add(Message(conversation_id=128, role="user", text="Да, давайте созвонимся"))
            db.commit()
            trigger_id = db.query(Message).filter(Message.conversation_id == 128).first().id

        booked_reply = "Забронировал встречу на 25.04.2026, 21:15-21:45 МСК. Ссылка Zoom: https://zoom.us/j/123456789"
        with patch("backend.telegram_client.SessionLocal", self.Session):
            with patch("backend.telegram_client.asyncio.sleep", AsyncMock()):
                with patch("backend.gpt_handler.generate_reply", AsyncMock(return_value=f"Отлично, договорились.\\n{BOOK_MEETING_MARKER}")):
                    with patch("backend.telegram_client.maybe_book_meeting_from_reply", AsyncMock(return_value=(
                        f"Отлично, договорились.\n\n{booked_reply}",
                        {"ok": True, "created": True, "reply_text": booked_reply},
                    ))) as book:
                        with patch("backend.telegram_client.send_manual_message", AsyncMock(return_value={"ok": True})) as send:
                            asyncio.run(
                                tg._run_scheduled_auto_reply(
                                    account_id=28,
                                    conversation_id=128,
                                    tg_user_id="428",
                                    trigger_message_id=trigger_id,
                                    delay_s=7.0,
                                    scheduled_at=tg._utcnow(),
                                )
                            )

        book.assert_awaited_once()
        sent_text = send.await_args.args[3]
        self.assertIn("Отлично, договорились.", sent_text)
        self.assertIn(booked_reply, sent_text)
        self.assertNotIn(BOOK_MEETING_MARKER, sent_text)

    def test_run_scheduled_auto_reply_sends_clean_fallback_when_booking_fails(self):
        with self._db() as db:
            db.add(
                Account(
                    id=29,
                    name="Ana",
                    phone="+573122997129",
                    app_id="2040",
                    app_hash="hash",
                    auto_reply=True,
                )
            )
            db.add(Settings(id=1, provider="openai", auto_reply_enabled=True, openai_key="sk-test", model="gpt-4o-mini"))
            db.add(Conversation(id=129, account_id=29, tg_user_id="429", tg_username="lead_user_29", status="active"))
            db.add(Message(conversation_id=129, role="user", text="Да, хочу созвон"))
            db.commit()
            trigger_id = db.query(Message).filter(Message.conversation_id == 129).first().id

        with patch("backend.telegram_client.SessionLocal", self.Session):
            with patch("backend.telegram_client.asyncio.sleep", AsyncMock()):
                with patch("backend.gpt_handler.generate_reply", AsyncMock(return_value=f"Отлично, договорились.\\n{BOOK_MEETING_MARKER}")):
                    with patch("backend.telegram_client.maybe_book_meeting_from_reply", AsyncMock(side_effect=HTTPException(409, "No free slot"))):
                        with patch("backend.telegram_client.send_manual_message", AsyncMock(return_value={"ok": True})) as send:
                            asyncio.run(
                                tg._run_scheduled_auto_reply(
                                    account_id=29,
                                    conversation_id=129,
                                    tg_user_id="429",
                                    trigger_message_id=trigger_id,
                                    delay_s=7.0,
                                    scheduled_at=tg._utcnow(),
                                )
                            )

        sent_text = send.await_args.args[3]
        self.assertIn("Отлично, договорились.", sent_text)
        self.assertIn("вернусь со ссылкой", sent_text)
        self.assertNotIn(BOOK_MEETING_MARKER, sent_text)

    def test_run_scheduled_auto_reply_skips_if_new_user_message_arrives_after_generation(self):
        with self._db() as db:
            db.add(
                Account(
                    id=30,
                    name="Ana",
                    phone="+573122997130",
                    app_id="2040",
                    app_hash="hash",
                    auto_reply=True,
                )
            )
            db.add(Settings(id=1, provider="openai", auto_reply_enabled=True, openai_key="sk-test", model="gpt-4o-mini"))
            db.add(Conversation(id=130, account_id=30, tg_user_id="430", tg_username="lead_user_30", status="active"))
            db.add(Message(conversation_id=130, role="user", text="Первое сообщение"))
            db.commit()
            trigger_id = db.query(Message).filter(Message.conversation_id == 130).first().id

        async def add_new_user_message(db, conversation_id, reply):
            db.add(Message(conversation_id=conversation_id, role="user", text="Второе сообщение"))
            db.commit()
            return reply, None

        with patch("backend.telegram_client.SessionLocal", self.Session):
            with patch("backend.telegram_client.asyncio.sleep", AsyncMock()):
                with patch("backend.gpt_handler.generate_reply", AsyncMock(return_value="Ответ на первое сообщение")):
                    with patch("backend.telegram_client.maybe_book_meeting_from_reply", AsyncMock(side_effect=add_new_user_message)):
                        with patch("backend.telegram_client.send_manual_message", AsyncMock(return_value={"ok": True})) as send:
                            asyncio.run(
                                tg._run_scheduled_auto_reply(
                                    account_id=30,
                                    conversation_id=130,
                                    tg_user_id="430",
                                    trigger_message_id=trigger_id,
                                    delay_s=7.0,
                                    scheduled_at=tg._utcnow(),
                                )
                            )

        send.assert_not_awaited()

    def test_record_agent_run_persists_redacted_json(self):
        with self._db() as db:
            run = record_agent_run(
                db,
                conversation_id=501,
                run_type="reply",
                model="gpt-5.4-mini",
                input_payload={"openai_key": "sk-secret", "messages": ["hello"]},
                output_payload={"action": "send_reply"},
            )
            stored = db.query(AgentRun).filter(AgentRun.id == run.id).first()

        self.assertEqual(stored.status, "succeeded")
        self.assertEqual(stored.run_type, "reply")
        self.assertNotIn("sk-secret", stored.input_json)
        self.assertEqual(json.loads(stored.output_json)["action"], "send_reply")

    def test_scenario_mining_creates_draft_scenario_from_conversation(self):
        with self._db() as db:
            db.add(Account(id=31, name="Ana", phone="+573122997131", app_id="2040", app_hash="hash"))
            db.add(Conversation(id=131, account_id=31, tg_user_id="431", tg_first_name="Lead"))
            db.add(Message(conversation_id=131, role="user", text="Это продажа? Мне не интересно покупать."))
            db.add(Message(conversation_id=131, role="assistant", text="Нет, это короткое исследовательское интервью."))
            db.commit()

            scenario = mine_scenario_from_conversation(db, 131)

            stored = db.query(ScenarioCard).filter(ScenarioCard.id == scenario.id).first()

        self.assertEqual(stored.status, "draft")
        self.assertEqual(stored.intent, "sales_objection")
        self.assertIn("продаж", stored.trigger_summary.lower())

    def test_founder_research_pack_seeds_active_grouped_scenarios_idempotently(self):
        with self._db() as db:
            first = seed_founder_research_pack(db)
            second = seed_founder_research_pack(db)
            cards = db.query(ScenarioCard).filter(ScenarioCard.tags.like("%pack:founder_research%")).all()
            grouped = group_scenarios(cards)

        labels = {group["label"] for group in grouped}
        combined_reply_text = "\n".join(card.recommended_reply for card in cards).lower()

        self.assertGreaterEqual(first["created"], 20)
        self.assertEqual(second["created"], 0)
        self.assertEqual(first["total"], len(cards))
        self.assertTrue(all(card.status == "active" for card in cards))
        self.assertIn("Вопросы и ответы", labels)
        self.assertIn("Назначение встречи", labels)
        self.assertIn("Ограничения", labels)
        self.assertIn("это не продажа", combined_reply_text)

    def test_active_scenarios_match_founder_research_faq_question(self):
        with self._db() as db:
            seed_founder_research_pack(db)

            matches = active_scenarios_for_text(db, "Это продажа? Что вы продаете?", limit=1)

        self.assertEqual(matches[0].intent, "sales_objection")
        self.assertIn("не продажа", matches[0].recommended_reply.lower())
        self.assertIn("Это продажа?", serialize_scenario(matches[0])["example_questions"])

    def test_scenario_pack_endpoint_returns_grouped_cards(self):
        app = FastAPI()
        app.include_router(scenarios_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            seed_response = client.post("/api/scenarios/seed-founder-research-pack")
            grouped_response = client.get("/api/scenarios/grouped?status=active")
        finally:
            client.close()

        self.assertEqual(seed_response.status_code, 200)
        self.assertGreaterEqual(seed_response.json()["created"], 20)
        self.assertEqual(grouped_response.status_code, 200)
        self.assertTrue(any(group["label"] == "Вопросы и ответы" for group in grouped_response.json()))

    def test_analyze_conversations_creates_idempotent_suggested_scenarios(self):
        with self._db() as db:
            db.add(Account(id=35, name="Ana", phone="+573122997135", app_id="2040", app_hash="hash"))
            db.add(Conversation(id=135, account_id=35, tg_user_id="435", tg_first_name="Lead"))
            db.add(Message(conversation_id=135, role="user", text="А это продажа? Я ничего покупать не планирую."))
            db.add(Message(conversation_id=135, role="assistant", text="Нет, это исследовательский разговор."))
            db.commit()

            first = analyze_conversations_for_suggestions(db)
            second = analyze_conversations_for_suggestions(db)
            suggestions = db.query(ScenarioCard).filter(ScenarioCard.status == "suggested").all()

        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].intent, "sales_objection")
        self.assertEqual(suggestions[0].source_conversation_id, 135)
        self.assertIn("auto:conversation_analysis", suggestions[0].tags)

    def test_analyze_conversations_endpoint_returns_improve_queue_items(self):
        with self._db() as db:
            db.add(Account(id=36, name="Ana", phone="+573122997136", app_id="2040", app_hash="hash"))
            db.add(Conversation(id=136, account_id=36, tg_user_id="436", tg_first_name="Lead"))
            db.add(Message(conversation_id=136, role="user", text="Давайте созвонимся на неделе."))
            db.commit()

        app = FastAPI()
        app.include_router(scenarios_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            response = client.post("/api/scenarios/analyze-conversations")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["created"], 1)
        self.assertEqual(payload["suggestions"][0]["status"], "suggested")
        self.assertEqual(payload["suggestions"][0]["source_conversation_id"], 136)

    def test_build_scenario_dify_document_keeps_scenario_structure(self):
        card = ScenarioCard(
            id=137,
            title="Это не продажа",
            intent="sales_objection",
            trigger_summary="Собеседник спрашивает, не продажа ли это.",
            recommended_reply="Нет, это исследовательский разговор.",
            avoid_reply="Не спорить.",
            status="active",
            tags="group:faq,key:sales_objection,not_sales",
        )

        document = build_scenario_dify_document(card)

        self.assertEqual(document["name"], "scenario-137-eto-ne-prodazha.md")
        self.assertIn("# Это не продажа", document["text"])
        self.assertIn("intent: sales_objection", document["text"])
        self.assertIn("Собеседник спрашивает, не продажа ли это.", document["text"])
        self.assertIn("Нет, это исследовательский разговор.", document["text"])
        self.assertIn("Не спорить.", document["text"])

    def test_list_scenarios_excludes_legacy_by_default(self):
        with self._db() as db:
            db.add(
                ScenarioCard(
                    title="Новый сценарий",
                    intent="context_question",
                    trigger_summary="Рабочий сценарий.",
                    recommended_reply="Ответ.",
                    status="active",
                )
            )
            db.add(
                ScenarioCard(
                    title="Старый сценарий",
                    intent="legacy",
                    trigger_summary="Старый сценарий.",
                    recommended_reply="Старый ответ.",
                    status="legacy",
                )
            )
            db.commit()

            default_response = [card.title for card in list_scenarios(db)]
            legacy_response = [card.title for card in list_scenarios(db, status="legacy")]

        self.assertIn("Новый сценарий", default_response)
        self.assertNotIn("Старый сценарий", default_response)
        self.assertEqual(legacy_response, ["Старый сценарий"])

    def test_mark_founder_research_pack_legacy_removes_seeded_cards_from_active_set(self):
        with self._db() as db:
            seed_founder_research_pack(db)

            result = mark_founder_research_pack_legacy(db)
            active_pack_cards = (
                db.query(ScenarioCard)
                .filter(
                    ScenarioCard.status == "active",
                    ScenarioCard.tags.like("%pack:founder_research%"),
                )
                .count()
            )
            legacy_pack_cards = db.query(ScenarioCard).filter(ScenarioCard.status == "legacy").count()

        self.assertGreaterEqual(result["updated"], 20)
        self.assertEqual(active_pack_cards, 0)
        self.assertGreaterEqual(legacy_pack_cards, 20)

    def test_mark_founder_research_pack_legacy_endpoint(self):
        app = FastAPI()
        app.include_router(scenarios_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            client.post("/api/scenarios/seed-founder-research-pack")
            response = client.post("/api/scenarios/legacy/founder-research-pack")
            grouped_response = client.get("/api/scenarios/grouped")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.json()["updated"], 20)
        self.assertFalse(any(group["key"] == "faq" for group in grouped_response.json()))

    def test_sync_scenarios_to_dify_creates_and_updates_documents(self):
        class FakeDifyClient:
            def __init__(self):
                self.created = []
                self.updated = []

            def create_document_by_text(self, *, name, text):
                self.created.append({"name": name, "text": text})
                return {"document": {"id": "doc-created"}, "batch": "batch-created"}

            def update_document_by_text(self, *, document_id, name, text):
                self.updated.append({"document_id": document_id, "name": name, "text": text})
                return {"document": {"id": document_id}, "batch": "batch-updated"}

        with self._db() as db:
            db.add(
                ScenarioCard(
                    id=138,
                    title="Новый сценарий",
                    intent="context_question",
                    trigger_summary="Спрашивают контекст.",
                    recommended_reply="Коротко объяснить контекст.",
                    status="active",
                )
            )
            db.add(
                ScenarioCard(
                    id=139,
                    title="Существующий сценарий",
                    intent="book_meeting",
                    trigger_summary="Готовы к встрече.",
                    recommended_reply="Подтвердить слот.",
                    status="active",
                    dify_document_id="doc-existing",
                )
            )
            db.add(
                ScenarioCard(
                    id=140,
                    title="Черновик",
                    intent="draft",
                    trigger_summary="Не должен синкаться.",
                    recommended_reply="Не синкать.",
                    status="draft",
                )
            )
            db.commit()

            fake_client = FakeDifyClient()
            result = sync_scenarios_to_dify(db, client=fake_client, status="active")
            created_card = db.query(ScenarioCard).filter(ScenarioCard.id == 138).first()
            updated_card = db.query(ScenarioCard).filter(ScenarioCard.id == 139).first()

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(fake_client.created), 1)
        self.assertEqual(fake_client.updated[0]["document_id"], "doc-existing")
        self.assertEqual(created_card.dify_document_id, "doc-created")
        self.assertEqual(created_card.dify_sync_status, "synced")
        self.assertEqual(updated_card.dify_sync_status, "synced")

    def test_dify_sync_endpoint_returns_sync_result(self):
        app = FastAPI()
        app.include_router(scenarios_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            with patch(
                "backend.routers.scenarios.sync_scenarios_to_dify",
                return_value={"status": "active", "total": 1, "created": 1, "updated": 0, "failed": 0, "items": []},
            ):
                response = client.post("/api/scenarios/dify/sync?status=active")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["created"], 1)

    def test_sandbox_replay_is_dry_run_and_uses_active_scenarios(self):
        with self._db() as db:
            db.add(Account(id=32, name="Ana", phone="+573122997132", app_id="2040", app_hash="hash"))
            db.add(Conversation(id=132, account_id=32, tg_user_id="432", tg_first_name="Lead"))
            db.add(Message(conversation_id=132, role="user", text="Да, давайте созвонимся завтра."))
            db.add(
                ScenarioCard(
                    title="Lead agrees to call",
                    intent="book_meeting",
                    trigger_summary="Lead agrees to a call",
                    recommended_reply="Confirm and book a meeting.",
                    status="active",
                    tags="booking,call",
                )
            )
            db.commit()

            result = replay_conversation_sandbox(db, conversation_id=132, dry_run_tools=True)
            runs = db.query(AgentRun).filter(AgentRun.conversation_id == 132).all()
            meetings = db.query(ScheduledMeeting).filter(ScheduledMeeting.conversation_id == 132).all()

        self.assertEqual(result["reply"]["action"], "book_meeting")
        self.assertTrue(result["would_book_meeting"])
        self.assertEqual(result["tool_result_preview"]["mode"], "dry_run")
        self.assertGreaterEqual(len(result["selected_scenarios"]), 1)
        self.assertEqual(len(meetings), 0)
        self.assertTrue(any(run.run_type == "sandbox" for run in runs))

    def test_sandbox_replay_uses_selected_founder_pack_faq_reply(self):
        with self._db() as db:
            seed_founder_research_pack(db)
            db.add(Account(id=34, name="Ana", phone="+573122997134", app_id="2040", app_hash="hash"))
            db.add(Conversation(id=134, account_id=34, tg_user_id="434", tg_first_name="Lead"))
            db.add(Message(conversation_id=134, role="user", text="Это продажа? Я ничего покупать не хочу."))
            db.commit()

            result = replay_conversation_sandbox(db, conversation_id=134, dry_run_tools=True)

        self.assertEqual(result["selected_scenarios"][0]["intent"], "sales_objection")
        self.assertIn("не продажа", result["reply"]["reply_text"].lower())

    def test_eval_runner_returns_scorecard_for_agent_cases(self):
        cases = [
            {
                "id": "booking_case",
                "history": [{"role": "user", "text": "Ок, давайте созвонимся"}],
                "expected_action": "book_meeting",
                "must_not_include": ["[[BOOK_MEETING]]"],
            },
            {
                "id": "question_case",
                "history": [{"role": "user", "text": "А что вы исследуете?"}],
                "expected_action": "send_reply",
                "must_include": ["исслед"],
            },
        ]

        result = run_local_eval_cases(cases)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["score"], 1.0)

    def test_agent_debug_endpoint_replays_conversation(self):
        with self._db() as db:
            db.add(Account(id=33, name="Ana", phone="+573122997133", app_id="2040", app_hash="hash"))
            db.add(Conversation(id=133, account_id=33, tg_user_id="433", tg_first_name="Lead"))
            db.add(Message(conversation_id=133, role="user", text="Сколько длится интервью?"))
            db.commit()

        app = FastAPI()
        app.include_router(agents_router.router)
        app.include_router(sandbox_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            response = client.post("/api/sandbox/replay", json={"conversation_id": 133, "dry_run_tools": True})
            runs_response = client.get("/api/agents/runs?conversation_id=133")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"]["action"], "send_reply")
        self.assertEqual(runs_response.status_code, 200)
        self.assertGreaterEqual(len(runs_response.json()), 1)

    def test_n8n_sandbox_replay_records_decision_without_sending(self):
        with self._db() as db:
            db.add(Account(id=37, name="Ana", phone="+573122997137", app_id="2040", app_hash="hash"))
            db.add(Conversation(id=137, account_id=37, tg_user_id="437", tg_first_name="Lead"))
            db.add(Message(conversation_id=137, role="user", text="Ок, давайте созвонимся."))
            db.commit()

            decision = N8nAgentDecision(
                approved=True,
                stage="scheduling",
                intent="availability_offer",
                reply_text="Да, давайте подберем удобное время.",
                ops_action="none",
                reason="Lead is open to a call.",
            )
            with patch(
                "backend.sandbox.call_n8n_agent",
                AsyncMock(return_value=N8nAgentCallResult(ok=True, decision=decision, raw_response=decision.model_dump(mode="json"))),
            ) as call:
                result = asyncio.run(replay_conversation_n8n_sandbox(db, conversation_id=137))
            runs = db.query(AgentRun).filter(AgentRun.conversation_id == 137).all()

        self.assertEqual(call.await_count, 1)
        self.assertEqual(result["engine"], "n8n")
        self.assertFalse(result["would_send"])
        self.assertTrue(result["policy"]["safe_to_send"])
        self.assertEqual(result["decision"]["reply_text"], "Да, давайте подберем удобное время.")
        self.assertTrue(any(run.run_type == "sandbox_n8n" for run in runs))

    def test_n8n_sandbox_replay_includes_dify_knowledge_cards(self):
        with self._db() as db:
            db.add(Account(id=57, name="Ana", phone="+573122997157", app_id="2040", app_hash="hash"))
            db.add(Conversation(id=157, account_id=57, tg_user_id="457", tg_first_name="Lead"))
            db.add(Message(conversation_id=157, role="user", text="А что я получу за интервью?"))
            db.commit()

            decision = N8nAgentDecision(
                approved=True,
                stage="qualification",
                intent="other",
                reply_text="Личная польза — краткий итог исследования после серии интервью.",
                ops_action="none",
            )
            dify_result = {
                "query": "Последнее сообщение пользователя:\nА что я получу за интервью?",
                "cards": [{"source": "dify", "title": "value-question.md", "score": 0.8, "content": "Не повторять питч."}],
                "error": None,
                "configured": True,
            }
            with patch("backend.sandbox.retrieve_dify_knowledge_cards", AsyncMock(return_value=dify_result)):
                with patch(
                    "backend.sandbox.call_n8n_agent",
                    AsyncMock(return_value=N8nAgentCallResult(ok=True, decision=decision, raw_response=decision.model_dump(mode="json"))),
                ) as call:
                    result = asyncio.run(replay_conversation_n8n_sandbox(db, conversation_id=157))

        request = call.await_args.args[0]
        self.assertTrue(result["policy"]["safe_to_send"])
        self.assertEqual(request.knowledge_cards[0]["title"], "value-question.md")

    def test_n8n_sandbox_blocks_fake_booking_claim(self):
        with self._db() as db:
            db.add(Account(id=38, name="Ana", phone="+573122997138", app_id="2040", app_hash="hash"))
            db.add(Conversation(id=138, account_id=38, tg_user_id="438", tg_first_name="Lead"))
            db.add(Message(conversation_id=138, role="user", text="Да, подходит."))
            db.commit()

            decision = N8nAgentDecision(
                approved=True,
                stage="scheduling",
                intent="availability_offer",
                reply_text="Инвайт отправил, ссылка Zoom: https://zoom.us/j/123",
                ops_action="none",
            )
            with patch(
                "backend.sandbox.call_n8n_agent",
                AsyncMock(return_value=N8nAgentCallResult(ok=True, decision=decision, raw_response=decision.model_dump(mode="json"))),
            ):
                result = asyncio.run(replay_conversation_n8n_sandbox(db, conversation_id=138))
            stored = db.query(AgentRun).filter(AgentRun.conversation_id == 138).first()

        self.assertFalse(result["policy"]["safe_to_send"])
        self.assertIn("booking_claim_without_record", result["policy"]["issues"])
        self.assertEqual(stored.status, "blocked")

    def test_agent_policy_blocks_repetitive_long_cta_reply(self):
        decision = {
            "approved": True,
            "intent": "other",
            "reply_text": (
                "Понимаю вопрос — если коротко, прямой пользы в виде сервиса тут пока нет: "
                "это исследовательский разговор, а в ответ могу потом прислать краткое резюме "
                "по повторяющимся паттернам и боли, которые увидим по найму. Если вам это не очень "
                "интересно, тоже ок; если интересно, можем просто выбрать удобные 20–30 минут."
            ),
            "ops_action": "none",
        }
        recent_messages = [
            {"role": "assistant", "text": "Ничего обязательного — только короткий разговор про ваш опыт найма, а вам в ответ пришлю краткий итог по типовым проблемам и паттернам."},
            {"role": "user", "text": "Я имею ввиду что я за это получу"},
        ]

        policy = validate_agent_decision(decision, recent_messages=recent_messages)

        self.assertFalse(policy["safe_to_send"])
        self.assertIn("reply_too_long_for_intent", policy["issues"])
        self.assertIn("repeated_meeting_cta", policy["issues"])

    def test_agent_policy_allows_short_incremental_value_reply(self):
        decision = {
            "approved": True,
            "intent": "other",
            "reply_text": "Понял. Личная выгода — краткий итог исследования после серии интервью. Если это не ценно, не буду отвлекать.",
            "ops_action": "none",
        }
        recent_messages = [
            {"role": "assistant", "text": "Могу потом прислать краткое резюме по повторяющимся паттернам."},
            {"role": "user", "text": "Я имею ввиду что я за это получу"},
        ]

        policy = validate_agent_decision(decision, recent_messages=recent_messages)

        self.assertTrue(policy["safe_to_send"])
        self.assertEqual(policy["final_reply_text"], decision["reply_text"])

    def test_agent_policy_allows_booking_confirmation_with_long_calendar_link(self):
        calendar_url = "https://calendar.google.com/calendar/render?action=TEMPLATE&text=" + ("a" * 900)
        decision = {
            "approved": True,
            "intent": "availability_offer",
            "reply_text": f"Поставил встречу на 28.04.2026, 19:00-19:30 МСК. Ссылка для добавления в календарь: {calendar_url}",
            "ops_action": "create_booking",
            "booking": {
                "start_at": "2026-04-28T19:00:00+03:00",
                "calendar_add_url": calendar_url,
            },
        }

        policy = validate_agent_decision(decision, booking_record_exists=True, recent_messages=[
            {"role": "user", "text": "Давай завтра на 7"},
        ])

        self.assertTrue(policy["safe_to_send"])
        self.assertEqual(policy["issues"], [])

    def test_telegram_outgoing_text_renders_urls_as_clickable_label(self):
        calendar_url = "https://calendar.google.com/calendar/render?action=TEMPLATE&text=Interview&dates=20260428"
        send_text, persisted_text, kwargs = tg._prepare_telegram_outgoing_text(
            f"Поставил встречу. Добавьте событие в календарь: {calendar_url}"
        )

        self.assertEqual(kwargs, {"parse_mode": "html"})
        self.assertNotIn(calendar_url, persisted_text)
        self.assertEqual(persisted_text, "Поставил встречу. Добавьте событие в календарь: ссылка")
        self.assertIn('href="https://calendar.google.com/calendar/render?action=TEMPLATE&amp;text=Interview&amp;dates=20260428"', send_text)
        self.assertIn(">ссылка</a>", send_text)

    def test_n8n_adapter_rejects_invalid_decision_schema(self):
        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"approved": True, "stage": "not_a_stage"}

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, *args, **kwargs):
                return FakeResponse()

        request = N8nAgentRequest(
            event_id="test:invalid",
            mode="sandbox",
            conversation={"id": 1},
            messages=[],
        )
        with patch("backend.n8n_agent.httpx.AsyncClient", FakeClient):
            result = asyncio.run(call_n8n_agent(request, webhook_url="https://example.test/webhook"))

        self.assertFalse(result.ok)
        self.assertIn("Invalid n8n decision schema", result.error)

    def test_n8n_adapter_accepts_draft_response_wrapper(self):
        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "draft": {
                        "body": "Это короткий тестовый ответ.",
                        "reply_text": "Это короткий тестовый ответ.",
                    }
                }

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, *args, **kwargs):
                return FakeResponse()

        request = N8nAgentRequest(
            event_id="test:draft-wrapper",
            mode="sandbox",
            conversation={"id": 1},
            messages=[],
        )
        with patch("backend.n8n_agent.httpx.AsyncClient", FakeClient):
            result = asyncio.run(call_n8n_agent(request, webhook_url="https://example.test/webhook"))

        self.assertTrue(result.ok)
        self.assertTrue(result.decision.approved)
        self.assertEqual(result.decision.reply_text, "Это короткий тестовый ответ.")
        self.assertEqual(result.decision.reason, "draft_response")

    def test_n8n_adapter_accepts_output_with_booking_result_wrapper(self):
        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "output": {
                        "reply_text": "Назначил встречу на 09.05.2026, 15:00-15:40 МСК.",
                        "next_action": "booking_success",
                    },
                    "booking_result": {
                        "ok": True,
                        "booking_id": "4",
                        "start_at": "2026-05-09T15:00:00+03:00",
                        "duration_minutes": 40,
                        "calendar_event_id": "calendar-event-1",
                        "calendar_add_url": "https://calendar.google.com/calendar/render?action=TEMPLATE",
                        "zoom_meeting_id": "83274689727",
                        "zoom_join_url": "https://zoom.us/j/83274689727",
                    },
                    "reason": "Booking Agent created Google Calendar event and Zoom meeting.",
                }

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, *args, **kwargs):
                return FakeResponse()

        request = N8nAgentRequest(
            event_id="test:booking-wrapper",
            mode="sandbox",
            conversation={"id": 1},
            messages=[],
        )
        with patch("backend.n8n_agent.httpx.AsyncClient", FakeClient):
            result = asyncio.run(call_n8n_agent(request, webhook_url="https://example.test/webhook"))

        self.assertTrue(result.ok)
        self.assertTrue(result.decision.approved)
        self.assertEqual(result.decision.stage, "scheduling")
        self.assertEqual(result.decision.ops_action, "create_booking")
        self.assertEqual(result.decision.booking.start_at, "2026-05-09T15:00:00+03:00")
        self.assertEqual(result.decision.model_dump(mode="json")["booking"]["calendar_event_id"], "calendar-event-1")

    def test_n8n_adapter_accepts_busy_booking_wrapper_as_approved_reply(self):
        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "output": {
                        "reply_text": "Этот слот уже занят. Могу предложить: 09.05 16:00-16:40 МСК.",
                        "next_action": "ask_slot",
                    },
                    "booking_result": {
                        "ok": False,
                        "status": "busy",
                        "alternatives": ["09.05 16:00-16:40 МСК"],
                    },
                    "reason": "Booking Agent did not create a meeting.",
                }

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, *args, **kwargs):
                return FakeResponse()

        request = N8nAgentRequest(
            event_id="test:busy-booking-wrapper",
            mode="sandbox",
            conversation={"id": 1},
            messages=[],
        )
        with patch("backend.n8n_agent.httpx.AsyncClient", FakeClient):
            result = asyncio.run(call_n8n_agent(request, webhook_url="https://example.test/webhook"))

        self.assertTrue(result.ok)
        self.assertTrue(result.decision.approved)
        self.assertEqual(result.decision.stage, "scheduling")
        self.assertEqual(result.decision.intent, "availability_offer")
        self.assertEqual(result.decision.ops_action, "none")
        self.assertIn("Этот слот уже занят", result.decision.reply_text)

    def test_pipeline_answers_existing_meeting_status_without_calling_n8n(self):
        with self._db() as db:
            pipeline = AgentPipeline(
                id=47,
                name="n8n staging",
                type="n8n_webhook",
                status="active",
                config_json=json.dumps({"mode": "live", "webhook_url": "https://n8n.test/webhook"}),
            )
            conversation = Conversation(id=147, account_id=47, tg_user_id="747", status="active")
            user_message = Message(
                id=1471,
                conversation_id=147,
                role="user",
                text="ну и что там по встрече?",
                created_at=datetime(2026, 5, 8, 17, 6, tzinfo=ZoneInfo("Europe/Moscow")),
            )
            db.add(pipeline)
            db.add(conversation)
            db.add(user_message)
            db.add(
                ScheduledMeeting(
                    conversation_id=147,
                    status="scheduled",
                    scheduled_start=datetime(2026, 5, 9, 15, 0, tzinfo=ZoneInfo("Europe/Moscow")),
                    scheduled_end=datetime(2026, 5, 9, 15, 40, tzinfo=ZoneInfo("Europe/Moscow")),
                    timezone="Europe/Moscow",
                    calendar_add_url="https://calendar.google.com/calendar/render?action=TEMPLATE",
                    zoom_join_url="https://zoom.us/j/123456789",
                )
            )
            db.commit()

            with patch("backend.pipeline_runner.call_n8n_agent", AsyncMock()) as n8n_call:
                result = asyncio.run(
                    run_pipeline_for_auto_reply(
                        db,
                        pipeline=pipeline,
                        conversation=conversation,
                        messages=[user_message],
                        trigger_message_id=1471,
                    )
                )

            runs = db.query(AgentRun).filter(AgentRun.conversation_id == 147).all()

        n8n_call.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["engine"], "conversation_state_guard")
        self.assertIn("Да, всё стоит", result["reply_text"])
        self.assertIn("09.05.2026", result["reply_text"])
        self.assertIn("https://zoom.us/j/123456789", result["reply_text"])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, "succeeded")

    def test_pipeline_request_includes_latest_user_message_batch(self):
        captured_request = None

        async def fake_call(request, **kwargs):
            nonlocal captured_request
            captured_request = request
            return N8nAgentCallResult(
                ok=True,
                decision=N8nAgentDecision(
                    approved=True,
                    stage="qualification",
                    intent="other",
                    reply_text="Да, понял. Уточню по встрече.",
                ),
                raw_response={"draft": {"body": "Да, понял. Уточню по встрече."}},
                status_code=200,
            )

        with self._db() as db:
            pipeline = AgentPipeline(
                id=48,
                name="n8n staging",
                type="n8n_webhook",
                status="active",
                config_json=json.dumps({"mode": "live", "webhook_url": "https://n8n.test/webhook"}),
            )
            conversation = Conversation(id=1480, account_id=48, tg_user_id="748", status="active")
            messages = [
                Message(id=1481, conversation_id=1480, role="assistant", text="Когда удобно созвониться?"),
                Message(id=1482, conversation_id=1480, role="user", text="Завтра в 15"),
                Message(id=1483, conversation_id=1480, role="user", text="И пришли ссылку"),
            ]
            db.add(pipeline)
            db.add(conversation)
            db.add_all(messages)
            db.commit()

            with patch("backend.pipeline_runner.retrieve_dify_knowledge_cards", AsyncMock(return_value={
                "configured": False,
                "query": "",
                "cards": [],
                "error": "dify_not_configured",
            })):
                with patch("backend.pipeline_runner.call_n8n_agent", fake_call):
                    result = asyncio.run(
                        run_pipeline_for_auto_reply(
                            db,
                            pipeline=pipeline,
                            conversation=conversation,
                            messages=messages,
                            trigger_message_id=1483,
                        )
                    )

        self.assertTrue(result["ok"])
        self.assertIsNotNone(captured_request)
        latest_user_messages = captured_request.conversation_state["latest_user_messages"]
        self.assertEqual([item["text"] for item in latest_user_messages], ["Завтра в 15", "И пришли ссылку"])

    def test_agent_pipeline_smoke_auto_reply_uses_synthetic_messages_and_returns_send(self):
        app = FastAPI()
        app.include_router(agent_pipelines_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(
                AgentPipeline(
                    id=49,
                    name="n8n smoke",
                    type="n8n_webhook",
                    status="active",
                    config_json=json.dumps({"mode": "live", "webhook_url": "https://n8n.test/webhook"}),
                )
            )
            db.add(Conversation(id=149, account_id=49, tg_user_id="749", status="active"))
            db.add(Message(id=1491, conversation_id=149, role="assistant", text="Когда удобно созвониться?"))
            db.add(Message(id=1492, conversation_id=149, role="user", text="Старое неотвеченное сообщение"))
            db.commit()

        captured_request = None

        async def fake_call(request, **kwargs):
            nonlocal captured_request
            captured_request = request
            return N8nAgentCallResult(
                ok=True,
                decision=N8nAgentDecision(
                    approved=True,
                    stage="scheduling",
                    intent="availability_offer",
                    reply_text="Да, понял. Проверю по встрече.",
                    ops_action="none",
                ),
                raw_response={"draft": {"body": "Да, понял. Проверю по встрече."}},
                status_code=200,
            )

        client = TestClient(app)
        try:
            with patch("backend.pipeline_runner.retrieve_dify_knowledge_cards", AsyncMock(return_value={
                "configured": False,
                "query": "",
                "cards": [],
                "error": "dify_not_configured",
            })):
                with patch("backend.pipeline_runner.call_n8n_agent", fake_call):
                    response = client.post(
                        "/api/agent-pipelines/49/smoke-auto-reply",
                        json={
                            "conversation_id": 149,
                            "messages": ["Завтра в 15", "И пришли ссылку"],
                            "dry_run_tools": True,
                        },
                    )
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["verdict"], "SEND")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["synthetic_messages"], ["Завтра в 15", "И пришли ссылку"])
        self.assertEqual(payload["history_messages_count"], 2)
        self.assertEqual(payload["smoke_history_messages_count"], 1)
        self.assertEqual([item["text"] for item in captured_request.messages[-2:]], ["Завтра в 15", "И пришли ссылку"])
        self.assertNotIn("Старое неотвеченное сообщение", [item["text"] for item in captured_request.messages])
        self.assertEqual([item["text"] for item in captured_request.conversation_state["latest_user_messages"]], ["Завтра в 15", "И пришли ссылку"])
        with self._db() as db:
            persisted = db.query(Message).filter(Message.conversation_id == 149).all()
        self.assertEqual(len(persisted), 2)

    def test_agent_pipeline_smoke_auto_reply_returns_blocked_verdict(self):
        app = FastAPI()
        app.include_router(agent_pipelines_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(
                AgentPipeline(
                    id=50,
                    name="n8n smoke blocked",
                    type="n8n_webhook",
                    status="active",
                    config_json=json.dumps({"mode": "live", "webhook_url": "https://n8n.test/webhook"}),
                )
            )
            db.add(Conversation(id=150, account_id=50, tg_user_id="750", status="active"))
            db.add(Message(id=1501, conversation_id=150, role="assistant", text="Расскажите про опыт."))
            db.commit()

        decision = N8nAgentDecision(
            approved=False,
            stage="qualification",
            intent="other",
            reply_text="Тестовый ответ без approve.",
            ops_action="none",
        )
        client = TestClient(app)
        try:
            with patch("backend.pipeline_runner.retrieve_dify_knowledge_cards", AsyncMock(return_value={
                "configured": False,
                "query": "",
                "cards": [],
                "error": "dify_not_configured",
            })):
                with patch(
                    "backend.pipeline_runner.call_n8n_agent",
                    AsyncMock(return_value=N8nAgentCallResult(ok=True, decision=decision, raw_response=decision.model_dump(mode="json"), status_code=200)),
                ):
                    response = client.post(
                        "/api/agent-pipelines/50/smoke-auto-reply",
                        json={"conversation_id": 150, "messages": ["что дальше?"]},
                    )
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["verdict"], "BLOCKED")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["policy_issues"], ["decision_not_approved"])

    def test_agent_pipeline_crud_and_campaign_assignment(self):
        app = FastAPI()
        app.include_router(agent_pipelines_router.router)
        app.include_router(campaigns_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(Account(id=39, name="Ana", phone="+573122997139", app_id="2040", app_hash="hash"))
            db.commit()

        client = TestClient(app)
        try:
            pipeline_response = client.post("/api/agent-pipelines/", json={
                "name": "n8n HR agent",
                "type": "n8n_webhook",
                "status": "active",
                "config": {"mode": "live", "webhook_url": "https://n8n.test/webhook", "shared_secret": "secret"},
            })
            pipeline_id = pipeline_response.json()["id"]
            campaign_response = client.post("/api/campaigns/", json={
                "name": "Pipeline campaign",
                "account_ids": [39],
                "messages": ["hi"],
                "targets": ["lead_user"],
                "agent_pipeline_id": pipeline_id,
            })
            campaigns_response = client.get("/api/campaigns/")
        finally:
            client.close()

        self.assertEqual(pipeline_response.status_code, 200)
        self.assertEqual(pipeline_response.json()["config"]["shared_secret"], "")
        self.assertTrue(pipeline_response.json()["config"]["shared_secret_configured"])
        self.assertEqual(campaign_response.status_code, 200)
        self.assertEqual(campaigns_response.json()[0]["agent_pipeline_id"], pipeline_id)
        self.assertEqual(campaigns_response.json()[0]["agent_pipeline_name"], "n8n HR agent")

    def test_create_campaign_rejects_sandbox_agent_pipeline(self):
        app = FastAPI()
        app.include_router(campaigns_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(Account(id=404, name="Ana", phone="+573122997404", app_id="2040", app_hash="hash"))
            db.add(
                AgentPipeline(
                    id=404,
                    name="Sandbox pipeline",
                    type="n8n_webhook",
                    status="active",
                    config_json=json.dumps({"mode": "sandbox", "webhook_url": "https://n8n.test/webhook"}),
                )
            )
            db.commit()

        client = TestClient(app)
        try:
            response = client.post("/api/campaigns/", json={
                "name": "Bad pipeline campaign",
                "account_ids": [404],
                "messages": ["hi"],
                "targets": ["lead_user"],
                "agent_pipeline_id": 404,
            })
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 400)
        self.assertIn("must be live", response.json()["detail"])

    def test_start_campaign_rejects_existing_sandbox_agent_pipeline_before_worker_call(self):
        app = FastAPI()
        app.include_router(campaigns_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(Account(id=405, name="Ana", phone="+573122997405", app_id="2040", app_hash="hash"))
            db.add(
                AgentPipeline(
                    id=405,
                    name="Sandbox pipeline",
                    type="n8n_webhook",
                    status="active",
                    config_json=json.dumps({"mode": "sandbox", "webhook_url": "https://n8n.test/webhook"}),
                )
            )
            db.add(
                Campaign(
                    id=405,
                    name="Existing bad campaign",
                    account_id=405,
                    account_ids="[405]",
                    messages='["hi"]',
                    status="draft",
                    agent_pipeline_id=405,
                )
            )
            db.commit()

        client = TestClient(app)
        try:
            with patch("backend.routers.campaigns.owns_telegram_runtime", return_value=False):
                with patch("backend.routers.campaigns.forward_to_worker", AsyncMock()) as forward:
                    response = client.post("/api/campaigns/405/start")
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 400)
        self.assertIn("must be live", response.json()["detail"])
        self.assertEqual(forward.await_count, 0)

    def test_campaigns_are_scoped_by_project(self):
        app = FastAPI()
        app.include_router(projects_router.router)
        app.include_router(campaigns_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(Account(id=401, name="Ana", phone="+573122997401", app_id="2040", app_hash="hash"))
            db.add(Project(id=10, name="HR Discovery", status="active"))
            db.add(Project(id=11, name="Founder Research", status="active"))
            db.commit()

        client = TestClient(app)
        try:
            response_a = client.post("/api/campaigns/", json={
                "name": "Project A campaign",
                "project_id": 10,
                "account_ids": [401],
                "messages": ["hi"],
                "targets": ["lead_a"],
            })
            response_b = client.post("/api/campaigns/", json={
                "name": "Project B campaign",
                "project_id": 11,
                "account_ids": [401],
                "messages": ["hi"],
                "targets": ["lead_b"],
            })
            campaigns_a = client.get("/api/campaigns/?project_id=10")
            campaigns_b = client.get("/api/campaigns/?project_id=11")
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response_a.status_code, 200)
        self.assertEqual(response_b.status_code, 200)
        self.assertEqual([c["name"] for c in campaigns_a.json()], ["Project A campaign"])
        self.assertEqual([c["name"] for c in campaigns_b.json()], ["Project B campaign"])
        self.assertEqual(campaigns_a.json()[0]["project_id"], 10)

    def test_delete_campaign_detaches_conversations_and_removes_targets(self):
        app = FastAPI()
        app.include_router(campaigns_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(Account(id=403, name="Ana", phone="+573122997403", app_id="2040", app_hash="hash"))
            db.add(
                Campaign(
                    id=88,
                    name="Old campaign",
                    account_id=403,
                    account_ids="[403]",
                    messages='["hi"]',
                    status="done",
                )
            )
            db.add(CampaignTarget(campaign_id=88, username="lead_user", status="sent", account_id=403))
            db.add(Conversation(id=188, account_id=403, tg_user_id="488", tg_username="lead_user", source_campaign_id=88))
            db.commit()

        client = TestClient(app)
        try:
            with patch("backend.routers.campaigns.tg.stop_campaign", AsyncMock()):
                response = client.delete("/api/campaigns/88")
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200, response.text)
        with self._db() as db:
            conv = db.query(Conversation).filter(Conversation.id == 188).first()
            self.assertIsNotNone(conv)
            self.assertIsNone(conv.source_campaign_id)
            self.assertIsNone(db.query(Campaign).filter(Campaign.id == 88).first())
            self.assertEqual(db.query(CampaignTarget).filter(CampaignTarget.campaign_id == 88).count(), 0)

    def test_project_can_link_global_account_and_proxy(self):
        app = FastAPI()
        app.include_router(projects_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(Project(id=20, name="HR Discovery", status="active"))
            db.add(Account(id=402, name="Shared account", phone="+573122997402", app_id="2040", app_hash="hash"))
            db.add(ProxyPool(id=30, label="Shared proxy", host="127.0.0.1", port=1080, proxy_type="SOCKS5"))
            db.commit()

        client = TestClient(app)
        try:
            account_link = client.post("/api/projects/20/accounts/402/attach")
            proxy_link = client.post("/api/projects/20/proxies/30/attach")
            resources = client.get("/api/projects/20/resources")
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(account_link.status_code, 200)
        self.assertEqual(proxy_link.status_code, 200)
        self.assertEqual(resources.json()["accounts"][0]["id"], 402)
        self.assertEqual(resources.json()["proxies"][0]["id"], 30)
        with self._db() as db:
            self.assertEqual(db.query(ProjectAccount).count(), 1)
            self.assertEqual(db.query(ProjectProxy).count(), 1)

    def test_install_n8n_workflow_syncs_registry_settings_and_assigns_accounts(self):
        app = FastAPI()
        app.include_router(agent_pipelines_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        registry_rows = [
            ("N8N_BASE_URL", "https://n8n.test", False),
            ("N8N_API_KEY", "n8n-secret-key", True),
            ("OPENAI_PROVIDER", "openai", False),
            ("OPENAI_MODEL_DEFAULT", "gpt-5.4-mini", False),
            ("OPENAI_API_KEY", "sk-proj-registry-secret", True),
            ("GOOGLE_CLIENT_ID", "google-client-id", False),
            ("GOOGLE_CLIENT_SECRET", "google-client-secret", True),
            ("GOOGLE_REDIRECT_URI_STAGING", "https://tg.test/api/integrations/google/callback", False),
            ("GOOGLE_OAUTH_STATE_SECRET", "google-state-secret", True),
            ("GOOGLE_CALENDAR_EMAIL", "ops@example.com", False),
            ("ZOOM_ACCOUNT_ID", "zoom-account", False),
            ("ZOOM_CLIENT_ID", "zoom-client", False),
            ("ZOOM_CLIENT_SECRET", "zoom-secret", True),
            ("ZOOM_HOST_EMAIL", "ops@example.com", False),
        ]
        with self._db() as db:
            for key, value, is_secret in registry_rows:
                db.add(
                    AgentRuntimeConfigRegistry(
                        environment="staging",
                        project_key="tg-outreach",
                        scope="runtime",
                        key=key,
                        value=value,
                        is_secret=is_secret,
                        source="test",
                        status="active",
                    )
                )
            db.add(Account(id=501, name="Ana", phone="+573122997501", app_id="2040", app_hash="hash"))
            db.commit()

        workflow = {
            "id": "exported-id",
            "name": "HR Discovery",
            "active": False,
            "nodes": [
                {
                    "id": "hook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "hr-discovery-agent"},
                }
            ],
            "connections": {},
        }
        calls = []

        async def fake_n8n_request(**kwargs):
            calls.append(kwargs)
            if kwargs["method"] == "POST" and kwargs["path"] == "workflows":
                self.assertNotIn("id", kwargs["json_body"])
                self.assertNotIn("active", kwargs["json_body"])
                return {"id": "wf-installed", "name": kwargs["json_body"]["name"], "nodes": kwargs["json_body"]["nodes"]}
            if kwargs["method"] == "POST" and kwargs["path"] == "workflows/wf-installed/activate":
                return {"ok": True}
            self.fail(f"unexpected n8n request: {kwargs}")

        client = TestClient(app)
        try:
            with patch("backend.agent_pipeline_installer.n8n_request", fake_n8n_request):
                response = client.post(
                    "/api/agent-pipelines/n8n/install",
                    json={
                        "workflow": workflow,
                        "project_id": None,
                        "mode": "live",
                        "status": "active",
                        "assign_account_ids": [501],
                        "registry_environment": "staging",
                        "registry_project_key": "tg-outreach",
                    },
                )
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["workflow"]["id"], "wf-installed")
        self.assertTrue(payload["workflow"]["activated"])
        self.assertEqual(payload["workflow"]["webhook_url"], "https://n8n.test/webhook/hr-discovery-agent")
        self.assertEqual(payload["pipeline"]["status"], "active")
        self.assertEqual(payload["pipeline"]["config"]["workflow_id"], "wf-installed")
        self.assertEqual(payload["pipeline"]["config"]["mode"], "live")
        self.assertEqual(payload["assigned_account_ids"], [501])
        self.assertTrue(payload["settings_sync"]["OPENAI_API_KEY"]["configured"])
        response_text = json.dumps(payload)
        self.assertNotIn("sk-proj-registry-secret", response_text)
        self.assertNotIn("n8n-secret-key", response_text)
        self.assertEqual([call["path"] for call in calls], ["workflows", "workflows/wf-installed/activate"])

        with self._db() as db:
            settings = db.query(Settings).filter(Settings.id == 1).one()
            account = db.query(Account).filter(Account.id == 501).one()
            self.assertEqual(settings.provider, "openai")
            self.assertEqual(settings.model, "gpt-5.4-mini")
            self.assertEqual(decrypt_value(settings.openai_key), "sk-proj-registry-secret")
            self.assertEqual(settings.google_client_id, "google-client-id")
            self.assertEqual(decrypt_value(settings.google_client_secret), "google-client-secret")
            self.assertEqual(settings.google_redirect_uri, "https://tg.test/api/integrations/google/callback")
            self.assertEqual(decrypt_value(settings.google_oauth_state_secret), "google-state-secret")
            self.assertEqual(settings.zoom_client_id, "zoom-client")
            self.assertEqual(decrypt_value(settings.zoom_client_secret), "zoom-secret")
            self.assertEqual(account.agent_pipeline_id, payload["pipeline"]["id"])

    def test_install_n8n_workflow_rejects_hardcoded_secret_values(self):
        app = FastAPI()
        app.include_router(agent_pipelines_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        workflow = {
            "name": "Unsafe workflow",
            "nodes": [
                {
                    "id": "hook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "unsafe-agent", "apiKey": "sk-proj-hardcoded-secret-value"},
                }
            ],
        }
        client = TestClient(app)
        try:
            response = client.post(
                "/api/agent-pipelines/n8n/install",
                json={
                    "workflow": workflow,
                    "n8n_base_url": "https://n8n.test",
                    "n8n_api_key": "n8n-secret-key",
                    "registry_environment": "staging",
                    "registry_project_key": "tg-outreach",
                },
            )
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 400)
        self.assertIn("hardcoded secret", response.json()["detail"])

    def test_bind_n8n_workflow_updates_pipeline_config(self):
        app = FastAPI()
        app.include_router(agent_pipelines_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(AgentPipeline(id=44, name="Bindable", type="n8n_webhook", status="active", config_json="{}"))
            db.commit()

        workflow = {
            "id": "wf_1",
            "name": "Auto reply workflow",
            "nodes": [
                {
                    "id": "hook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "auto-reply-orchestrator"},
                }
            ],
        }
        client = TestClient(app)
        try:
            response = client.post("/api/agent-pipelines/44/bind-n8n-workflow", json={
                "base_url": "http://localhost:5678",
                "api_key": "test-key",
                "workflow_id": "wf_1",
                "workflow": workflow,
                "mode": "live",
                "shared_secret": "secret",
            })
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["config"]["workflow_id"], "wf_1")
        self.assertEqual(payload["config"]["workflow_name"], "Auto reply workflow")
        self.assertEqual(payload["config"]["webhook_url"], "http://localhost:5678/webhook/auto-reply-orchestrator")
        self.assertEqual(payload["config"]["workflow_editor_url"], "http://localhost:5678/workflow/wf_1")
        self.assertEqual(payload["config"]["shared_secret"], "")
        self.assertTrue(payload["config"]["shared_secret_configured"])

    def test_list_n8n_workflows_from_registry_uses_runtime_connection_without_leaking_api_key(self):
        app = FastAPI()
        app.include_router(agent_pipelines_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(
                AgentRuntimeConfigRegistry(
                    environment="staging",
                    project_key="tg-outreach",
                    scope="n8n",
                    key="N8N_BASE_URL",
                    value="https://n8n.test",
                    is_secret=False,
                    status="active",
                )
            )
            db.add(
                AgentRuntimeConfigRegistry(
                    environment="staging",
                    project_key="tg-outreach",
                    scope="n8n",
                    key="N8N_API_KEY",
                    value="n8n-secret-key",
                    is_secret=True,
                    status="active",
                )
            )
            db.commit()

        calls = []

        async def fake_n8n_request(**kwargs):
            calls.append(kwargs)
            self.assertEqual(kwargs["base_url"], "https://n8n.test")
            self.assertEqual(kwargs["api_key"], "n8n-secret-key")
            return {
                "data": [
                    {
                        "id": "wf-active",
                        "name": "HR Discovery Agent",
                        "active": True,
                        "nodes": [
                            {
                                "type": "n8n-nodes-base.webhook",
                                "parameters": {"path": "hr-discovery"},
                            }
                        ],
                    }
                ]
            }

        client = TestClient(app)
        try:
            with patch("backend.routers.agent_pipelines.n8n_request", fake_n8n_request):
                response = client.post(
                    "/api/agent-pipelines/n8n/workflows/from-registry",
                    json={"registry_environment": "staging", "registry_project_key": "tg-outreach"},
                )
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["n8n"]["base_url"], "https://n8n.test")
        self.assertNotIn("n8n-secret-key", json.dumps(payload))
        self.assertEqual(payload["workflows"][0]["id"], "wf-active")
        self.assertEqual(payload["workflows"][0]["webhook_path"], "hr-discovery")
        self.assertEqual(payload["workflows"][0]["webhook_url"], "https://n8n.test/webhook/hr-discovery")
        self.assertTrue(payload["workflows"][0]["active"])
        self.assertEqual(calls[0]["path"], "workflows")

    def test_list_n8n_workflows_from_registry_uses_railway_n8n_url_fallback(self):
        app = FastAPI()
        app.include_router(agent_pipelines_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(
                AgentRuntimeConfigRegistry(
                    environment="staging",
                    project_key="tg-outreach",
                    scope="n8n",
                    key="N8N_API_KEY",
                    value="n8n-secret-key",
                    is_secret=True,
                    status="active",
                )
            )
            db.commit()

        async def fake_n8n_request(**kwargs):
            self.assertEqual(kwargs["base_url"], "https://n8n-staging.test")
            self.assertEqual(kwargs["api_key"], "n8n-secret-key")
            return {"data": []}

        client = TestClient(app)
        try:
            with patch.dict(os.environ, {"RAILWAY_SERVICE_N8N_URL": "https://n8n-staging.test"}):
                with patch("backend.routers.agent_pipelines.n8n_request", fake_n8n_request):
                    response = client.post(
                        "/api/agent-pipelines/n8n/workflows/from-registry",
                        json={"registry_environment": "staging", "registry_project_key": "tg-outreach"},
                    )
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["n8n"]["base_url_source"], "env:RAILWAY_SERVICE_N8N_URL")

    def test_list_n8n_workflows_from_registry_normalizes_railway_n8n_url_without_protocol(self):
        app = FastAPI()
        app.include_router(agent_pipelines_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(
                AgentRuntimeConfigRegistry(
                    environment="staging",
                    project_key="tg-outreach",
                    scope="n8n",
                    key="N8N_API_KEY",
                    value="n8n-secret-key",
                    is_secret=True,
                    status="active",
                )
            )
            db.commit()

        async def fake_n8n_request(**kwargs):
            self.assertEqual(kwargs["base_url"], "https://n8n-staging.test")
            return {"data": []}

        client = TestClient(app)
        try:
            with patch.dict(os.environ, {"RAILWAY_SERVICE_N8N_URL": "n8n-staging.test"}):
                with patch("backend.routers.agent_pipelines.n8n_request", fake_n8n_request):
                    response = client.post(
                        "/api/agent-pipelines/n8n/workflows/from-registry",
                        json={"registry_environment": "staging", "registry_project_key": "tg-outreach"},
                    )
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["n8n"]["base_url"], "https://n8n-staging.test")

    def test_list_n8n_workflows_from_registry_returns_setup_status_when_api_key_missing(self):
        app = FastAPI()
        app.include_router(agent_pipelines_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(
                AgentRuntimeConfigRegistry(
                    environment="staging",
                    project_key="tg-outreach",
                    scope="n8n",
                    key="N8N_BASE_URL",
                    value="https://n8n.test",
                    status="active",
                )
            )
            db.commit()

        client = TestClient(app)
        try:
            response = client.post(
                "/api/agent-pipelines/n8n/workflows/from-registry",
                json={"registry_environment": "staging", "registry_project_key": "tg-outreach"},
            )
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["setup_required"])
        self.assertEqual(payload["missing"], ["N8N_API_KEY"])
        self.assertEqual(payload["n8n"]["base_url"], "https://n8n.test")
        self.assertFalse(payload["n8n"]["api_key_configured"])
        self.assertEqual(payload["workflows"], [])

    def test_connect_existing_n8n_workflow_runs_smoke_test_before_creating_pipeline(self):
        app = FastAPI()
        app.include_router(agent_pipelines_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            for key, value, is_secret in [
                ("N8N_BASE_URL", "https://n8n.test", False),
                ("N8N_API_KEY", "n8n-secret-key", True),
            ]:
                db.add(
                    AgentRuntimeConfigRegistry(
                        environment="staging",
                        project_key="tg-outreach",
                        scope="n8n",
                        key=key,
                        value=value,
                        is_secret=is_secret,
                        status="active",
                    )
                )
            db.commit()

        async def fake_n8n_request(**kwargs):
            self.assertEqual(kwargs["path"], "workflows/wf-active")
            return {
                "id": "wf-active",
                "name": "HR Discovery Agent",
                "active": True,
                "nodes": [
                    {
                        "type": "n8n-nodes-base.webhook",
                        "parameters": {"path": "hr-discovery"},
                    }
                ],
            }

        decision = N8nAgentDecision(
            approved=True,
            stage="qualification",
            intent="trust_question",
            reply_text="Это короткий тестовый ответ.",
            ops_action="none",
        )

        client = TestClient(app)
        try:
            with patch("backend.routers.agent_pipelines.n8n_request", fake_n8n_request):
                with patch(
                    "backend.routers.agent_pipelines.call_n8n_agent",
                    AsyncMock(return_value=N8nAgentCallResult(ok=True, decision=decision, raw_response=decision.model_dump(mode="json"), status_code=200)),
                ) as smoke:
                    response = client.post(
                        "/api/agent-pipelines/n8n/workflows/connect",
                        json={
                            "workflow_id": "wf-active",
                            "project_id": None,
                            "mode": "sandbox",
                            "status": "active",
                            "registry_environment": "staging",
                            "registry_project_key": "tg-outreach",
                        },
                    )
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["smoke_test"]["status"], "passed")
        self.assertEqual(payload["pipeline"]["config"]["workflow_id"], "wf-active")
        self.assertEqual(payload["pipeline"]["config"]["workflow_name"], "HR Discovery Agent")
        self.assertEqual(payload["pipeline"]["config"]["webhook_url"], "https://n8n.test/webhook/hr-discovery")
        self.assertEqual(payload["pipeline"]["config"]["last_smoke_test_status"], "passed")
        self.assertEqual(payload["pipeline"]["config"]["mode"], "sandbox")
        self.assertEqual(smoke.await_args.kwargs["webhook_url"], "https://n8n.test/webhook/hr-discovery")
        self.assertEqual(smoke.await_args.args[0].messages[0]["text"], "Что за продукт?")

    def test_connect_existing_n8n_workflow_rejects_invalid_smoke_response(self):
        app = FastAPI()
        app.include_router(agent_pipelines_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(AgentRuntimeConfigRegistry(environment="staging", project_key="tg-outreach", scope="n8n", key="N8N_BASE_URL", value="https://n8n.test", status="active"))
            db.add(AgentRuntimeConfigRegistry(environment="staging", project_key="tg-outreach", scope="n8n", key="N8N_API_KEY", value="n8n-secret-key", is_secret=True, status="active"))
            db.commit()

        async def fake_n8n_request(**kwargs):
            return {
                "id": "wf-active",
                "name": "Broken Agent",
                "active": True,
                "nodes": [{"type": "n8n-nodes-base.webhook", "parameters": {"path": "broken-agent"}}],
            }

        decision = N8nAgentDecision(approved=True, stage="qualification", intent="other", reply_text="", ops_action="none")
        client = TestClient(app)
        try:
            with patch("backend.routers.agent_pipelines.n8n_request", fake_n8n_request):
                with patch("backend.routers.agent_pipelines.call_n8n_agent", AsyncMock(return_value=N8nAgentCallResult(ok=True, decision=decision))):
                    response = client.post(
                        "/api/agent-pipelines/n8n/workflows/connect",
                        json={
                            "workflow_id": "wf-active",
                            "registry_environment": "staging",
                            "registry_project_key": "tg-outreach",
                        },
                    )
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 400)
        self.assertIn("empty reply_text", response.json()["detail"])

    def test_connect_existing_n8n_workflow_rejects_inactive_workflow(self):
        app = FastAPI()
        app.include_router(agent_pipelines_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self._db() as db:
            db.add(AgentRuntimeConfigRegistry(environment="staging", project_key="tg-outreach", scope="n8n", key="N8N_BASE_URL", value="https://n8n.test", status="active"))
            db.add(AgentRuntimeConfigRegistry(environment="staging", project_key="tg-outreach", scope="n8n", key="N8N_API_KEY", value="n8n-secret-key", is_secret=True, status="active"))
            db.commit()

        async def fake_n8n_request(**kwargs):
            return {
                "id": "wf-inactive",
                "name": "Inactive Agent",
                "active": False,
                "nodes": [{"type": "n8n-nodes-base.webhook", "parameters": {"path": "inactive-agent"}}],
            }

        client = TestClient(app)
        try:
            with patch("backend.routers.agent_pipelines.n8n_request", fake_n8n_request):
                response = client.post(
                    "/api/agent-pipelines/n8n/workflows/connect",
                    json={
                        "workflow_id": "wf-inactive",
                        "registry_environment": "staging",
                        "registry_project_key": "tg-outreach",
                    },
                )
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 400)
        self.assertIn("must be active", response.json()["detail"])

    def test_auto_reply_uses_active_agent_pipeline_instead_of_legacy_prompt(self):
        with self._db() as db:
            db.add(Settings(id=1, provider="openai", openai_key="", model="gpt-4o-mini", auto_reply_enabled=True, context_messages=10))
            db.add(Account(id=40, name="Ana", phone="+573122997140", app_id="2040", app_hash="hash", auto_reply=True))
            db.add(
                AgentPipeline(
                    id=41,
                    name="Live pipeline",
                    type="n8n_webhook",
                    status="active",
                    config_json=json.dumps({"mode": "live", "webhook_url": "https://n8n.test/webhook"}),
                )
            )
            db.add(
                Campaign(
                    id=42,
                    name="Pipeline campaign",
                    account_id=40,
                    account_ids="[40]",
                    messages='["hi"]',
                    status="running",
                    agent_pipeline_id=41,
                )
            )
            db.add(Conversation(id=143, account_id=40, tg_user_id="443", tg_first_name="Lead", source_campaign_id=42))
            db.add(Message(id=144, conversation_id=143, role="user", text="Да, интересно."))
            db.commit()

        decision = N8nAgentDecision(
            approved=True,
            stage="qualification",
            intent="other",
            reply_text="Отлично, расскажу коротко и предложу пару слотов.",
            ops_action="none",
        )
        with patch("backend.telegram_client.SessionLocal", self.Session):
            with patch("backend.telegram_client.asyncio.sleep", AsyncMock()):
                with patch("backend.pipeline_runner.call_n8n_agent", AsyncMock(return_value=N8nAgentCallResult(ok=True, decision=decision, raw_response=decision.model_dump(mode="json")))):
                    with patch("backend.gpt_handler.generate_reply", AsyncMock(return_value="legacy reply")) as generate:
                        with patch("backend.telegram_client.send_manual_message", AsyncMock(return_value={"ok": True})) as send:
                            asyncio.run(
                                tg._run_scheduled_auto_reply(
                                    account_id=40,
                                    conversation_id=143,
                                    tg_user_id="443",
                                    trigger_message_id=144,
                                    delay_s=0.0,
                                    scheduled_at=tg._utcnow(),
                                )
                            )

        self.assertEqual(generate.await_count, 0)
        self.assertEqual(send.await_count, 1)
        self.assertEqual(send.await_args.args[3], "Отлично, расскажу коротко и предложу пару слотов.")

    def test_agent_pipeline_uses_production_webhook_url_from_imported_config(self):
        with self._db() as db:
            pipeline = AgentPipeline(
                id=145,
                name="Imported n8n pipeline",
                type="n8n_webhook",
                status="active",
                config_json=json.dumps({
                    "mode": "live",
                    "production_webhook_url": "https://n8n.test/webhook/imported",
                }),
            )
            conversation = Conversation(id=146, account_id=40, tg_user_id="446", tg_first_name="Lead")
            message = Message(id=147, conversation_id=146, role="user", text="Да, интересно.")
            db.add_all([pipeline, conversation, message])
            db.commit()

            decision = N8nAgentDecision(
                approved=True,
                stage="qualification",
                intent="other",
                reply_text="Отлично, договоримся о времени.",
                ops_action="none",
            )
            with patch("backend.pipeline_runner.call_n8n_agent", AsyncMock(return_value=N8nAgentCallResult(ok=True, decision=decision, raw_response=decision.model_dump(mode="json")))) as call:
                result = asyncio.run(
                    run_pipeline_for_auto_reply(
                        db,
                        pipeline=pipeline,
                        conversation=conversation,
                        messages=[message],
                        trigger_message_id=147,
                    )
                )

        self.assertTrue(result["ok"])
        self.assertEqual(call.await_args.kwargs["webhook_url"], "https://n8n.test/webhook/imported")

    def test_agent_pipeline_payload_includes_active_scenario_cards(self):
        with self._db() as db:
            pipeline = AgentPipeline(
                id=149,
                name="Scenario-aware n8n pipeline",
                type="n8n_webhook",
                status="active",
                config_json=json.dumps({"mode": "live", "webhook_url": "https://n8n.test/webhook"}),
            )
            conversation = Conversation(id=150, account_id=40, tg_user_id="450", tg_first_name="Lead")
            message = Message(id=151, conversation_id=150, role="user", text="А что мне будет?")
            db.add_all([pipeline, conversation, message])
            db.add(
                ScenarioCard(
                    title="Личная польза от интервью",
                    intent="value_question",
                    trigger_summary="Спрашивают, что собеседник получит за участие.",
                    recommended_reply="Коротко назвать личную пользу без повторного питча.",
                    avoid_reply="Не повторять длинное описание исследования.",
                    status="active",
                    tags="value,benefit,получит",
                )
            )
            db.commit()

            decision = N8nAgentDecision(
                approved=True,
                stage="qualification",
                intent="other",
                reply_text="Коротко: пришлю итог по паттернам после интервью.",
                ops_action="none",
            )
            with patch("backend.pipeline_runner.call_n8n_agent", AsyncMock(return_value=N8nAgentCallResult(ok=True, decision=decision, raw_response=decision.model_dump(mode="json")))) as call:
                result = asyncio.run(
                    run_pipeline_for_auto_reply(
                        db,
                        pipeline=pipeline,
                        conversation=conversation,
                        messages=[message],
                        trigger_message_id=151,
                    )
                )

        self.assertTrue(result["ok"])
        request = call.await_args.args[0]
        self.assertEqual(request.scenario_cards[0]["intent"], "value_question")
        self.assertIn("Коротко назвать", request.scenario_cards[0]["recommended_reply"])

    def test_dify_retriever_normalizes_retrieve_records(self):
        from backend.dify_retriever import DifyRetrievalConfig, retrieve_dify_knowledge_cards

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "records": [
                        {
                            "score": 0.78,
                            "segment": {
                                "id": "seg-1",
                                "content": "## Как отвечать\nКоротко объяснить личную пользу.",
                                "document": {"id": "doc-1", "name": "value-question.md"},
                            },
                        }
                    ]
                }

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, url, headers=None, json=None):
                self.url = url
                self.headers = headers
                self.payload = json
                return FakeResponse()

        config = DifyRetrievalConfig(
            api_base_url="https://dify.test/v1",
            api_key="dataset-key",
            dataset_id="dataset-1",
            timeout_s=3,
        )
        with patch("backend.dify_retriever.httpx.AsyncClient", FakeClient):
            result = asyncio.run(retrieve_dify_knowledge_cards("А что мне будет?", config=config, top_k=3))

        self.assertIsNone(result["error"])
        self.assertEqual(result["query"], "А что мне будет?")
        self.assertEqual(result["cards"][0]["source"], "dify")
        self.assertEqual(result["cards"][0]["score"], 0.78)
        self.assertEqual(result["cards"][0]["title"], "value-question.md")
        self.assertIn("личную пользу", result["cards"][0]["content"])

    def test_agent_pipeline_payload_includes_dify_knowledge_cards(self):
        with self._db() as db:
            pipeline = AgentPipeline(
                id=154,
                name="Dify-aware n8n pipeline",
                type="n8n_webhook",
                status="active",
                config_json=json.dumps({"mode": "live", "webhook_url": "https://n8n.test/webhook"}),
            )
            conversation = Conversation(id=155, account_id=40, tg_user_id="455", tg_first_name="Lead")
            older = Message(id=156, conversation_id=155, role="assistant", text="Это исследование про найм.")
            latest = Message(id=157, conversation_id=155, role="user", text="А что я за это получу?")
            db.add_all([pipeline, conversation, older, latest])
            db.commit()

            decision = N8nAgentDecision(
                approved=True,
                stage="qualification",
                intent="other",
                reply_text="Личная польза — краткий итог исследования после серии интервью.",
                ops_action="none",
            )
            dify_result = {
                "query": "Последнее сообщение пользователя:\nА что я за это получу?",
                "cards": [
                    {
                        "source": "dify",
                        "title": "value-question.md",
                        "score": 0.82,
                        "content": "Коротко объяснить личную пользу, не повторять длинный питч.",
                        "document_id": "doc-1",
                        "segment_id": "seg-1",
                    }
                ],
                "error": None,
                "configured": True,
            }
            with patch("backend.pipeline_runner.retrieve_dify_knowledge_cards", AsyncMock(return_value=dify_result)) as retrieve:
                with patch("backend.pipeline_runner.call_n8n_agent", AsyncMock(return_value=N8nAgentCallResult(ok=True, decision=decision, raw_response=decision.model_dump(mode="json")))) as call:
                    result = asyncio.run(
                        run_pipeline_for_auto_reply(
                            db,
                            pipeline=pipeline,
                            conversation=conversation,
                            messages=[older, latest],
                            trigger_message_id=157,
                        )
                    )

        self.assertTrue(result["ok"])
        retrieve.assert_awaited_once()
        self.assertIn("А что я за это получу?", retrieve.await_args.args[0])
        request = call.await_args.args[0]
        self.assertEqual(request.knowledge_cards[0]["source"], "dify")
        self.assertIn("личную пользу", request.knowledge_cards[0]["content"])
        self.assertEqual(request.settings["knowledge"]["source"], "dify")
        self.assertEqual(request.settings["knowledge"]["cards_count"], 1)

    def test_dify_retrieval_query_strips_long_urls(self):
        from backend.pipeline_runner import _dify_retrieval_query

        long_url = "https://calendar.google.com/calendar/render?action=TEMPLATE&text=" + ("a" * 2000)
        query = _dify_retrieval_query([
            {"role": "user", "text": "Окей понял! Ладно я готов, можем назначить созвон"},
            {"role": "assistant", "text": "Отлично. Тогда напишите, пожалуйста, 2–3 удобных окна по Москве, и я подстроюсь."},
            {"role": "user", "text": "Давай завтра на 4"},
            {"role": "assistant", "text": "В это время слот уже занят. Свободные альтернативы: 28.04 18:15-18:45 МСК, 28.04 19:00-19:30 МСК, 28.04 19:45-20:15 МСК."},
            {"role": "assistant", "text": f"Добавьте событие в календарь: {long_url}"},
            {"role": "user", "text": "А что я за это получу?"},
        ])

        self.assertIn("А что я за это получу?", query)
        self.assertIn("[link]", query)
        self.assertNotIn(long_url, query)
        self.assertLessEqual(len(query), 250)

    def test_list_campaigns_reports_runtime_task_state(self):
        with self._db() as db:
            db.add(
                Campaign(
                    id=60,
                    name="Runtime truth",
                    account_id=1,
                    account_ids="[1]",
                    messages='["hi"]',
                    status="running",
                )
            )
            db.commit()

        app = FastAPI()
        app.include_router(campaigns_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            with patch("backend.routers.campaigns.owns_telegram_runtime", return_value=True):
                with patch("backend.routers.campaigns.tg.campaign_is_running", return_value=False):
                    response = client.get("/api/campaigns/")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
        finally:
            client.close()
            app.dependency_overrides.clear()

        self.assertEqual(payload[0]["status"], "running")
        self.assertFalse(payload[0]["is_running"])

    def test_serialize_account_returns_simple_public_status(self):
        account = Account(
            id=14,
            name="Ana",
            phone="+573122997092",
            app_id="2040",
            app_hash="hash",
            auto_reply=True,
        )
        account.connection_state = "online"
        account.proxy_state = "ok"
        account.session_state = "valid"
        account.eligibility_state = "eligible"
        tg._clients[14] = object()

        payload = accounts_router._serialize_account(account)

        self.assertEqual(payload["status"], "working")
        self.assertTrue(payload["is_online"])
        self.assertTrue(payload["can_receive"])
        self.assertTrue(payload["can_auto_reply"])
        self.assertTrue(payload["can_start_outreach"])
        self.assertEqual(payload["connection_state"], "online")
        self.assertEqual(payload["eligibility_state"], "eligible")

    def test_public_status_ignores_transient_outgoing_limits(self):
        for code, message in (
            ("PEER_FLOOD", "Telegram временно ограничил исходящие"),
            ("FLOOD_WAIT", "FloodWait 600s"),
        ):
            account = Account(
                id=15,
                name="Ana",
                phone="+573122997093",
                app_id="2040",
                app_hash="hash",
                auto_reply=True,
            )
            account.connection_state = "online"
            account.proxy_state = "ok"
            account.session_state = "valid"
            account.eligibility_state = "eligible"
            account.last_error_code = code
            account.last_error_message = message
            tg._clients[15] = object()

            payload = accounts_router._serialize_account(account)

            self.assertEqual(payload["status"], "working")
            self.assertEqual(payload["reason"], "Аккаунт онлайн и принимает сообщения")
            self.assertTrue(payload["can_start_outreach"])
            self.assertNotIn("health", payload)

    def test_resolution_restriction_does_not_block_account_status(self):
        account = Account(
            id=16,
            name="Ana",
            phone="+573122997094",
            app_id="2040",
            app_hash="hash",
            auto_reply=True,
        )
        account.connection_state = "online"
        account.proxy_state = "ok"
        account.session_state = "valid"
        account.eligibility_state = "blocked_resolution"
        account.last_error_code = "USERNAME_RESOLUTION_RESTRICTED"
        account.last_error_message = "Public username exists, but this account cannot resolve it"
        tg._clients[16] = object()

        public_status = tg.build_account_status(account)
        internal_state = tg._serialize_runtime_state(account)

        self.assertEqual(public_status["status"], "working")
        self.assertTrue(public_status["can_start_outreach"])
        self.assertEqual(internal_state["eligibility_state"], "eligible")
        self.assertIsNone(internal_state["last_error_code"])

    def test_public_status_normalizes_unsupported_runtime_states(self):
        account = Account(
            id=17,
            name="Ana",
            phone="+573122997095",
            app_id="2040",
            app_hash="hash",
            auto_reply=True,
        )
        account.connection_state = "legacy_locked"
        account.proxy_state = "ok"
        account.session_state = "valid"
        account.eligibility_state = "legacy_blocked"

        public_status = tg.build_account_status(account)
        internal_state = tg._serialize_runtime_state(account)

        self.assertFalse(public_status["is_online"])
        self.assertEqual(public_status["status"], "not_working")
        self.assertEqual(internal_state["connection_state"], "offline")
        self.assertEqual(internal_state["eligibility_state"], "blocked_runtime")

    def test_public_status_keeps_online_state_from_db_when_local_client_is_absent(self):
        account = Account(
            id=18,
            name="Ana",
            phone="+573122997096",
            app_id="2040",
            app_hash="hash",
            auto_reply=True,
        )
        account.connection_state = "online"
        account.proxy_state = "ok"
        account.session_state = "valid"
        account.needs_reauth = False

        public_status = tg.build_account_status(account)
        payload = tg.serialize_public_account(account)

        self.assertTrue(public_status["is_online"])
        self.assertEqual(public_status["status"], "working")
        self.assertTrue(public_status["can_start_outreach"])
        self.assertEqual(payload["connection_state"], "online")
        self.assertEqual(payload["eligibility_state"], "eligible")

    def test_public_payload_marks_runtime_block_when_session_is_valid_but_client_is_offline(self):
        account = Account(
            id=19,
            name="Ana",
            phone="+573122997097",
            app_id="2040",
            app_hash="hash",
            auto_reply=True,
        )
        account.connection_state = "offline"
        account.proxy_state = "ok"
        account.session_state = "valid"
        account.needs_reauth = False

        payload = tg.serialize_public_account(account)

        self.assertEqual(payload["connection_state"], "offline")
        self.assertFalse(payload["can_start_outreach"])
        self.assertEqual(payload["reason"], "Telegram-клиент не подключён")
        self.assertEqual(payload["eligibility_state"], "blocked_runtime")

    def test_save_session_attempts_reconnect_when_client_missing(self):
        fake_client = object()

        async def fake_reconnect(account_id, requested_by="system"):
            self.assertEqual(account_id, 55)
            self.assertEqual(requested_by, "save-session")
            tg._clients[55] = fake_client
            return {"ok": True}

        with patch.dict(tg._clients, {}, clear=True):
            with patch("backend.telegram_client.reconnect_account_runtime", fake_reconnect):
                with patch("backend.telegram_client._save_session_string", AsyncMock()) as save:
                    result = asyncio.run(tg.save_session_now(55))

        self.assertTrue(result)
        save.assert_awaited_once_with(55, fake_client)

    def test_unblock_forwards_to_worker_when_runtime_is_split(self):
        with self._db() as db:
            db.add(Account(name="Ana", phone="+1", app_id="2040", app_hash="hash"))
            db.commit()

        app = FastAPI()
        app.include_router(accounts_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            with patch("backend.routers.accounts.owns_telegram_runtime", return_value=False):
                with patch(
                    "backend.routers.accounts._forward_or_fail",
                    AsyncMock(return_value={"ok": True, "started": True}),
                ) as mocked:
                    response = client.post("/api/accounts/1/unblock")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": True, "started": True})
            mocked.assert_awaited_once_with("POST", "/internal/runtime/accounts/1/unblock")
        finally:
            client.close()
            app.dependency_overrides.clear()

    def test_create_account_copies_proxy_pool_password_by_proxy_id(self):
        with self._db() as db:
            db.add(
                ProxyPool(
                    host="79.175.96.142",
                    port=8184,
                    proxy_type="SOCKS5",
                    username="user397647",
                    password="z4a6tw",
                )
            )
            db.commit()

        app = FastAPI()
        app.include_router(accounts_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            response = client.post(
                "/api/accounts/",
                json={"name": "Vasilisa", "phone": "+573122997092", "proxy_id": 1},
            )
            self.assertEqual(response.status_code, 200)
        finally:
            client.close()
            app.dependency_overrides.clear()

        with self._db() as db:
            account = db.query(Account).filter(Account.phone == "+573122997092").first()
            self.assertEqual(account.proxy_host, "79.175.96.142")
            self.assertEqual(account.proxy_port, 8184)
            self.assertEqual(account.proxy_user, "user397647")
            self.assertEqual(account.proxy_pass, "z4a6tw")

    def test_create_account_resolves_keep_proxy_password_placeholder(self):
        with self._db() as db:
            db.add(
                ProxyPool(
                    host="82.39.223.11",
                    port=8184,
                    proxy_type="SOCKS5",
                    username="user397647",
                    password="z4a6tw",
                )
            )
            db.commit()

        app = FastAPI()
        app.include_router(accounts_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            response = client.post(
                "/api/accounts/",
                json={
                    "name": "Old Frontend",
                    "phone": "+573122997093",
                    "proxy_host": "82.39.223.11",
                    "proxy_port": 8184,
                    "proxy_type": "SOCKS5",
                    "proxy_user": "user397647",
                    "proxy_pass": "__keep__",
                },
            )
            self.assertEqual(response.status_code, 200)
        finally:
            client.close()
            app.dependency_overrides.clear()

        with self._db() as db:
            account = db.query(Account).filter(Account.phone == "+573122997093").first()
            self.assertEqual(account.proxy_pass, "z4a6tw")

    def test_update_account_can_select_proxy_by_proxy_id(self):
        with self._db() as db:
            db.add(
                Account(
                    id=81,
                    name="Needs Proxy",
                    phone="+573122997181",
                    app_id="2040",
                    app_hash="hash",
                )
            )
            db.add(
                ProxyPool(
                    id=91,
                    host="104.164.5.115",
                    port=8184,
                    proxy_type="HTTP",
                    username="user397647",
                    password="z4a6tw",
                    proxy_state="ok",
                )
            )
            db.commit()

        app = FastAPI()
        app.include_router(accounts_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            response = client.patch("/api/accounts/81", json={"proxy_id": 91})
            self.assertEqual(response.status_code, 200)
        finally:
            client.close()
            app.dependency_overrides.clear()

        with self._db() as db:
            account = db.query(Account).filter(Account.id == 81).first()
            self.assertEqual(account.proxy_host, "104.164.5.115")
            self.assertEqual(account.proxy_port, 8184)
            self.assertEqual(account.proxy_type, "HTTP")
            self.assertEqual(account.proxy_user, "user397647")
            self.assertEqual(account.proxy_pass, "z4a6tw")

    def test_proxy_pool_autodetects_type_when_line_omits_type(self):
        app = FastAPI()
        app.include_router(proxy_pool_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            with patch(
                "backend.routers.proxy_pool.detect_proxy_type",
                AsyncMock(return_value={"ok": True, "proxy_type": "HTTP", "rtt_ms": 42, "attempts": []}),
            ) as detect:
                response = client.post(
                    "/api/proxy-pool/",
                    json={"line": "82.39.223.11:8184:user397647:z4a6tw"},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["proxy_type"], "HTTP")
            detect.assert_awaited_once()
            self.assertIsNone(detect.await_args.kwargs["preferred_type"])
        finally:
            client.close()
            app.dependency_overrides.clear()

        with self._db() as db:
            proxy = db.query(ProxyPool).filter(ProxyPool.host == "82.39.223.11").first()
            self.assertEqual(proxy.proxy_type, "HTTP")
            self.assertEqual(proxy.proxy_state, "ok")
            self.assertEqual(proxy.proxy_last_rtt_ms, 42)

    def test_proxy_pool_type_prefix_is_used_as_detection_preference(self):
        app = FastAPI()
        app.include_router(proxy_pool_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            with patch(
                "backend.routers.proxy_pool.detect_proxy_type",
                AsyncMock(return_value={"ok": True, "proxy_type": "HTTP", "rtt_ms": 42, "attempts": []}),
            ) as detect:
                response = client.post(
                    "/api/proxy-pool/",
                    json={"line": "HTTP:82.39.223.11:8184:user397647:z4a6tw"},
                )
            self.assertEqual(response.status_code, 200)
            detect.assert_awaited_once()
            self.assertEqual(detect.await_args.kwargs["preferred_type"], "HTTP")
        finally:
            client.close()
            app.dependency_overrides.clear()

    def test_proxy_pool_test_persists_timeout_state(self):
        with self._db() as db:
            db.add(
                ProxyPool(
                    id=92,
                    host="82.39.223.11",
                    port=8184,
                    proxy_type="HTTP",
                    username="user397647",
                    password="z4a6tw",
                )
            )
            db.commit()

        app = FastAPI()
        app.include_router(proxy_pool_router.router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        try:
            with patch(
                "backend.routers.proxy_pool.detect_proxy_type",
                AsyncMock(
                    return_value={
                        "ok": False,
                        "attempts": [
                            {"proxy_type": "HTTP", "error_type": "ProxyError"},
                            {"proxy_type": "SOCKS5", "error_type": "TimeoutError"},
                        ],
                    }
                ),
            ):
                response = client.post("/api/proxy-pool/92/test")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["proxy_state"], "timeout")
            self.assertIn("HTTP=ProxyError", payload["last_error_message"])
        finally:
            client.close()
            app.dependency_overrides.clear()

        with self._db() as db:
            proxy = db.query(ProxyPool).filter(ProxyPool.id == 92).first()
            self.assertEqual(proxy.proxy_state, "timeout")
            self.assertIn("SOCKS5=TimeoutError", proxy.last_error_message)

    def test_proxy_connectivity_check_persists_detected_type_for_account_and_pool(self):
        with self._db() as db:
            db.add(
                ProxyPool(
                    host="79.175.96.142",
                    port=8184,
                    proxy_type="SOCKS5",
                    username="user397647",
                    password="z4a6tw",
                )
            )
            db.add(
                Account(
                    id=70,
                    name="Proxy Account",
                    phone="+573122997170",
                    app_id="2040",
                    app_hash="hash",
                    proxy_host="79.175.96.142",
                    proxy_port=8184,
                    proxy_type="SOCKS5",
                    proxy_user="user397647",
                    proxy_pass="z4a6tw",
                )
            )
            db.commit()

        account = SimpleNamespace(
            id=70,
            proxy_host="79.175.96.142",
            proxy_port=8184,
            proxy_type="SOCKS5",
            proxy_user="user397647",
            proxy_pass="z4a6tw",
        )
        with patch("backend.telegram_client.SessionLocal", self.Session):
            with patch(
                "backend.telegram_client.detect_proxy_type",
                AsyncMock(return_value={"ok": True, "proxy_type": "HTTP", "rtt_ms": 31, "attempts": []}),
            ):
                result = asyncio.run(tg._proxy_connectivity_check(account))

        self.assertTrue(result["ok"])
        self.assertEqual(result["detected_proxy_type"], "HTTP")
        with self._db() as db:
            stored_account = db.query(Account).filter(Account.id == 70).first()
            stored_proxy = db.query(ProxyPool).filter(ProxyPool.host == "79.175.96.142").first()
            self.assertEqual(stored_account.proxy_type, "HTTP")
            self.assertEqual(stored_proxy.proxy_type, "HTTP")

    def test_handle_message_persists_incoming_even_when_auto_reply_is_disabled(self):
        with self._db() as db:
            db.add(
                Account(
                    id=1,
                    name="Ana",
                    phone="+573122997092",
                    app_id="2040",
                    app_hash="hash",
                    auto_reply=True,
                )
            )
            db.add(Settings(id=1, provider="openai", auto_reply_enabled=False, model="gpt-4o-mini"))
            db.add(
                Conversation(
                    id=10,
                    account_id=1,
                    tg_user_id="42",
                    tg_username="lead_user",
                    tg_first_name="Lead",
                    status="active",
                )
            )
            db.commit()

        sender = SimpleNamespace(
            id=42,
            bot=False,
            username="lead_user",
            first_name="Lead",
            last_name="User",
        )
        event = FakeEvent(sender=sender, text="Привет, это ответ")

        with patch("backend.telegram_client.SessionLocal", self.Session):
            with patch("backend.telegram_client._ws_broadcast", None):
                asyncio.run(tg._handle_message(1, event))

        with self._db() as db:
            messages = (
                db.query(Message)
                .filter(Message.conversation_id == 10)
                .order_by(Message.id.asc())
                .all()
            )
            conv = db.query(Conversation).filter(Conversation.id == 10).first()

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, "user")
        self.assertEqual(messages[0].text, "Привет, это ответ")
        self.assertEqual(conv.last_message, "Привет, это ответ")
        self.assertEqual(conv.unread_count, 1)

    def test_handle_message_persists_incoming_even_without_provider_key(self):
        with self._db() as db:
            db.add(
                Account(
                    id=2,
                    name="Ana",
                    phone="+573122997093",
                    app_id="2040",
                    app_hash="hash",
                    auto_reply=True,
                )
            )
            db.add(Settings(id=1, provider="openai", auto_reply_enabled=True, openai_key="", model="gpt-4o-mini"))
            db.add(
                Conversation(
                    id=11,
                    account_id=2,
                    tg_user_id="43",
                    tg_username="lead_user_2",
                    tg_first_name="Lead",
                    status="active",
                )
            )
            db.commit()

        sender = SimpleNamespace(
            id=43,
            bot=False,
            username="lead_user_2",
            first_name="Lead",
            last_name="User",
        )
        event = FakeEvent(sender=sender, text="У меня есть вопрос")

        with patch("backend.telegram_client.SessionLocal", self.Session):
            with patch("backend.telegram_client._ws_broadcast", None):
                asyncio.run(tg._handle_message(2, event))

        with self._db() as db:
            messages = (
                db.query(Message)
                .filter(Message.conversation_id == 11)
                .order_by(Message.id.asc())
                .all()
            )
            conv = db.query(Conversation).filter(Conversation.id == 11).first()

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, "user")
        self.assertEqual(messages[0].text, "У меня есть вопрос")
        self.assertEqual(conv.last_message, "У меня есть вопрос")
        self.assertEqual(conv.unread_count, 1)

    def test_handle_message_schedules_auto_reply_without_generating_inline(self):
        with self._db() as db:
            db.add(
                Account(
                    id=21,
                    name="Ana",
                    phone="+573122997121",
                    app_id="2040",
                    app_hash="hash",
                    auto_reply=True,
                )
            )
            db.add(Settings(id=1, provider="openai", auto_reply_enabled=True, openai_key="sk-test", model="gpt-4o-mini"))
            db.add(
                Conversation(
                    id=121,
                    account_id=21,
                    tg_user_id="421",
                    tg_username="lead_user_21",
                    tg_first_name="Lead",
                    status="active",
                )
            )
            db.commit()

        sender = SimpleNamespace(
            id=421,
            bot=False,
            username="lead_user_21",
            first_name="Lead",
            last_name="User",
        )
        event = FakeEvent(sender=sender, text="Когда можем созвониться?")

        with patch("backend.telegram_client.SessionLocal", self.Session):
            with patch("backend.telegram_client._ws_broadcast", None):
                with patch("backend.telegram_client._schedule_auto_reply", return_value=25.0, create=True) as schedule:
                    with patch("backend.gpt_handler.generate_reply", AsyncMock(return_value="AI reply")) as generate:
                        with patch("backend.telegram_client.send_manual_message", AsyncMock(return_value={"ok": True})) as send:
                            asyncio.run(tg._handle_message(21, event))

        with self._db() as db:
            message = db.query(Message).filter(Message.conversation_id == 121, Message.role == "user").first()

        self.assertIsNotNone(message)
        schedule.assert_called_once_with(
            account_id=21,
            conversation_id=121,
            tg_user_id="421",
            trigger_message_id=message.id,
            inbound_text="Когда можем созвониться?",
        )
        generate.assert_not_awaited()
        send.assert_not_awaited()

    def test_schedule_auto_reply_cancels_previous_pending_task(self):
        old_task = FakeCreatedTask(done_value=False)
        new_task = FakeCreatedTask(done_value=False)

        def fake_create_task(coro):
            coro.close()
            return new_task

        tg._pending_auto_reply_tasks[122] = old_task
        with patch("backend.telegram_client.asyncio.create_task", side_effect=fake_create_task):
            delay = tg._schedule_auto_reply(22, 122, "422", 777)

        self.assertEqual(delay, 0.0)
        self.assertTrue(old_task.cancelled)
        self.assertIs(tg._pending_auto_reply_tasks[122], new_task)

    def test_auto_reply_delay_classifies_text_and_task_type(self):
        quick_type = tg._classify_auto_reply_task_type("Что за продукт?")
        scheduling_type = tg._classify_auto_reply_task_type("Давайте завтра в 16:00")
        quick_delay = tg._auto_reply_delay_seconds("Что за продукт?", task_type=quick_type, jitter=0)
        long_delay = tg._auto_reply_delay_seconds("Расскажите подробнее " * 40, task_type="trust", jitter=0)
        scheduling_delay = tg._auto_reply_delay_seconds("Давайте завтра в 16:00", task_type=scheduling_type, jitter=0)

        self.assertEqual(quick_type, "trust")
        self.assertEqual(scheduling_type, "booking")
        self.assertEqual(quick_delay, 0.0)
        self.assertEqual(long_delay, 0.0)
        self.assertEqual(scheduling_delay, 0.0)

    def test_run_scheduled_auto_reply_generates_and_sends_without_artificial_sleep(self):
        with self._db() as db:
            db.add(
                Account(
                    id=23,
                    name="Ana",
                    phone="+573122997123",
                    app_id="2040",
                    app_hash="hash",
                    auto_reply=True,
                )
            )
            db.add(Settings(id=1, provider="openai", auto_reply_enabled=True, openai_key="sk-test", model="gpt-4o-mini"))
            db.add(
                Conversation(
                    id=123,
                    account_id=23,
                    tg_user_id="423",
                    tg_username="lead_user_23",
                    tg_first_name="Lead",
                    status="active",
                )
            )
            db.add(Message(conversation_id=123, role="user", text="Расскажите подробнее"))
            db.commit()
            trigger_id = db.query(Message).filter(Message.conversation_id == 123).first().id

        with patch("backend.telegram_client.SessionLocal", self.Session):
            with patch("backend.telegram_client.asyncio.sleep", AsyncMock()) as sleep:
                tg._clients[23] = FakePresenceClient()
                with patch("backend.gpt_handler.generate_reply", AsyncMock(return_value="Конечно, расскажу.")) as generate:
                    with patch("backend.telegram_client.send_manual_message", AsyncMock(return_value={"ok": True})) as send:
                        asyncio.run(
                            tg._run_scheduled_auto_reply(
                                account_id=23,
                                conversation_id=123,
                                tg_user_id="423",
                                trigger_message_id=trigger_id,
                                delay_s=17.0,
                                scheduled_at=tg._utcnow(),
                            )
                        )

        sleep.assert_not_awaited()
        generate.assert_awaited_once()
        send.assert_awaited_once_with(23, "423", 123, "Конечно, расскажу.")

    def test_send_manual_message_falls_back_to_username_when_peer_id_cache_missing(self):
        with self._db() as db:
            db.add(Account(id=52, name="Ana", phone="+573122997152", app_id="2040", app_hash="hash"))
            db.add(
                Conversation(
                    id=152,
                    account_id=52,
                    tg_user_id="6289865060",
                    tg_username="rodmirpronaim",
                    tg_first_name="Lead",
                    status="active",
                )
            )
            db.commit()

        client = FakeManualSendClient()
        tg._clients[52] = client
        with patch("backend.telegram_client.SessionLocal", self.Session):
            result = asyncio.run(tg.send_manual_message(52, "6289865060", 152, "Ссылка на событие"))

        self.assertTrue(result["ok"])
        self.assertEqual(client.resolved, ["rodmirpronaim"])
        self.assertEqual(len(client.sent), 2)
        self.assertIsInstance(client.sent[0][0], int)
        self.assertEqual(client.sent[1][0].username, "rodmirpronaim")

    def test_send_manual_message_persists_compact_visible_link_text(self):
        calendar_url = "https://calendar.google.com/calendar/render?action=TEMPLATE&text=Interview&dates=20260428"
        with self._db() as db:
            db.add(Account(id=53, name="Ana", phone="+573122997153", app_id="2040", app_hash="hash"))
            db.add(
                Conversation(
                    id=153,
                    account_id=53,
                    tg_user_id="6289865060",
                    tg_username="rodmirpronaim",
                    tg_first_name="Lead",
                    status="active",
                )
            )
            db.commit()

        client = FakeManualSendClient()
        tg._clients[53] = client
        with patch("backend.telegram_client.SessionLocal", self.Session):
            result = asyncio.run(
                tg.send_manual_message(
                    53,
                    "6289865060",
                    153,
                    f"Поставил встречу. Добавьте событие в календарь: {calendar_url}",
                )
            )

        with self._db() as db:
            stored = db.query(Message).filter(Message.conversation_id == 153).order_by(Message.id.desc()).first()

        self.assertTrue(result["ok"])
        self.assertEqual(client.sent[1][2], {"parse_mode": "html"})
        self.assertIn("<a href=", client.sent[1][1])
        self.assertNotIn(calendar_url, stored.text)
        self.assertEqual(stored.text, "Поставил встречу. Добавьте событие в календарь: ссылка")

    def test_run_scheduled_auto_reply_skips_stale_trigger_message(self):
        with self._db() as db:
            db.add(
                Account(
                    id=24,
                    name="Ana",
                    phone="+573122997124",
                    app_id="2040",
                    app_hash="hash",
                    auto_reply=True,
                )
            )
            db.add(Settings(id=1, provider="openai", auto_reply_enabled=True, openai_key="sk-test", model="gpt-4o-mini"))
            db.add(
                Conversation(
                    id=124,
                    account_id=24,
                    tg_user_id="424",
                    tg_username="lead_user_24",
                    tg_first_name="Lead",
                    status="active",
                )
            )
            db.add(Message(conversation_id=124, role="user", text="Первый вопрос"))
            db.commit()
            old_trigger_id = db.query(Message).filter(Message.conversation_id == 124).first().id
            db.add(Message(conversation_id=124, role="user", text="Новый вопрос"))
            db.commit()

        with patch("backend.telegram_client.SessionLocal", self.Session):
            with patch("backend.telegram_client.asyncio.sleep", AsyncMock()):
                with patch("backend.gpt_handler.generate_reply", AsyncMock(return_value="AI reply")) as generate:
                    with patch("backend.telegram_client.send_manual_message", AsyncMock(return_value={"ok": True})) as send:
                        asyncio.run(
                            tg._run_scheduled_auto_reply(
                                account_id=24,
                                conversation_id=124,
                                tg_user_id="424",
                                trigger_message_id=old_trigger_id,
                                delay_s=7.0,
                                scheduled_at=tg._utcnow(),
                            )
                        )

        generate.assert_not_awaited()
        send.assert_not_awaited()

    def test_outgoing_outreach_message_creates_conversation_immediately(self):
        with self._db() as db:
            db.add(Account(id=3, name="Ana", phone="+573122997094", app_id="2040", app_hash="hash"))
            db.commit()

        with patch("backend.telegram_client.SessionLocal", self.Session):
            conv = tg._persist_outgoing_outreach_message(
                account_id=3,
                source_campaign_id=77,
                tg_user_id="44",
                tg_username="lead_user_3",
                tg_first_name="Lead",
                text="Привет! Это первое сообщение",
            )

        self.assertIsNotNone(conv)
        self.assertEqual(conv.source_campaign_id, 77)

        with self._db() as db:
            stored_conv = db.query(Conversation).filter(Conversation.account_id == 3, Conversation.tg_user_id == "44").first()
            messages = db.query(Message).filter(Message.conversation_id == stored_conv.id).all()

        self.assertIsNotNone(stored_conv)
        self.assertEqual(stored_conv.last_message, "Привет! Это первое сообщение")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, "assistant")

    def test_handle_message_ignores_non_outreach_chat_without_existing_conversation(self):
        with self._db() as db:
            db.add(
                Account(
                    id=4,
                    name="Ana",
                    phone="+573122997095",
                    app_id="2040",
                    app_hash="hash",
                    auto_reply=True,
                )
            )
            db.add(Settings(id=1, provider="openai", auto_reply_enabled=True, openai_key="", model="gpt-4o-mini"))
            db.commit()

        sender = SimpleNamespace(
            id=45,
            bot=False,
            username="stranger_user",
            first_name="Stranger",
            last_name="User",
        )
        event = FakeEvent(sender=sender, text="Это не outreach чат")

        with patch("backend.telegram_client.SessionLocal", self.Session):
            with patch("backend.telegram_client._ws_broadcast", None):
                asyncio.run(tg._handle_message(4, event))

        with self._db() as db:
            conversations = db.query(Conversation).filter(Conversation.account_id == 4).count()
            messages = db.query(Message).count()

        self.assertEqual(conversations, 0)
        self.assertEqual(messages, 0)


if __name__ == "__main__":
    unittest.main()
