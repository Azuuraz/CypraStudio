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
    # Deliberately stronger than the first expression pass. Edge's free
    # endpoint does not expose native emotional styles, so tiny prosody
    # offsets were effectively inaudible on many voices.
    "neutral": (0, 0, 0),
    "calm": (-14, -9, -4),
    "friendly": (7, 7, 2),
    "cheerful": (16, 18, 8),
    "serious": (-9, -12, 4),
    "sad": (-18, -18, -8),
    "angry": (18, 11, 12),
    "dramatic": (-12, -11, 11),
    "narrator": (-10, -7, 5),
}

_MANUAL_PAUSE = re.compile(r"\[pause\s*:\s*(\d{1,5})\s*\]", re.IGNORECASE)

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


def _shape_pause_cues(text: str, style: str) -> str:
    """Strengthen punctuation without creating another Edge network request.

    Edge already interprets punctuation prosodically. Expressive mode adds
    non-spoken ellipsis cues after stronger boundaries so pauses are more
    noticeable while synthesis remains a single request for ordinary text.
    """
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value or style != "expressive":
        return value

    # Normalize existing ASCII ellipses first so we do not repeatedly amplify
    # text when a plan is rebuilt. The Unicode ellipsis is retained by the
    # speech sanitizers and interpreted as punctuation by Edge.
    value = re.sub(r"\.{3,}", "…", value)
    value = re.sub(r"([.!?])\s+(?=[A-Z0-9\"'\(])", r"\1 … ", value)
    value = re.sub(r"([;:])\s+", r"\1 … ", value)
    value = re.sub(r"\s*[—–]\s*", " — … ", value)
    return re.sub(r"\s+", " ", value).strip()


def build_speech_plan(text: str, *, style: object = "natural", maximum_segments: int = 24) -> list[dict[str, object]]:
    """Build a bounded speech plan without multiplying Edge round-trips.

    Natural and expressive punctuation stay inside one synthesis request. Only
    explicit ``[pause:NNN]`` markers create additional requests because they
    require a deterministic client-side silence duration. Manual pauses remain
    capped to 2000 ms.
    """
    value = str(text or "").replace("\x00", " ").strip()
    if not value:
        return []
    pause_style = normalize_pause_style(style)
    maximum_segments = max(1, min(48, int(maximum_segments or 24)))

    matches = list(_MANUAL_PAUSE.finditer(value))
    if not matches:
        shaped = _shape_pause_cues(value, pause_style)
        return [{"text": shaped, "pause_after_ms": 0}] if shaped else []

    plan: list[dict[str, object]] = []
    pos = 0
    for match in matches:
        spoken = _shape_pause_cues(value[pos:match.start()], pause_style)
        pause_ms = min(2000, int(match.group(1)))
        if spoken:
            plan.append({"text": spoken, "pause_after_ms": pause_ms})
        elif plan:
            plan[-1]["pause_after_ms"] = max(int(plan[-1]["pause_after_ms"]), pause_ms)
        pos = match.end()

    tail = _shape_pause_cues(value[pos:], pause_style)
    if tail:
        plan.append({"text": tail, "pause_after_ms": 0})

    if not plan:
        return []
    if len(plan) > maximum_segments:
        head = plan[: maximum_segments - 1]
        tail_items = plan[maximum_segments - 1 :]
        merged_text = " ".join(str(item["text"]).strip() for item in tail_items if str(item["text"]).strip())
        head.append({"text": merged_text, "pause_after_ms": int(tail_items[-1]["pause_after_ms"]) if tail_items else 0})
        plan = head
    return plan

