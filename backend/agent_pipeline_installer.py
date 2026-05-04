from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models import Account, AgentPipeline, AgentPipelineVersion, AgentRuntimeConfigRegistry, Settings
from backend.n8n_workspace import (
    N8nWorkspaceError,
    extract_webhook_path,
    n8n_request,
    normalize_n8n_base_url,
    production_webhook_url,
    workflow_editor_url,
)
from backend.projects import resolve_project_id
from backend.security import encrypt_value


VALID_INSTALL_MODES = {"sandbox", "shadow", "live"}
VALID_PIPELINE_STATUSES = {"draft", "active", "archived"}

DROP_N8N_EXPORT_KEYS = {
    "id",
    "active",
    "createdAt",
    "updatedAt",
    "versionId",
    "triggerCount",
    "shared",
    "tags",
    "pinData",
}

SECRETISH_KEYS = {
    "api_key",
    "apikey",
    "apiKey",
    "authorization",
    "bearer",
    "client_secret",
    "clientSecret",
    "password",
    "private_key",
    "privateKey",
    "refresh_token",
    "refreshToken",
    "secret",
    "token",
}

SECRET_VALUE_PATTERN = re.compile(
    r"(sk-(?:proj-)?[A-Za-z0-9_-]{10,}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{20,}|"
    r"ya29\.[0-9A-Za-z._-]{10,}|gh[pousr]_[0-9A-Za-z_]{10,}|Bearer\s+[0-9A-Za-z._-]{20,})"
)


class PipelineInstallError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class RegistryValue:
    value: str
    key: str
    source: str
    is_secret: bool


@dataclass
class N8nPipelineInstallResult:
    pipeline: AgentPipeline
    workflow: dict[str, Any]
    settings_sync: dict[str, dict[str, Any]]
    assigned_account_ids: list[int]
    warnings: list[str]


@dataclass
class N8nRuntimeConnection:
    base_url: str
    api_key: str
    environment: str
    project_key: str
    base_url_source: str
    api_key_source: str


@dataclass
class N8nRuntimeSetupStatus:
    base_url: str
    api_key: str
    environment: str
    project_key: str
    base_url_source: str
    api_key_source: str
    missing: list[str]


def default_registry_environment() -> str:
    return (
        os.getenv("RUNTIME_CONFIG_ENV")
        or os.getenv("APP_ENV")
        or os.getenv("RAILWAY_ENVIRONMENT_NAME")
        or os.getenv("RAILWAY_ENVIRONMENT")
        or ""
    ).strip()


def default_registry_project_key() -> str:
    return (os.getenv("RUNTIME_CONFIG_PROJECT_KEY") or os.getenv("PROJECT_KEY") or "tg-outreach").strip()


def _normal(value: Optional[str]) -> str:
    return (value or "").strip()


def _registry_row_score(row: AgentRuntimeConfigRegistry, *, environment: str, project_key: str, key_order: dict[str, int]) -> tuple:
    env = _normal(row.environment).lower()
    project = _normal(row.project_key).lower()
    desired_env = _normal(environment).lower()
    desired_project = _normal(project_key).lower()
    score = 0
    if desired_env and env == desired_env:
        score += 100
    elif not env:
        score += 10
    elif not desired_env:
        score += 1
    if desired_project and project == desired_project:
        score += 40
    elif not project:
        score += 5
    elif not desired_project:
        score += 1
    key_rank = len(key_order) - key_order.get(row.key, len(key_order))
    updated_at = row.updated_at or datetime.min
    return (score, key_rank, updated_at, row.id or 0)


def registry_value(
    db: Session,
    keys: Iterable[str],
    *,
    environment: str = "",
    project_key: str = "",
) -> Optional[RegistryValue]:
    key_list = [key for key in keys if key]
    if not key_list:
        return None
    rows = (
        db.query(AgentRuntimeConfigRegistry)
        .filter(AgentRuntimeConfigRegistry.key.in_(key_list))
        .filter(
            or_(
                AgentRuntimeConfigRegistry.status.is_(None),
                AgentRuntimeConfigRegistry.status == "",
                AgentRuntimeConfigRegistry.status == "active",
            )
        )
        .all()
    )
    rows = [row for row in rows if _normal(row.value)]
    if not rows:
        return None
    key_order = {key: index for index, key in enumerate(key_list)}
    row = sorted(
        rows,
        key=lambda item: _registry_row_score(item, environment=environment, project_key=project_key, key_order=key_order),
        reverse=True,
    )[0]
    return RegistryValue(value=_normal(row.value), key=row.key, source=row.source or "registry", is_secret=bool(row.is_secret))


def _google_redirect_keys(environment: str) -> list[str]:
    env = _normal(environment).lower()
    if "prod" in env:
        return ["GOOGLE_REDIRECT_URI_PRODUCTION", "GOOGLE_REDIRECT_URI"]
    if "stag" in env:
        return ["GOOGLE_REDIRECT_URI_STAGING", "GOOGLE_REDIRECT_URI"]
    if env in {"local", "dev", "development"}:
        return ["GOOGLE_REDIRECT_URI_LOCAL", "GOOGLE_REDIRECT_URI"]
    return [
        "GOOGLE_REDIRECT_URI",
        "GOOGLE_REDIRECT_URI_STAGING",
        "GOOGLE_REDIRECT_URI_PRODUCTION",
        "GOOGLE_REDIRECT_URI_LOCAL",
    ]


def _settings_bindings(environment: str) -> list[dict[str, Any]]:
    return [
        {"canonical": "OPENAI_PROVIDER", "keys": ["OPENAI_PROVIDER"], "column": "provider", "secret": False},
        {"canonical": "OPENAI_MODEL_DEFAULT", "keys": ["OPENAI_MODEL_DEFAULT", "OPENAI_MODEL"], "column": "model", "secret": False},
        {"canonical": "OPENAI_API_KEY", "keys": ["OPENAI_API_KEY"], "column": "openai_key", "secret": True},
        {"canonical": "GOOGLE_CLIENT_ID", "keys": ["GOOGLE_CLIENT_ID"], "column": "google_client_id", "secret": False},
        {"canonical": "GOOGLE_CLIENT_SECRET", "keys": ["GOOGLE_CLIENT_SECRET"], "column": "google_client_secret", "secret": True},
        {"canonical": "GOOGLE_REDIRECT_URI", "keys": _google_redirect_keys(environment), "column": "google_redirect_uri", "secret": False},
        {"canonical": "GOOGLE_OAUTH_STATE_SECRET", "keys": ["GOOGLE_OAUTH_STATE_SECRET"], "column": "google_oauth_state_secret", "secret": True},
        {"canonical": "GOOGLE_CALENDAR_EMAIL", "keys": ["GOOGLE_CALENDAR_EMAIL"], "column": "google_calendar_email", "secret": False},
        {"canonical": "ZOOM_ACCOUNT_ID", "keys": ["ZOOM_ACCOUNT_ID"], "column": "zoom_account_id", "secret": False},
        {"canonical": "ZOOM_CLIENT_ID", "keys": ["ZOOM_CLIENT_ID"], "column": "zoom_client_id", "secret": False},
        {"canonical": "ZOOM_CLIENT_SECRET", "keys": ["ZOOM_CLIENT_SECRET"], "column": "zoom_client_secret", "secret": True},
        {"canonical": "ZOOM_HOST_EMAIL", "keys": ["ZOOM_HOST_EMAIL"], "column": "zoom_host_email", "secret": False},
    ]


def sync_settings_from_registry(
    db: Session,
    *,
    environment: str = "",
    project_key: str = "",
) -> dict[str, dict[str, Any]]:
    settings = db.query(Settings).filter(Settings.id == 1).first()
    if not settings:
        settings = Settings(id=1)
        db.add(settings)
        db.flush()

    report: dict[str, dict[str, Any]] = {}
    for binding in _settings_bindings(environment):
        found = registry_value(db, binding["keys"], environment=environment, project_key=project_key)
        canonical = binding["canonical"]
        report[canonical] = {
            "configured": bool(found),
            "target": f"settings.{binding['column']}",
            "secret": bool(binding["secret"]),
            "source_key": found.key if found else None,
        }
        if not found:
            continue
        value = found.value
        if binding["secret"]:
            setattr(settings, binding["column"], encrypt_value(value))
        else:
            setattr(settings, binding["column"], value)
    return report


def _is_secret_placeholder(value: str) -> bool:
    text = value.strip()
    if not text:
        return True
    lowered = text.lower()
    if "$env." in lowered or "process.env" in lowered or "${" in text:
        return True
    if lowered.startswith(("your_", "replace_", "placeholder", "todo", "<")):
        return True
    if "api_key" in lowered and any(marker in lowered for marker in ("your", "replace", "example", "placeholder")):
        return True
    return False


def _find_hardcoded_secrets(value: Any, *, path: str = "$", key_hint: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            findings.extend(_find_hardcoded_secrets(child, path=child_path, key_hint=str(key)))
        return findings
    if isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_hardcoded_secrets(child, path=f"{path}[{index}]", key_hint=key_hint))
        return findings
    if not isinstance(value, str):
        return findings
    if _is_secret_placeholder(value):
        return findings
    normalized_key = re.sub(r"[^A-Za-z0-9]", "", key_hint).lower()
    secretish_key = normalized_key in {re.sub(r"[^A-Za-z0-9]", "", item).lower() for item in SECRETISH_KEYS}
    if SECRET_VALUE_PATTERN.search(value):
        findings.append(path)
    elif secretish_key and len(value.strip()) >= 12:
        findings.append(path)
    return findings


def validate_workflow_for_install(workflow: dict[str, Any]) -> None:
    if not isinstance(workflow, dict):
        raise PipelineInstallError(400, "n8n workflow JSON must be an object")
    if not _normal(workflow.get("name")):
        raise PipelineInstallError(400, "n8n workflow name is required")
    if not isinstance(workflow.get("nodes"), list) or not workflow["nodes"]:
        raise PipelineInstallError(400, "n8n workflow must contain nodes")
    findings = _find_hardcoded_secrets(workflow)
    if findings:
        locations = ", ".join(findings[:5])
        suffix = "" if len(findings) <= 5 else f" and {len(findings) - 5} more"
        raise PipelineInstallError(400, f"Workflow contains hardcoded secret values at {locations}{suffix}. Use registry/env variables or n8n credentials instead.")
    if not extract_webhook_path(workflow):
        raise PipelineInstallError(400, "n8n workflow must contain a Webhook node with a path")


def sanitize_workflow_for_import(workflow: dict[str, Any]) -> dict[str, Any]:
    cleaned = copy.deepcopy(workflow)
    for key in DROP_N8N_EXPORT_KEYS:
        cleaned.pop(key, None)
    cleaned.setdefault("connections", {})
    cleaned.setdefault("settings", {})
    return cleaned


def _resolve_runtime_value(
    db: Session,
    *,
    explicit: str = "",
    keys: list[str],
    env_name: str,
    fallback_env_names: Optional[list[str]] = None,
    environment: str,
    project_key: str,
) -> tuple[str, str]:
    if _normal(explicit):
        return _normal(explicit), "request"
    found = registry_value(db, keys, environment=environment, project_key=project_key)
    if found:
        return found.value, f"registry:{found.key}"
    env_value = _normal(os.getenv(env_name))
    if env_value:
        return env_value, f"env:{env_name}"
    for fallback_env_name in fallback_env_names or []:
        env_value = _normal(os.getenv(fallback_env_name))
        if env_value:
            return env_value, f"env:{fallback_env_name}"
    return "", ""


def resolve_n8n_runtime_setup_status(
    db: Session,
    *,
    registry_environment: str = "",
    registry_project_key: str = "",
    n8n_base_url: str = "",
    n8n_api_key: str = "",
) -> N8nRuntimeSetupStatus:
    environment = _normal(registry_environment) or default_registry_environment()
    project_key = _normal(registry_project_key) or default_registry_project_key()
    base_url, base_url_source = _resolve_runtime_value(
        db,
        explicit=n8n_base_url,
        keys=["N8N_BASE_URL"],
        env_name="N8N_BASE_URL",
        fallback_env_names=["RAILWAY_SERVICE_N8N_URL", "WEBHOOK_URL"],
        environment=environment,
        project_key=project_key,
    )
    api_key, api_key_source = _resolve_runtime_value(
        db,
        explicit=n8n_api_key,
        keys=["N8N_API_KEY"],
        env_name="N8N_API_KEY",
        environment=environment,
        project_key=project_key,
    )
    base_url = normalize_n8n_base_url(base_url)
    missing: list[str] = []
    if not base_url:
        missing.append("N8N_BASE_URL")
    if not api_key:
        missing.append("N8N_API_KEY")
    return N8nRuntimeSetupStatus(
        base_url=base_url,
        api_key=api_key,
        environment=environment,
        project_key=project_key,
        base_url_source=base_url_source,
        api_key_source=api_key_source,
        missing=missing,
    )


def resolve_n8n_runtime_connection(
    db: Session,
    *,
    registry_environment: str = "",
    registry_project_key: str = "",
    n8n_base_url: str = "",
    n8n_api_key: str = "",
) -> N8nRuntimeConnection:
    setup = resolve_n8n_runtime_setup_status(
        db,
        registry_environment=registry_environment,
        registry_project_key=registry_project_key,
        n8n_base_url=n8n_base_url,
        n8n_api_key=n8n_api_key,
    )
    if "N8N_BASE_URL" in setup.missing:
        raise PipelineInstallError(400, "N8N_BASE_URL is required in request, registry, or environment")
    if "N8N_API_KEY" in setup.missing:
        raise PipelineInstallError(400, "N8N_API_KEY is required in request, registry, or environment")
    return N8nRuntimeConnection(
        base_url=setup.base_url,
        api_key=setup.api_key,
        environment=setup.environment,
        project_key=setup.project_key,
        base_url_source=setup.base_url_source,
        api_key_source=setup.api_key_source,
    )


def _response_data(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def _write_version(db: Session, pipeline: AgentPipeline, config: dict[str, Any]) -> None:
    latest = (
        db.query(AgentPipelineVersion)
        .filter(AgentPipelineVersion.pipeline_id == pipeline.id)
        .order_by(AgentPipelineVersion.version.desc(), AgentPipelineVersion.id.desc())
        .first()
    )
    next_version = (latest.version + 1) if latest else 1
    if latest:
        latest.is_active = False
    db.add(
        AgentPipelineVersion(
            pipeline_id=pipeline.id,
            version=next_version,
            config_json=json.dumps(config, ensure_ascii=False),
            is_active=True,
            created_by="n8n-installer",
        )
    )


async def install_n8n_pipeline(
    db: Session,
    *,
    workflow: dict[str, Any],
    project_id: Optional[int] = None,
    pipeline_id: Optional[int] = None,
    name: str = "",
    description: str = "",
    mode: str = "live",
    status: str = "active",
    assign_account_ids: Optional[list[int]] = None,
    registry_environment: str = "",
    registry_project_key: str = "",
    n8n_base_url: str = "",
    n8n_api_key: str = "",
    sync_settings: bool = True,
    activate_workflow: bool = True,
    shared_secret: str = "",
    timeout_s: float = 20.0,
) -> N8nPipelineInstallResult:
    validate_workflow_for_install(workflow)
    mode = _normal(mode) or "live"
    if mode not in VALID_INSTALL_MODES:
        raise PipelineInstallError(400, f"Invalid pipeline mode: {mode}")
    status = _normal(status) or "active"
    if status not in VALID_PIPELINE_STATUSES:
        raise PipelineInstallError(400, f"Invalid pipeline status: {status}")

    connection = resolve_n8n_runtime_connection(
        db,
        registry_environment=registry_environment,
        registry_project_key=registry_project_key,
        n8n_base_url=n8n_base_url,
        n8n_api_key=n8n_api_key,
    )
    environment = connection.environment
    project_key = connection.project_key
    settings_sync = sync_settings_from_registry(db, environment=environment, project_key=project_key) if sync_settings else {}
    base_url = connection.base_url
    api_key = connection.api_key

    existing_config: dict[str, Any] = {}
    pipeline: Optional[AgentPipeline] = None
    if pipeline_id is not None:
        pipeline = db.query(AgentPipeline).filter(AgentPipeline.id == int(pipeline_id)).first()
        if not pipeline:
            raise PipelineInstallError(404, "Pipeline not found")
        try:
            existing_config = json.loads(pipeline.config_json or "{}")
        except Exception:
            existing_config = {}

    requested_account_ids = [int(account_id) for account_id in (assign_account_ids or [])]
    accounts: list[Account] = []
    if requested_account_ids:
        accounts = db.query(Account).filter(Account.id.in_(requested_account_ids)).all()
        found_ids = {account.id for account in accounts}
        missing = sorted(set(requested_account_ids) - found_ids)
        if missing:
            raise PipelineInstallError(404, f"Account(s) not found: {', '.join(str(item) for item in missing)}")

    webhook_path = extract_webhook_path(workflow)
    import_body = sanitize_workflow_for_import(workflow)
    try:
        imported_raw = await n8n_request(
            base_url=base_url,
            api_key=api_key,
            method="POST",
            path="workflows",
            json_body=import_body,
            timeout_s=timeout_s,
        )
        imported = _response_data(imported_raw)
        workflow_id = _normal(str(imported.get("id") or ""))
        workflow_name = _normal(imported.get("name")) or _normal(workflow.get("name"))
        activated = False
        if activate_workflow and workflow_id:
            await n8n_request(
                base_url=base_url,
                api_key=api_key,
                method="POST",
                path=f"workflows/{workflow_id}/activate",
                timeout_s=timeout_s,
            )
            activated = True
    except N8nWorkspaceError as exc:
        raise PipelineInstallError(400, f"n8n import failed: {exc}") from exc

    warnings: list[str] = []
    if activate_workflow and not workflow_id:
        warnings.append("n8n did not return workflow id; activation was skipped")

    if pipeline is None:
        pipeline = AgentPipeline(project_id=resolve_project_id(db, project_id), name="n8n pipeline", type="n8n_webhook", status="draft", config_json="{}")
        db.add(pipeline)
        db.flush()

    resolved_project_id = pipeline.project_id if project_id is None and pipeline.project_id else resolve_project_id(db, project_id)
    final_name = _normal(name) or workflow_name or "n8n pipeline"
    pipeline.name = final_name
    pipeline.description = description if description is not None else (pipeline.description or "")
    pipeline.type = "n8n_webhook"
    pipeline.status = status
    pipeline.project_id = resolved_project_id
    config = {
        **existing_config,
        "n8n_base_url": base_url,
        "workflow_id": workflow_id,
        "workflow_name": workflow_name or final_name,
        "workflow_editor_url": workflow_editor_url(base_url, workflow_id),
        "webhook_path": webhook_path,
        "webhook_url": production_webhook_url(base_url, webhook_path),
        "mode": mode,
        "timeout_s": float(timeout_s or 20.0),
        "shared_secret": shared_secret or existing_config.get("shared_secret", ""),
        "runtime_config_source": "agent_runtime_config_registry",
        "runtime_registry_environment": environment,
        "runtime_registry_project_key": project_key,
        "installed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "n8n_base_url_source": connection.base_url_source,
        "n8n_api_key_source": connection.api_key_source,
        "workflow_activated": activated,
    }
    pipeline.config_json = json.dumps(config, ensure_ascii=False)
    pipeline.updated_at = datetime.utcnow()
    _write_version(db, pipeline, config)

    assigned_ids: list[int] = []
    for account in accounts:
        account.agent_pipeline_id = pipeline.id
        assigned_ids.append(account.id)

    db.commit()
    db.refresh(pipeline)
    return N8nPipelineInstallResult(
        pipeline=pipeline,
        workflow={
            "id": workflow_id,
            "name": workflow_name,
            "activated": activated,
            "webhook_path": webhook_path,
            "webhook_url": production_webhook_url(base_url, webhook_path),
            "editor_url": workflow_editor_url(base_url, workflow_id),
        },
        settings_sync=settings_sync,
        assigned_account_ids=sorted(assigned_ids),
        warnings=warnings,
    )
