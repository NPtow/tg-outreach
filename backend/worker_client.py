from typing import Any

import httpx
from fastapi import HTTPException

from backend.runtime_config import owns_telegram_runtime, worker_shared_token, worker_url


async def forward_to_worker(method: str, path: str, json_body: dict[str, Any] | None = None) -> Any:
    if owns_telegram_runtime():
        raise RuntimeError("forward_to_worker should not be used when the current process owns the runtime")

    base_url = worker_url()
    if not base_url:
        raise HTTPException(503, "Telegram worker is not configured")

    headers = {}
    token = worker_shared_token()
    if token:
        headers["X-Worker-Token"] = token

    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.request(method, f"{base_url}{path}", json=json_body, headers=headers)

    if response.status_code >= 400:
        detail = response.text
        try:
            payload = response.json()
            detail = payload.get("detail", detail)
        except Exception:
            pass
        raise HTTPException(response.status_code, detail)

    return response.json() if response.content else None
