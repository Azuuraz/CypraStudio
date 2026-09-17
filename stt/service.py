"""Local-first speech-to-text service for CypraStudio live calls.

Preparation is deliberately lazy and user-triggered. Dependency installation and
model acquisition run in a background worker so the WebView stays responsive.
Preparation state and a bounded local log make failures diagnosable instead of
appearing as a permanently stuck button.
"""

from __future__ import annotations

import gc
import importlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any


class STTUnavailable(RuntimeError):
    pass


SUPPORTED_MODELS = {"tiny.en", "base.en", "small.en"}
SUPPORTED_AUDIO_TYPES = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
}
MAX_AUDIO_BYTES = 16 * 1024 * 1024
PREPARE_TIMEOUT_SECONDS = 600


def normalize_model(value: object) -> str:
    candidate = str(value or "base.en").strip().lower()
    return candidate if candidate in SUPPORTED_MODELS else "base.en"


def audio_signature_valid(data: bytes, content_type: str) -> bool:
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    if mime == "audio/webm":
        return data.startswith(b"\x1a\x45\xdf\xa3")
    if mime == "audio/ogg":
        return data.startswith(b"OggS")
    if mime in {"audio/wav", "audio/x-wav"}:
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WAVE"
    if mime in {"audio/mp4", "audio/m4a"}:
        return len(data) >= 12 and data[4:8] == b"ftyp"
    return False


def _compact_error(value: object, limit: int = 420) -> str:
    text = " ".join(str(value or "").replace("\x00", "").split()).strip()
    return text[:limit]


class LocalSTTService:
    """Lazy CPU/int8 faster-whisper runtime with project-owned model storage."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.root = (self.project_root / "MatrixFiles" / "Voice" / "STT").resolve()
        self.models_dir = self.root / "models"
        self.tmp_dir = self.root / "tmp"
        self.prepare_log = self.root / "prepare.log"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._prepare_lock = threading.Lock()
        self._prepare_thread: threading.Thread | None = None
        self._model: Any = None
        self._model_name = "base.en"
        self._active = False
        self._last_error = ""
        self._prepare_state = "idle"
        self._prepare_message = "Local STT not prepared"
        self._prepare_started_at = 0.0

    @staticmethod
    def dependency_available() -> bool:
        try:
            return importlib.util.find_spec("faster_whisper") is not None
        except Exception:
            return False

    def _set_prepare_state(self, state: str, message: str, *, error: str = "") -> None:
        with self._lock:
            self._prepare_state = str(state or "idle")
            self._prepare_message = _compact_error(message, 260)
            if error:
                self._last_error = _compact_error(error)
            elif state == "ready":
                self._last_error = ""

    def status(self) -> dict[str, object]:
        with self._lock:
            thread = self._prepare_thread
            running = bool(thread and thread.is_alive())
            return {
                "dependency": self.dependency_available(),
                "model_ready": self._model is not None,
                "active": self._active,
                "model": self._model_name,
                "device": "CPU",
                "compute_type": "int8",
                "models_dir": str(self.models_dir.relative_to(self.project_root)),
                "prepare_log": str(self.prepare_log.relative_to(self.project_root)),
                "prepare_state": self._prepare_state,
                "prepare_message": self._prepare_message,
                "preparing": running,
                "prepare_started_at": self._prepare_started_at or None,
                "last_error": self._last_error or None,
            }

    def _write_prepare_log_header(self, model_name: str) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.prepare_log.write_text(
                f"CypraStudio local STT preparation\n"
                f"time={time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"python={sys.version.split()[0]}\n"
                f"executable={sys.executable}\n"
                f"model={model_name}\n\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    def _log_prepare(self, text: object) -> None:
        try:
            with self.prepare_log.open("a", encoding="utf-8", errors="replace") as handle:
                handle.write(str(text or "") + "\n")
        except OSError:
            pass

    def _prepare_log_tail(self) -> str:
        try:
            text = self.prepare_log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        useful = [line.strip() for line in text.splitlines() if line.strip()]
        # Pip normally leaves the actionable error in the final few lines.
        return _compact_error(" | ".join(useful[-5:]), 420)

    def _install_dependency(self) -> bool:
        if self.dependency_available():
            return True
        package = "faster-whisper>=1.2,<2"
        base_args = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--prefer-binary",
            "--retries",
            "2",
            "--timeout",
            "60",
        ]
        offline = self.project_root / "Setup" / "python_packages"
        attempts: list[tuple[str, list[str]]] = []
        if offline.exists() and any(path.is_file() and path.suffix.lower() in {".whl", ".zip"} for path in offline.iterdir()):
            attempts.append(("offline", base_args + ["--no-index", "--find-links", str(offline), package]))
        attempts.append(("online", base_args + [package]))
        for label, args in attempts:
            self._log_prepare(f"dependency attempt={label}")
            try:
                with self.prepare_log.open("a", encoding="utf-8", errors="replace") as log:
                    result = subprocess.run(
                        args,
                        cwd=str(self.project_root),
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=PREPARE_TIMEOUT_SECONDS,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                        text=True,
                    )
            except subprocess.TimeoutExpired:
                self._log_prepare(f"dependency attempt={label} timed out after {PREPARE_TIMEOUT_SECONDS}s")
                continue
            except OSError as exc:
                self._log_prepare(f"dependency attempt={label} failed: {type(exc).__name__}: {exc}")
                continue
            self._log_prepare(f"dependency attempt={label} exit={result.returncode}")
            if result.returncode == 0:
                importlib.invalidate_caches()
                if self.dependency_available():
                    return True
                self._log_prepare("pip returned success but faster_whisper is still not importable")
        return False

    def _model_path(self, selected: str, allow_download: bool) -> str:
        from faster_whisper.utils import download_model

        def cached_path() -> str:
            path = Path(download_model(selected, cache_dir=str(self.models_dir), local_files_only=True))
            for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
                if not (path / name).is_file() or not (path / name).stat().st_size:
                    raise FileNotFoundError(f"Local STT cache is incomplete: {name}")
            return str(path)

        try:
            return cached_path()
        except Exception:
            if not allow_download:
                raise
        self._set_prepare_state("downloading", f"Downloading {selected} model (up to {PREPARE_TIMEOUT_SECONDS // 60} minutes)…")
        self._log_prepare(f"Downloading {selected} using HTTP; timeout={PREPARE_TIMEOUT_SECONDS}s")
        # Isolate network acquisition so a stalled native transfer or cache lock
        # can be terminated, and a later preparation attempt can retry safely.
        env = os.environ.copy()
        env.update(HF_HUB_DISABLE_XET="1", HF_HUB_DOWNLOAD_TIMEOUT="30", HF_HUB_ETAG_TIMEOUT="15")
        args = [sys.executable, "-c",
                "import sys; from faster_whisper.utils import download_model; "
                "download_model(sys.argv[1], cache_dir=sys.argv[2])",
                selected, str(self.models_dir)]
        try:
            with self.prepare_log.open("a", encoding="utf-8", errors="replace") as log:
                result = subprocess.run(args, cwd=str(self.project_root), env=env,
                                        stdout=log, stderr=subprocess.STDOUT,
                                        timeout=PREPARE_TIMEOUT_SECONDS,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired as exc:
            raise STTUnavailable("Local STT download timed out. Check your connection and retry Prepare Local STT.") from exc
        if result.returncode:
            raise STTUnavailable(self._prepare_log_tail() or "Local STT model download failed")
        return cached_path()

    def prepare(self, *, model_name: str = "base.en", allow_install: bool, allow_download: bool) -> bool:
        selected = normalize_model(model_name)
        with self._prepare_lock:
            with self._lock:
                if self._model is not None and self._model_name == selected:
                    self._set_prepare_state("ready", f"Local STT ready · {selected}")
                    return True
            if not self.dependency_available():
                if not allow_install:
                    self._set_prepare_state("error", "Local STT dependency is not installed", error="faster-whisper is not installed")
                    return False
                self._set_prepare_state("installing", "Installing faster-whisper and binary dependencies…")
                if not self._install_dependency():
                    detail = self._prepare_log_tail() or "pip could not install faster-whisper"
                    self._set_prepare_state("error", "Local STT dependency installation failed", error=detail)
                    return False
            try:
                self._set_prepare_state(
                    "downloading" if allow_download else "loading",
                    f"Downloading/loading {selected} into project-local STT storage…" if allow_download else f"Loading local {selected} model…",
                )
                from faster_whisper import WhisperModel

                model_path = self._model_path(selected, allow_download)
                self._set_prepare_state("loading", f"Loading local {selected} model…")
                self._log_prepare(f"Loading {selected} on CPU")
                model = WhisperModel(
                    model_path,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=2,
                    num_workers=1,
                    download_root=str(self.models_dir),
                    local_files_only=True,
                )
            except Exception as exc:
                detail = f"{type(exc).__name__}: {_compact_error(exc)}"
                self._log_prepare("model prepare failed: " + detail)
                self._set_prepare_state("error", "Local STT model preparation failed", error=detail)
                return False
            with self._lock:
                self._model = model
                self._model_name = selected
                self._last_error = ""
            self._set_prepare_state("ready", f"Local STT ready · {selected} · CPU int8")
            self._log_prepare("ready")
            return True

    def _prepare_job(self, selected: str, allow_install: bool, allow_download: bool) -> None:
        try:
            self.prepare(model_name=selected, allow_install=allow_install, allow_download=allow_download)
        except Exception as exc:  # defensive boundary; prepare normally converts errors into status
            detail = f"{type(exc).__name__}: {_compact_error(exc)}"
            self._log_prepare("unexpected prepare error: " + detail)
            self._set_prepare_state("error", "Local STT preparation failed", error=detail)

    def begin_prepare(self, *, model_name: str = "base.en", allow_install: bool, allow_download: bool) -> dict[str, object]:
        selected = normalize_model(model_name)
        with self._lock:
            if self._model is not None and self._model_name == selected:
                self._set_prepare_state("ready", f"Local STT ready · {selected} · CPU int8")
                return self.status()
            if self._prepare_thread is not None and self._prepare_thread.is_alive():
                return self.status()
            self._model_name = selected
            self._last_error = ""
            self._prepare_started_at = time.time()
            self._prepare_state = "queued"
            self._prepare_message = f"Preparing {selected}…"
            self._write_prepare_log_header(selected)
            thread = threading.Thread(
                target=self._prepare_job,
                args=(selected, bool(allow_install), bool(allow_download)),
                daemon=True,
                name="cypra-stt-prepare",
            )
            self._prepare_thread = thread
            thread.start()
        return self.status()

    def transcribe(self, data: bytes, *, content_type: str, model_name: str = "base.en") -> str:
        mime = str(content_type or "").split(";", 1)[0].strip().lower()
        if mime not in SUPPORTED_AUDIO_TYPES:
            raise ValueError("Unsupported microphone audio type")
        if not data or len(data) > MAX_AUDIO_BYTES:
            raise ValueError("Microphone audio is empty or too large")
        if not audio_signature_valid(data, mime):
            raise ValueError("Microphone audio signature does not match its type")
        selected = normalize_model(model_name)
        if not self.prepare(model_name=selected, allow_install=False, allow_download=False):
            raise STTUnavailable("Local STT is not prepared")
        with self._lock:
            model = self._model
            self._active = True
        suffix = SUPPORTED_AUDIO_TYPES[mime]
        path: str | None = None
        try:
            fd, path = tempfile.mkstemp(prefix="utterance-", suffix=suffix, dir=str(self.tmp_dir))
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            segments, _info = model.transcribe(
                path,
                language="en",
                beam_size=1,
                best_of=1,
                vad_filter=True,
                condition_on_previous_text=False,
                without_timestamps=True,
            )
            text = " ".join(str(segment.text or "").strip() for segment in segments if str(segment.text or "").strip()).strip()
            return text
        except STTUnavailable:
            raise
        except Exception as exc:
            with self._lock:
                self._last_error = type(exc).__name__
            raise STTUnavailable("Local transcription failed") from exc
        finally:
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except Exception:
                    pass
            with self._lock:
                self._active = False

    def release(self) -> None:
        with self._lock:
            self._model = None
            self._active = False
        gc.collect()
