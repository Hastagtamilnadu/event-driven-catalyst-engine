from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceLeadTimeMetric:
    source_id: str
    total_observations: int
    matched_exchange_count: int
    mean_lead_minutes: float
    median_lead_minutes: float
    min_lead_minutes: float
    max_lead_minutes: float
    p90_lead_minutes: float


class LeadTimeAnalyzer:
    """Analyzes empirical lead times between source publication and exchange dissemination."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def compute_lead_times(self) -> list[SourceLeadTimeMetric]:
        query = """
            SELECT source_id,
                   (julianday(exchange_first_seen_at_utc) - julianday(source_published_at_utc)) * 1440.0 AS lead_min
            FROM source_observation
            WHERE exchange_first_seen_at_utc IS NOT NULL
              AND source_published_at_utc IS NOT NULL
            ORDER BY source_id, lead_min ASC
        """
        cur = self.connection.execute(query)
        rows = cur.fetchall()

        by_source: dict[str, list[float]] = {}
        for r in rows:
            by_source.setdefault(str(r[0]), []).append(float(r[1]))

        results = []
        for src, leads in by_source.items():
            n = len(leads)
            mean_val = sum(leads) / n
            med_val = leads[n // 2]
            p90_val = leads[int(n * 0.90)] if n > 1 else leads[0]
            results.append(
                SourceLeadTimeMetric(
                    source_id=src,
                    total_observations=n,
                    matched_exchange_count=n,
                    mean_lead_minutes=round(mean_val, 2),
                    median_lead_minutes=round(med_val, 2),
                    min_lead_minutes=round(min(leads), 2),
                    max_lead_minutes=round(max(leads), 2),
                    p90_lead_minutes=round(p90_val, 2),
                )
            )
        return results
