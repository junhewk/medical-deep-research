from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Medical Deep Research"
    data_dir: Path = Path("python_data")
    db_filename: str = "medical_deep_research.sqlite"
    legacy_db_path: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8080
    native_window: bool = False
    storage_secret: str = "medical-deep-research-local"
    offline_mode: bool = False

    model_config = SettingsConfigDict(
        env_prefix="MDR_",
        env_file=".env",
        extra="ignore",
    )

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename


def load_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
