import asyncio
import time
from typing import Optional

from python_socks import ProxyType
from python_socks.async_.asyncio import Proxy


SUPPORTED_PROXY_TYPES = ("HTTP", "SOCKS5", "SOCKS4")
TELEGRAM_PROBE_HOST = "149.154.167.50"
TELEGRAM_PROBE_PORT = 443
PROXY_PROBE_TIMEOUT_S = 8.0

_PYTHON_SOCKS_TYPES = {
    "HTTP": ProxyType.HTTP,
    "SOCKS5": ProxyType.SOCKS5,
    "SOCKS4": ProxyType.SOCKS4,
}
_TELETHON_PROXY_TYPES = {
    "HTTP": "http",
    "SOCKS5": "socks5",
    "SOCKS4": "socks4",
}


def normalize_proxy_type(value: Optional[str], default: str = "SOCKS5") -> str:
    proxy_type = (value or default or "SOCKS5").strip().upper()
    if proxy_type not in SUPPORTED_PROXY_TYPES:
        raise ValueError(f"Unsupported proxy type: {value}")
    return proxy_type


def telethon_proxy_type(value: Optional[str]) -> str:
    return _TELETHON_PROXY_TYPES[normalize_proxy_type(value)]


def proxy_type_candidates(preferred_type: Optional[str] = None) -> list[str]:
    candidates: list[str] = []
    if preferred_type:
        candidates.append(normalize_proxy_type(preferred_type))
    # HTTP first catches common provider exports where the UI previously saved SOCKS5.
    for proxy_type in ("HTTP", "SOCKS5", "SOCKS4"):
        if proxy_type not in candidates:
            candidates.append(proxy_type)
    return candidates


async def probe_proxy_type(
    *,
    host: str,
    port: int,
    proxy_type: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    dest_host: str = TELEGRAM_PROBE_HOST,
    dest_port: int = TELEGRAM_PROBE_PORT,
    timeout_s: float = PROXY_PROBE_TIMEOUT_S,
) -> dict:
    normalized_type = normalize_proxy_type(proxy_type)
    started = time.perf_counter()
    try:
        proxy = Proxy.create(
            proxy_type=_PYTHON_SOCKS_TYPES[normalized_type],
            host=str(host).strip(),
            port=int(port),
            username=str(username).strip() if username else None,
            password=str(password) if password else None,
        )
        sock = await asyncio.wait_for(
            proxy.connect(dest_host=dest_host, dest_port=dest_port),
            timeout=timeout_s,
        )
        sock.close()
        return {
            "ok": True,
            "proxy_type": normalized_type,
            "rtt_ms": int((time.perf_counter() - started) * 1000),
        }
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "proxy_type": normalized_type,
            "error_type": "TimeoutError",
            "error": "Proxy connection timed out",
        }
    except Exception as exc:
        return {
            "ok": False,
            "proxy_type": normalized_type,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


async def detect_proxy_type(
    *,
    host: str,
    port: int,
    username: Optional[str] = None,
    password: Optional[str] = None,
    preferred_type: Optional[str] = None,
    timeout_s: float = PROXY_PROBE_TIMEOUT_S,
) -> dict:
    candidates = proxy_type_candidates(preferred_type)
    attempts = []
    if preferred_type:
        preferred = await probe_proxy_type(
            host=host,
            port=port,
            proxy_type=candidates[0],
            username=username,
            password=password,
            timeout_s=timeout_s,
        )
        attempts.append(preferred)
        if preferred.get("ok"):
            return {
                "ok": True,
                "proxy_type": preferred["proxy_type"],
                "rtt_ms": preferred.get("rtt_ms"),
                "attempts": attempts,
            }
        candidates = candidates[1:]

    attempts.extend(
        await asyncio.gather(
            *[
                probe_proxy_type(
                    host=host,
                    port=port,
                    proxy_type=proxy_type,
                    username=username,
                    password=password,
                    timeout_s=timeout_s,
                )
                for proxy_type in candidates
            ]
        )
    )
    for proxy_type in candidates:
        match = next((attempt for attempt in attempts if attempt["proxy_type"] == proxy_type), None)
        if match and match.get("ok"):
            return {"ok": True, "proxy_type": proxy_type, "rtt_ms": match.get("rtt_ms"), "attempts": attempts}
    return {"ok": False, "attempts": attempts}
