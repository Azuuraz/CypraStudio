from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import threading
import time
import traceback
import atexit
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)
LOG = DATA / "launch.log"
READY = DATA / "studio.ready"
APP_RUNTIME = DATA / "app.runtime.json"
BUILD_ID = "2.3.16-edge-voice-switch-20260916"
APP_ID = "matrixstudio2-local"
os.chdir(ROOT)
sys.dont_write_bytecode = True


def log(message: str) -> None:
    try:
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  " + message + "\n")
    except Exception:
        pass



def write_app_runtime(port: int) -> None:
    payload = {
        "pid": os.getpid(),
        "port": int(port),
        "instance_id": os.environ.get("MATRIXSTUDIO2_INSTANCE_ID", ""),
        "root": str(ROOT),
        "started_at": time.time(),
    }
    try:
        tmp = APP_RUNTIME.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, APP_RUNTIME)
    except Exception:
        log("app runtime marker write failed: " + traceback.format_exc())


def clear_app_runtime() -> None:
    try:
        if APP_RUNTIME.exists():
            current = json.loads(APP_RUNTIME.read_text(encoding="utf-8"))
            if int(current.get("pid") or 0) == os.getpid():
                APP_RUNTIME.unlink(missing_ok=True)
    except Exception:
        pass


atexit.register(clear_app_runtime)

def read_settings() -> dict:
    try:
        return json.loads((DATA / "settings.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_ui_state() -> dict:
    try:
        return json.loads((DATA / "ui_state.json").read_text(encoding="utf-8"))
    except Exception:
        return {}



def valid_port(value: object) -> int | None:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1024 <= port <= 65535 else None


def resolve_port(settings: dict) -> int:
    env_port = valid_port(os.environ.get("MATRIXSTUDIO2_PORT"))
    if env_port is not None:
        return env_port
    saved_port = valid_port(settings.get("port"))
    if saved_port is not None:
        return saved_port
    return 8765

def valid_dimension(value: object, floor: int, ceiling: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(floor, min(ceiling, parsed))

def mark_ready(kind: str, url: str) -> None:
    try:
        tmp = READY.with_suffix(".ready.tmp")
        tmp.write_text(f"{os.getpid()}|{os.environ.get('MATRIXSTUDIO2_INSTANCE_ID','')}|{os.environ.get('MATRIXSTUDIO2_PORT','')}|{kind}|{url}", encoding="utf-8")
        os.replace(tmp, READY)
    except Exception:
        log("ready marker failed: " + traceback.format_exc())


def health_ok(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.0) as r:
            payload = json.loads(r.read().decode("utf-8"))
            return payload.get("app_id") == APP_ID and payload.get("build_id") == BUILD_ID
    except Exception:
        return False


def run_server(port: int) -> None:
    try:
        import uvicorn
        uvicorn.run("server:app", host="127.0.0.1", port=port, log_level="warning", access_log=False)
    except BaseException:
        log("server startup failed:\n" + traceback.format_exc())


def main() -> int:
    settings = read_settings()
    ui_state = read_ui_state()
    port = resolve_port(settings)
    log(f"desktop resolved app port {port}")
    url = f"http://127.0.0.1:{port}/"
    thread = threading.Thread(target=run_server, args=(port,), daemon=True, name="matrixstudio2-server")
    thread.start()
    deadline = time.time() + 30
    while time.time() < deadline:
        if health_ok(port):
            break
        if not thread.is_alive():
            log("server thread exited before becoming ready")
            return 2
        time.sleep(0.2)
    else:
        log("server did not become ready")
        return 2

    write_app_runtime(port)
    force_browser = os.environ.get("MATRIXSTUDIO2_BROWSER", "").lower() in {"1", "true", "yes"}
    if force_browser:
        webbrowser.open(url)
        mark_ready("browser", url)
        while thread.is_alive():
            time.sleep(1)
        return 0

    try:
        import webview
        width = valid_dimension(ui_state.get("window_width") or settings.get("window_width"), 900, 7680, 1440)
        height = valid_dimension(ui_state.get("window_height") or settings.get("window_height"), 650, 4320, 900)
        window = webview.create_window(
            "MatrixStudio2.0",
            url,
            width=width,
            height=height,
            min_size=(900, 650),
            background_color="#06080a",
        )
        ready_once = threading.Event()

        def report_ready(*_args) -> None:
            if not ready_once.is_set():
                ready_once.set()
                mark_ready("webview", url)

        # Backends differ slightly in when `loaded` fires. A visible native
        # window is sufficient for launcher handoff, while `loaded` remains a
        # second readiness signal when available.
        if hasattr(window.events, "shown"):
            window.events.shown += report_ready
        window.events.loaded += report_ready
        webview.start(debug=False)
        clear_app_runtime()
        return 0
    except Exception:
        log("webview failed; browser fallback:\n" + traceback.format_exc())
        webbrowser.open(url)
        mark_ready("browser", url)
        while thread.is_alive():
            time.sleep(1)
        return 0



if __name__ == "__main__":
    raise SystemExit(main())
