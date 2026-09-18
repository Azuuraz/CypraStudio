from __future__ import annotations

import base64
import ctypes
import json
import os
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Iterator

import requests

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = "https://openrouter.ai/api/v1"
MODEL_PREFIX = "openrouter::"
SECRET_PATH = ROOT / "data" / "openrouter.secret.json"
APP_TITLE = "MatrixStudio2.0"

# Curated against OpenRouter's live /api/v1/models catalog on 2026-09-18.
# Free endpoint slugs are volatile, so `openrouter/free` remains the durable
# default and retired direct free endpoints are never redirected to paid models.
MODELS: tuple[dict[str, Any], ...] = (
    {
        "id": "openrouter/free",
        "name": "Auto Free Router",
        "free": True,
        "context": 200000,
        "description": "Automatically selects an available free OpenRouter model.",
    },
    {
        "id": "deepseek/deepseek-v4-flash-0731:free",
        "name": "DeepSeek V4 Flash 0731 (Free)",
        "free": True,
        "context": 1048576,
        "description": "Coding, reasoning, and agent workflows with a current free endpoint.",
    },
    {
        "id": "qwen/qwen3.8-27b:free",
        "name": "Qwen3.8 27B (Free)",
        "free": True,
        "context": 1000000,
        "description": "Current Qwen free endpoint for coding, research, multimodal work, and long-running agents.",
    },
    {
        "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "name": "Nemotron 3 Ultra 550B-A55B (Free)",
        "free": True,
        "context": 202752,
        "description": "Large reasoning/orchestration model; free endpoint availability and provider terms can change.",
    },
    {
        "id": "nex-agi/nex-n2.5-pro:free",
        "name": "Nex N2.5 Pro (Free)",
        "free": True,
        "context": 262144,
        "description": "Agentic coding and verified software-engineering workflows.",
    },
    {
        "id": "nvidia/nemotron-3-super-120b-a12b:free",
        "name": "Nemotron 3 Super 120B-A12B (Free)",
        "free": True,
        "context": 262144,
        "description": "Efficient agentic reasoning and multi-step task planning.",
    },
)

# OpenRouter occasionally renames model slugs while keeping the underlying model
# unchanged. Preserve old MatrixStudio sessions only for identity-preserving
# renames; never redirect a retired free model to a paid endpoint.
LEGACY_MODEL_ALIASES: dict[str, str] = {
    "nvidia/nemotron-3-super:free": "nvidia/nemotron-3-super-120b-a12b:free",
}

_MODEL_IDS = {row["id"] for row in MODELS}


def list_models() -> list[dict[str, Any]]:
    return [dict(row) for row in MODELS]


def encode_model(slug: str) -> str:
    clean = str(slug or "").strip()
    if not clean:
        raise ValueError("OpenRouter model is required.")
    return MODEL_PREFIX + clean


def is_openrouter_model(value: str) -> bool:
    return str(value or "").startswith(MODEL_PREFIX)


def decode_model(value: str) -> str:
    raw = str(value or "").strip()
    if not is_openrouter_model(raw):
        raise ValueError("Not an OpenRouter model specification.")
    return raw[len(MODEL_PREFIX):]


def validate_model(slug: str) -> str:
    clean = str(slug or "").strip()
    clean = LEGACY_MODEL_ALIASES.get(clean, clean)
    if clean not in _MODEL_IDS:
        raise ValueError("That OpenRouter model is unavailable or no longer in MatrixStudio's current catalog.")
    return clean


def model_info(slug: str) -> dict[str, Any] | None:
    clean = str(slug or "").strip()
    return next((dict(row) for row in MODELS if row["id"] == clean), None)


def _free_model(slug: str) -> bool:
    info = model_info(slug)
    return bool(info and info.get("free"))


def _env_key() -> str:
    return str(os.environ.get("OPENROUTER_API_KEY") or "").strip()


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> tuple[_DATA_BLOB, Any]:
    if not data:
        return _DATA_BLOB(0, None), None
    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))), buf


def _configure_dpapi(crypt32: Any, kernel32: Any) -> None:
    """Give ctypes the exact Win32 DPAPI signatures before calling them."""
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p


def _protect_windows(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Persistent OpenRouter key storage requires Windows DPAPI.")
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        _configure_dpapi(crypt32, kernel32)
        in_blob, _ = _blob(data)
        out_blob = _DATA_BLOB()
        CRYPTPROTECT_UI_FORBIDDEN = 0x01
        description = ctypes.c_wchar_p("MatrixStudio2.0 OpenRouter")
        ok = crypt32.CryptProtectData(
            ctypes.byref(in_blob), description, None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
        )
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Windows DPAPI could not protect the OpenRouter key: {exc}") from exc


def _unprotect_windows(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Persistent OpenRouter key storage requires Windows DPAPI.")
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        _configure_dpapi(crypt32, kernel32)
        in_blob, _ = _blob(data)
        out_blob = _DATA_BLOB()
        CRYPTPROTECT_UI_FORBIDDEN = 0x01
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
        )
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Windows DPAPI could not read the saved OpenRouter key: {exc}") from exc


def save_api_key(key: str) -> dict[str, Any]:
    clean = str(key or "").strip()
    if len(clean) < 20 or not clean.startswith("sk-or-"):
        raise ValueError("Enter a valid OpenRouter API key beginning with sk-or-.")
    protected = _protect_windows(clean.encode("utf-8"))
    SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 1,
        "provider": "openrouter",
        "dpapi": base64.b64encode(protected).decode("ascii"),
    }
    tmp = SECRET_PATH.with_suffix(SECRET_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, SECRET_PATH)
    return key_status()


def delete_api_key() -> None:
    try:
        SECRET_PATH.unlink(missing_ok=True)
    except OSError as exc:
        raise RuntimeError(f"Could not remove the saved OpenRouter key: {exc}") from exc


def load_api_key() -> str:
    env = _env_key()
    if env:
        return env
    if not SECRET_PATH.exists():
        return ""
    if os.name != "nt":
        return ""
    try:
        payload = json.loads(SECRET_PATH.read_text(encoding="utf-8"))
        encoded = str(payload.get("dpapi") or "")
        if not encoded:
            return ""
        return _unprotect_windows(base64.b64decode(encoded)).decode("utf-8").strip()
    except Exception:
        return ""


def key_status() -> dict[str, Any]:
    env = _env_key()
    saved = bool(SECRET_PATH.exists())
    configured = bool(env or load_api_key())
    source = "environment" if env else ("windows-dpapi" if configured and saved else "none")
    return {"configured": configured, "source": source, "saved": bool(saved and source == "windows-dpapi")}


def public_status(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = dict(settings or {})
    status = key_status()
    selected = str(settings.get("openrouter_chat_model") or "openrouter/free").strip()
    if selected not in _MODEL_IDS:
        selected = "openrouter/free"
    return {
        **status,
        "enabled": bool(settings.get("openrouter_allow_online")),
        "selected_model": selected,
        "models": list_models(),
        "endpoint": API_ROOT,
    }


def test_api_key() -> dict[str, Any]:
    key = load_api_key()
    if not key:
        raise RuntimeError("No OpenRouter API key is configured.")
    response = requests.get(
        f"{API_ROOT}/key",
        headers={"Authorization": f"Bearer {key}"},
        timeout=(5, 20),
    )
    if response.status_code == 401:
        raise RuntimeError("OpenRouter rejected this API key.")
    if not response.ok:
        raise RuntimeError(f"OpenRouter key check failed with HTTP {response.status_code}.")
    data = response.json().get("data") or {}
    return {
        "ok": True,
        "configured": True,
        "source": key_status()["source"],
        "is_free_tier": bool(data.get("is_free_tier")),
        "label": str(data.get("label") or ""),
        "limit": data.get("limit"),
        "limit_remaining": data.get("limit_remaining"),
        "usage": data.get("usage"),
    }


def _reasoning_effort(mode: str) -> str:
    value = str(mode or "auto").lower()
    if value == "direct":
        return "none"
    if value == "deep":
        return "high"
    return "medium"


def stream_chat(
    settings: dict[str, Any],
    messages: list[dict[str, str]],
    *,
    model_override: str,
    session_id: str = "",
    _allow_free_fallback: bool = True,
) -> Iterator[tuple[str, str | dict[str, Any]]]:
    if not bool(settings.get("openrouter_allow_online")):
        raise RuntimeError("Online chat is disabled in Runtime settings.")
    key = load_api_key()
    if not key:
        raise RuntimeError("OpenRouter API key is not configured.")
    slug = validate_model(decode_model(model_override))
    body: dict[str, Any] = {
        "model": slug,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": float(settings.get("chat_temperature") or 0.65),
        "reasoning_effort": _reasoning_effort(settings.get("think_mode")),
    }
    num_predict = int(settings.get("ollama_num_predict") or -1)
    if num_predict > 0:
        body["max_tokens"] = num_predict
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-OpenRouter-Title": APP_TITLE,
    }
    started = time.perf_counter()
    response = requests.post(
        f"{API_ROOT}/chat/completions",
        headers=headers,
        json=body,
        stream=True,
        timeout=(10, 600),
    )
    if (
        not response.ok
        and _allow_free_fallback
        and slug != "openrouter/free"
        and _free_model(slug)
        and response.status_code in {429, 502, 503, 504}
    ):
        response.close()
        yield from stream_chat(
            settings,
            messages,
            model_override=encode_model("openrouter/free"),
            session_id=session_id,
            _allow_free_fallback=False,
        )
        return
    with response as r:
        if not r.ok:
            detail = r.text[:1000]
            raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {detail}")
        usage: dict[str, Any] = {}
        resolved_model = slug
        finish_reason = None
        for raw in r.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = str(raw).strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            item = json.loads(payload)
            if item.get("error"):
                error = item.get("error")
                if (
                    _allow_free_fallback
                    and slug != "openrouter/free"
                    and _free_model(slug)
                    and isinstance(error, dict)
                    and str(error.get("code") or "") in {"429", "502", "503", "504"}
                ):
                    yield from stream_chat(
                        settings,
                        messages,
                        model_override=encode_model("openrouter/free"),
                        session_id=session_id,
                        _allow_free_fallback=False,
                    )
                    return
                if isinstance(error, dict):
                    raise RuntimeError(str(error.get("message") or error))
                raise RuntimeError(str(error))
            if item.get("model"):
                resolved_model = str(item.get("model"))
            if isinstance(item.get("usage"), dict):
                usage = dict(item["usage"])
            choices = item.get("choices") or []
            if not choices:
                continue
            choice = choices[0] or {}
            finish_reason = choice.get("finish_reason") or finish_reason
            delta = choice.get("delta") or {}
            thinking = delta.get("reasoning") or delta.get("reasoning_content")
            content = delta.get("content")
            if thinking:
                yield "think", str(thinking)
            if content:
                yield "content", str(content)
        elapsed = max(0.001, time.perf_counter() - started)
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        generated_tokens = int(usage.get("completion_tokens") or 0)
        yield "stats", {
            "provider": "openrouter",
            "model": resolved_model,
            "done_reason": finish_reason,
            "prompt_tokens": prompt_tokens,
            "generated_tokens": generated_tokens,
            "total_tokens": int(usage.get("total_tokens") or (prompt_tokens + generated_tokens)),
            "tokens_per_second": round(generated_tokens / elapsed, 2) if generated_tokens else 0.0,
            "elapsed_seconds": round(elapsed, 2),
            "reasoning_control": _reasoning_effort(settings.get("think_mode")),
        }
