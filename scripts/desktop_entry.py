"""PyInstaller entry point for the desktop app.

Sets native_window=True so the app opens in a pywebview window
instead of a browser tab. All other settings come from env / .env.
"""
import os
import sys

# Ensure the bundled package is importable when frozen
if getattr(sys, "frozen", False):
    bundle_dir = os.path.dirname(sys.executable)
    if bundle_dir not in sys.path:
        sys.path.insert(0, bundle_dir)

# Force native window mode for desktop builds
os.environ.setdefault("MDR_NATIVE_WINDOW", "true")

from medical_deep_research.main import main  # noqa: E402

if __name__ == "__main__":
    main()
