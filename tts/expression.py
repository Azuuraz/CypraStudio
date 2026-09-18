"""Deterministic expressive controls for Edge speech.

No model calls, sentiment services, or SSML are used here. The module maps
local presets/cues to bounded Edge prosody and builds a bounded speech plan.
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
TTS_EXPRESSION_DETAILS = ("subtle", "natural", "lively")

# rate %, pitch Hz, volume %
_TONE_DELTAS: dict[str, tuple[int, int, int]] = {
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
_DETAIL_STRENGTH = {"subtle": 0.72, "natural": 1.0, "lively": 1.16}

_MANUAL_PAUSE = re.compile(r"\[pause\s*:\s*(\d{1,5})\s*\]", re.IGNORECASE)
_EXPRESSION_CUE = re.compile(r"\[(soft|excited|serious|slow|fast|emphasis|normal)\]", re.IGNORECASE)
_PLAN_TOKEN = re.compile(
    r"\[pause\s*:\s*(\d{1,5})\s*\]|\[(soft|excited|serious|slow|fast|emphasis|normal)\]",
    re.IGNORECASE,
)

_CUE_PROFILES: dict[str, dict[str, object]] = {
    "soft": {"tone": "calm", "rate_scale": 0.92, "pitch_scale": 0.96, "volume_scale": 0.88, "intensity_scale": 0.78},
    "excited": {"tone": "cheerful", "rate_scale": 1.10, "pitch_scale": 1.08, "volume_scale": 1.05, "intensity_scale": 1.15},
    "serious": {"tone": "serious", "rate_scale": 0.95, "pitch_scale": 0.96, "volume_scale": 1.02, "intensity_scale": 1.05},
    "slow": {"tone": None, "rate_scale": 0.82, "pitch_scale": 1.0, "volume_scale": 1.0, "intensity_scale": 1.0},
    "fast": {"tone": None, "rate_scale": 1.15, "pitch_scale": 1.0, "volume_scale": 1.0, "intensity_scale": 1.0},
    "emphasis": {"tone": None, "rate_scale": 0.96, "pitch_scale": 1.05, "volume_scale": 1.10, "intensity_scale": 1.08},
    "normal": {"tone": None, "rate_scale": 1.0, "pitch_scale": 1.0, "volume_scale": 1.0, "intensity_scale": 1.0},
}


def normalize_tone(value: object) -> str:
    candidate = str(value or "neutral").strip().lower()
    return candidate if candidate in TTS_TONES else "neutral"


def normalize_pause_style(value: object) -> str:
    candidate = str(value or "natural").strip().lower()
    return candidate if candidate in TTS_PAUSE_STYLES else "natural"


def normalize_expression_detail(value: object) -> str:
    candidate = str(value or "natural").strip().lower()
    return candidate if candidate in TTS_EXPRESSION_DETAILS else "natural"


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
    detail: object = "natural",
) -> dict[str, str]:
    """Combine a tone preset with manual controls and a bounded detail level."""
    resolved = resolve_tone(tone, text)
    try:
        strength = max(0.0, min(1.0, float(intensity)))
    except Exception:
        strength = 0.7
    strength *= _DETAIL_STRENGTH[normalize_expression_detail(detail)]
    strength = max(0.0, min(1.0, strength))
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


def shape_edge_text(text: str, style: object = "natural", detail: object = "natural") -> str:
    """Add punctuation-only cadence cues while keeping one Edge request.

    Edge already interprets punctuation prosodically. This local transform never
    calls another model and never requires another network round trip.
    """
    value = _PLAN_TOKEN.sub(" ", str(text or ""))
    value = re.sub(r"\s+", " ", value).strip()
    pause_style = normalize_pause_style(style)
    expression_detail = normalize_expression_detail(detail)
    if not value or pause_style == "off":
        return value

    value = re.sub(r"\.{3,}", "…", value)
    # Keep natural mode restrained. Expressive mode deliberately creates more
    # audible room at sentence/phrase boundaries, but still stays in one Edge
    # synthesis request unless the caller supplied explicit bracket cues.
    if pause_style == "natural":
        value = re.sub(r"\s*[—–]\s*", " — ", value)
        if expression_detail == "lively":
            value = re.sub(r"([!?])\s+(?=[A-Z0-9\"'\(])", r"\1 … ", value)
    else:
        if expression_detail == "subtle":
            value = re.sub(r"\s*[—–]\s*", " — … ", value)
        else:
            value = re.sub(r"([.!?])\s+(?=[A-Z0-9\"'\(])", r"\1 … ", value)
            value = re.sub(r"([;:])\s+", r"\1 … ", value)
            value = re.sub(r"\s*[—–]\s*", " — … ", value)
            if expression_detail == "lively":
                # Stronger question/exclamation recovery plus small clause
                # breathing room. No extra synthesis request is introduced.
                value = re.sub(r"([!?])\s+…\s+", r"\1 … … ", value)
                value = re.sub(r",\s+(?=(?:but|and|so|because|while|then|however)\b)", ", … ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip()


def _chunk_speech_text(text: str, maximum_chunk_chars: int) -> list[str]:
    """Split long speech at strong boundaries without dropping tail text."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    limit = max(400, min(5000, int(maximum_chunk_chars or 3200)))
    if not value:
        return []
    if len(value) <= limit:
        return [value]

    chunks: list[str] = []
    remaining = value
    minimum_cut = max(160, int(limit * 0.45))
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = -1
        for match in re.finditer(r"[.!?][\"')\]]*\s+", window):
            if match.end() >= minimum_cut:
                cut = match.end()
        if cut < minimum_cut:
            for match in re.finditer(r"[;:]\s+", window):
                if match.end() >= minimum_cut:
                    cut = match.end()
        if cut < minimum_cut:
            space = window.rfind(" ", minimum_cut)
            if space >= minimum_cut:
                cut = space + 1
        if cut <= 0:
            cut = limit
        chunk = remaining[:cut].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def build_speech_plan(
    text: str,
    *,
    style: object = "natural",
    detail: object = "natural",
    maximum_segments: int = 48,
    maximum_chunk_chars: int = 3200,
    first_chunk_chars: int | None = None,
) -> list[dict[str, object]]:
    """Build a bounded long-form/cue speech plan.

    Ordinary short speech stays one Edge request. Explicit cue markers may split
    the utterance so local prosody overrides can change without SSML. Long-form
    chunks are still prefetched by the client while current audio is playing.
    """
    value = str(text or "").replace("\x00", " ").strip()
    if not value:
        return []
    pause_style = normalize_pause_style(style)
    expression_detail = normalize_expression_detail(detail)
    maximum_segments = max(1, min(96, int(maximum_segments or 48)))
    maximum_chunk_chars = max(400, min(5000, int(maximum_chunk_chars or 3200)))

    plan: list[dict[str, object]] = []
    cue_state = dict(_CUE_PROFILES["normal"])
    expression_cues_seen = False

    def append_spoken(spoken: str, pause_ms: int = 0) -> None:
        shaped = shape_edge_text(spoken, pause_style, expression_detail)
        if not shaped:
            if pause_ms and plan:
                plan[-1]["pause_after_ms"] = max(int(plan[-1]["pause_after_ms"]), min(2000, max(0, int(pause_ms))))
            return
        chunks: list[str] = []
        if not plan and first_chunk_chars and maximum_segments > 1:
            opening_limit = max(400, min(maximum_chunk_chars, int(first_chunk_chars)))
            if len(shaped) > opening_limit:
                opening = _chunk_speech_text(shaped, opening_limit)[0]
                chunks.append(opening)
                shaped = shaped[len(opening):].strip()
        chunks.extend(_chunk_speech_text(shaped, maximum_chunk_chars))
        for chunk in chunks:
            item: dict[str, object] = {"text": chunk, "pause_after_ms": 0}
            if expression_cues_seen:
                item.update(cue_state)
            plan.append(item)
        if chunks and pause_ms:
            plan[-1]["pause_after_ms"] = min(2000, max(0, int(pause_ms)))

    pos = 0
    for match in _PLAN_TOKEN.finditer(value):
        append_spoken(value[pos:match.start()])
        pause_value, cue_name = match.group(1), match.group(2)
        if pause_value is not None:
            if plan:
                plan[-1]["pause_after_ms"] = max(int(plan[-1]["pause_after_ms"]), min(2000, max(0, int(pause_value))))
        elif cue_name:
            expression_cues_seen = True
            cue_state = dict(_CUE_PROFILES[cue_name.lower()])
        pos = match.end()
    append_spoken(value[pos:])

    if not plan:
        return []
    if len(plan) > maximum_segments:
        head = plan[: maximum_segments - 1]
        overflow = plan[maximum_segments - 1 :]
        overflow_text = " ".join(str(item["text"]).strip() for item in overflow if str(item["text"]).strip())
        tail: dict[str, object] = {"text": overflow_text.strip(), "pause_after_ms": 0}
        if expression_cues_seen and overflow:
            for key in ("tone", "rate_scale", "pitch_scale", "volume_scale", "intensity_scale"):
                if key in overflow[0]:
                    tail[key] = overflow[0][key]
        head.append(tail)
        plan = head
    return plan
