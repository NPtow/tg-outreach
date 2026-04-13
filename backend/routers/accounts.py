import logging
import os
import shutil
import tempfile
import zipfile

from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Account
import backend.telegram_client as tg

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class AccountCreate(BaseModel):
    name: str
    phone: str
    app_id: str
    app_hash: str


class SendCodeRequest(BaseModel):
    account_id: int


class VerifyCodeRequest(BaseModel):
    account_id: int
    phone_code_hash: str
    code: str
    password: str = ""


@router.get("/")
def list_accounts(db: Session = Depends(get_db)):
    accounts = db.query(Account).all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "phone": a.phone,
            "app_id": a.app_id,
            "is_active": tg.is_running(a.id),
            "auto_reply": a.auto_reply,
            "needs_reauth": bool(getattr(a, "needs_reauth", False)),
            "prompt_template_id": a.prompt_template_id,
            "created_at": a.created_at,
        }
        for a in accounts
    ]


@router.post("/")
def create_account(data: AccountCreate, db: Session = Depends(get_db)):
    existing = db.query(Account).filter(Account.phone == data.phone).first()
    if existing:
        raise HTTPException(400, "Account with this phone already exists")
    acc = Account(
        name=data.name,
        phone=data.phone,
        app_id=data.app_id,
        app_hash=data.app_hash,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return {"id": acc.id, "name": acc.name, "phone": acc.phone}


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
        ok = await tg.start_client(acc)
        if ok:
            acc.is_active = True
            db.commit()
    return result


@router.post("/{account_id}/reconnect")
async def reconnect_account(account_id: int, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(404, "Account not found")
    acc.needs_reauth = False
    db.commit()
    ok = await tg.start_client(acc)
    if ok:
        acc.is_active = True
        db.commit()
        return {"ok": True}
    needs_reauth = bool(getattr(acc, "needs_reauth", False))
    return {"ok": False, "needs_reauth": needs_reauth, "error": "Session expired — re-authorization required" if needs_reauth else "Connection failed"}


@router.post("/{account_id}/toggle-reply")
def toggle_reply(account_id: int, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(404, "Account not found")
    acc.auto_reply = not acc.auto_reply
    db.commit()
    return {"auto_reply": acc.auto_reply}


class SetPromptRequest(BaseModel):
    prompt_template_id: Optional[int]


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
    proxy_type: str = Form("HTTP"),
    proxy_user: str = Form(""),
    proxy_pass: str = Form(""),
    tdata_zip: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Import a Telegram account from a tdata zip archive."""
    existing = db.query(Account).filter(Account.phone == phone).first()
    if existing:
        raise HTTPException(400, "Account with this phone already exists")

    tmp_dir = tempfile.mkdtemp()
    try:
        # Save and extract zip
        zip_path = os.path.join(tmp_dir, "tdata.zip")
        with open(zip_path, "wb") as f:
            f.write(await tdata_zip.read())
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp_dir)

        # Find tdata folder (contains key_datas file)
        tdata_path = None
        for root, _dirs, files in os.walk(tmp_dir):
            if "key_datas" in files:
                tdata_path = root
                break
        if not tdata_path:
            raise HTTPException(400, "tdata folder not found in zip (key_datas missing)")

        # Create account record (use Telegram Desktop API credentials)
        acc = Account(
            name=name,
            phone=phone,
            app_id="2040",
            app_hash="b18441a1ff607e10a989891a5462e627",
            proxy_host=proxy_host or None,
            proxy_port=proxy_port or None,
            proxy_type=proxy_type or None,
            proxy_user=proxy_user or None,
            proxy_pass=proxy_pass or None,
        )
        db.add(acc)
        db.commit()
        db.refresh(acc)

        # Build proxy tuple for opentele
        proxy = None
        if proxy_host and proxy_port:
            import socks
            type_map = {"HTTP": socks.HTTP, "SOCKS5": socks.SOCKS5}
            ptype = type_map.get(proxy_type.upper(), socks.HTTP)
            proxy = (ptype, proxy_host, int(proxy_port), True,
                     proxy_user or None, proxy_pass or None)

        # Convert tdata → Telethon StringSession via opentele
        from opentele.td import TDesktop
        from opentele.api import UseCurrentSession
        from telethon.sessions import StringSession

        tdesk = TDesktop(tdata_path)
        client = await tdesk.ToTelethon(
            session=StringSession(),
            flag=UseCurrentSession,
            proxy=proxy,
        )
        await client.connect()
        authorized = await client.is_user_authorized()
        session_str = client.session.save() if authorized else None
        await client.disconnect()

        if not authorized or not session_str:
            db.delete(acc)
            db.commit()
            raise HTTPException(400, "Account not authorized after tdata conversion")

        acc.session_string = session_str
        db.commit()

        # Start the live client
        ok = await tg.start_client(acc)
        if ok:
            acc.is_active = True
            db.commit()

        return {"id": acc.id, "name": acc.name, "phone": acc.phone, "ok": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"tdata import failed: {e}", exc_info=True)
        # Clean up account if created
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
    await tg.stop_client(account_id)
    db.delete(acc)
    db.commit()
    return {"ok": True}
