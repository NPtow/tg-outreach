from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Conversation
from backend.runtime_config import owns_telegram_runtime, runtime_role, worker_shared_token
import backend.telegram_client as tg

router = APIRouter(prefix="/internal/runtime", tags=["internal-runtime"])


def require_worker_token(x_worker_token: Optional[str] = Header(default=None)) -> None:
    expected = worker_shared_token()
    if not expected:
        raise HTTPException(503, "WORKER_SHARED_TOKEN is not configured")
    if x_worker_token != expected:
        raise HTTPException(401, "Invalid worker token")


class SendConversationRequest(BaseModel):
    text: str


@router.get("/status", dependencies=[Depends(require_worker_token)])
def runtime_status():
    return {
        "ok": True,
        "role": runtime_role(),
        "owns_runtime": owns_telegram_runtime(),
    }


@router.post("/accounts/{account_id}/proxy-test", dependencies=[Depends(require_worker_token)])
async def proxy_test(account_id: int):
    return await tg.proxy_test_account(account_id)


@router.post("/accounts/{account_id}/reconnect", dependencies=[Depends(require_worker_token)])
async def reconnect(account_id: int):
    result = await tg.reconnect_account_runtime(account_id, requested_by="internal")
    if not result.get("ok"):
        raise HTTPException(400, result)
    return result


@router.post("/accounts/{account_id}/clear-quarantine", dependencies=[Depends(require_worker_token)])
async def clear_quarantine(account_id: int):
    return await tg.clear_quarantine(account_id)


@router.post("/accounts/{account_id}/save-session", dependencies=[Depends(require_worker_token)])
async def save_session(account_id: int):
    ok = await tg.save_session_now(account_id)
    if not ok:
        raise HTTPException(400, "Account is not connected")
    return {"ok": True}


@router.post("/conversations/{conv_id}/send", dependencies=[Depends(require_worker_token)])
async def send_conversation_message(conv_id: int, data: SendConversationRequest, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    result = await tg.send_manual_message(conv.account_id, conv.tg_user_id, conv.id, data.text)
    if not result.get("ok"):
        raise HTTPException(400, result)
    return result


@router.post("/campaigns/{campaign_id}/start", dependencies=[Depends(require_worker_token)])
async def start_campaign(campaign_id: int):
    result = await tg.preflight_and_start_campaign(campaign_id)
    if not result.get("ok"):
        raise HTTPException(400, result)
    return result


@router.post("/campaigns/{campaign_id}/pause", dependencies=[Depends(require_worker_token)])
async def pause_campaign(campaign_id: int):
    await tg.stop_campaign(campaign_id)
    return {"ok": True}
