"""Local web boundary checks for MatrixStudio2.0.

The app intentionally has no LAN-facing mode. These helpers defend the local
HTTP surface against DNS rebinding, cross-site browser actions, and mislabeled
image uploads without introducing account/auth state into a localhost desktop app.
"""

from __future__ import annotations

from urllib.parse import urlsplit

_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}


def _hostname(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        # urlsplit needs a scheme to parse host:port reliably.
        parsed = urlsplit(raw if "://" in raw else f"http://{raw}")
        return (parsed.hostname or "").lower().rstrip(".")
    except Exception:
        return ""


def host_header_is_loopback(host_header: str | None) -> bool:
    return _hostname(str(host_header or "")) in _LOOPBACK_NAMES


def origin_matches_request(origin: str | None, request_base: str) -> bool:
    value = str(origin or "").strip()
    if not value or value.lower() == "null":
        return False
    try:
        src = urlsplit(value)
        dst = urlsplit(str(request_base or ""))
    except Exception:
        return False
    if src.scheme not in {"http", "https"} or dst.scheme not in {"http", "https"}:
        return False
    if (src.hostname or "").lower().rstrip(".") not in _LOOPBACK_NAMES:
        return False
    if (dst.hostname or "").lower().rstrip(".") not in _LOOPBACK_NAMES:
        return False
    src_port = src.port or (443 if src.scheme == "https" else 80)
    dst_port = dst.port or (443 if dst.scheme == "https" else 80)
    return src.scheme == dst.scheme and src_port == dst_port and (src.hostname or "").lower().rstrip(".") == (dst.hostname or "").lower().rstrip(".")


def valid_image_signature(data: bytes, content_type: str) -> bool:
    sample = bytes(data[:16] if data else b"")
    kind = str(content_type or "").split(";", 1)[0].strip().lower()
    if kind == "image/png":
        return sample.startswith(b"\x89PNG\r\n\x1a\n")
    if kind == "image/jpeg":
        return len(sample) >= 3 and sample[:3] == b"\xff\xd8\xff"
    if kind == "image/webp":
        return len(sample) >= 12 and sample[:4] == b"RIFF" and sample[8:12] == b"WEBP"
    return False


def security_headers(path: str = "") -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
        "Content-Security-Policy": (
            "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
            "form-action 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'"
        ),
    }
    if str(path or "").startswith("/api/"):
        headers["Cache-Control"] = "no-store"
    return headers
