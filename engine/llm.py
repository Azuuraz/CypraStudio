from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST = "127.0.0.1:11435"
STARTER_MODEL = "llama3.2:3b"
BASE_GPU_NUM_LAYERS = 999
FULL_GPU_THRESHOLD = 1.0
HF_MODEL_REGISTRY = ROOT / "data" / "huggingface" / "installed_models.json"
_MODEL_CACHE: dict[str, Any] = {"ts": 0.0, "models": [], "error": None}
_CACHE_LOCK = threading.Lock()
_PULL_LOCK = threading.Lock()
_RUNTIME_HEALTH_LOCK = threading.Lock()
_RUNTIME_HEALTH: dict[str, Any] = {"last_ok": 0.0, "consecutive_failures": 0, "last_error": None}
_ACTIVE_LOCK = threading.Lock()
_ACTIVE_GENERATIONS = 0
_HF_GPU_POLICY_LOCK = threading.Lock()
_RUNNER_PRUNE_LOCK = threading.Lock()
_HF_GPU_MODE_CACHE: dict[str, dict[str, Any]] = {}
_PULL_STATE: dict[str, Any] = {
    "running": False,
    "model": None,
    "status": "idle",
    "completed": 0,
    "total": 0,
    "error": None,
}


def ollama_root() -> str:
    """Return the private Ollama loopback endpoint only.

    MatrixStudio is intentionally local-only; accepting a remote OLLAMA_HOST
    would silently transmit prompts and model-management requests off-device.
    """
    from urllib.parse import urlsplit

    raw = (os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).strip().rstrip("/")
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "http" or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("OLLAMA_HOST must use the local loopback interface")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("OLLAMA_HOST contains unsupported components")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("OLLAMA_HOST has an invalid port") from exc
    if port is None or not (1024 <= int(port) <= 65535):
        raise ValueError("OLLAMA_HOST must include a valid local port")
    return f"http://[{host}]:{port}" if host == "::1" else f"http://{host}:{port}"


def model_store() -> str:
    """Return only this project's private Ollama model store.

    The launcher still exports OLLAMA_MODELS for the Ollama child process, but
    application code never trusts an inherited value that could redirect model
    management into a host/global store.
    """
    return str((ROOT / "OllamaModels").resolve())



def _mark_runtime_ok() -> None:
    with _RUNTIME_HEALTH_LOCK:
        _RUNTIME_HEALTH["last_ok"] = time.time()
        _RUNTIME_HEALTH["consecutive_failures"] = 0
        _RUNTIME_HEALTH["last_error"] = None


def _mark_runtime_failure(error: Exception | str) -> None:
    with _RUNTIME_HEALTH_LOCK:
        _RUNTIME_HEALTH["consecutive_failures"] = int(_RUNTIME_HEALTH.get("consecutive_failures") or 0) + 1
        _RUNTIME_HEALTH["last_error"] = str(error)


def _runtime_health_snapshot() -> dict[str, Any]:
    with _RUNTIME_HEALTH_LOCK:
        last_ok = float(_RUNTIME_HEALTH.get("last_ok") or 0.0)
        failures = int(_RUNTIME_HEALTH.get("consecutive_failures") or 0)
        error = _RUNTIME_HEALTH.get("last_error")
    with _ACTIVE_LOCK:
        active = int(_ACTIVE_GENERATIONS)
    age = max(0.0, time.time() - last_ok) if last_ok else None
    return {"last_ok": last_ok, "last_ok_age": age, "consecutive_failures": failures, "last_error": error, "active_generations": active}


def _set_generation_active(delta: int) -> None:
    global _ACTIVE_GENERATIONS
    with _ACTIVE_LOCK:
        _ACTIVE_GENERATIONS = max(0, int(_ACTIVE_GENERATIONS) + int(delta))


def list_models(force: bool = False) -> list[dict[str, Any]]:
    with _CACHE_LOCK:
        if not force and time.time() - float(_MODEL_CACHE["ts"]) < 5:
            return list(_MODEL_CACHE["models"])
        previous = list(_MODEL_CACHE.get("models") or [])
    rows: list[dict[str, Any]] = []
    error = None
    try:
        r = requests.get(f"{ollama_root()}/api/tags", timeout=2.5)
        r.raise_for_status()
        _mark_runtime_ok()
        for item in r.json().get("models") or []:
            rows.append(
                {
                    "name": item.get("name") or item.get("model"),
                    "model": item.get("model") or item.get("name"),
                    "size": item.get("size"),
                    "modified_at": item.get("modified_at"),
                    "details": item.get("details") or {},
                    "digest": item.get("digest"),
                }
            )
    except Exception as exc:
        error = str(exc)
        _mark_runtime_failure(exc)
        # A short status probe can time out while the resident model is busy.
        # Keep the last authoritative installed-model list instead of pretending
        # the project store suddenly became empty.
        rows = previous
    with _CACHE_LOCK:
        _MODEL_CACHE.update({"ts": time.time(), "models": rows, "error": error})
    return rows


def _model_names(models: list[dict[str, Any]]) -> list[str]:
    return [str(m.get("name") or m.get("model") or "").strip() for m in models if (m.get("name") or m.get("model"))]


def _is_base_gpu_only_model(model: str) -> bool:
    return str(model or "").strip() == STARTER_MODEL


def _is_huggingface_model(model: str) -> bool:
    name = str(model or "").strip()
    if not name:
        return False
    if name.lower().startswith("hf-"):
        return True
    try:
        payload = json.loads(HF_MODEL_REGISTRY.read_text(encoding="utf-8"))
        models = payload.get("models") or {}
        if name in models:
            return True
        if ":" not in name and f"{name}:latest" in models:
            return True
    except (FileNotFoundError, OSError, ValueError, TypeError):
        pass
    return False


def remember_huggingface_model(
    model: str,
    *,
    repo_id: str,
    revision: str,
    quant: str,
    size_bytes: int,
) -> None:
    name = str(model or "").strip()
    if not name:
        raise ValueError("Cannot record an empty Hugging Face model name.")
    try:
        payload = json.loads(HF_MODEL_REGISTRY.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {}
    except (FileNotFoundError, OSError, ValueError, TypeError):
        payload = {}
    models = payload.get("models")
    if not isinstance(models, dict):
        models = {}
    models[name] = {
        "repo_id": str(repo_id or "").strip(),
        "revision": str(revision or "").strip(),
        "quant": str(quant or "").strip(),
        "size_bytes": max(0, int(size_bytes or 0)),
        "recorded_at": time.time(),
    }
    payload = {"schema": 1, "models": models}
    HF_MODEL_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    tmp = HF_MODEL_REGISTRY.with_suffix(HF_MODEL_REGISTRY.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, HF_MODEL_REGISTRY)


def _forget_huggingface_model(model: str) -> bool:
    name = str(model or "").strip()
    if not name:
        return False
    try:
        payload = json.loads(HF_MODEL_REGISTRY.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return False
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return False
    models = payload.get("models")
    if not isinstance(models, dict):
        return False
    keys = [name]
    if ":" not in name:
        keys.append(f"{name}:latest")
    removed = False
    for key in keys:
        if key in models:
            models.pop(key, None)
            removed = True
    if not removed:
        return False
    payload = {"schema": 1, "models": models}
    HF_MODEL_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    tmp = HF_MODEL_REGISTRY.with_suffix(HF_MODEL_REGISTRY.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, HF_MODEL_REGISTRY)
    return True


def delete_model(model: str) -> dict[str, Any]:
    """Delete one project-local Ollama model after unloading it.

    The operation is intentionally unavailable while a generation is active.
    A successful response means Ollama no longer reports the model and any
    Hugging Face origin record for the same local name has been removed.
    """
    name = str(model or "").strip()
    if not name:
        raise ValueError("Model name is required.")
    with _ACTIVE_LOCK:
        if _ACTIVE_GENERATIONS:
            raise RuntimeError("Wait for the active response to finish before deleting a model.")

    loaded = False
    try:
        response = requests.get(f"{ollama_root()}/api/ps", timeout=3)
        if response.ok:
            running = [
                str(item.get("name") or item.get("model") or "").strip()
                for item in (response.json().get("models") or [])
            ]
            loaded = name in running or (":" not in name and f"{name}:latest" in running)
    except Exception:
        loaded = False

    if loaded:
        response = requests.post(
            f"{ollama_root()}/api/generate",
            json={"model": name, "prompt": "", "stream": False, "keep_alive": 0},
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(f"Could not unload {name} before deletion: Ollama HTTP {response.status_code}: {response.text[:500]}")

    response = requests.delete(f"{ollama_root()}/api/delete", json={"model": name}, timeout=120)
    if not response.ok:
        raise RuntimeError(f"Could not delete {name}: Ollama HTTP {response.status_code}: {response.text[:800]}")

    with _CACHE_LOCK:
        _MODEL_CACHE["ts"] = 0.0
    remaining_rows = list_models(force=True)
    remaining = _model_names(remaining_rows)
    aliases = {name}
    if ":" not in name:
        aliases.add(f"{name}:latest")
    if any(item in aliases for item in remaining):
        raise RuntimeError(f"Ollama still reports {name} after the delete request.")

    _forget_huggingface_model(name)
    with _HF_GPU_POLICY_LOCK:
        _HF_GPU_MODE_CACHE.pop(name, None)
        if ":" not in name:
            _HF_GPU_MODE_CACHE.pop(f"{name}:latest", None)
    return {"ok": True, "deleted": name, "unloaded": loaded, "remaining": remaining}


def _gpu_load_options(
    settings: dict[str, Any],
    model: str,
    *,
    gpu_mode: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    options: dict[str, Any] = {"num_ctx": int(settings.get("ollama_num_ctx") or 8192)}
    full_gpu = _is_base_gpu_only_model(model) or (_is_huggingface_model(model) and gpu_mode != "auto")
    if full_gpu:
        # num_gpu is a layer count, not a GPU count. The factory model always
        # requests every layer; Hugging Face GGUFs request every layer unless a
        # previous full-offload attempt proved that this model/context needs
        # Ollama's automatic partial-offload placement.
        options["num_gpu"] = BASE_GPU_NUM_LAYERS
    else:
        # Keep automatic/partial-offload models disk-backed instead of asking the
        # OS to commit the full GGUF into pageable RAM. This restores the
        # low-RAM disk + GPU behavior used before the GPU-policy changes while
        # still letting Ollama decide how many layers fit in VRAM.
        options["use_mmap"] = True
    options.update(extra)
    return options


def _gpu_residency(item: dict[str, Any] | None) -> dict[str, Any]:
    row = item or {}
    size = int(row.get("size") or 0)
    size_vram = int(row.get("size_vram") or 0)
    if size <= 0:
        percent = None
        fully_gpu = False
    else:
        percent = max(0, min(100, round((size_vram / size) * 100)))
        fully_gpu = size_vram >= int(size * FULL_GPU_THRESHOLD)
    processor = (
        "100% GPU" if fully_gpu
        else (f"{percent}% GPU / {100 - percent}% CPU" if percent is not None and percent > 0
              else "100% CPU" if percent == 0
              else "Unknown")
    )
    return {
        "gpu_percent": percent,
        "fully_gpu": fully_gpu,
        "processor": processor,
    }


def _prune_stale_project_runners_if_idle() -> bool:
    """Remove detached MatrixStudio llama runners before Ollama reloads a model.

    Ollama's 5-minute keep-alive unloads the model runner, not the long-lived
    `ollama serve` daemon. On Windows a detached llama-server can occasionally
    survive that unload. If /api/ps is empty, no model is resident, so any
    runner still tied to this project's private store is stale and safe to
    remove. The PowerShell lifecycle script owns the process verification.
    """
    if os.name != "nt":
        return False
    with _ACTIVE_LOCK:
        if _ACTIVE_GENERATIONS:
            return False
    with _RUNNER_PRUNE_LOCK:
        try:
            response = requests.get(f"{ollama_root()}/api/ps", timeout=2.5)
            if not response.ok or (response.json().get("models") or []):
                return False
        except Exception:
            return False

        script = ROOT / "kill-localhost.ps1"
        if not script.exists():
            return False
        try:
            port = int(str(ollama_root()).rsplit(":", 1)[-1])
        except (TypeError, ValueError):
            port = 0
        command = [
            "powershell.exe", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-ProjectOnly", "-BestEffort", "-RunnersOnly",
        ]
        if port > 0:
            command.extend(["-CurrentPort", str(port)])
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return result.returncode == 0
        except Exception:
            return False


def _running_model(model: str, timeout: float = 3.0) -> dict[str, Any] | None:
    r = requests.get(f"{ollama_root()}/api/ps", timeout=timeout)
    r.raise_for_status()
    target = str(model or "").strip()
    for item in r.json().get("models") or []:
        name = str(item.get("name") or item.get("model") or "").strip()
        if name == target or (":" not in target and name == f"{target}:latest"):
            return item
    return None


def _verify_base_gpu_residency(model: str, expected_ctx: int | None = None) -> dict[str, Any]:
    if not _is_base_gpu_only_model(model):
        return {"gpu_percent": None, "fully_gpu": False, "processor": "Automatic"}
    item = _running_model(model)
    if not item:
        raise RuntimeError("Base model GPU-only policy could not verify the loaded model in Ollama.")
    residency = _gpu_residency(item)
    loaded_ctx = int(item.get("context_length") or 0)
    if expected_ctx and loaded_ctx and loaded_ctx != int(expected_ctx):
        raise RuntimeError(
            f"Base model GPU-only policy loaded the wrong context size ({loaded_ctx} instead of {int(expected_ctx)})."
        )
    if not residency["fully_gpu"]:
        shown = residency["processor"]
        raise RuntimeError(
            f"Base model GPU-only policy requires 100% GPU residency, but Ollama reported {shown}. "
            "Unload VRAM, reduce context, or close other GPU-heavy applications and retry."
        )
    return {**residency, "context_length": loaded_ctx, "size": item.get("size"), "size_vram": item.get("size_vram")}


def _warm_request(settings: dict[str, Any], model: str, *, gpu_mode: str | None = None) -> requests.Response:
    body = {
        "model": model,
        "prompt": "",
        "stream": False,
        "keep_alive": _keep_alive(settings),
        "options": _gpu_load_options(settings, model, gpu_mode=gpu_mode, num_predict=1),
    }
    return requests.post(f"{ollama_root()}/api/generate", json=body, timeout=600)


def _ensure_base_gpu_resident(settings: dict[str, Any], model: str) -> None:
    if not _is_base_gpu_only_model(model):
        return
    expected_ctx = int(settings.get("ollama_num_ctx") or 8192)
    try:
        item = _running_model(model)
    except Exception:
        item = None
    if item:
        residency = _gpu_residency(item)
        loaded_ctx = int(item.get("context_length") or 0)
        if residency["fully_gpu"] and (not loaded_ctx or loaded_ctx == expected_ctx):
            return
    response = _warm_request(settings, model)
    if not response.ok:
        raise RuntimeError(f"Ollama HTTP {response.status_code}: {response.text[:800]}")
    _verify_base_gpu_residency(model, expected_ctx)


def _response_is_gpu_memory_failure(response: requests.Response) -> bool:
    text = str(getattr(response, "text", "") or "").lower()
    return any(token in text for token in (
        "out of memory",
        "vram",
        "cuda",
        "ggml_cuda",
        "failed to allocate",
        "unable to allocate",
        "memory allocation",
        "requires more memory",
    ))


def _ensure_hf_gpu_preference(settings: dict[str, Any], model: str) -> dict[str, Any]:
    if not _is_huggingface_model(model) or _is_base_gpu_only_model(model):
        return {"gpu_mode": "auto", "gpu_percent": None, "fully_gpu": False, "processor": "Automatic"}
    expected_ctx = int(settings.get("ollama_num_ctx") or 8192)
    with _HF_GPU_POLICY_LOCK:
        cached = dict(_HF_GPU_MODE_CACHE.get(model) or {})
        try:
            item = _running_model(model)
        except Exception:
            item = None
        if item:
            residency = _gpu_residency(item)
            loaded_ctx = int(item.get("context_length") or 0)
            same_ctx = not loaded_ctx or loaded_ctx == expected_ctx
            if residency["fully_gpu"] and same_ctx:
                _HF_GPU_MODE_CACHE[model] = {"gpu_mode": "full", "context_length": expected_ctx}
                return {**residency, "gpu_mode": "full", "context_length": loaded_ctx}
            if same_ctx and cached.get("context_length") == expected_ctx and cached.get("gpu_mode") == "auto":
                return {**residency, "gpu_mode": "auto", "context_length": loaded_ctx}

        response = _warm_request(settings, model, gpu_mode="full")
        if not response.ok:
            if not _response_is_gpu_memory_failure(response):
                raise RuntimeError(f"Ollama HTTP {response.status_code}: {response.text[:800]}")
            fallback = _warm_request(settings, model, gpu_mode="auto")
            if not fallback.ok:
                raise RuntimeError(f"Ollama HTTP {fallback.status_code}: {fallback.text[:800]}")
            item = _running_model(model)
            if not item:
                raise RuntimeError("Hugging Face automatic offload fallback could not verify the loaded model in Ollama.")
            residency = _gpu_residency(item)
            loaded_ctx = int(item.get("context_length") or 0)
            _HF_GPU_MODE_CACHE[model] = {"gpu_mode": "auto", "context_length": expected_ctx}
            return {**residency, "gpu_mode": "auto", "context_length": loaded_ctx}
        item = _running_model(model)
        if not item:
            raise RuntimeError("Hugging Face GPU-first policy could not verify the loaded model in Ollama.")
        residency = _gpu_residency(item)
        loaded_ctx = int(item.get("context_length") or 0)
        if not residency["fully_gpu"]:
            fallback = _warm_request(settings, model, gpu_mode="auto")
            if not fallback.ok:
                raise RuntimeError(f"Ollama HTTP {fallback.status_code}: {fallback.text[:800]}")
            item = _running_model(model)
            if not item:
                raise RuntimeError("Hugging Face automatic offload fallback could not verify the loaded model in Ollama.")
            residency = _gpu_residency(item)
            loaded_ctx = int(item.get("context_length") or 0)
            _HF_GPU_MODE_CACHE[model] = {"gpu_mode": "auto", "context_length": expected_ctx}
            return {**residency, "gpu_mode": "auto", "context_length": loaded_ctx}
        _HF_GPU_MODE_CACHE[model] = {"gpu_mode": "full", "context_length": expected_ctx}
        return {**residency, "gpu_mode": "full", "context_length": loaded_ctx}


def resolve_model(settings: dict[str, Any], force: bool = False) -> str | None:
    """Return an installed model, preferring the configured model.

    A stale configured model must never be sent to Ollama. If that model is
    missing but this project's store contains another model, use the installed
    model as a safe fallback. If the project store is empty, return None.
    """
    models = list_models(force=force)
    names = _model_names(models)
    if not names:
        return None

    configured = str(settings.get("ollama_chat_model") or "").strip()
    if configured in names:
        return configured

    # Ollama may expose an explicit :latest tag while older settings omitted it.
    if configured and ":" not in configured:
        tagged = f"{configured}:latest"
        if tagged in names:
            return tagged

    return names[0]


def runtime_status(settings: dict[str, Any]) -> dict[str, Any]:
    models = list_models(force=True)
    tags_error = _MODEL_CACHE.get("error")
    resolved = resolve_model(settings, force=False)
    loaded_details: list[dict[str, Any]] = []
    ps_ok = False
    ps_error = None
    try:
        r = requests.get(f"{ollama_root()}/api/ps", timeout=2.5)
        r.raise_for_status()
        ps_ok = True
        _mark_runtime_ok()
        for item in r.json().get("models") or []:
            residency = _gpu_residency(item)
            loaded_details.append({
                "name": item.get("name") or item.get("model"),
                "model": item.get("model") or item.get("name"),
                "size": item.get("size"),
                "size_vram": item.get("size_vram"),
                "context_length": item.get("context_length"),
                "expires_at": item.get("expires_at"),
                "details": item.get("details") or {},
                **residency,
            })
    except Exception as exc:
        ps_error = str(exc)
        _mark_runtime_failure(exc)

    health = _runtime_health_snapshot()
    age = health.get("last_ok_age")
    recent_success = age is not None and float(age) <= 20.0
    immediate_success = tags_error is None or ps_ok
    # During a generation Ollama may not answer a parallel /api/tags or /api/ps
    # probe quickly. A recent successful stream is authoritative proof that the
    # runtime is alive, so expose BUSY instead of a false OFFLINE state.
    online = bool(immediate_success or recent_success or health.get("active_generations"))
    runtime_state = "online" if immediate_success else ("busy" if online else "offline")

    configured = str(settings.get("ollama_chat_model") or "").strip()
    selected_info = next((m for m in models if (m.get("name") or m.get("model")) == resolved), None)
    loaded_names = [str(m.get("name") or m.get("model") or "").strip() for m in loaded_details]
    loaded_names = [x for x in loaded_names if x]
    loaded_vram = sum(int(m.get("size_vram") or 0) for m in loaded_details)
    selected_loaded = next((m for m in loaded_details if (m.get("name") or m.get("model")) == resolved), None)
    selected_residency = _gpu_residency(selected_loaded) if selected_loaded else {"gpu_percent": None, "fully_gpu": False, "processor": "Not loaded"}
    return {
        "ok": online,
        "state": runtime_state,
        "busy": runtime_state == "busy" or bool(health.get("active_generations")),
        "endpoint": ollama_root(),
        "model_store": model_store(),
        "models": models,
        "loaded_models": loaded_names,
        "loaded_model_details": loaded_details,
        "loaded_vram_bytes": loaded_vram,
        "selected_gpu_percent": selected_residency["gpu_percent"],
        "selected_fully_gpu": selected_residency["fully_gpu"],
        "selected_processor": selected_residency["processor"],
        "base_gpu_policy": "gpu_only" if _is_base_gpu_only_model(resolved or configured) else "automatic",
        "configured_model": configured,
        "selected_model": resolved or configured,
        "selected_model_info": selected_info or {},
        "model_ready": bool(resolved) and online,
        "fallback_used": bool(resolved and configured and resolved != configured),
        "model_count": len(models),
        "starter_model": STARTER_MODEL,
        "num_ctx": settings.get("ollama_num_ctx"),
        "active_generations": int(health.get("active_generations") or 0),
        "last_ok_age": health.get("last_ok_age"),
        "probe_error": tags_error or ps_error,
        "error": None if online else (tags_error or ps_error or health.get("last_error")),
    }


def _think_value(mode: str) -> bool | str | None:
    """Translate one resolved Studio reasoning mode to Ollama's think control.

    Direct must be explicit: omitting the flag lets some reasoning-capable models
    fall back to their own default thinking behavior, which can turn a greeting
    into a long hidden reasoning pass. Standard requests normal thinking and Deep
    requests the highest available level. Auto is only a persisted UI mode; the
    server resolves it to Direct/Standard/Deep before generation.
    """
    mode = str(mode or "auto").lower()
    if mode == "direct":
        return False
    if mode == "standard":
        return True
    if mode == "deep":
        return "high"
    return None


def _post_chat(body: dict[str, Any]):
    return requests.post(f"{ollama_root()}/api/chat", json=body, stream=True, timeout=(3.0, 600.0))


def stream_chat(
    settings: dict[str, Any],
    messages: list[dict[str, str]],
    *,
    model_override: str | None = None,
) -> Iterator[tuple[str, str | dict[str, Any]]]:
    model = str(model_override or resolve_model(settings) or "").strip()
    if not model:
        raise RuntimeError("No local model is installed in MatrixStudio2.0.")

    _prune_stale_project_runners_if_idle()
    _ensure_base_gpu_resident(settings, model)
    gpu_mode: str | None = None
    if _is_huggingface_model(model) and not _is_base_gpu_only_model(model):
        gpu_mode = str(_ensure_hf_gpu_preference(settings, model).get("gpu_mode") or "auto")

    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "keep_alive": _keep_alive(settings),
        "options": _gpu_load_options(
            settings,
            model,
            gpu_mode=gpu_mode,
            temperature=float(settings.get("chat_temperature") or 0.65),
        ),
    }
    num_predict = int(settings.get("ollama_num_predict") or -1)
    if num_predict != 0:
        body["options"]["num_predict"] = num_predict
    think = _think_value(settings.get("think_mode"))
    if think is not None:
        body["think"] = think

    started = time.perf_counter()
    _set_generation_active(1)
    think_control = "off" if think is False else "deep" if think == "high" else "standard" if think is True else "default"
    try:
        response = _post_chat(body)
        if response.ok:
            _mark_runtime_ok()

        # Reasoning support varies by model/runtime. Deep first asks for the
        # level-aware high mode, then boolean thinking, then model-default.
        # Standard falls from boolean thinking to model-default. Direct sends
        # think:false explicitly; only an older runtime that rejects the field
        # can force a compatibility fallback.
        if not response.ok and "think" in body and response.status_code in {400, 422}:
            detail = response.text[:1000]
            lowered = detail.lower()
            response.close()
            if "think" not in lowered and "thinking" not in lowered and "boolean" not in lowered:
                raise RuntimeError(f"Ollama HTTP {response.status_code}: {detail}")
            if body.get("think") == "high":
                body["think"] = True
                think_control = "standard-fallback"
                response = _post_chat(body)
                if not response.ok and response.status_code in {400, 422}:
                    detail2 = response.text[:1000]
                    lowered2 = detail2.lower()
                    response.close()
                    if "think" in lowered2 or "thinking" in lowered2 or "boolean" in lowered2:
                        body.pop("think", None)
                        think_control = "default-fallback"
                        response = _post_chat(body)
                    else:
                        raise RuntimeError(f"Ollama HTTP {response.status_code}: {detail2}")
            else:
                body.pop("think", None)
                think_control = "default-fallback"
                response = _post_chat(body)

        with response as r:
            if not r.ok:
                detail = r.text[:1000]
                raise RuntimeError(f"Ollama HTTP {r.status_code}: {detail}")
            _mark_runtime_ok()
            for raw in r.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                item = json.loads(raw)
                if item.get("error"):
                    raise RuntimeError(str(item["error"]))
                _mark_runtime_ok()
                msg = item.get("message") or {}
                thinking = msg.get("thinking") or item.get("thinking")
                content = msg.get("content")
                if thinking:
                    yield "think", str(thinking)
                if content:
                    yield "content", str(content)
                if item.get("done"):
                    prompt_eval = int(item.get("prompt_eval_count") or 0)
                    eval_count = int(item.get("eval_count") or 0)
                    elapsed = max(0.001, time.perf_counter() - started)
                    yield "stats", {
                        "model": model,
                        "done_reason": item.get("done_reason"),
                        "prompt_tokens": prompt_eval,
                        "generated_tokens": eval_count,
                        "tokens_per_second": round(eval_count / elapsed, 2) if eval_count else 0.0,
                        "elapsed_seconds": round(elapsed, 2),
                        "reasoning_control": think_control,
                    }
    except Exception as exc:
        _mark_runtime_failure(exc)
        raise
    finally:
        _set_generation_active(-1)


def unload_models() -> list[str]:
    names: list[str] = []
    try:
        r = requests.get(f"{ollama_root()}/api/ps", timeout=3)
        if r.ok:
            names = [
                m.get("name") or m.get("model")
                for m in (r.json().get("models") or [])
                if (m.get("name") or m.get("model"))
            ]
    except Exception:
        return []
    unloaded = []
    for name in names:
        try:
            r = requests.post(
                f"{ollama_root()}/api/generate",
                json={"model": name, "prompt": "", "stream": False, "keep_alive": 0},
                timeout=20,
            )
            if r.ok:
                unloaded.append(name)
        except Exception:
            pass
    return unloaded


def warm_model(settings: dict[str, Any], model_override: str | None = None) -> dict[str, Any]:
    model = str(model_override or resolve_model(settings, force=True) or "").strip()
    if not model:
        raise RuntimeError("No local model is installed. Pull a model first.")
    _prune_stale_project_runners_if_idle()
    result: dict[str, Any] = {"ok": True, "model": model}
    if _is_base_gpu_only_model(model):
        r = _warm_request(settings, model)
        if not r.ok:
            raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:800]}")
        result.update(_verify_base_gpu_residency(model, int(settings.get("ollama_num_ctx") or 8192)))
        result["gpu_mode"] = "full"
        return result
    if _is_huggingface_model(model):
        result.update(_ensure_hf_gpu_preference(settings, model))
        return result
    r = _warm_request(settings, model)
    if not r.ok:
        raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:800]}")
    return result


class _FixedLengthUpload:
    """File-like upload body that keeps Content-Length without chunked encoding.

    `requests` treats generator bodies as chunked streams, even when a manual
    Content-Length header is supplied. Ollama's blob endpoint expects a normal
    file upload, so expose a read()-based body with a stable __len__ instead.
    """

    def __init__(self, path: Path, cancel=None):
        self.path = Path(path)
        self.cancel = cancel
        self.handle = None
        self.size = int(self.path.stat().st_size)

    def __len__(self) -> int:
        return self.size

    def __enter__(self):
        self.handle = self.path.open("rb")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def read(self, amount: int = -1):
        if self.cancel and self.cancel():
            raise RuntimeError("Model import cancelled during Ollama blob upload.")
        if self.handle is None:
            raise RuntimeError("GGUF upload file is not open.")
        return self.handle.read(amount)

    def tell(self):
        if self.handle is None:
            return 0
        return self.handle.tell()

    def seek(self, *args):
        if self.handle is None:
            raise RuntimeError("GGUF upload file is not open.")
        return self.handle.seek(*args)

    def fileno(self):
        if self.handle is None:
            raise RuntimeError("GGUF upload file is not open.")
        return self.handle.fileno()

    def close(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None


def register_gguf_model(
    model_name: str,
    files: list[dict[str, Any]],
    progress=None,
    cancel=None,
) -> dict[str, Any]:
    """Register already-verified GGUF files with the private Ollama runtime.

    Files are uploaded by SHA-256 blob digest, then assembled through /api/create.
    Repository content is never executed and no shell command is used.
    """
    name = str(model_name or "").strip()
    if not name or any(ch.isspace() for ch in name):
        raise ValueError("Enter a valid local model name.")
    rows = list(files or [])
    if not rows:
        raise ValueError("No GGUF files were provided for registration.")

    create_files: dict[str, str] = {}
    for item in rows:
        if cancel and cancel():
            raise RuntimeError("Model import cancelled before Ollama registration.")
        file_name = str(item.get("name") or "").strip()
        path = Path(item.get("path") or "")
        digest = str(item.get("sha256") or "").strip().lower()
        size = int(item.get("size") or 0)
        if not file_name.lower().endswith(".gguf") or Path(file_name).name != file_name:
            raise ValueError("Ollama registration accepts GGUF basenames only.")
        if not path.is_file():
            raise RuntimeError(f"GGUF file is missing: {file_name}")
        if size <= 0:
            size = path.stat().st_size
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Invalid SHA-256 digest for {file_name}.")
        digest_ref = f"sha256:{digest}"
        create_files[file_name] = digest_ref

        if progress:
            progress("registering", f"Checking {file_name} in Ollama")
        head = requests.head(f"{ollama_root()}/api/blobs/{digest_ref}", timeout=(3.0, 15.0))
        if head.status_code == 404:
            if cancel and cancel():
                raise RuntimeError("Model import cancelled before Ollama blob upload.")
            if progress:
                progress("registering", f"Uploading {file_name} to Ollama")
            with _FixedLengthUpload(path, cancel=cancel) as upload:
                response = requests.post(
                    f"{ollama_root()}/api/blobs/{digest_ref}",
                    data=upload,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=(3.0, 3600.0),
                )
            if response.status_code not in {200, 201}:
                raise RuntimeError(f"Ollama blob upload failed for {file_name}: HTTP {response.status_code}: {response.text[:800]}")
        elif head.status_code != 200:
            head.raise_for_status()

    if cancel and cancel():
        raise RuntimeError("Model import cancelled before Ollama model creation.")
    if progress:
        progress("creating", f"Creating {name} in Ollama")
    body = {"model": name, "files": create_files, "stream": True}
    success = False
    with requests.post(
        f"{ollama_root()}/api/create",
        json=body,
        stream=True,
        timeout=(3.0, 3600.0),
    ) as response:
        if not response.ok:
            raise RuntimeError(f"Ollama create failed: HTTP {response.status_code}: {response.text[:800]}")
        for raw in response.iter_lines(decode_unicode=True):
            if not raw:
                continue
            item = json.loads(raw)
            status = str(item.get("status") or "").strip()
            if item.get("error"):
                raise RuntimeError(str(item.get("error")))
            if progress and status:
                progress("creating", status)
            if status.lower() == "success":
                success = True
    if not success:
        raise RuntimeError("Ollama model creation ended without a success status.")

    models = list_models(force=True)
    names = _model_names(models)
    resolved = name if name in names else (f"{name}:latest" if ":" not in name and f"{name}:latest" in names else "")
    if not resolved:
        raise RuntimeError(f"Ollama reported success but {name} did not appear in the local model list.")
    return {"ok": True, "model": resolved, "files": create_files}


def _pull_worker(model: str) -> None:
    global _PULL_STATE
    try:
        with requests.post(
            f"{ollama_root()}/api/pull",
            json={"model": model, "stream": True},
            stream=True,
            timeout=(3, 3600),
        ) as r:
            r.raise_for_status()
            for raw in r.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                item = json.loads(raw)
                with _PULL_LOCK:
                    _PULL_STATE["status"] = item.get("status") or _PULL_STATE["status"]
                    _PULL_STATE["completed"] = int(item.get("completed") or 0)
                    _PULL_STATE["total"] = int(item.get("total") or 0)
                    if item.get("error"):
                        _PULL_STATE["error"] = str(item["error"])
            list_models(force=True)
    except Exception as exc:
        with _PULL_LOCK:
            _PULL_STATE["error"] = str(exc)
    finally:
        with _PULL_LOCK:
            _PULL_STATE["running"] = False
            if not _PULL_STATE.get("error"):
                _PULL_STATE["status"] = "success"


def start_pull(model: str) -> dict[str, Any]:
    model = str(model or "").strip()
    if not model or any(ch.isspace() for ch in model):
        raise ValueError("Enter a valid Ollama model name.")
    with _PULL_LOCK:
        if _PULL_STATE["running"]:
            raise RuntimeError(f"Already pulling {_PULL_STATE['model']}")
        _PULL_STATE.update(
            {"running": True, "model": model, "status": "starting", "completed": 0, "total": 0, "error": None}
        )
    threading.Thread(target=_pull_worker, args=(model,), daemon=True, name="matrixstudio2-pull").start()
    return pull_status()


def pull_status() -> dict[str, Any]:
    with _PULL_LOCK:
        return dict(_PULL_STATE)


def _keep_alive(settings):
    value = settings.get("ollama_keep_alive")
    value = str(value).strip() if value is not None else ""
    try:
        return int(value)
    except ValueError:
        return value or "5m"
