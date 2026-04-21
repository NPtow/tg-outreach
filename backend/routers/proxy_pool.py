from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List

from backend.database import get_db
from backend.models import ProxyPool, Account

router = APIRouter(prefix="/api/proxy-pool", tags=["proxy_pool"])


class ProxyCreate(BaseModel):
    # Accept "host:port:user:pass" or "host:port" as a single line
    line: Optional[str] = None
    # Or individual fields
    label: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    proxy_type: str = "SOCKS5"
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
def add_proxy(data: ProxyCreate, db: Session = Depends(get_db)):
    if data.line:
        parts = [x.strip() for x in data.line.split(":")]
        if len(parts) < 2:
            raise HTTPException(400, "Format: host:port or host:port:user:pass")
        host = parts[0]
        try:
            port = int(parts[1])
        except ValueError:
            raise HTTPException(400, "Port must be a number")
        username = parts[2] if len(parts) > 2 else None
        password = parts[3] if len(parts) > 3 else None
        label = None
    else:
        if not data.host or not data.port:
            raise HTTPException(400, "host and port required")
        host, port, username, password, label = data.host, data.port, data.username, data.password, data.label

    p = ProxyPool(host=host, port=port, proxy_type=data.proxy_type.upper(),
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
