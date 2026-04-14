import os


def runtime_role() -> str:
    return (os.getenv("TG_RUNTIME_ROLE", "all") or "all").strip().lower()


def owns_telegram_runtime() -> bool:
    return runtime_role() in {"all", "worker"}


def worker_url() -> str:
    return (os.getenv("TG_WORKER_URL", "") or "").strip().rstrip("/")


def worker_shared_token() -> str:
    return (os.getenv("WORKER_SHARED_TOKEN", "") or "").strip()


def app_auth_token() -> str:
    return (os.getenv("APP_AUTH_TOKEN", "") or "").strip()


def cors_allowed_origins() -> list[str]:
    raw = (os.getenv("CORS_ALLOWED_ORIGINS", "") or "").strip()
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
