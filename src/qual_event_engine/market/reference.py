from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field


class MembershipRecord(BaseModel):
    symbol: str
    legal_name: str
    effective_from_utc: datetime
    effective_to_utc: datetime | None = None
    series: str = "EQ"
    listed_status: str = "ACTIVE"
    surveillance_status: str = "NONE"
    price_band_pct: float | None = Field(default=None, ge=0)
    market_cap_inr: float | None = Field(default=None, ge=0)
    adv20_shares: float | None = Field(default=None, ge=0)
    adt20_inr: float | None = Field(default=None, ge=0)
    eligible: bool
    eligibility_reasons: list[str] = Field(default_factory=list)
    source_id: str
    source_version: str
    isin: str | None = None


class FundamentalRecord(BaseModel):
    symbol: str
    metric: str
    value: float
    eligible_at_utc: datetime
    system_first_seen_at_utc: datetime
    source_id: str
    source_version: str
    isin: str | None = None
    period_end: str | None = None
    issuer_disseminated_at_utc: datetime | None = None


class CorporateActionRecord(BaseModel):
    symbol: str
    action_type: str
    ex_date: str
    adjustment_factor: float = Field(gt=0)
    source_id: str
    source_document_ref: str | None = None
    isin: str | None = None


def _records(path: Path, model: type[BaseModel]) -> list[BaseModel]:
    if not path.exists():
        raise FileNotFoundError(path)
    output: list[BaseModel] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                try:
                    output.append(model.model_validate(json.loads(line)))
                except Exception as exc:
                    raise ValueError(
                        f"Invalid {model.__name__} at {path}:{line_number}: {exc}"
                    ) from exc
    return output


def import_membership(connection: sqlite3.Connection, path: Path) -> int:
    inserted = 0
    for record in _records(path, MembershipRecord):
        assert isinstance(record, MembershipRecord)
        result = connection.execute(
            """INSERT INTO security_membership(
              membership_id,isin,symbol,legal_name,effective_from_utc,effective_to_utc,series,
              listed_status,surveillance_status,price_band_pct,market_cap_inr,adv20_shares,adt20_inr,
              eligible,eligibility_reasons,source_id,source_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,effective_from_utc,source_version) DO NOTHING""",
            (
                str(uuid4()),
                record.isin,
                record.symbol.upper(),
                record.legal_name,
                record.effective_from_utc.astimezone(UTC).isoformat(),
                record.effective_to_utc.astimezone(UTC).isoformat()
                if record.effective_to_utc
                else None,
                record.series,
                record.listed_status,
                record.surveillance_status,
                record.price_band_pct,
                record.market_cap_inr,
                record.adv20_shares,
                record.adt20_inr,
                int(record.eligible),
                json.dumps(record.eligibility_reasons),
                record.source_id,
                record.source_version,
            ),
        )
        inserted += result.rowcount
    return inserted


def import_fundamentals(connection: sqlite3.Connection, path: Path) -> int:
    inserted = 0
    for record in _records(path, FundamentalRecord):
        assert isinstance(record, FundamentalRecord)
        result = connection.execute(
            """INSERT INTO point_in_time_fundamental(
              fundamental_id,isin,symbol,metric,value,period_end,issuer_disseminated_at_utc,
              system_first_seen_at_utc,eligible_at_utc,source_id,source_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,metric,eligible_at_utc,source_version) DO NOTHING""",
            (
                str(uuid4()),
                record.isin,
                record.symbol.upper(),
                record.metric,
                record.value,
                record.period_end,
                record.issuer_disseminated_at_utc.astimezone(UTC).isoformat()
                if record.issuer_disseminated_at_utc
                else None,
                record.system_first_seen_at_utc.astimezone(UTC).isoformat(),
                record.eligible_at_utc.astimezone(UTC).isoformat(),
                record.source_id,
                record.source_version,
            ),
        )
        inserted += result.rowcount
    return inserted


def import_corporate_actions(connection: sqlite3.Connection, path: Path) -> int:
    inserted = 0
    for record in _records(path, CorporateActionRecord):
        assert isinstance(record, CorporateActionRecord)
        result = connection.execute(
            """INSERT INTO corporate_action(
              action_id,isin,symbol,action_type,ex_date,adjustment_factor,source_id,source_document_ref
            ) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,action_type,ex_date,source_id) DO NOTHING""",
            (
                str(uuid4()),
                record.isin,
                record.symbol.upper(),
                record.action_type,
                record.ex_date,
                record.adjustment_factor,
                record.source_id,
                record.source_document_ref,
            ),
        )
        inserted += result.rowcount
    return inserted


def latest_fundamental(
    connection: sqlite3.Connection, symbol: str, metric: str, as_of_utc: datetime
) -> float | None:
    row = connection.execute(
        """SELECT value FROM point_in_time_fundamental
           WHERE symbol=? AND metric=? AND eligible_at_utc<=?
           ORDER BY eligible_at_utc DESC LIMIT 1""",
        (symbol.upper(), metric, as_of_utc.astimezone(UTC).isoformat()),
    ).fetchone()
    return float(row["value"]) if row else None
