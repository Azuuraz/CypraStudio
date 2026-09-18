from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tts.policy import normalize_edge_voice, normalize_fallback, normalize_piper_voice, normalize_provider
from tts.expression import normalize_expression_detail, normalize_pause_style, normalize_tone

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SESSIONS = DATA / "sessions"
SESSION_TRASH = DATA / "trash" / "sessions"
SETTINGS_PATH = DATA / "settings.json"
SETTINGS_BACKUP_PATH = DATA / "settings.lastgood.json"
UI_STATE_PATH = DATA / "ui_state.json"
_LOCK = threading.RLock()

DEFAULT_SETTINGS: dict[str, Any] = {
    "settings_schema": 18,
    "port": 8765,
    "ollama_chat_model": "llama3.2:3b",
    "chat_provider": "local",
    "openrouter_allow_online": False,
    "openrouter_chat_model": "openrouter/free",
    "ollama_num_ctx": 8192,
    "ollama_keep_alive": "5m",
    "ollama_num_predict": -1,
    "chat_temperature": 0.65,
    "history_turns": 12,
    "retrieval_enabled": True,
    "retrieval_include_knowledge": True,
    "retrieval_include_older_chat": True,
    "retrieval_include_cross_chat": True,
    "retrieval_max_chunks": 4,
    "retrieval_max_chars": 3600,
    "think_mode": "auto",
    "show_model_thinking": True,
    "plain_chat": False,
    "show_generation_stats": True,
    "show_message_model": False,
    "auto_title_chats": True,
    "confirm_delete_chat": True,
    "voice_output_enabled": False,
    "tts_provider": "browser",
    "tts_allow_online": False,
    "tts_edge_voice": "en-US-AvaNeural",
    "tts_local_voice": "en_US-lessac-medium",
    "tts_online_fallback": "browser",
    "tts_rate": 1.0,
    "tts_pitch": 1.0,
    "tts_volume": 1.0,
    "tts_tone": "neutral",
    "tts_intensity": 0.7,
    "tts_pause_style": "natural",
    "tts_expression_detail": "natural",
    "tts_auto_speak": False,
    "tts_skip_code": True,
    "tts_skip_urls": True,
    "tts_max_chars": 50000,
    "tts_stop_previous": True,
    "tts_cpu_threads": 2,
    "stt_provider": "hybrid",
    "stt_allow_browser_online": False,
    "stt_local_model": "base.en",
    "stt_max_seconds": 60,
    "system_prompt": "Be accurate, practical, concise, and complete.",
    "selected_specialist_id": "",
    "ui_mode": "dark",
    "theme_preset": "matrix",
    "custom_colors_enabled": False,
    "accent_color": "#66e2ba",
    "accent_secondary": "#24d49a",
    "background_color": "#07100d",
    "panel_color": "#0a1215",
    "user_bubble_color": "#15302a",
    "assistant_bubble_color": "#111b22",
    "muted_text_color": "#82969a",
    "background_image_enabled": False,
    "background_image_version": 0,
    "background_image_opacity": 0.62,
    "background_blur": 16.0,
    "background_dim": 0.42,
    "background_zoom": 100.0,
    "background_fit": "preserve",
    "gradients_enabled": False,
    "gradient_strength": 0.42,
    "panel_opacity": 0.88,
    "panel_blur": 18.0,
    "glow_strength": 0.32,
    "ui_density": "comfortable",
    "ui_font_scale": 1.0,
    "chat_font_scale": 1.0,
    "reduce_motion": False,
    "companion_enabled": True,
    "companion_scale": 1.0,
    "companion_dock": "right",
    "companion_side_offset": 6,
    "companion_bottom_offset": 0,
    "companion_opacity": 1.0,
    "companion_animation_speed": 1.0,
    "companion_ambient_mode": "normal",
    "companion_click_reactions": True,
    "companion_state_reactions": True,
    "window_width": 1440,
    "window_height": 900,
}

DEFAULT_UI_STATE: dict[str, Any] = {
    "active_session_id": "",
    "draft": "",
    "session_drafts": {},
    "session_scroll": {},
    "sidebar_collapsed": False,
    "window_width": 1440,
    "window_height": 900,
}

CONTEXT_CHOICES = (4096, 8192, 16384, 32768, 65536, 131072)
THINK_CHOICES = {"auto", "standard", "deep"}
THEME_CHOICES = {"matrix", "ember", "violet", "ice"}
DENSITY_CHOICES = {"comfortable", "compact"}

RESET_SETTING_GROUPS: dict[str, frozenset[str]] = {
    "runtime": frozenset({"port", "ollama_chat_model", "chat_provider", "openrouter_allow_online", "openrouter_chat_model", "ollama_num_ctx", "ollama_keep_alive", "ollama_num_predict"}),
    "chat": frozenset({"chat_temperature", "history_turns", "plain_chat", "show_generation_stats", "show_message_model", "auto_title_chats", "confirm_delete_chat", "system_prompt", "retrieval_enabled", "retrieval_include_knowledge", "retrieval_include_older_chat", "retrieval_include_cross_chat", "retrieval_max_chunks", "retrieval_max_chars"}),
    "voice": frozenset({"voice_output_enabled", "tts_provider", "tts_allow_online", "tts_edge_voice", "tts_local_voice", "tts_online_fallback", "tts_rate", "tts_pitch", "tts_volume", "tts_tone", "tts_intensity", "tts_pause_style", "tts_expression_detail", "tts_auto_speak", "tts_skip_code", "tts_skip_urls", "tts_max_chars", "tts_stop_previous", "tts_cpu_threads", "stt_provider", "stt_allow_browser_online", "stt_local_model", "stt_max_seconds"}),
    "reasoning": frozenset({"think_mode", "show_model_thinking"}),
    "specialists": frozenset({"selected_specialist_id"}),
    "appearance": frozenset({"ui_mode", "theme_preset", "ui_density", "ui_font_scale", "chat_font_scale", "reduce_motion", "window_width", "window_height", "custom_colors_enabled", "accent_color", "accent_secondary", "background_color", "panel_color", "user_bubble_color", "assistant_bubble_color", "muted_text_color", "background_image_enabled", "background_image_version", "background_image_opacity", "background_blur", "background_dim", "background_zoom", "background_fit", "gradients_enabled", "gradient_strength", "panel_opacity", "panel_blur", "glow_strength"}),
    "companion": frozenset({"companion_enabled", "companion_scale", "companion_dock", "companion_side_offset", "companion_bottom_offset", "companion_opacity", "companion_animation_speed", "companion_ambient_mode", "companion_click_reactions", "companion_state_reactions"}),
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _coerce_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = dict(raw or {})
    out = deepcopy(DEFAULT_SETTINGS)
    out.update({k: v for k, v in src.items() if k in out})
    try:
        out["port"] = max(1024, min(65535, int(out["port"])))
    except Exception:
        out["port"] = DEFAULT_SETTINGS["port"]
    try:
        ctx = int(out["ollama_num_ctx"])
        out["ollama_num_ctx"] = min(CONTEXT_CHOICES, key=lambda x: abs(x - ctx))
    except Exception:
        out["ollama_num_ctx"] = DEFAULT_SETTINGS["ollama_num_ctx"]
    try:
        out["ollama_num_predict"] = int(out["ollama_num_predict"])
    except Exception:
        out["ollama_num_predict"] = -1
    try:
        out["chat_temperature"] = max(0.0, min(2.0, float(out["chat_temperature"])))
    except Exception:
        out["chat_temperature"] = DEFAULT_SETTINGS["chat_temperature"]
    try:
        out["history_turns"] = max(1, min(64, int(out["history_turns"])))
    except Exception:
        out["history_turns"] = DEFAULT_SETTINGS["history_turns"]
    provider = str(out.get("chat_provider") or "local").lower().strip()
    out["chat_provider"] = provider if provider in {"local", "openrouter"} else "local"
    openrouter_model = str(out.get("openrouter_chat_model") or "openrouter/free").strip()
    try:
        from engine import openrouter as _openrouter
        out["openrouter_chat_model"] = _openrouter.validate_model(openrouter_model)
    except Exception:
        out["openrouter_chat_model"] = "openrouter/free"
    think_mode = str(out["think_mode"]).lower()
    if think_mode == "on":
        think_mode = "standard"
    elif think_mode == "off":
        think_mode = "auto"
    out["think_mode"] = think_mode if think_mode in THINK_CHOICES else "auto"
    if str(out["theme_preset"]).lower() not in THEME_CHOICES:
        out["theme_preset"] = "matrix"
    if str(out["ui_density"]).lower() not in DENSITY_CHOICES:
        out["ui_density"] = "comfortable"
    out["ui_mode"] = "light" if str(out["ui_mode"]).lower() == "light" else "dark"
    for key in ("ui_font_scale", "chat_font_scale"):
        try:
            low = 0.75 if key == "ui_font_scale" else 0.8
            out[key] = max(low, min(1.4, float(out[key])))
        except Exception:
            out[key] = 1.0
    for key in ("window_width", "window_height"):
        try:
            floor = 900 if key == "window_width" else 650
            out[key] = max(floor, int(out[key]))
        except Exception:
            out[key] = DEFAULT_SETTINGS[key]
    try:
        out["companion_scale"] = max(0.55, min(1.60, float(out.get("companion_scale", 1.0))))
    except Exception:
        out["companion_scale"] = 1.0
    out["companion_dock"] = "left" if str(out.get("companion_dock", "right")).lower() == "left" else "right"
    for key, low, high in (("companion_side_offset", 0, 160), ("companion_bottom_offset", 0, 220)):
        try:
            out[key] = max(low, min(high, int(out.get(key, DEFAULT_SETTINGS[key]))))
        except Exception:
            out[key] = DEFAULT_SETTINGS[key]
    try:
        out["companion_opacity"] = max(0.35, min(1.0, float(out.get("companion_opacity", 1.0))))
    except Exception:
        out["companion_opacity"] = 1.0
    try:
        out["companion_animation_speed"] = max(0.50, min(1.75, float(out.get("companion_animation_speed", 1.0))))
    except Exception:
        out["companion_animation_speed"] = 1.0
    ambient_mode = str(out.get("companion_ambient_mode", "normal")).lower()
    out["companion_ambient_mode"] = ambient_mode if ambient_mode in {"off", "quiet", "normal", "lively"} else "normal"
    for key in ("openrouter_allow_online", "show_model_thinking", "plain_chat", "show_generation_stats", "show_message_model", "auto_title_chats", "confirm_delete_chat", "retrieval_enabled", "retrieval_include_knowledge", "retrieval_include_older_chat", "retrieval_include_cross_chat", "reduce_motion", "companion_enabled", "companion_click_reactions", "companion_state_reactions", "custom_colors_enabled", "background_image_enabled", "voice_output_enabled", "tts_allow_online", "tts_auto_speak", "tts_skip_code", "tts_skip_urls", "tts_stop_previous", "stt_allow_browser_online"):
        out[key] = _as_bool(out[key])
    out["tts_provider"] = normalize_provider(out.get("tts_provider"))
    out["tts_edge_voice"] = normalize_edge_voice(out.get("tts_edge_voice"))
    out["tts_local_voice"] = normalize_piper_voice(out.get("tts_local_voice"))
    out["tts_online_fallback"] = normalize_fallback(out.get("tts_online_fallback"))
    out["tts_tone"] = normalize_tone(out.get("tts_tone"))
    out["tts_pause_style"] = normalize_pause_style(out.get("tts_pause_style"))
    out["tts_expression_detail"] = normalize_expression_detail(out.get("tts_expression_detail"))
    for key in ("tts_rate", "tts_pitch"):
        try:
            out[key] = max(0.5, min(2.0, float(out.get(key) or 1.0)))
        except Exception:
            out[key] = 1.0
    try:
        out["tts_volume"] = max(0.5, min(1.5, float(out.get("tts_volume") or 1.0)))
    except Exception:
        out["tts_volume"] = 1.0
    try:
        out["tts_intensity"] = max(0.0, min(1.0, float(out.get("tts_intensity") if out.get("tts_intensity") is not None else 0.7)))
    except Exception:
        out["tts_intensity"] = 0.7
    try:
        raw_tts_max = int(out.get("tts_max_chars") or 50000)
        # Schema 12 shipped 1200 as the factory default. Migrate that exact
        # legacy default to full-response speech while preserving intentional
        # custom limits from existing installations.
        src_schema = int(src.get("settings_schema", 0) or 0)
        if src_schema < 13 and raw_tts_max == 1200:
            raw_tts_max = 50000
        out["tts_max_chars"] = max(100, min(50000, raw_tts_max))
    except Exception:
        out["tts_max_chars"] = 50000
    try:
        out["tts_cpu_threads"] = max(1, min(4, int(out.get("tts_cpu_threads") or 2)))
    except Exception:
        out["tts_cpu_threads"] = 2
    out["stt_provider"] = "hybrid"
    stt_model = str(out.get("stt_local_model") or "base.en").strip().lower()
    out["stt_local_model"] = stt_model if stt_model in {"tiny.en", "base.en", "small.en"} else "base.en"
    try:
        out["stt_max_seconds"] = max(5, min(60, int(out.get("stt_max_seconds") or 60)))
    except Exception:
        out["stt_max_seconds"] = 60
    # MatrixStudio2.0 keeps custom artwork undistorted: foreground composition is fixed.
    out["background_fit"] = "preserve"
    out["background_zoom"] = 100.0
    # 2.0.11 intentionally forced blur to zero while edge-fill was removed. On
    # the first 2.0.12 load, restore a conservative edge-fill default only for
    # settings written by the older schema. The main image itself is never blurred.
    try:
        old_schema = int(src.get("settings_schema", 0) or 0)
    except Exception:
        old_schema = 0
    if old_schema < 6 and float(src.get("background_blur", 0) or 0) <= 0:
        out["background_blur"] = 16.0
    out["gradients_enabled"] = _as_bool(out["gradients_enabled"])
    import re
    for key in ("accent_color", "accent_secondary", "background_color", "panel_color", "user_bubble_color", "assistant_bubble_color", "muted_text_color"):
        value = str(out.get(key) or DEFAULT_SETTINGS[key]).strip()
        out[key] = value if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else DEFAULT_SETTINGS[key]
    float_ranges = {
        "background_image_opacity": (0.0, 1.0),
        "background_blur": (0.0, 40.0),
        "background_dim": (0.0, 0.95),
        "background_zoom": (100.0, 140.0),
        "panel_opacity": (0.45, 1.0),
        "panel_blur": (0.0, 32.0),
        "glow_strength": (0.0, 1.0),
        "gradient_strength": (0.0, 1.0),
    }
    for key, (low, high) in float_ranges.items():
        try:
            out[key] = max(low, min(high, float(out[key])))
        except Exception:
            out[key] = DEFAULT_SETTINGS[key]
    try:
        out["background_image_version"] = max(0, int(out["background_image_version"]))
    except Exception:
        out["background_image_version"] = 0
    try:
        out["retrieval_max_chunks"] = max(1, min(6, int(out.get("retrieval_max_chunks") or 4)))
    except Exception:
        out["retrieval_max_chunks"] = 4
    try:
        out["retrieval_max_chars"] = max(800, min(6000, int(out.get("retrieval_max_chars") or 3600)))
    except Exception:
        out["retrieval_max_chars"] = 3600
    out["ollama_chat_model"] = str(out.get("ollama_chat_model") if out.get("ollama_chat_model") is not None else DEFAULT_SETTINGS["ollama_chat_model"]).strip()
    out["ollama_keep_alive"] = str(out["ollama_keep_alive"] or "5m").strip()
    prompt = str(out["system_prompt"] or DEFAULT_SETTINGS["system_prompt"]).strip()
    # Migrate only known factory prompts. Preserve genuinely custom user prompts.
    if prompt in {
        "You are the local MatrixStudio2.0 assistant. Be accurate, practical, concise, and complete.",
        "You are MatrixStudio2.0. Be accurate, practical, concise, and complete.",
    }:
        prompt = DEFAULT_SETTINGS["system_prompt"]
    out["system_prompt"] = prompt
    specialist = str(out.get("selected_specialist_id") or "").strip().lower()
    out["selected_specialist_id"] = "".join(ch for ch in specialist if ch.isalnum() or ch in "-_")[:120]
    out["settings_schema"] = 18
    return out


def _persist_settings(settings: dict[str, Any]) -> None:
    # Keep a last-known-good copy so an interrupted external launcher write cannot
    # silently reset the UI to defaults on the next start.
    _atomic_json(SETTINGS_PATH, settings)
    _atomic_json(SETTINGS_BACKUP_PATH, settings)


def load_settings() -> dict[str, Any]:
    with _LOCK:
        raw: dict[str, Any] = {}
        primary_ok = False
        if SETTINGS_PATH.exists():
            try:
                candidate = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                if isinstance(candidate, dict):
                    raw = candidate
                    primary_ok = True
            except Exception:
                primary_ok = False
        if not primary_ok and SETTINGS_BACKUP_PATH.exists():
            try:
                candidate = json.loads(SETTINGS_BACKUP_PATH.read_text(encoding="utf-8"))
                if isinstance(candidate, dict):
                    raw = candidate
            except Exception:
                raw = {}
        settings = _coerce_settings(raw)
        if (not primary_ok) or raw != settings or not SETTINGS_BACKUP_PATH.exists():
            _persist_settings(settings)
        return settings


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        current = load_settings()
        current.update({k: v for k, v in patch.items() if k in DEFAULT_SETTINGS})
        current = _coerce_settings(current)
        _persist_settings(current)
        return current


def reset_settings(section: str = "all") -> dict[str, Any]:
    section = str(section or "all").strip().lower()
    if section != "all" and section not in RESET_SETTING_GROUPS:
        raise ValueError(f"Unknown settings section: {section}")
    with _LOCK:
        if section == "all":
            next_settings = deepcopy(DEFAULT_SETTINGS)
        else:
            current = load_settings()
            for key in RESET_SETTING_GROUPS[section]:
                current[key] = deepcopy(DEFAULT_SETTINGS[key])
            next_settings = _coerce_settings(current)
        _persist_settings(next_settings)
        return next_settings


def _coerce_ui_state(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = dict(raw or {})
    out = deepcopy(DEFAULT_UI_STATE)
    out.update({k: v for k, v in src.items() if k in out})
    sid = str(out.get("active_session_id") or "").strip()
    out["active_session_id"] = "".join(ch for ch in sid if ch.isalnum() or ch in "-_")[:80]
    out["draft"] = str(out.get("draft") or "")[:100000]
    drafts = out.get("session_drafts") if isinstance(out.get("session_drafts"), dict) else {}
    clean_drafts: dict[str, str] = {}
    for key, value in list(drafts.items())[-100:]:
        safe = "".join(ch for ch in str(key) if ch.isalnum() or ch in "-_")[:80]
        if safe:
            clean_drafts[safe] = str(value or "")[:100000]
    out["session_drafts"] = clean_drafts
    scrolls = out.get("session_scroll") if isinstance(out.get("session_scroll"), dict) else {}
    clean_scrolls: dict[str, int] = {}
    for key, value in list(scrolls.items())[-100:]:
        safe = "".join(ch for ch in str(key) if ch.isalnum() or ch in "-_")[:80]
        if not safe:
            continue
        try:
            clean_scrolls[safe] = max(0, min(100000000, int(float(value or 0))))
        except Exception:
            continue
    out["session_scroll"] = clean_scrolls
    out["sidebar_collapsed"] = _as_bool(out.get("sidebar_collapsed"))
    for key, floor, ceiling, fallback in (
        ("window_width", 900, 7680, 1440),
        ("window_height", 650, 4320, 900),
    ):
        try:
            out[key] = max(floor, min(ceiling, int(out.get(key) or fallback)))
        except Exception:
            out[key] = fallback
    return out


def load_ui_state() -> dict[str, Any]:
    with _LOCK:
        try:
            raw = json.loads(UI_STATE_PATH.read_text(encoding="utf-8")) if UI_STATE_PATH.exists() else {}
        except Exception:
            raw = {}
        state = _coerce_ui_state(raw)
        if raw != state:
            _atomic_json(UI_STATE_PATH, state)
        return state


def update_ui_state(patch: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        current = load_ui_state()
        current.update({k: v for k, v in patch.items() if k in DEFAULT_UI_STATE})
        current = _coerce_ui_state(current)
        _atomic_json(UI_STATE_PATH, current)
        return current


def reset_ui_state() -> dict[str, Any]:
    with _LOCK:
        state = deepcopy(DEFAULT_UI_STATE)
        _atomic_json(UI_STATE_PATH, state)
        return state


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_generation_profile(model: str = "", think_mode: str = "auto", *, locked: bool = False) -> dict[str, Any]:
    model_name = str(model or "").strip()
    mode = str(think_mode or "auto").lower().strip()
    if mode not in THINK_CHOICES:
        mode = "auto"
    return {"model": model_name, "think_mode": mode, "locked": bool(locked)}


def infer_session_generation_profile(
    session: dict[str, Any],
    *,
    default_model: str = "",
    default_think_mode: str = "auto",
) -> dict[str, Any]:
    """Return a normalized per-chat generation profile.

    New chats remain editable. Legacy chats are locked and recover their model /
    requested reasoning mode from persisted assistant metadata when available.
    """
    messages = list(session.get("messages") or [])
    existing = session.get("generation_profile")
    if isinstance(existing, dict):
        profile = _clean_generation_profile(
            existing.get("model") or default_model,
            existing.get("think_mode") or default_think_mode,
            locked=bool(existing.get("locked")) or bool(messages),
        )
        return profile

    model = str(default_model or "").strip()
    mode = str(default_think_mode or "auto").lower().strip()
    if messages:
        for msg in messages:
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            stats = msg.get("stats") if isinstance(msg.get("stats"), dict) else {}
            candidate = str(stats.get("model") or msg.get("model") or "").strip()
            if candidate:
                model = candidate
                break
        for msg in messages:
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            candidate = str(msg.get("reasoning_mode") or "").lower().strip()
            if candidate in THINK_CHOICES:
                mode = candidate
                break
    return _clean_generation_profile(model, mode, locked=bool(messages))


def new_session(
    title: str = "New chat",
    *,
    model: str = "",
    think_mode: str = "auto",
) -> dict[str, Any]:
    import uuid
    sid = uuid.uuid4().hex
    stamp = now_iso()
    session = {
        "id": sid,
        "title": title,
        "pinned": False,
        "created_at": stamp,
        "updated_at": stamp,
        "generation_profile": _clean_generation_profile(model, think_mode, locked=False),
        "messages": [],
    }
    save_session(session)
    return session


def session_path(sid: str) -> Path:
    safe = "".join(ch for ch in str(sid) if ch.isalnum() or ch in "-_")[:80]
    if not safe:
        raise ValueError("invalid session id")
    return SESSIONS / f"{safe}.json"


def save_session(session: dict[str, Any]) -> None:
    with _LOCK:
        session["updated_at"] = now_iso()
        _atomic_json(session_path(session["id"]), session)


def load_session(sid: str) -> dict[str, Any] | None:
    with _LOCK:
        p = session_path(sid)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
                return None
            return data
        except Exception:
            return None


def list_sessions() -> list[dict[str, Any]]:
    SESSIONS.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in SESSIONS.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            messages = d.get("messages") or []
            preview = ""
            for msg in reversed(messages):
                text = " ".join(str(msg.get("content") or "").split()) if isinstance(msg, dict) else ""
                if text:
                    preview = text[:140]
                    break
            rows.append({
                "id": d.get("id") or p.stem,
                "title": d.get("title") or "Chat",
                "pinned": _as_bool(d.get("pinned")),
                "preview": preview,
                "created_at": d.get("created_at"),
                "updated_at": d.get("updated_at"),
                "message_count": len(messages),
            })
        except Exception:
            continue
    rows.sort(key=lambda x: (not bool(x.get("pinned")), str(x.get("updated_at") or "")), reverse=False)
    pinned = [x for x in rows if x.get("pinned")]
    normal = [x for x in rows if not x.get("pinned")]
    pinned.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    normal.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    rows = pinned + normal
    return rows




def update_session_generation(
    sid: str,
    *,
    model: str | None = None,
    think_mode: str | None = None,
) -> dict[str, Any] | None:
    with _LOCK:
        session = load_session(sid)
        if not session:
            return None
        messages = list(session.get("messages") or [])
        current = infer_session_generation_profile(session)
        if messages or current.get("locked"):
            raise ValueError("This chat has already started; its model and reasoning mode are locked.")
        next_model = current.get("model") if model is None else str(model or "").strip()
        next_mode = current.get("think_mode") if think_mode is None else str(think_mode or "auto").lower().strip()
        session["generation_profile"] = _clean_generation_profile(next_model, next_mode, locked=False)
        save_session(session)
        return session


def lock_session_generation(
    session: dict[str, Any],
    *,
    default_model: str = "",
    default_think_mode: str = "auto",
) -> dict[str, Any]:
    profile = infer_session_generation_profile(
        session,
        default_model=default_model,
        default_think_mode=default_think_mode,
    )
    profile["locked"] = True
    session["generation_profile"] = profile
    save_session(session)
    return profile

def update_session_meta(sid: str, *, title: str | None = None, pinned: bool | None = None) -> dict[str, Any] | None:
    with _LOCK:
        session = load_session(sid)
        if not session:
            return None
        if title is not None:
            clean = " ".join(str(title).strip().split())[:120]
            session["title"] = clean or "New chat"
        if pinned is not None:
            session["pinned"] = bool(pinned)
        save_session(session)
        return session

def _prune_session_trash(limit: int = 100) -> None:
    SESSION_TRASH.mkdir(parents=True, exist_ok=True)
    rows = sorted(SESSION_TRASH.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in rows[max(1, int(limit)):]:
        try:
            stale.unlink()
        except OSError:
            pass


def delete_session(sid: str) -> dict[str, Any]:
    """Soft-delete a session so the UI can offer Undo.

    Returns a small descriptor instead of permanently unlinking the chat.
    """
    with _LOCK:
        p = session_path(sid)
        if not p.exists():
            return {"ok": False, "trash_id": ""}
        SESSION_TRASH.mkdir(parents=True, exist_ok=True)
        import uuid
        trash_id = f"{int(datetime.now(timezone.utc).timestamp())}-{uuid.uuid4().hex[:10]}-{p.stem}"
        target = SESSION_TRASH / f"{trash_id}.json"
        os.replace(p, target)
        _prune_session_trash()
        return {"ok": True, "trash_id": trash_id, "session_id": p.stem}


def restore_deleted_session(trash_id: str) -> dict[str, Any] | None:
    safe = "".join(ch for ch in str(trash_id) if ch.isalnum() or ch in "-_")[:180]
    if not safe:
        return None
    with _LOCK:
        source = SESSION_TRASH / f"{safe}.json"
        if not source.exists():
            return None
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except Exception:
            return None
        sid = str(data.get("id") or safe.rsplit("-", 1)[-1])
        target = session_path(sid)
        if target.exists():
            return None
        os.replace(source, target)
        return load_session(sid)


def derive_title(text: str) -> str:
    line = " ".join(str(text).strip().split())
    if not line:
        return "New chat"
    return line[:52] + ("…" if len(line) > 52 else "")


def export_workspace_bundle() -> dict[str, Any]:
    sessions: list[dict[str, Any]] = []
    for meta in list_sessions():
        row = load_session(str(meta.get("id") or ""))
        if row:
            sessions.append(row)
    return {
        "format": "matrixstudio2.workspace",
        "version": 1,
        "exported_at": now_iso(),
        "settings": load_settings(),
        "sessions": sessions,
    }


def import_workspace_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise ValueError("Import must be a JSON object")
    imported = 0
    # Accept both a full workspace bundle and a single chat export.
    if isinstance(bundle.get("messages"), list):
        source_sessions = [bundle]
        settings_patch = None
    else:
        if bundle.get("format") not in {None, "matrixstudio2.workspace"}:
            raise ValueError("Unsupported MatrixStudio2.0 import format")
        source_sessions = bundle.get("sessions") or []
        settings_patch = bundle.get("settings") if isinstance(bundle.get("settings"), dict) else None
    if not isinstance(source_sessions, list):
        raise ValueError("Import sessions must be a list")
    if settings_patch is not None:
        update_settings(settings_patch)
    import uuid
    for raw in source_sessions[:5000]:
        if not isinstance(raw, dict) or not isinstance(raw.get("messages"), list):
            continue
        clean_messages = []
        for msg in raw.get("messages")[:20000]:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role not in {"user", "assistant"}:
                continue
            clean = {
                "role": role,
                "content": str(msg.get("content") or "")[:1000000],
                "created_at": msg.get("created_at"),
            }
            if role == "assistant":
                clean["thinking"] = str(msg.get("thinking") or "")[:2000000]
                clean["stats"] = msg.get("stats") if isinstance(msg.get("stats"), dict) else {}
                clean["reasoning_mode"] = str(msg.get("reasoning_mode") or "auto")[:20]
            clean_messages.append(clean)
        sid = uuid.uuid4().hex
        stamp = now_iso()
        session = {
            "id": sid,
            "title": str(raw.get("title") or "Imported chat")[:120],
            "created_at": str(raw.get("created_at") or stamp),
            "updated_at": stamp,
            "messages": clean_messages,
        }
        save_session(session)
        imported += 1
    return {"imported_sessions": imported, "settings": load_settings()}
