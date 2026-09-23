from __future__ import annotations

"""§20.1 Health report and §29.4 source health contract.

Required health fields:
1. daily count vs expected range
2. cursor advancement
3. hash collision rate
4. parse failure rate
5. source latency
6. archive freshness
7. db WAL status
8. paper position reconciliation
9. model latency
10. incident count
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from qual_event_engine.config import read_yaml
from qual_event_engine.research.reports import reconciliation_report
from qual_event_engine.runtime import project_root

REQUIRED_HEALTH_FIELDS = (
    "daily_count_vs_expected_range",
    "cursor_advancement",
    "hash_collision_rate",
    "parse_failure_rate",
    "source_latency",
    "archive_freshness",
    "db_wal_status",
    "paper_position_reconciliation",
    "model_latency",
    "incident_count",
)


def health_snapshot(connection: sqlite3.Connection) -> dict[str, object]:
    cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    source_rows = connection.execute(
        """SELECT source_id,COUNT(*) AS count,MAX(system_first_seen_at_utc) AS latest
           FROM source_observation GROUP BY source_id ORDER BY source_id"""
    ).fetchall()
    state_rows = connection.execute(
        "SELECT event_state,COUNT(*) AS count FROM canonical_event GROUP BY event_state"
    ).fetchall()
    order_rows = connection.execute(
        "SELECT status,COUNT(*) AS count FROM paper_order GROUP BY status"
    ).fetchall()
    incidents = connection.execute(
        "SELECT severity,service,summary,opened_at_utc FROM incident WHERE status='OPEN' ORDER BY opened_at_utc DESC"
    ).fetchall()

    fields = compute_health_fields(connection)
    status = "FROZEN" if incidents or fields["freeze_recommended"] else "OK"
    return {
        "status": status,
        "sources": [dict(row) for row in source_rows],
        "event_states": [dict(row) for row in state_rows],
        "order_states": [dict(row) for row in order_rows],
        "open_incidents": [dict(row) for row in incidents],
        "cutoff_utc": cutoff,
        **{name: fields[name] for name in REQUIRED_HEALTH_FIELDS},
        "source_health_alerts": fields["source_health_alerts"],
        "freeze_recommended": fields["freeze_recommended"],
    }


def compute_health_fields(connection: sqlite3.Connection) -> dict[str, Any]:
    now = datetime.now(UTC)
    day_start = datetime(now.year, now.month, now.day, tzinfo=UTC).isoformat()
    expected = _source_expected_ranges()
    alerts: list[dict[str, Any]] = []

    counts: dict[str, int] = {}
    for row in connection.execute(
        """
        SELECT source_id, COUNT(*) FROM source_observation
        WHERE system_first_seen_at_utc >= ?
        GROUP BY source_id
        """,
        (day_start,),
    ).fetchall():
        counts[str(row[0])] = int(row[1])

    daily_vs_range: dict[str, Any] = {}
    for source_id, bounds in expected.items():
        count = counts.get(source_id, 0)
        lo, hi = bounds["health_min_count"], bounds["health_max_count"]
        expected_empty = not bounds.get("enabled", True)
        status = "OK"
        if count == 0 and not expected_empty:
            status = "COUNT_ZERO"
            alerts.append({"source_id": source_id, "reason": "count=0 outside expected empty period"})
        elif count > hi:
            status = "COUNT_IMPLAUSIBLY_HIGH"
            alerts.append({"source_id": source_id, "reason": "count implausibly high"})
        elif count < lo and not expected_empty:
            status = "COUNT_BELOW_MIN"
        daily_vs_range[source_id] = {
            "count": count,
            "health_min_count": lo,
            "health_max_count": hi,
            "status": status,
        }

    cursor_rows = connection.execute(
        """
        SELECT source_id,
               MAX(system_first_seen_at_utc) AS latest,
               COUNT(*) AS n
        FROM source_observation
        GROUP BY source_id
        """
    ).fetchall()
    cursor_advancement: dict[str, Any] = {}
    stale_cut = (now - timedelta(hours=36)).isoformat()
    for row in cursor_rows:
        latest = row["latest"]
        advanced = bool(latest and str(latest) >= stale_cut)
        cursor_advancement[str(row["source_id"])] = {
            "latest_system_first_seen_at_utc": latest,
            "advanced": advanced,
        }
        if not advanced:
            alerts.append({"source_id": row["source_id"], "reason": "cursor does not advance"})

    total_obs = connection.execute("SELECT COUNT(*) FROM source_observation").fetchone()[0]
    distinct_hash = connection.execute(
        "SELECT COUNT(DISTINCT raw_sha256) FROM source_observation WHERE raw_sha256 IS NOT NULL"
    ).fetchone()[0]
    collisions = max(0, int(total_obs) - int(distinct_hash))
    collision_rate = (collisions / total_obs) if total_obs else 0.0
    if collision_rate > 0.02 and total_obs >= 20:
        alerts.append({"source_id": "*", "reason": "hash collision rate jumps"})

    parse_total = connection.execute("SELECT COUNT(*) FROM raw_document").fetchone()[0]
    parse_fail = connection.execute(
        """
        SELECT COUNT(*) FROM raw_document
        WHERE parser_status IN ('UNSUPPORTED','MALICIOUS')
           OR extraction_quality IN ('UNSUPPORTED','MALICIOUS')
        """
    ).fetchone()[0]
    parse_failure_rate = (int(parse_fail) / int(parse_total)) if parse_total else 0.0
    if parse_failure_rate > 0.10 and parse_total >= 10:
        alerts.append({"source_id": "*", "reason": "parsing failure above tolerance"})

    latency_rows = connection.execute(
        """
        SELECT source_id,
               AVG((julianday(system_first_seen_at_utc) - julianday(source_published_at_utc)) * 1440.0)
                 AS avg_latency_minutes
        FROM source_observation
        WHERE source_published_at_utc IS NOT NULL AND system_first_seen_at_utc IS NOT NULL
        GROUP BY source_id
        """
    ).fetchall()
    source_latency = {str(r["source_id"]): r["avg_latency_minutes"] for r in latency_rows}

    archive_row = connection.execute(
        "SELECT MAX(archived_at_utc) FROM raw_document"
    ).fetchone()
    archive_latest = archive_row[0] if archive_row else None
    archive_fresh = bool(archive_latest and str(archive_latest) >= stale_cut)

    wal = connection.execute("PRAGMA journal_mode").fetchone()
    wal_status = str(wal[0]).upper() if wal else "UNKNOWN"
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    integrity_ok = bool(integrity and str(integrity[0]).lower() == "ok")

    recon = reconciliation_report(connection)

    model_row = connection.execute(
        "SELECT AVG(latency_ms), COUNT(*) FROM analyst_assessment WHERE latency_ms IS NOT NULL"
    ).fetchone()
    model_latency = {
        "average_latency_ms": model_row[0] if model_row else None,
        "assessments": int(model_row[1]) if model_row else 0,
    }

    incident_count = int(
        connection.execute("SELECT COUNT(*) FROM incident WHERE status='OPEN'").fetchone()[0]
    )

    freeze = bool(alerts) or incident_count > 0 or not recon.get("is_reconciled", True)
    return {
        "daily_count_vs_expected_range": daily_vs_range,
        "cursor_advancement": cursor_advancement,
        "hash_collision_rate": collision_rate,
        "parse_failure_rate": parse_failure_rate,
        "source_latency": source_latency,
        "archive_freshness": {"latest_archived_at_utc": archive_latest, "fresh": archive_fresh},
        "db_wal_status": {"journal_mode": wal_status, "integrity_ok": integrity_ok},
        "paper_position_reconciliation": recon,
        "model_latency": model_latency,
        "incident_count": incident_count,
        "source_health_alerts": alerts,
        "freeze_recommended": freeze,
    }


def evaluate_source_health_contract(
    source_id: str,
    document_count: int,
    cursor_advanced: bool,
    hash_collision_rate: float,
    parse_failure_rate: float,
    expected_empty_period: bool,
    health_max_count: int,
    parse_failure_tolerance: float = 0.10,
    hash_collision_jump: float = 0.02,
) -> list[str]:
    """§29.4 alert conditions."""
    reasons: list[str] = []
    if document_count == 0 and not expected_empty_period:
        reasons.append("count=0 outside expected empty period")
    if document_count > health_max_count:
        reasons.append("count implausibly high")
    if not cursor_advanced:
        reasons.append("cursor does not advance")
    if hash_collision_rate > hash_collision_jump:
        reasons.append("hash collision rate jumps")
    if parse_failure_rate > parse_failure_tolerance:
        reasons.append("parsing failure above tolerance")
    return reasons


def _source_expected_ranges() -> dict[str, dict[str, Any]]:
    path = project_root() / "configs" / "sources.yaml"
    if not path.exists():
        return {}
    raw = read_yaml(path)
    sources = raw.get("sources", raw)
    out: dict[str, dict[str, Any]] = {}
    if isinstance(sources, dict):
        for _key, cfg in sources.items():
            if not isinstance(cfg, dict):
                continue
            sid = str(cfg.get("source_id", _key))
            out[sid] = {
                "health_min_count": int(cfg.get("health_min_count", 1)),
                "health_max_count": int(cfg.get("health_max_count", 10_000)),
                "enabled": bool(cfg.get("enabled", True)),
            }
    return out


def open_incident(connection: sqlite3.Connection, severity: str, service: str, summary: str) -> str:
    incident_id = str(uuid4())
    connection.execute(
        """INSERT INTO incident(incident_id,severity,service,opened_at_utc,status,summary)
           VALUES(?,?,?,?,?,?)""",
        (incident_id, severity, service, datetime.now(UTC).isoformat(), "OPEN", summary),
    )
    return incident_id


def record_source_health(
    connection: sqlite3.Connection, source_id: str, status: str, document_count: int, detail: str
) -> str:
    health_id = str(uuid4())
    connection.execute(
        """INSERT INTO source_health(health_id,source_id,checked_at_utc,status,document_count,detail)
           VALUES(?,?,?,?,?,?)""",
        (
            health_id,
            source_id,
            datetime.now(UTC).isoformat(),
            status,
            document_count,
            detail,
        ),
    )
    return health_id


def write_jsonl_log(log_root: Path, payload: dict[str, Any]) -> Path:
    """§35.3 logs are JSON Lines in data/logs/YYYY/MM/DD."""
    now = datetime.now(UTC)
    folder = log_root / f"{now.year:04d}" / f"{now.month:02d}" / f"{now.day:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "health.jsonl"
    import json

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, default=str) + "\n")
    return path
