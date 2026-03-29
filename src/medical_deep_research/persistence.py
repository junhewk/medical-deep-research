from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine, select

from .config import Settings
from .models import ApiKey, ResearchRun, Setting


class AppDatabase:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{settings.db_path}", echo=False)

    def create_all(self) -> None:
        SQLModel.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine) as session:
            yield session

    def bootstrap_defaults(self) -> None:
        with self.session() as session:
            language = session.get(Setting, "language")
            if language is None:
                session.add(Setting(key="language", value="en", category="general"))
            session.commit()

    def import_legacy_data(self, legacy_db_path: Path | None) -> bool:
        if not legacy_db_path or not legacy_db_path.exists():
            return False

        with self.session() as session:
            already_imported = session.exec(select(ApiKey)).first() or session.exec(select(ResearchRun)).first()
            if already_imported:
                return False

        try:
            with sqlite3.connect(legacy_db_path) as legacy, self.session() as session:
                legacy.row_factory = sqlite3.Row

                for row in legacy.execute("select service, api_key from api_keys"):
                    session.add(ApiKey(service=row["service"], api_key=row["api_key"]))

                for row in legacy.execute("select key, value, category from settings"):
                    session.merge(Setting(key=row["key"], value=row["value"], category=row["category"]))

                reports_by_research = {
                    row["research_id"]: row["content"]
                    for row in legacy.execute("select research_id, content from reports")
                }

                for row in legacy.execute(
                    "select id, query, query_type, mode, status, progress, error_message, created_at, started_at, completed_at from research"
                ):
                    provider = "openai"
                    model = "gpt-5.2"
                    payload = json.dumps({"migrated_from_legacy": True})

                    def parse_timestamp(raw: int | None) -> datetime | None:
                        if not raw:
                            return None
                        return datetime.fromtimestamp(raw, UTC)

                    run = ResearchRun(
                        id=row["id"],
                        query=row["query"],
                        query_type=row["query_type"] or "free",
                        mode=row["mode"] or "detailed",
                        provider=provider,
                        model=model,
                        runtime_name="Legacy Import",
                        status=row["status"] or "completed",
                        phase="imported",
                        progress=row["progress"] or 100,
                        query_payload_json=payload,
                        result_markdown=reports_by_research.get(row["id"]),
                        error_message=row["error_message"],
                    )
                    run.created_at = parse_timestamp(row["created_at"]) or run.created_at
                    run.started_at = parse_timestamp(row["started_at"])
                    run.completed_at = parse_timestamp(row["completed_at"])
                    session.add(run)

                session.commit()
                return True
        except sqlite3.OperationalError:
            return False
