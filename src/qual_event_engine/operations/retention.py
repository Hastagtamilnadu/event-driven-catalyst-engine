from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    raw_archive_retention_days: int = 3650  # 10 years
    job_run_retention_days: int = 90
    health_check_retention_days: int = 30
    incident_retention_days: int = 1825  # 5 years


class RetentionManager:
    """Enforces data retention, table purging, and storage maintenance according to Section 29."""

    def __init__(self, connection: sqlite3.Connection, policy: RetentionPolicy | None = None) -> None:
        self.connection = connection
        self.policy = policy or RetentionPolicy()

    def purge_expired_records(self) -> dict[str, int]:
        now = datetime.now(UTC)
        results = {}

        # 1. Purge old health checks
        health_cutoff = (now - timedelta(days=self.policy.health_check_retention_days)).isoformat()
        cur = self.connection.execute("DELETE FROM source_health WHERE checked_at_utc < ?", (health_cutoff,))
        results["purged_source_health"] = cur.rowcount

        # 2. Purge old job runs
        job_cutoff = (now - timedelta(days=self.policy.job_run_retention_days)).isoformat()
        cur = self.connection.execute("DELETE FROM job_run WHERE completed_at_utc < ?", (job_cutoff,))
        results["purged_job_runs"] = cur.rowcount

        return results

    def optimize_database(self) -> None:
        self.connection.execute("PRAGMA optimize")
