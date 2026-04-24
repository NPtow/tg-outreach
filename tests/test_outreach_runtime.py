import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import get_db, Base
from backend.models import Account, Campaign, CampaignTarget, Conversation, Message, ProxyPool, Settings
from backend.routers import accounts as accounts_router
from backend.routers import campaigns as campaigns_router
from backend.routers import proxy_pool as proxy_pool_router
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
    def __init__(self, *, sender, text, is_out=False):
        self._sender = sender
        self.is_out = is_out
        self.message = SimpleNamespace(text=text)

    async def get_sender(self):
        return self._sender




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
        with patch("backend.telegram_client._auto_reply_delay_seconds", return_value=12.5):
            with patch("backend.telegram_client.asyncio.create_task", side_effect=fake_create_task):
                delay = tg._schedule_auto_reply(22, 122, "422", 777)

        self.assertEqual(delay, 12.5)
        self.assertTrue(old_task.cancelled)
        self.assertIs(tg._pending_auto_reply_tasks[122], new_task)

    def test_run_scheduled_auto_reply_waits_then_generates_and_sends(self):
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
                with patch("backend.gpt_handler.generate_reply", AsyncMock(return_value="Конечно, расскажу.")) as generate:
                    with patch("backend.telegram_client.send_manual_message", AsyncMock(return_value={"ok": True})) as send:
                        asyncio.run(
                            tg._run_scheduled_auto_reply(
                                account_id=23,
                                conversation_id=123,
                                tg_user_id="423",
                                trigger_message_id=trigger_id,
                                delay_s=7.0,
                                scheduled_at=tg._utcnow(),
                            )
                        )

        sleep.assert_awaited_once_with(7.0)
        generate.assert_awaited_once()
        send.assert_awaited_once_with(23, "423", 123, "Конечно, расскажу.")

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
