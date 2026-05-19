"""PyInstaller entry point for the desktop app.

Boots the native PySide6 Qt application directly. There is no embedded
browser and no local HTTP server — the UI calls the backend in-process
via the same event loop (asyncio + qasync).
"""
import multiprocessing
import os
import sys

multiprocessing.freeze_support()

if getattr(sys, "frozen", False):
    bundle_dir = os.path.dirname(sys.executable)
    if bundle_dir not in sys.path:
        sys.path.insert(0, bundle_dir)
    # When launched from Finder, CWD is "/" — change to a writable user directory
    os.chdir(os.path.expanduser("~"))

    # When launched from Finder, stdout/stderr may be invalid file descriptors.
    # Redirect them to a log file so libraries that write to them don't crash.
    if sys.platform == "darwin":
        _log_dir = os.path.expanduser("~/Library/Logs/MedicalDeepResearch")
    elif sys.platform == "win32":
        _log_dir = os.path.expanduser(r"~\AppData\Local\MedicalDeepResearch\Logs")
    else:
        _log_dir = os.path.expanduser("~/.local/share/MedicalDeepResearch/logs")
    os.makedirs(_log_dir, exist_ok=True)
    _log_path = os.path.join(_log_dir, "app.log")
    _log_file = open(_log_path, "a")  # noqa: SIM115
    sys.stdout = _log_file
    sys.stderr = _log_file


def main() -> int:
    from medical_deep_research.main import main as _main
    return _main()


if __name__ == "__main__":
    sys.exit(main())
