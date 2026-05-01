from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
import re
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from backend.models import ScenarioCard


class DifyKnowledgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DifyKnowledgeConfig:
    api_base_url: str
    api_key: str
    dataset_id: str
    indexing_technique: str = "high_quality"
    doc_form: str = "text_model"
    doc_language: str = "Russian"
    timeout_s: float = 30.0

    @classmethod
    def from_env(cls) -> "DifyKnowledgeConfig":
        return cls(
            api_base_url=os.getenv("DIFY_API_BASE_URL", "http://127.0.0.1/v1").rstrip("/"),
            api_key=os.getenv("DIFY_API_KEY", ""),
            dataset_id=os.getenv("DIFY_DATASET_ID", ""),
            indexing_technique=os.getenv("DIFY_INDEXING_TECHNIQUE", "high_quality"),
            doc_form=os.getenv("DIFY_DOC_FORM", "text_model"),
            doc_language=os.getenv("DIFY_DOC_LANGUAGE", "Russian"),
            timeout_s=float(os.getenv("DIFY_TIMEOUT_S", "30")),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.api_base_url and self.api_key and self.dataset_id)


class DifyKnowledgeClientProtocol(Protocol):
    def create_document_by_text(self, *, name: str, text: str) -> dict:
        ...

    def update_document_by_text(self, *, document_id: str, name: str, text: str) -> dict:
        ...


class DifyKnowledgeClient:
    def __init__(self, config: DifyKnowledgeConfig | None = None):
        self.config = config or DifyKnowledgeConfig.from_env()
        if not self.config.is_configured:
            raise DifyKnowledgeError("Dify is not configured: set DIFY_API_BASE_URL, DIFY_API_KEY, DIFY_DATASET_ID")

    def create_document_by_text(self, *, name: str, text: str) -> dict:
        payload = self._document_payload(name=name, text=text)
        return self._post_with_aliases(
            [
                f"/datasets/{self.config.dataset_id}/document/create-by-text",
                f"/datasets/{self.config.dataset_id}/document/create_by_text",
            ],
            payload,
        )

    def update_document_by_text(self, *, document_id: str, name: str, text: str) -> dict:
        payload = self._document_payload(name=name, text=text, include_indexing=False)
        return self._post_with_aliases(
            [
                f"/datasets/{self.config.dataset_id}/documents/{document_id}/update-by-text",
                f"/datasets/{self.config.dataset_id}/documents/{document_id}/update_by_text",
            ],
            payload,
        )

    def list_documents(self, *, page: int = 1, limit: int = 100, keyword: str | None = None) -> dict:
        params: dict[str, str | int] = {"page": page, "limit": limit}
        if keyword:
            params["keyword"] = keyword
        return self._get(f"/datasets/{self.config.dataset_id}/documents", params=params)

    def get_document(self, *, document_id: str) -> dict:
        return self._get(f"/datasets/{self.config.dataset_id}/documents/{document_id}")

    def list_document_segments(self, *, document_id: str, page: int = 1, limit: int = 100) -> dict:
        return self._get(
            f"/datasets/{self.config.dataset_id}/documents/{document_id}/segments",
            params={"page": page, "limit": limit},
        )

    def _document_payload(self, *, name: str, text: str, include_indexing: bool = True) -> dict:
        payload = {
            "name": name,
            "text": text,
            "doc_form": self.config.doc_form,
            "doc_language": self.config.doc_language,
            "process_rule": {"mode": "automatic"},
        }
        if include_indexing:
            payload["indexing_technique"] = self.config.indexing_technique
        return payload

    def _post_with_aliases(self, paths: list[str], payload: dict) -> dict:
        last_error: Exception | None = None
        with httpx.Client(timeout=self.config.timeout_s) as client:
            for path in paths:
                url = f"{self.config.api_base_url}{path}"
                try:
                    response = client.post(url, headers=self._headers(), json=payload)
                    if response.status_code == 404 and path != paths[-1]:
                        last_error = DifyKnowledgeError(f"Dify endpoint not found: {path}")
                        continue
                    response.raise_for_status()
                    return response.json()
                except Exception as exc:
                    last_error = exc
                    if path == paths[-1]:
                        break
        raise DifyKnowledgeError(str(last_error))

    def _get(self, path: str, *, params: dict | None = None) -> dict:
        url = f"{self.config.api_base_url}{path}"
        try:
            with httpx.Client(timeout=self.config.timeout_s) as client:
                response = client.get(url, headers=self._headers(), params=params)
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            raise DifyKnowledgeError(str(exc)) from exc

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }


def build_scenario_dify_document(card: ScenarioCard) -> dict:
    scenario_id = card.id or "new"
    title = (card.title or f"Scenario {scenario_id}").strip()
    tags = ", ".join(tag.strip() for tag in (card.tags or "").split(",") if tag.strip())
    source = card.source_conversation_id or ""
    text = "\n".join(
        [
            f"# {title}",
            "",
            "```metadata",
            "type: scenario_card",
            f"scenario_id: {scenario_id}",
            f"intent: {card.intent or ''}",
            f"status: {card.status or ''}",
            f"tags: {tags}",
            f"source_conversation_id: {source}",
            "```",
            "",
            "## Когда применять",
            card.trigger_summary or "",
            "",
            "## Как отвечать",
            card.recommended_reply or "",
            "",
            "## Чего избегать",
            card.avoid_reply or "",
            "",
            "## Служебные данные",
            f"- ID сценария: {scenario_id}",
            f"- Тип: {card.intent or ''}",
            f"- Статус: {card.status or ''}",
        ]
    ).strip()
    return {
        "name": f"scenario-{scenario_id}-{_slugify(title)}.md",
        "text": text,
    }


def sync_scenarios_to_dify(
    db: Session,
    *,
    client: DifyKnowledgeClientProtocol | None = None,
    status: str = "active",
    limit: int | None = None,
) -> dict:
    dify_client = client or DifyKnowledgeClient()
    query = db.query(ScenarioCard).filter(ScenarioCard.status == status).order_by(ScenarioCard.id.asc())
    if limit:
        query = query.limit(limit)
    cards = query.all()

    created = 0
    updated = 0
    failed = 0
    items = []
    for card in cards:
        document = build_scenario_dify_document(card)
        try:
            if card.dify_document_id:
                response = dify_client.update_document_by_text(
                    document_id=card.dify_document_id,
                    name=document["name"],
                    text=document["text"],
                )
                updated += 1
                action = "updated"
            else:
                response = dify_client.create_document_by_text(name=document["name"], text=document["text"])
                card.dify_document_id = _extract_document_id(response)
                created += 1
                action = "created"
            card.dify_sync_status = "synced"
            card.dify_sync_error = None
            card.dify_synced_at = datetime.utcnow()
            items.append({"scenario_id": card.id, "action": action, "dify_document_id": card.dify_document_id})
        except Exception as exc:
            failed += 1
            card.dify_sync_status = "failed"
            card.dify_sync_error = str(exc)[:1000]
            items.append({"scenario_id": card.id, "action": "failed", "error": card.dify_sync_error})

    db.commit()
    return {
        "status": status,
        "total": len(cards),
        "created": created,
        "updated": updated,
        "failed": failed,
        "items": items,
    }


def _extract_document_id(response: dict) -> str:
    document_id = (response.get("document") or {}).get("id")
    if not document_id:
        raise DifyKnowledgeError("Dify response did not include document.id")
    return document_id


def _slugify(value: str) -> str:
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
        "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    normalized = "".join(translit.get(char, char) for char in value.lower())
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "scenario"
