from __future__ import annotations

from nicegui import ui

from .config import load_settings
from .persistence import AppDatabase
from .service import ResearchService
from .ui import build_ui


def main() -> None:
    settings = load_settings()
    database = AppDatabase(settings)
    database.create_all()
    database.bootstrap_defaults()
    database.import_legacy_data(settings.legacy_db_path)
    service = ResearchService(database)

    port = settings.port
    if settings.native_window:
        from nicegui import native
        port = native.find_open_port()

    ui.run(
        root=lambda: build_ui(service),
        title=settings.app_name,
        host=settings.host,
        port=port,
        native=settings.native_window,
        storage_secret=settings.storage_secret,
        reload=False,
    )


if __name__ == "__main__":
    main()
