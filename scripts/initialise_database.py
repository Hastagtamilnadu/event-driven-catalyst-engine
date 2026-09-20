"""
Database initialization script (§26, §28, §35.1).
Initializes the SQLite transactional ledger and applies all compatible migrations.
"""
from __future__ import annotations

import sqlite3
import sys

from qual_event_engine.persistence.database import initialise
from qual_event_engine.settings import get_settings


def main() -> int:
    settings = get_settings()
    print(f"Initialising database at {settings.db_path}...")
    try:
        initialise(settings.db_path)
        print("Database initialisation and migration check complete.")
        return 0
    except (sqlite3.Error, OSError) as e:
        print(f"Error initialising database: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
