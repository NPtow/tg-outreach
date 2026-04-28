from __future__ import annotations

from typing import Any, Optional

import httpx


class N8nWorkspaceError(Exception):
    pass


def normalize_n8n_base_url(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/")


def workflow_editor_url(base_url: str, workflow_id: Optional[str] = None) -> str:
    base = normalize_n8n_base_url(base_url)
    if not base:
        return ""
    if workflow_id:
        return f"{base}/workflow/{workflow_id}"
    return f"{base}/workflow/new"


def production_webhook_url(base_url: str, webhook_path: str) -> str:
    base = normalize_n8n_base_url(base_url)
    path = (webhook_path or "").strip().lstrip("/")
    if not base or not path:
        return ""
    if path.startswith("webhook/"):
        return f"{base}/{path}"
    return f"{base}/webhook/{path}"


def extract_webhook_path(workflow: dict[str, Any]) -> str:
    for node in workflow.get("nodes") or []:
        node_type = node.get("type") or ""
        if node_type.endswith(".webhook") or node_type == "n8n-nodes-base.webhook":
            params = node.get("parameters") or {}
            path = params.get("path")
            if path:
                return str(path)
    return ""


async def n8n_request(
    *,
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    json_body: Optional[dict[str, Any]] = None,
    timeout_s: float = 20.0,
) -> Any:
    base = normalize_n8n_base_url(base_url)
    if not base:
        raise N8nWorkspaceError("n8n base URL is required")
    if not api_key:
        raise N8nWorkspaceError("n8n API key is required")
    url = f"{base}/api/v1/{path.lstrip('/')}"
    headers = {"Accept": "application/json", "X-N8N-API-KEY": api_key}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.request(method, url, json=json_body, headers=headers)
        response.raise_for_status()
        if response.content:
            return response.json()
        return {"ok": True}
    except Exception as exc:
        detail = getattr(getattr(exc, "response", None), "text", None)
        raise N8nWorkspaceError(detail or str(exc)) from exc
