import asyncio
import base64
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Account
from backend.runtime_config import owns_telegram_runtime
from backend.security import decrypt_value, encrypt_value, has_secret
from backend.worker_client import forward_to_worker
import backend.telegram_client as tg

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class AccountCreate(BaseModel):
    name: str
    phone: str
    app_id: str
    app_hash: str
    proxy_host: str = ""
    proxy_port: Optional[int] = None
    proxy_type: str = "SOCKS5"
    proxy_user: str = ""
    proxy_pass: str = ""


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    app_id: Optional[str] = None
    app_hash: Optional[str] = None
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None
    proxy_type: Optional[str] = None
    proxy_user: Optional[str] = None
    proxy_pass: Optional[str] = None


class SendCodeRequest(BaseModel):
    account_id: int


class VerifyCodeRequest(BaseModel):
    account_id: int
    phone_code_hash: str
    code: str
    password: str = ""


class SetPromptRequest(BaseModel):
    prompt_template_id: Optional[int]


def _serialize_account(account: Account) -> dict:
    return {
        "id": account.id,
        "name": account.name,
        "phone": account.phone,
        "app_id": account.app_id,
        "is_active": account.connection_state == "online",
        "auto_reply": account.auto_reply,
        "needs_reauth": bool(getattr(account, "needs_reauth", False)),
        "tdata_stored": has_secret(account.tdata_blob),
        "prompt_template_id": account.prompt_template_id,
        "created_at": account.created_at,
        "proxy_host": account.proxy_host or "",
        "proxy_port": account.proxy_port,
        "proxy_type": account.proxy_type or "SOCKS5",
        "proxy_user": account.proxy_user or "",
        "connection_state": account.connection_state or "offline",
        "proxy_state": account.proxy_state or "unknown",
        "session_state": account.session_state or "missing",
        "eligibility_state": account.eligibility_state or "blocked_auth",
        "last_error_code": account.last_error_code,
        "last_error_message": account.last_error_message,
        "last_error_at": account.last_error_at,
        "last_proxy_check_at": account.last_proxy_check_at,
        "last_connect_at": account.last_connect_at,
        "last_seen_online_at": account.last_seen_online_at,
        "quarantine_until": account.quarantine_until,
        "warmup_level": account.warmup_level or 0,
        "session_source": account.session_source or "",
        "proxy_last_rtt_ms": account.proxy_last_rtt_ms,
    }


def _safe_extract_zip(archive: zipfile.ZipFile, target_dir: str) -> None:
    target_path = Path(target_dir).resolve()
    for member in archive.infolist():
        member_path = (target_path / member.filename).resolve()
        if target_path not in member_path.parents and member_path != target_path:
            raise HTTPException(400, "Archive contains an invalid path")
    archive.extractall(target_dir)


async def _forward_or_fail(method: str, path: str, json_body: Optional[dict] = None) -> dict:
    return await forward_to_worker(method, path, json_body=json_body)


@router.get("/")
def list_accounts(db: Session = Depends(get_db)):
    accounts = db.query(Account).all()
    return [_serialize_account(a) for a in accounts]


@router.get("/{account_id}/health")
def get_account_health(account_id: int, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(404, "Account not found")
    return _serialize_account(acc)


def _generate_device_params(account_id: int) -> dict:
    """Generate unique but consistent device fingerprint via opentele.
    Mimics real Telegram Desktop — makes the client invisible among normal users."""
    try:
        from opentele.api import API as TgAPI
        api = TgAPI.TelegramDesktop.Generate(unique_id=str(account_id))
        return {
            "device_model": api.device_model,
            "system_version": api.system_version,
            "app_version": "6.7.5 x64",
            "lang_code": "ru",
        }
    except Exception:
        return {
            "device_model": "Desktop",
            "system_version": "Windows 10",
            "app_version": "6.7.5 x64",
            "lang_code": "ru",
        }


@router.post("/")
def create_account(data: AccountCreate, db: Session = Depends(get_db)):
    existing = db.query(Account).filter(Account.phone == data.phone).first()
    if existing:
        raise HTTPException(400, "Account with this phone already exists")
    acc = Account(
        name=data.name,
        phone=data.phone,
        app_id=data.app_id,
        app_hash=encrypt_value(data.app_hash),
        proxy_host=data.proxy_host or None,
        proxy_port=data.proxy_port or None,
        proxy_type=(data.proxy_type or "SOCKS5").upper(),
        proxy_user=data.proxy_user or None,
        proxy_pass=encrypt_value(data.proxy_pass) if data.proxy_pass else None,
        session_source="phone_code",
    )
    db.add(acc)
    db.flush()  # get acc.id before commit
    params = _generate_device_params(acc.id)
    acc.device_model = params["device_model"]
    acc.system_version = params["system_version"]
    acc.app_version = params["app_version"]
    acc.lang_code = params["lang_code"]
    db.commit()
    db.refresh(acc)
    return {"id": acc.id, "name": acc.name, "phone": acc.phone}


@router.patch("/{account_id}")
def update_account(account_id: int, data: AccountUpdate, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(404, "Account not found")

    for field in ("name", "phone", "app_id"):
        value = getattr(data, field)
        if value is not None:
            setattr(acc, field, value)

    if data.app_hash is not None:
        acc.app_hash = encrypt_value(data.app_hash) if data.app_hash else acc.app_hash

    if data.proxy_host is not None:
        acc.proxy_host = data.proxy_host or None
    if data.proxy_port is not None:
        acc.proxy_port = data.proxy_port or None
    if data.proxy_type is not None:
        acc.proxy_type = (data.proxy_type or "SOCKS5").upper()
    if data.proxy_user is not None:
        acc.proxy_user = data.proxy_user or None
    if data.proxy_pass is not None:
        acc.proxy_pass = encrypt_value(data.proxy_pass) if data.proxy_pass else None

    db.commit()
    db.refresh(acc)
    return _serialize_account(acc)


@router.post("/send-code")
async def send_code(data: SendCodeRequest, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == data.account_id).first()
    if not acc:
        raise HTTPException(404, "Account not found")
    result = await tg.send_code_request(acc)
    return result


@router.post("/verify-code")
async def verify_code(data: VerifyCodeRequest, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == data.account_id).first()
    if not acc:
        raise HTTPException(404, "Account not found")
    result = await tg.login_new_account(acc, data.phone_code_hash, data.code, data.password)
    if result["ok"]:
        if owns_telegram_runtime():
            reconnect_result = await tg.reconnect_account_runtime(acc.id, requested_by="verify-code")
        else:
            reconnect_result = await _forward_or_fail("POST", f"/internal/runtime/accounts/{acc.id}/reconnect")
        result["runtime"] = reconnect_result
    return result


@router.post("/{account_id}/proxy-test")
async def proxy_test(account_id: int, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(404, "Account not found")
    if owns_telegram_runtime():
        return await tg.proxy_test_account(account_id)
    return await _forward_or_fail("POST", f"/internal/runtime/accounts/{account_id}/proxy-test")


@router.post("/{account_id}/save-session")
async def save_session(account_id: int, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(404, "Account not found")
    if owns_telegram_runtime():
        ok = await tg.save_session_now(account_id)
        if not ok:
            raise HTTPException(400, "Account is not connected")
        return {"ok": True}
    return await _forward_or_fail("POST", f"/internal/runtime/accounts/{account_id}/save-session")


@router.post("/{account_id}/reconnect")
async def reconnect_account(account_id: int, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(404, "Account not found")
    if owns_telegram_runtime():
        result = await tg.reconnect_account_runtime(account_id, requested_by="api")
    else:
        result = await _forward_or_fail("POST", f"/internal/runtime/accounts/{account_id}/reconnect")
    if not result.get("ok"):
        raise HTTPException(400, result)
    return result


@router.post("/{account_id}/toggle-reply")
def toggle_reply(account_id: int, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(404, "Account not found")
    acc.auto_reply = not acc.auto_reply
    db.commit()
    return {"auto_reply": acc.auto_reply}


@router.post("/{account_id}/set-prompt")
def set_prompt(account_id: int, data: SetPromptRequest, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(404, "Account not found")
    acc.prompt_template_id = data.prompt_template_id
    db.commit()
    return {"ok": True, "prompt_template_id": acc.prompt_template_id}


@router.post("/import-tdata")
async def import_tdata(
    name: str = Form(...),
    phone: str = Form(...),
    proxy_host: str = Form(""),
    proxy_port: int = Form(0),
    proxy_type: str = Form("SOCKS5"),
    proxy_user: str = Form(""),
    proxy_pass: str = Form(""),
    tdata_zip: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    existing = db.query(Account).filter(Account.phone == phone).first()
    if existing:
        raise HTTPException(400, "Account with this phone already exists")

    tmp_dir = tempfile.mkdtemp()
    try:
        zip_path = os.path.join(tmp_dir, "tdata.zip")
        with open(zip_path, "wb") as f:
            f.write(await tdata_zip.read())
        with zipfile.ZipFile(zip_path) as archive:
            _safe_extract_zip(archive, tmp_dir)

        tdata_path = None
        for root, _dirs, files in os.walk(tmp_dir):
            if "key_datas" in files:
                tdata_path = root
                break
        if not tdata_path:
            raise HTTPException(400, "tdata folder not found in zip (key_datas missing)")

        acc = Account(
            name=name,
            phone=phone,
            app_id="2040",
            app_hash=encrypt_value("b18441a1ff607e10a989891a5462e627"),
            proxy_host=proxy_host or None,
            proxy_port=proxy_port or None,
            proxy_type=(proxy_type or "SOCKS5").upper(),
            proxy_user=proxy_user or None,
            proxy_pass=encrypt_value(proxy_pass) if proxy_pass else None,
            session_source="tdata",
        )
        db.add(acc)
        db.commit()
        db.refresh(acc)

        session_str = await tg.convert_tdata_to_session(
            tdata_path=tdata_path,
            proxy_host=proxy_host or None,
            proxy_port=proxy_port or None,
            proxy_type=(proxy_type or "SOCKS5").upper(),
            proxy_user=proxy_user or None,
            proxy_pass=proxy_pass or None,
        )
        if not session_str:
            db.delete(acc)
            db.commit()
            raise HTTPException(400, "Account not authorized after tdata conversion")

        acc.session_string = encrypt_value(session_str)
        with open(zip_path, "rb") as f:
            acc.tdata_blob = encrypt_value(base64.b64encode(f.read()).decode("utf-8"))
        db.commit()

        if owns_telegram_runtime():
            runtime_result = await tg.reconnect_account_runtime(acc.id, requested_by="import-tdata")
        else:
            runtime_result = await _forward_or_fail("POST", f"/internal/runtime/accounts/{acc.id}/reconnect")
        return {"id": acc.id, "name": acc.name, "phone": acc.phone, "ok": True, "runtime": runtime_result}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("tdata import failed: %s", e, exc_info=True)
        try:
            acc_check = db.query(Account).filter(Account.phone == phone).first()
            if acc_check:
                db.delete(acc_check)
                db.commit()
        except Exception:
            pass
        raise HTTPException(500, f"Import failed: {e}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.delete("/{account_id}")
async def delete_account(account_id: int, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(404, "Account not found")
    if owns_telegram_runtime():
        await tg.stop_client(account_id)
    db.delete(acc)
    db.commit()
    return {"ok": True}
