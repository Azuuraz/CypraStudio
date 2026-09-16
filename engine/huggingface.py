from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

GIB = 1024 ** 3
LIKELY_LIMIT = int(4.6 * GIB)
TIGHT_LIMIT = int(5.4 * GIB)
PARTIAL_LIMIT = int(8.0 * GIB)

MAX_FILE_BYTES = 100 * GIB
MAX_INSTALL_BYTES = 200 * GIB
DISK_MARGIN_BYTES = 1 * GIB
ROOT = Path(__file__).resolve().parents[1]
HF_TMP_ROOT = ROOT / "data" / "huggingface" / "tmp"
_INSTALL_LOCK = threading.RLock()
_CANCEL_EVENT = threading.Event()
_INSTALL_STATE: dict[str, Any] = {
    "running": False,
    "job_id": None,
    "phase": "idle",
    "repo_id": None,
    "revision": None,
    "group_id": None,
    "quant": None,
    "local_name": None,
    "completed": 0,
    "total": 0,
    "percent": 0,
    "current_file": None,
    "status": "Idle",
    "error": None,
    "cancel_requested": False,
    "cancellable": False,
    "select_after": True,
}


class InstallCancelled(RuntimeError):
    pass

_REPO_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SPLIT_RE = re.compile(r"^(?P<base>.+)-(?P<index>\d{5})-of-(?P<count>\d{5})\.gguf$", re.IGNORECASE)
_QUANT_RE = re.compile(
    r"(?i)(?:^|[-_.])(?P<quant>(?:UD[-_][A-Z0-9][A-Z0-9._-]*)|(?:IQ[1-4](?:_[A-Z0-9]+)+)|(?:Q[2-8](?:_[A-Z0-9]+)+))(?=$|[-_.])"
)


def normalize_repo_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw or any(ord(ch) < 32 for ch in raw):
        raise ValueError("Enter a Hugging Face repository such as owner/model-GGUF.")

    if "://" in raw:
        parsed = urlparse(raw)
        if parsed.scheme.lower() != "https" or parsed.hostname not in {"huggingface.co", "www.huggingface.co"}:
            raise ValueError("Only public https://huggingface.co model URLs are supported.")
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            raise ValueError("Hugging Face URL must identify owner/repository.")
        raw = "/".join(parts[:2])

    parts = raw.split("/")
    if len(parts) != 2:
        raise ValueError("Repository must use owner/repository format.")
    owner, repo = parts
    if owner in {".", ".."} or repo in {".", ".."}:
        raise ValueError("Repository path traversal is not allowed.")
    if not _REPO_PART.fullmatch(owner) or not _REPO_PART.fullmatch(repo):
        raise ValueError("Repository contains unsupported characters.")
    return f"{owner}/{repo}"


def _slug_piece(value: str, *, allow_colon: bool = False) -> str:
    text = str(value or "").strip().lower()
    if allow_colon:
        # preserve one tag separator, sanitize name and tag separately
        name, sep, tag = text.partition(":")
        name = re.sub(r"[^a-z0-9._/-]+", "-", name)
        name = re.sub(r"[-_.]{2,}", "-", name).strip("-._/") or "model"
        if sep:
            tag = re.sub(r"[^a-z0-9._-]+", "-", tag)
            tag = re.sub(r"[-_.]{2,}", "-", tag).strip("-._") or "latest"
            return f"{name}:{tag}"
        return name
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    return re.sub(r"[-_.]{2,}", "-", text).strip("-._") or "custom"


def safe_local_model_name(repo_id: str, quant: str, override: str = "") -> str:
    if str(override or "").strip():
        return _slug_piece(override, allow_colon=True)
    normalized = normalize_repo_id(repo_id)
    owner, repo = normalized.split("/", 1)
    base = f"hf-{owner}-{repo}"
    base = _slug_piece(base, allow_colon=False)
    quant_tag = _slug_piece(str(quant or "custom").replace(" / ", "-"), allow_colon=False)
    return f"{base}:{quant_tag}"


def infer_quant(path: str) -> str:
    name = Path(str(path or "")).name
    stem = re.sub(r"-\d{5}-of-\d{5}\.gguf$", "", name, flags=re.IGNORECASE)
    if stem.lower().endswith(".gguf"):
        stem = stem[:-5]
    match = _QUANT_RE.search(stem)
    if not match:
        return "UNKNOWN / CUSTOM"
    quant = match.group("quant").upper().replace("UD_", "UD-")
    return quant


def classify_6gb(total_bytes: int) -> dict[str, Any]:
    size = max(0, int(total_bytes or 0))
    if size <= LIKELY_LIMIT:
        return {"tier": "likely", "label": "LIKELY 6 GB FIT", "rank": 0}
    if size <= TIGHT_LIMIT:
        return {"tier": "tight", "label": "TIGHT 6 GB", "rank": 1}
    if size <= PARTIAL_LIMIT:
        return {"tier": "partial", "label": "PARTIAL OFFLOAD LIKELY", "rank": 2}
    return {"tier": "heavy", "label": "RAM/OFFLOAD HEAVY", "rank": 3}


def _group_id(paths: list[str]) -> str:
    key = "\n".join(sorted(paths)).encode("utf-8")
    return hashlib.sha256(key).hexdigest()[:20]


def group_gguf_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    singles: list[dict[str, Any]] = []

    for raw in files or []:
        path = str(raw.get("path") or raw.get("rfilename") or "").strip()
        if not path.lower().endswith(".gguf"):
            continue
        size = max(0, int(raw.get("size") or 0))
        base_name = Path(path).name
        split = _SPLIT_RE.match(base_name)
        item = {"path": path, "name": base_name, "size": size}
        if split:
            key = split.group("base").lower()
            bucket = buckets.setdefault(
                key,
                {
                    "base": split.group("base"),
                    "expected": int(split.group("count")),
                    "shards": {},
                },
            )
            bucket["expected"] = max(int(bucket["expected"]), int(split.group("count")))
            bucket["shards"][int(split.group("index"))] = item
        else:
            singles.append(item)

    groups: list[dict[str, Any]] = []
    for bucket in buckets.values():
        expected = int(bucket["expected"])
        shards_map: dict[int, dict[str, Any]] = bucket["shards"]
        shards = [shards_map[i] for i in sorted(shards_map)]
        missing = [i for i in range(1, expected + 1) if i not in shards_map]
        total = sum(int(x["size"]) for x in shards)
        quant = infer_quant(bucket["base"] + ".gguf")
        paths = [x["path"] for x in shards]
        groups.append(
            {
                "id": _group_id(paths),
                "label": bucket["base"],
                "quant": quant,
                "files": shards,
                "total_bytes": total,
                "shard_count": len(shards),
                "expected_shards": expected,
                "missing_shards": missing,
                "complete": not missing and len(shards) == expected,
                "fit": classify_6gb(total),
            }
        )

    for item in singles:
        total = int(item["size"])
        groups.append(
            {
                "id": _group_id([item["path"]]),
                "label": Path(item["path"]).stem,
                "quant": infer_quant(item["path"]),
                "files": [item],
                "total_bytes": total,
                "shard_count": 1,
                "expected_shards": 1,
                "missing_shards": [],
                "complete": True,
                "fit": classify_6gb(total),
            }
        )

    return sort_groups(groups, "largest-fit")


def sort_groups(groups: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    rows = [deepcopy(g) for g in (groups or [])]
    mode = str(mode or "largest-fit").lower()
    if mode == "size":
        return sorted(rows, key=lambda g: (int(g.get("total_bytes") or 0), str(g.get("quant") or "")))
    if mode == "quant":
        return sorted(rows, key=lambda g: (str(g.get("quant") or ""), int(g.get("total_bytes") or 0)))

    tier_rank = {"likely": 0, "tight": 1, "partial": 2, "heavy": 3}
    return sorted(
        rows,
        key=lambda g: (
            tier_rank.get(str((g.get("fit") or {}).get("tier") or "heavy"), 9),
            -int(g.get("total_bytes") or 0),
            str(g.get("quant") or ""),
        ),
    )


HF_API = "https://huggingface.co/api/models"
HF_USER_AGENT = "MatrixStudio2/2.3 experimental GGUF importer"

def _hf_headers() -> dict[str, str]:
    return {"User-Agent": HF_USER_AGENT, "Accept": "application/json"}

def search_models(query: str, limit: int = 12) -> list[dict[str, Any]]:
    q = str(query or "").strip()
    if not q:
        return []
    bounded = max(1, min(30, int(limit or 12)))
    response = requests.get(
        HF_API,
        params={
            "search": q,
            "filter": "gguf",
            "limit": bounded,
            "sort": "downloads",
            "direction": -1,
        },
        headers=_hf_headers(),
        timeout=(3.5, 20),
    )
    response.raise_for_status()
    rows: list[dict[str, Any]] = []
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Hugging Face returned an unexpected search response.")
    for item in payload:
        if not isinstance(item, dict) or item.get("private"):
            continue
        repo_id = str(item.get("id") or item.get("modelId") or "").strip()
        try:
            repo_id = normalize_repo_id(repo_id)
        except ValueError:
            continue
        rows.append({
            "repo_id": repo_id,
            "downloads": int(item.get("downloads") or 0),
            "likes": int(item.get("likes") or 0),
            "revision": str(item.get("sha") or ""),
            "last_modified": item.get("lastModified") or item.get("last_modified"),
            "pipeline_tag": item.get("pipeline_tag"),
            "library_name": item.get("library_name"),
        })
    return rows

def inspect_repo(repo_input: str) -> dict[str, Any]:
    repo_id = normalize_repo_id(repo_input)
    response = requests.get(
        f"{HF_API}/{quote(repo_id, safe='/')}",
        params={"blobs": "true"},
        headers=_hf_headers(),
        timeout=(3.5, 20),
    )
    if response.status_code == 404:
        raise ValueError("Hugging Face repository was not found or is not public.")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Hugging Face returned an unexpected repository response.")
    if payload.get("private") or payload.get("gated") not in (False, None, "false"):
        raise ValueError("This experimental importer supports public, non-gated Hugging Face repositories only.")
    revision = str(payload.get("sha") or "").strip()
    if not revision:
        raise RuntimeError("Hugging Face did not return a commit revision for this repository.")
    gguf_files: list[dict[str, Any]] = []
    for sibling in payload.get("siblings") or []:
        if not isinstance(sibling, dict):
            continue
        path = str(sibling.get("rfilename") or sibling.get("path") or "").strip()
        if not path.lower().endswith(".gguf"):
            continue
        size = sibling.get("size")
        if size is None and isinstance(sibling.get("lfs"), dict):
            size = sibling["lfs"].get("size")
        gguf_files.append({"path": path, "size": max(0, int(size or 0))})
    groups = group_gguf_files(gguf_files)
    if not groups:
        raise ValueError("This repository does not expose any GGUF files.")
    for group in groups:
        group["suggested_local_name"] = safe_local_model_name(repo_id, str(group.get("quant") or "custom"))
    return {
        "repo_id": repo_id,
        "revision": revision,
        "downloads": int(payload.get("downloads") or 0),
        "likes": int(payload.get("likes") or 0),
        "last_modified": payload.get("lastModified") or payload.get("last_modified"),
        "groups": groups,
    }


def _allowed_download_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return False
    if parsed.scheme.lower() != "https":
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return (
        host in {"huggingface.co", "www.huggingface.co"}
        or host.endswith(".huggingface.co")
        or host.endswith(".hf.co")
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _preflight_disk(root: Path, total_bytes: int) -> None:
    total = int(total_bytes or 0)
    if total <= 0:
        raise RuntimeError("Hugging Face did not provide a reliable GGUF download size; safe install cannot start.")
    if total > MAX_INSTALL_BYTES:
        raise RuntimeError("Selected GGUF set exceeds the 200 GiB experimental safety ceiling.")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    free = int(shutil.disk_usage(root).free)
    needed = total + DISK_MARGIN_BYTES
    if free < needed:
        raise RuntimeError(
            f"Not enough free disk space for this model. Need about {needed / GIB:.1f} GiB including the 1 GiB working margin."
        )


def _download_file(
    url: str,
    destination: Path,
    expected_size: int,
    *,
    cancel_event: Any,
    progress: Any = None,
) -> Path:
    expected = int(expected_size or 0)
    if expected <= 0:
        raise RuntimeError("GGUF file size metadata is unavailable.")
    if expected > MAX_FILE_BYTES:
        raise RuntimeError("GGUF file exceeds the 100 GiB experimental safety ceiling.")
    if not _allowed_download_url(url):
        raise RuntimeError("Unsupported Hugging Face download URL.")

    destination = Path(destination)
    if destination.suffix.lower() != ".gguf":
        raise RuntimeError("Only .gguf files may be downloaded by this importer.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    if destination.exists() and destination.stat().st_size == expected:
        return destination
    if destination.exists():
        destination.unlink(missing_ok=True)

    if cancel_event.is_set():
        part.unlink(missing_ok=True)
        raise InstallCancelled("Hugging Face install cancelled.")

    resume_from = part.stat().st_size if part.exists() else 0
    if resume_from >= expected:
        part.unlink(missing_ok=True)
        resume_from = 0
    headers = _hf_headers()
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"

    try:
        with requests.get(
            url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=(5, 90),
        ) as response:
            if not _allowed_download_url(response.url):
                raise RuntimeError("Hugging Face redirected to an unsupported download host.")
            response.raise_for_status()
            append_mode = bool(resume_from and response.status_code == 206)
            if resume_from and not append_mode:
                part.unlink(missing_ok=True)
                resume_from = 0
            mode = "ab" if append_mode else "wb"
            written = resume_from
            with part.open(mode) as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if cancel_event.is_set():
                        raise InstallCancelled("Hugging Face install cancelled.")
                    if not chunk:
                        continue
                    handle.write(chunk)
                    written += len(chunk)
                    if written > expected:
                        raise RuntimeError("Downloaded GGUF exceeded its expected size.")
                    if progress:
                        progress(written)
        actual = part.stat().st_size if part.exists() else 0
        if actual != expected:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"Downloaded GGUF size mismatch: expected {expected} bytes, received {actual}.")
        os.replace(part, destination)
        return destination
    except InstallCancelled:
        part.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise


def _set_state(**patch: Any) -> dict[str, Any]:
    with _INSTALL_LOCK:
        _INSTALL_STATE.update(patch)
        total = int(_INSTALL_STATE.get("total") or 0)
        completed = int(_INSTALL_STATE.get("completed") or 0)
        _INSTALL_STATE["percent"] = round((completed / total) * 100, 1) if total else 0
        return dict(_INSTALL_STATE)


def install_status() -> dict[str, Any]:
    with _INSTALL_LOCK:
        return dict(_INSTALL_STATE)


def cancel_install() -> dict[str, Any]:
    with _INSTALL_LOCK:
        if not _INSTALL_STATE.get("running"):
            return dict(_INSTALL_STATE)
        if _INSTALL_STATE.get("phase") in {"creating", "ready"}:
            raise RuntimeError("Model creation has already committed and can no longer be cancelled safely.")
        _INSTALL_STATE["cancel_requested"] = True
        _INSTALL_STATE["status"] = "Cancelling…"
        _CANCEL_EVENT.set()
        return dict(_INSTALL_STATE)


def _file_download_url(repo_id: str, revision: str, path: str) -> str:
    safe_repo = quote(normalize_repo_id(repo_id), safe="/")
    safe_revision = quote(str(revision or ""), safe="")
    if not safe_revision:
        raise ValueError("Repository revision is required.")
    safe_path = quote(str(path or ""), safe="/")
    return f"https://huggingface.co/{safe_repo}/resolve/{safe_revision}/{safe_path}"


def _safe_download_basename(remote_path: str) -> str:
    raw = str(remote_path or "")
    if not raw or any(ord(ch) < 32 for ch in raw):
        raise ValueError("Invalid GGUF filename.")
    if raw.startswith(("/", "\\")) or "\\" in raw:
        raise ValueError("Unsafe GGUF filename path.")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Unsafe GGUF filename path.")
    name = parts[-1]
    if name in {"", ".", ".."} or not name.lower().endswith(".gguf"):
        raise ValueError("Only GGUF filenames are allowed.")
    if ":" in name:
        raise ValueError("Unsafe GGUF filename.")
    return name


def _record_installed_origin(model: str, repo: dict[str, Any], group: dict[str, Any]) -> bool:
    from engine import llm
    try:
        llm.remember_huggingface_model(
            model,
            repo_id=str(repo.get("repo_id") or ""),
            revision=str(repo.get("revision") or ""),
            quant=str(group.get("quant") or ""),
            size_bytes=int(group.get("total_bytes") or 0),
        )
    except (OSError, ValueError, TypeError):
        # The Ollama model has already been created at this point. Registry
        # metadata is useful for custom names but must never turn a successful
        # model import into a false failure.
        return False
    return True


def _install_worker(repo: dict[str, Any], group: dict[str, Any], local_name: str, select_after: bool, job_dir: Path) -> None:
    try:
        files = group.get("files") or []
        aggregate_done = 0
        downloaded: list[dict[str, Any]] = []
        _set_state(phase="downloading", status="Downloading GGUF", cancellable=True)
        for file_meta in files:
            if _CANCEL_EVENT.is_set():
                raise InstallCancelled("Hugging Face install cancelled.")
            remote_path = str(file_meta.get("path") or "")
            expected = int(file_meta.get("size") or 0)
            basename = _safe_download_basename(remote_path)
            target = job_dir / basename
            base_before = aggregate_done

            def on_progress(current: int, base: int = base_before) -> None:
                _set_state(completed=base + int(current), current_file=basename)

            url = _file_download_url(repo["repo_id"], repo["revision"], remote_path)
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    _download_file(url, target, expected, cancel_event=_CANCEL_EVENT, progress=on_progress)
                    last_error = None
                    break
                except InstallCancelled:
                    raise
                except Exception as exc:
                    last_error = exc
                    if attempt >= 2:
                        raise
                    time.sleep(0.35 * (attempt + 1))
            if last_error:
                raise last_error
            aggregate_done += expected
            _set_state(completed=aggregate_done, current_file=basename)
            downloaded.append({"name": basename, "path": target, "size": expected})

        _set_state(phase="verifying", status="Verifying SHA-256", cancellable=True, current_file=None)
        for item in downloaded:
            if _CANCEL_EVENT.is_set():
                raise InstallCancelled("Hugging Face install cancelled.")
            item["sha256"] = _sha256_file(Path(item["path"]))

        from engine import llm
        from engine.storage import load_settings

        while True:
            if _CANCEL_EVENT.is_set():
                raise InstallCancelled("Hugging Face install cancelled.")
            runtime = llm.runtime_status(load_settings())
            if runtime.get("ok"):
                break
            _set_state(
                phase="waiting_runtime",
                status="Reconnect the private Ollama runtime to continue",
                cancellable=True,
            )
            time.sleep(1.0)

        def registration_progress(phase: str, status: str) -> None:
            _set_state(phase=phase, status=status, cancellable=(phase != "creating"))

        result = llm.register_gguf_model(
            local_name,
            downloaded,
            progress=registration_progress,
            cancel=lambda: _CANCEL_EVENT.is_set(),
        )
        _record_installed_origin(result["model"], repo, group)
        if _CANCEL_EVENT.is_set():
            raise InstallCancelled("Hugging Face install cancelled.")
        if select_after:
            from engine.storage import update_settings
            update_settings({"ollama_chat_model": result["model"]})
        shutil.rmtree(job_dir, ignore_errors=True)
        _set_state(
            running=False, phase="ready", status="Ready", error=None, cancellable=False,
            completed=int(group.get("total_bytes") or 0), current_file=None, local_name=result["model"],
        )
    except InstallCancelled as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        _set_state(running=False, phase="cancelled", status="Cancelled", error=None, cancellable=False, current_file=None)
    except Exception as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        _set_state(running=False, phase="failed", status="Install failed", error=str(exc), cancellable=False, current_file=None)


def start_install(
    repo_id: str,
    revision: str,
    group_id: str,
    local_name: str = "",
    *,
    select_after: bool = True,
) -> dict[str, Any]:
    with _INSTALL_LOCK:
        if _INSTALL_STATE.get("running"):
            raise RuntimeError(f"Hugging Face install already running for {_INSTALL_STATE.get('repo_id') or 'a model'}.")

    from engine import llm
    if llm.pull_status().get("running"):
        raise RuntimeError("Wait for the current Ollama model pull to finish before importing from Hugging Face.")

    repo = inspect_repo(repo_id)
    if str(repo.get("revision") or "") != str(revision or ""):
        raise RuntimeError("Repository revision changed. Inspect the repository again before installing.")
    group = next((g for g in repo.get("groups") or [] if g.get("id") == group_id), None)
    if not group:
        raise ValueError("Selected GGUF group is no longer available in this repository revision.")
    if not group.get("complete"):
        raise ValueError("Selected split GGUF is incomplete and cannot be installed.")
    total = int(group.get("total_bytes") or 0)
    if total <= 0 or any(int(f.get("size") or 0) <= 0 for f in group.get("files") or []):
        raise RuntimeError("GGUF size metadata is unavailable, so safe disk preflight cannot be completed.")
    if any(int(f.get("size") or 0) > MAX_FILE_BYTES for f in group.get("files") or []):
        raise RuntimeError("One or more GGUF shards exceed the 100 GiB safety ceiling.")
    if total > MAX_INSTALL_BYTES:
        raise RuntimeError("Selected GGUF set exceeds the 200 GiB safety ceiling.")

    resolved_name = safe_local_model_name(repo["repo_id"], group.get("quant") or "custom", local_name)
    installed_names = {str(m.get("name") or m.get("model") or "") for m in llm.list_models(force=True)}
    if resolved_name in installed_names:
        raise RuntimeError(f"Model {resolved_name} is already installed.")

    if HF_TMP_ROOT.exists():
        for stale in HF_TMP_ROOT.iterdir():
            if stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)
            elif stale.is_file():
                stale.unlink(missing_ok=True)
    job_id = uuid.uuid4().hex[:16]
    job_dir = HF_TMP_ROOT / job_id
    _preflight_disk(job_dir, total)
    _CANCEL_EVENT.clear()
    _set_state(
        running=True, job_id=job_id, phase="preflight", repo_id=repo["repo_id"], revision=repo["revision"],
        group_id=group["id"], quant=group.get("quant"), local_name=resolved_name, completed=0, total=total,
        current_file=None, status="Preparing download", error=None, cancel_requested=False, cancellable=True,
        select_after=bool(select_after),
    )
    threading.Thread(
        target=_install_worker, args=(repo, group, resolved_name, bool(select_after), job_dir),
        daemon=True, name="matrixstudio2-huggingface-install",
    ).start()
    return install_status()
