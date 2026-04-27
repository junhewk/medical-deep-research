"""PyInstaller entry point for the desktop app.

Runs NiceGUI as a local server and opens a pywebview window on the main
thread.  This avoids NiceGUI's built-in native mode which spawns a
multiprocessing child for pywebview — that approach is unreliable inside
a frozen PyInstaller .app bundle on macOS because the child process
lifecycle conflicts with AppKit.
"""
import multiprocessing
import os
import re
import sys
import threading
from pathlib import Path

multiprocessing.freeze_support()

if getattr(sys, "frozen", False):
    bundle_dir = os.path.dirname(sys.executable)
    if bundle_dir not in sys.path:
        sys.path.insert(0, bundle_dir)
    # When launched from Finder, CWD is "/" — change to a writable user directory
    os.chdir(os.path.expanduser("~"))

    # When launched from Finder, stdout/stderr may be invalid file descriptors.
    # Redirect them to a log file so libraries that write to them don't crash.
    _log_dir = os.path.expanduser("~/Library/Logs/MedicalDeepResearch")
    os.makedirs(_log_dir, exist_ok=True)
    _log_path = os.path.join(_log_dir, "app.log")
    _log_file = open(_log_path, "a")  # noqa: SIM115
    sys.stdout = _log_file
    sys.stderr = _log_file

# Do NOT enable native_window — we manage the window ourselves
os.environ.setdefault("MDR_NATIVE_WINDOW", "false")


def _safe_download_target(filename: str) -> Path:
    """Return a writable, non-overwriting path in the user's Downloads folder."""
    downloads_dir = Path.home() / "Downloads"
    if not downloads_dir.exists():
        downloads_dir = Path.home()

    safe_name = Path(filename).name.strip() or "medical-deep-research-report.txt"
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", safe_name)
    stem = Path(safe_name).stem or "medical-deep-research-report"
    suffix = Path(safe_name).suffix or ".txt"

    target = downloads_dir / f"{stem}{suffix}"
    counter = 1
    while target.exists():
        target = downloads_dir / f"{stem} ({counter}){suffix}"
        counter += 1
    return target


class DesktopApi:
    """Small pywebview API for desktop-only file saves."""

    def save_text_file(self, filename: str, content: str) -> dict[str, str | bool]:
        try:
            target = _safe_download_target(filename)
            target.write_text(content, encoding="utf-8")
            return {"ok": True, "path": str(target)}
        except Exception as exc:  # pragma: no cover - reported to UI
            return {"ok": False, "error": str(exc)}


def _run_server(port: int) -> None:
    """Start NiceGUI in a background thread (no native window)."""
    import logging
    import traceback

    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("mdr.desktop")

    try:
        from medical_deep_research.config import load_settings
        from medical_deep_research.persistence import AppDatabase
        from medical_deep_research.service import ResearchService
        from medical_deep_research.ui import build_ui
        from nicegui import ui

        settings = load_settings()
        database = AppDatabase(settings)
        database.create_all()
        database.bootstrap_defaults()
        database.import_legacy_data(settings.legacy_db_path)
        service = ResearchService(database)

        ui.run(
            root=lambda: build_ui(service),
            title=settings.app_name,
            host="127.0.0.1",
            port=port,
            native=False,
            storage_secret=settings.storage_secret,
            reload=False,
            show=False,
        )
    except Exception:
        log.error("Server thread crashed:\n%s", traceback.format_exc())


def main() -> None:
    import socket
    import time

    # Pick a free port in a high range to avoid conflicts
    port = 0
    for candidate in range(18515, 18600):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", candidate))
                port = candidate
                break
        except OSError:
            continue
    if port == 0:
        # Fallback to OS-assigned
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

    # Start the NiceGUI server in a daemon thread
    server_thread = threading.Thread(target=_run_server, args=(port,), daemon=True)
    server_thread.start()

    # Wait for NiceGUI to actually serve content (not just TCP open)
    import urllib.request
    url = f"http://127.0.0.1:{port}"
    for _ in range(150):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    # Open pywebview window on the MAIN thread (required by macOS AppKit)
    import webview
    webview.create_window(
        "Medical Deep Research",
        url,
        width=1280,
        height=860,
        js_api=DesktopApi(),
    )
    webview.start()


if __name__ == "__main__":
    main()
