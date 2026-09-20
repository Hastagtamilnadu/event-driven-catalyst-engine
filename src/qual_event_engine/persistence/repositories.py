from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid4())


def insert_job(connection: sqlite3.Connection, job_name: str, config_hash: str) -> str:
    job_id = new_id()
    connection.execute(
        """INSERT INTO job_run(job_run_id,job_name,started_at_utc,status,config_hash,code_version)
           VALUES(?,?,?,?,?,?)""",
        (job_id, job_name, utc_now(), "STARTED", config_hash, "0.1.0"),
    )
    return job_id


def finish_job(
    connection: sqlite3.Connection, job_id: str, status: str, error: str | None = None
) -> None:
    connection.execute(
        "UPDATE job_run SET finished_at_utc=?, status=?, error_summary=? WHERE job_run_id=?",
        (utc_now(), status, error, job_id),
    )


def records(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def json_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)
