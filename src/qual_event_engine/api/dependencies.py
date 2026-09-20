from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator
from typing import Annotated

from fastapi import Header, HTTPException

from qual_event_engine.persistence.database import connect, initialise
from qual_event_engine.settings import Settings


def get_settings() -> Settings:
    settings = Settings.from_env()
    settings.ensure_directories()
    initialise(settings.db_path)
    return settings


def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    settings = get_settings()
    with connect(settings.db_path) as conn:
        yield conn


def require_write_token(
    x_qual_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = os.getenv("QUAL_ENGINE_LOCAL_API_TOKEN")
    if expected and x_qual_token != expected:
        raise HTTPException(status_code=401, detail="Invalid local API token")
