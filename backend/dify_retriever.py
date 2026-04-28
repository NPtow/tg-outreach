from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

import httpx


@dataclass(frozen=True)
class DifyRetrievalConfig:
    api_base_url: str
    api_key: str
    dataset_id: str
    timeout_s: float = 30.0

    @classmethod
    def from_env(cls) -> "DifyRetrievalConfig":
        return cls(
            api_base_url=os.getenv("DIFY_API_BASE_URL", "").rstrip("/"),
            api_key=os.getenv("DIFY_API_KEY", ""),
            dataset_id=os.getenv("DIFY_DATASET_ID", ""),
            timeout_s=float(os.getenv("DIFY_TIMEOUT_S", "30")),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.api_base_url and self.api_key and self.dataset_id)


async def retrieve_dify_knowledge_cards(
    query: str,
    *,
    config: DifyRetrievalConfig | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    cfg = config or DifyRetrievalConfig.from_env()
    clean_query = (query or "").strip()
    result: dict[str, Any] = {
        "configured": cfg.is_configured,
        "query": clean_query,
        "cards": [],
        "error": None,
    }
    if not cfg.is_configured:
        result["error"] = "dify_not_configured"
        return result
    if not clean_query:
        result["error"] = "empty_query"
        return result

    payload = {
        "query": clean_query[:4000],
        "retrieval_model": {
            "search_method": "semantic_search",
            "reranking_enable": False,
            "top_k": max(1, min(int(top_k or 5), 10)),
            "score_threshold_enabled": False,
        },
    }
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = f"{cfg.api_base_url}/datasets/{cfg.dataset_id}/retrieve"

    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_s) as client:
            response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        raw = response.json()
        result["cards"] = [_normalize_record(record) for record in (raw.get("records") or [])]
        result["cards"] = [card for card in result["cards"] if card.get("content")]
        return result
    except Exception as exc:
        response = getattr(exc, "response", None)
        detail = getattr(response, "text", "") or str(exc)
        result["error"] = detail[:1000]
        return result


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    segment = record.get("segment") or {}
    document = record.get("document") or segment.get("document") or {}
    content = (segment.get("content") or record.get("content") or "").strip()
    title = (
        document.get("name")
        or segment.get("document_name")
        or record.get("document_name")
        or document.get("id")
        or ""
    )
    return {
        "source": "dify",
        "title": title,
        "score": record.get("score"),
        "content": content[:2500],
        "document_id": document.get("id") or record.get("document_id") or "",
        "segment_id": segment.get("id") or record.get("segment_id") or "",
    }
