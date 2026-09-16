"""Deterministic expressive controls for Edge speech.

No model calls, sentiment services, or SSML are used here. The module only maps
user-selected presets to bounded Edge prosody and builds a bounded pause plan.
"""

from __future__ import annotations

import re

TTS_TONES = (
    "neutral",
    "calm",
    "friendly",
    "cheerful",
    "serious",
    "sad",
    "angry",
    "dramatic",
    "narrator",
    "auto",
)
TTS_PAUSE_STYLES = ("off", "natural", "expressive")

# rate %, pitch Hz, volume %
_TONE_DELTAS: dict[str, tuple[int, int, int]] = {
    "neutral": (0, 0, 0),
    "calm": (-8, -4, -2),
    "friendly": (2, 3, 0),
    "cheerful": (8, 8, 4),
    "serious": (-4, -5, 1),
    "sad": (-10, -10, -4),
    "angry": (10, 4, 8),
    "dramatic": (-4, -2, 5),
    "narrator": (-6, -3, 2),
}

_MANUAL_PAUSE = re.compile(r"\[pause\s*:\s*(\d{1,5})\s*\]", re.IGNORECASE)
_BOUNDARY = re.compile(r"\[pause\s*:\s*\d{1,5}\s*\]|\n+|\.{3,}|[.!?]+|[,:;]|[—–]", re.IGNORECASE)

_PAUSES = {
    "natural": {
        "comma": 90,
        "semicolon": 140,
        "dash": 180,
        "sentence": 220,
        "ellipsis": 360,
        "line": 280,
        "paragraph": 480,
    },
    "expressive": {
        "comma": 150,
        "semicolon": 220,
        "dash": 320,
        "sentence": 340,
        "ellipsis": 550,
        "line": 420,
        "paragraph": 700,
    },
}


def normalize_tone(value: object) -> str:
    candidate = str(value or "neutral").strip().lower()
    return candidate if candidate in TTS_TONES else "neutral"


def normalize_pause_style(value: object) -> str:
    candidate = str(value or "natural").strip().lower()
    return candidate if candidate in TTS_PAUSE_STYLES else "natural"


def resolve_tone(value: object, text: str = "") -> str:
    """Resolve AUTO with conservative, local, deterministic text cues."""
    tone = normalize_tone(value)
    if tone != "auto":
        return tone

    sample = str(text or "").strip().lower()
    if not sample:
        return "neutral"
    if re.search(r"\b(warning|critical|danger|security|failed|failure|error|unsafe|urgent)\b", sample):
        return "serious"
    if re.search(r"\b(unfortunately|sorry|regret|sad|lost|could not be recovered|cannot recover)\b", sample):
        return "sad"
    if re.search(r"\b(great|excellent|nice|success|successful|worked|complete|completed|ready)\b", sample) and "!" in sample:
        return "cheerful"
    if len(sample) >= 110 or re.search(r"\b(step|steps|first|second|next|configure|configuration|procedure|instructions?)\b", sample):
        return "narrator"
    return "friendly"


def _signed(value: int, suffix: str) -> str:
    return f"{value:+d}{suffix}"


def resolve_edge_prosody(
    tone: object,
    *,
    intensity: float = 0.7,
    speed: float = 1.0,
    pitch: float = 1.0,
    volume: float = 1.0,
    text: str = "",
) -> dict[str, str]:
    """Combine a tone preset with existing manual rate/pitch/volume controls."""
    resolved = resolve_tone(tone, text)
    try:
        strength = max(0.0, min(1.0, float(intensity)))
    except Exception:
        strength = 0.7
    try:
        speed_value = max(0.5, min(2.0, float(speed)))
    except Exception:
        speed_value = 1.0
    try:
        pitch_value = max(0.5, min(2.0, float(pitch)))
    except Exception:
        pitch_value = 1.0
    try:
        volume_value = max(0.5, min(1.5, float(volume)))
    except Exception:
        volume_value = 1.0

    tone_rate, tone_pitch, tone_volume = _TONE_DELTAS.get(resolved, (0, 0, 0))
    manual_rate = round((speed_value - 1.0) * 100)
    manual_pitch = round((pitch_value - 1.0) * 20)
    manual_volume = round((volume_value - 1.0) * 100)

    rate = max(-50, min(100, manual_rate + round(tone_rate * strength)))
    pitch_hz = max(-50, min(50, manual_pitch + round(tone_pitch * strength)))
    volume_pct = max(-50, min(50, manual_volume + round(tone_volume * strength)))
    return {
        "tone": resolved,
        "rate": _signed(rate, "%"),
        "pitch": _signed(pitch_hz, "Hz"),
        "volume": _signed(volume_pct, "%"),
    }


def _pause_kind(token: str) -> str:
    if token.startswith("\n"):
        return "paragraph" if token.count("\n") >= 2 else "line"
    if token.startswith("..."):
        return "ellipsis"
    if token in ("—", "–"):
        return "dash"
    if token in (",",):
        return "comma"
    if token in (";", ":"):
        return "semicolon"
    return "sentence"


def build_speech_plan(text: str, *, style: object = "natural", maximum_segments: int = 24) -> list[dict[str, object]]:
    """Split speech into bounded client-playback segments with real pause delays.

    Manual ``[pause:NNN]`` markers are always honored and capped to 2000 ms.
    Automatic punctuation pauses are disabled when style is ``off``.
    """
    value = str(text or "").replace("\x00", " ").strip()
    if not value:
        return []
    pause_style = normalize_pause_style(style)
    maximum_segments = max(1, min(48, int(maximum_segments or 24)))

    if pause_style == "off" and not _MANUAL_PAUSE.search(value):
        clean = re.sub(r"\s+", " ", value).strip()
        return [{"text": clean, "pause_after_ms": 0}] if clean else []

    plan: list[dict[str, object]] = []
    current = ""
    pos = 0

    def flush(pause_ms: int) -> None:
        nonlocal current
        spoken = re.sub(r"\s+", " ", current).strip()
        current = ""
        if spoken:
            plan.append({"text": spoken, "pause_after_ms": max(0, min(2000, int(pause_ms)))})
        elif plan and pause_ms:
            plan[-1]["pause_after_ms"] = max(int(plan[-1]["pause_after_ms"]), max(0, min(2000, int(pause_ms))))

    for match in _BOUNDARY.finditer(value):
        current += value[pos:match.start()]
        token = match.group(0)
        manual = _MANUAL_PAUSE.fullmatch(token)
        if manual:
            flush(min(2000, int(manual.group(1))))
        elif token.startswith("\n"):
            if pause_style == "off":
                current += " "
            else:
                flush(_PAUSES[pause_style][_pause_kind(token)])
        else:
            current += token
            if pause_style != "off":
                kind = _pause_kind(token)
                # Avoid turning every tiny comma fragment into a network call.
                if kind not in {"comma", "semicolon"} or len(current.strip()) >= 24:
                    flush(_PAUSES[pause_style][kind])
        pos = match.end()

    current += value[pos:]
    flush(0)
    if not plan:
        return []

    if len(plan) > maximum_segments:
        head = plan[: maximum_segments - 1]
        tail = plan[maximum_segments - 1 :]
        merged_text = " ".join(str(item["text"]).strip() for item in tail if str(item["text"]).strip())
        head.append({"text": merged_text, "pause_after_ms": int(tail[-1]["pause_after_ms"]) if tail else 0})
        plan = head
    return plan
