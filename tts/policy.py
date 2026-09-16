"""Small validation helpers for TTS settings and request boundaries."""

from __future__ import annotations

import re

_EDGE_VOICE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_PIPER_VOICE = re.compile(r"^[A-Za-z0-9_-]{1,96}$")
TTS_PROVIDERS = ("off", "browser", "edge", "local")
TTS_FALLBACKS = ("browser", "piper", "none")


def normalize_provider(value: object, default: str = "browser") -> str:
    candidate = str(value or default).strip().lower()
    return candidate if candidate in TTS_PROVIDERS else default


def normalize_edge_voice(value: object) -> str:
    candidate = str(value or "en-US-AvaNeural").strip()
    return candidate if _EDGE_VOICE.fullmatch(candidate) else "en-US-AvaNeural"


def normalize_piper_voice(value: object) -> str:
    candidate = str(value or "en_US-lessac-medium").strip()
    return candidate if _PIPER_VOICE.fullmatch(candidate) else "en_US-lessac-medium"


def normalize_fallback(value: object) -> str:
    candidate = str(value or "browser").strip().lower()
    return candidate if candidate in TTS_FALLBACKS else "browser"
