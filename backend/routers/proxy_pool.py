from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from backend.database import get_db
from backend.models import ProxyPool, Account
from backend.proxy_utils import SUPPORTED_PROXY_TYPES, detect_proxy_type, normalize_proxy_type

router = APIRouter(prefix="/api/proxy-pool", tags=["proxy_pool"])


class ProxyCreate(BaseModel):
    # Accept "host:port:user:pass", "host:port", or "TYPE:host:port:user:pass".
    line: Optional[str] = None
    # Or individual fields
    label: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    proxy_type: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


def _serialize(p: ProxyPool, used_by: Optional[str] = None) -> dict:
    return {
        "id": p.id,
        "label": p.label or "",
        "host": p.host,
        "port": p.port,
        "proxy_type": p.proxy_type,
        "username": p.username or "",
        "has_password": bool(p.password),
        "created_at": p.created_at,
        "used_by": used_by,
    }


def _parse_proxy_line(line: str) -> tuple[Optional[str], str, int, Optional[str], Optional[str]]:
    parts = [x.strip() for x in line.split(":")]
    if len(parts) < 2:
        raise HTTPException(400, "Format: host:port, host:port:user:pass, or TYPE:host:port:user:pass")

    proxy_type = None
    if parts[0].upper() in SUPPORTED_PROXY_TYPES:
        proxy_type = parts.pop(0).upper()

    if len(parts) < 2:
        raise HTTPException(400, "Format: host:port, host:port:user:pass, or TYPE:host:port:user:pass")

    host = parts[0]
    try:
        port = int(parts[1])
    except ValueError:
        raise HTTPException(400, "Port must be a number")
    username = parts[2] if len(parts) > 2 and parts[2] else None
    password = ":".join(parts[3:]) if len(parts) > 3 else None
    return proxy_type, host, port, username, password


def _attempt_summary(attempts: list[dict]) -> str:
    return ", ".join(
        f"{attempt.get('proxy_type')}={attempt.get('error_type') or 'failed'}"
        for attempt in attempts
    )


@router.get("/")
def list_proxies(db: Session = Depends(get_db)):
    proxies = db.query(ProxyPool).order_by(ProxyPool.id).all()
    # Build map of proxy -> account name
    accounts = db.query(Account).all()
    used = {}
    for acc in accounts:
        if acc.proxy_host and acc.proxy_port:
            key = f"{acc.proxy_host}:{acc.proxy_port}"
            used[key] = acc.name
    result = []
    for p in proxies:
        key = f"{p.host}:{p.port}"
        result.append(_serialize(p, used.get(key)))
    return result


@router.post("/")
async def add_proxy(data: ProxyCreate, db: Session = Depends(get_db)):
    try:
        requested_type = normalize_proxy_type(data.proxy_type) if data.proxy_type else None
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if data.line:
        line_type, host, port, username, password = _parse_proxy_line(data.line)
        requested_type = requested_type or line_type
        label = None
    else:
        if not data.host or not data.port:
            raise HTTPException(400, "host and port required")
        host, port, username, password, label = data.host, data.port, data.username, data.password, data.label

    detected = await detect_proxy_type(
        host=host,
        port=int(port),
        username=username,
        password=password,
        preferred_type=requested_type,
    )
    if not detected.get("ok"):
        raise HTTPException(
            400,
            f"Proxy does not connect to Telegram as HTTP/SOCKS5/SOCKS4: {_attempt_summary(detected.get('attempts', []))}",
        )

    p = ProxyPool(host=host, port=port, proxy_type=detected["proxy_type"],
                  username=username, password=password, label=label)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _serialize(p)


@router.delete("/{proxy_id}")
def delete_proxy(proxy_id: int, db: Session = Depends(get_db)):
    p = db.query(ProxyPool).filter(ProxyPool.id == proxy_id).first()
    if not p:
        raise HTTPException(404, "Proxy not found")
    db.delete(p)
    db.commit()
    return {"ok": True}
