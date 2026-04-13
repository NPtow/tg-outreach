import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.database import init_db
from backend.routers import accounts, conversations, settings, campaigns, prompts, dnc, contacts
import backend.telegram_client as tg

logging.basicConfig(level=logging.INFO)

# WebSocket connection manager
_ws_clients: Set[WebSocket] = set()


async def ws_broadcast(data: dict):
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
    await tg.start_all_accounts()
    yield
    for account_id in list(tg._clients.keys()):
        await tg.stop_client(account_id)


app = FastAPI(title="TG Outreach", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
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
