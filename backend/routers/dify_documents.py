from __future__ import annotations

from typing import Optional

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from backend.dify_knowledge import DifyKnowledgeClient, DifyKnowledgeConfig, DifyKnowledgeError


router = APIRouter(prefix="/api/dify", tags=["dify"])


class DifyDocumentWrite(BaseModel):
    name: str
    text: str


@router.get("/status")
def dify_status():
    config = DifyKnowledgeConfig.from_env()
    return {
        "configured": config.is_configured,
        "api_base_url": config.api_base_url,
        "dataset_id": config.dataset_id,
        "has_api_key": bool(config.api_key),
    }


@router.get("/documents")
def list_dify_documents(page: int = 1, limit: int = 100, keyword: Optional[str] = None):
    try:
        payload = DifyKnowledgeClient().list_documents(page=page, limit=min(limit, 100), keyword=keyword)
    except DifyKnowledgeError as exc:
        raise HTTPException(400, str(exc)) from exc

    documents = payload.get("data") or payload.get("documents") or []
    return {
        "data": [_normalize_document(document) for document in documents],
        "page": payload.get("page", page),
        "limit": payload.get("limit", limit),
        "total": payload.get("total", len(documents)),
        "has_more": payload.get("has_more", False),
    }


@router.get("/documents/{document_id}")
def get_dify_document(document_id: str):
    try:
        client = DifyKnowledgeClient()
        document_payload = client.get_document(document_id=document_id)
        segments_payload = client.list_document_segments(document_id=document_id, limit=100)
    except DifyKnowledgeError as exc:
        raise HTTPException(400, str(exc)) from exc

    document = document_payload.get("document") or document_payload.get("data") or document_payload
    segments = segments_payload.get("data") or segments_payload.get("segments") or []
    return {
        "document": _normalize_document(document),
        "segments": [_normalize_segment(segment) for segment in segments],
        "text": _segments_to_text(segments),
        "raw": {
            "document": document_payload,
            "segments": segments_payload,
        },
    }


@router.post("/documents")
def create_dify_document(data: DifyDocumentWrite):
    name, text = _clean_document_payload(data)
    try:
        response = DifyKnowledgeClient().create_document_by_text(name=name, text=text)
    except DifyKnowledgeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "document_id": _extract_response_document_id(response), "raw": response}


@router.put("/documents/{document_id}")
def update_dify_document(document_id: str, data: DifyDocumentWrite):
    name, text = _clean_document_payload(data)
    try:
        response = DifyKnowledgeClient().update_document_by_text(document_id=document_id, name=name, text=text)
    except DifyKnowledgeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "document_id": _extract_response_document_id(response) or document_id, "raw": response}


@router.delete("/documents/{document_id}")
def delete_dify_document(document_id: str):
    try:
        response = DifyKnowledgeClient().delete_document(document_id=document_id)
    except DifyKnowledgeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "document_id": document_id, "raw": response}


def _clean_document_payload(data: DifyDocumentWrite) -> tuple[str, str]:
    name = data.name.strip()
    text = data.text.strip()
    if not name:
        raise HTTPException(422, "Название документа не может быть пустым")
    if not text:
        raise HTTPException(422, "Текст документа не может быть пустым")
    return name, text


def _normalize_document(document: dict) -> dict:
    return {
        "id": document.get("id"),
        "name": document.get("name") or document.get("title") or "Без названия",
        "enabled": document.get("enabled"),
        "archived": document.get("archived"),
        "indexing_status": document.get("indexing_status") or document.get("display_status") or document.get("status"),
        "display_status": document.get("display_status"),
        "word_count": document.get("word_count"),
        "tokens": document.get("tokens"),
        "segment_count": document.get("segment_count") or document.get("chunk_count"),
        "created_at": document.get("created_at"),
        "updated_at": document.get("updated_at"),
        "source_type": document.get("data_source_type") or document.get("source_type"),
        "raw": document,
    }


def _normalize_segment(segment: dict) -> dict:
    return {
        "id": segment.get("id"),
        "position": segment.get("position"),
        "content": _segment_content(segment),
        "answer": segment.get("answer"),
        "keywords": segment.get("keywords") or [],
        "enabled": segment.get("enabled"),
        "word_count": segment.get("word_count"),
        "tokens": segment.get("tokens"),
        "raw": segment,
    }


def _segments_to_text(segments: list[dict]) -> str:
    ordered = sorted(segments, key=lambda item: item.get("position") or 0)
    parts = [_segment_content(segment).strip() for segment in ordered]
    return "\n\n".join(part for part in parts if part)


def _segment_content(segment: dict) -> str:
    return segment.get("content") or segment.get("text") or segment.get("body") or ""


def _extract_response_document_id(response: dict) -> str | None:
    return (response.get("document") or {}).get("id") or response.get("id")
