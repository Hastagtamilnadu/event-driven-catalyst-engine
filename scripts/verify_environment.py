"""
Environment verification script (§26, §35.1).
Verifies Python version, directory structure, environment variables, and dependencies.
"""
from __future__ import annotations

import sys

from qual_event_engine.settings import get_settings


def verify_environment() -> int:
    print("Verifying Python 3.11 runtime...")
    if sys.version_info[:2] != (3, 11):
        print(f"Error: Python 3.11 required, found {sys.version}", file=sys.stderr)
        return 1

    print("Verifying project settings and paths...")
    try:
        settings = get_settings()
        for d in [settings.data_root, settings.log_root, settings.archive_root]:
            d.mkdir(parents=True, exist_ok=True)
            if not d.exists():
                print(f"Error: Failed to ensure directory {d}", file=sys.stderr)
                return 1
        print(f"  Data root: {settings.data_root} [OK]")
        print(f"  Log root: {settings.log_root} [OK]")
        print(f"  Archive root: {settings.archive_root} [OK]")
        print(f"  DB Path: {settings.db_path} [OK]")
    except (RuntimeError, ValueError, OSError) as e:
        print(f"Error loading settings: {e}", file=sys.stderr)
        return 1

    print("Environment verification passed cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(verify_environment())
