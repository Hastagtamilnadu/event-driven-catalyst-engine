from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class JobExecutionRecord:
    job_run_id: str
    job_name: str
    started_at_utc: datetime
    completed_at_utc: datetime | None
    status: str  # RUNNING, COMPLETED, FAILED
    items_processed: int
    error_message: str | None = None


class JobManager:
    """Tracks background operational job executions and status in the database."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def start_job(self, job_name: str) -> JobExecutionRecord:
        job_run_id = str(uuid4())
        now = datetime.now(UTC)
        self.connection.execute(
            """
            INSERT INTO job_run (job_run_id, job_name, started_at_utc, status, items_processed)
            VALUES (?, ?, ?, 'RUNNING', 0)
            """,
            (job_run_id, job_name, now.isoformat()),
        )
        return JobExecutionRecord(
            job_run_id=job_run_id,
            job_name=job_name,
            started_at_utc=now,
            completed_at_utc=None,
            status="RUNNING",
            items_processed=0,
        )

    def complete_job(self, job_run_id: str, items_processed: int = 0) -> None:
        now = datetime.now(UTC).isoformat()
        self.connection.execute(
            """
            UPDATE job_run
            SET completed_at_utc = ?, status = 'COMPLETED', items_processed = ?
            WHERE job_run_id = ?
            """,
            (now, items_processed, job_run_id),
        )

    def fail_job(self, job_run_id: str, error_message: str) -> None:
        now = datetime.now(UTC).isoformat()
        self.connection.execute(
            """
            UPDATE job_run
            SET completed_at_utc = ?, status = 'FAILED', error_message = ?
            WHERE job_run_id = ?
            """,
            (now, error_message, job_run_id),
        )
