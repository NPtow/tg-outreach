import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Set

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.database import init_db
from backend.event_bus import get_latest_runtime_event_id, get_runtime_events, publish_runtime_event
from backend.routers import accounts, conversations, settings, campaigns, prompts, dnc, contacts, internal_runtime, warming
from backend.runtime_config import cors_allowed_origins, owns_telegram_runtime, runtime_role
from backend.security import require_http_auth, require_ws_auth
from backend.worker_client import forward_to_worker
import backend.telegram_client as tg
import backend.warming_worker as ww

logging.basicConfig(level=logging.INFO)

# WebSocket connection manager
_ws_clients: Set[WebSocket] = set()


async def ws_broadcast(data: dict):
    publish_runtime_event(data)
    dead = set()
    for ws in _ws_clients:
        try:
            await ws.send_text(json.dumps(data, default=str))
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    tg.set_ws_broadcast(ws_broadcast)
    relay_task = None
    if owns_telegram_runtime():
        await tg.start_all_accounts()
        await ww.start_all_warming_tasks()
    else:
        relay_task = asyncio.create_task(_relay_runtime_events())
    yield
    if relay_task:
        relay_task.cancel()
    if owns_telegram_runtime():
        for account_id in list(tg._clients.keys()):
            await tg.stop_client(account_id)


app = FastAPI(title="TG Outreach", lifespan=lifespan)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path.startswith("/api") and request.url.path != "/api/health":
        if not require_http_auth(request.headers.get("X-App-Token")):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts.router)
app.include_router(conversations.router)
app.include_router(settings.router)
app.include_router(campaigns.router)
app.include_router(prompts.router)
app.include_router(dnc.router)
app.include_router(contacts.router)
app.include_router(internal_runtime.router)
app.include_router(warming.router)


async def _relay_runtime_events():
    cursor = get_latest_runtime_event_id()
    while True:
        await asyncio.sleep(1.5)
        for event in get_runtime_events(after_id=cursor, limit=100):
            cursor = event["id"]
            dead = set()
            payload = event["payload"]
            for ws in _ws_clients:
                try:
                    await ws.send_text(json.dumps(payload, default=str))
                except Exception:
                    dead.add(ws)
            _ws_clients.difference_update(dead)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not require_ws_auth(websocket.query_params.get("token")):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        _ws_clients.discard(websocket)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/runtime/status")
async def runtime_status():
    if owns_telegram_runtime():
        return {
            "ok": True,
            "role": runtime_role(),
            "owns_runtime": True,
        }
    return await forward_to_worker("GET", "/internal/runtime/status")


# Serve built React frontend — must be last
_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
_DIST = os.path.abspath(_DIST)
logging.getLogger(__name__).info(f"Frontend dist path: {_DIST}, exists: {os.path.isdir(_DIST)}")

if os.path.isdir(_DIST):
    _assets = os.path.join(_DIST, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

@app.get("/")
@app.get("/{full_path:path}")
def serve_spa(full_path: str = ""):
    index = os.path.join(_DIST, "index.html")
    if os.path.isfile(index):
        return FileResponse(index)
    return {"detail": "Frontend not built. Run: cd frontend && npm run build"}
