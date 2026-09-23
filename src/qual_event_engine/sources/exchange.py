from __future__ import annotations

import hashlib
import json
import os
import random
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx

from qual_event_engine.domain.models import ManualEvent
from qual_event_engine.events.firmness import FirmnessEvaluator
from qual_event_engine.events.taxonomy import EventTaxonomy
from qual_event_engine.ingestion.manual import load_manifest
from qual_event_engine.sources.base import (
    FetchResult,
    RawSourceItem,
    SourceConnector,
    SourceCursor,
    SourceHealth,
    StandardSourceAdapter,
)

IST = ZoneInfo("Asia/Kolkata")

DEFAULT_NSE_BASE_URL = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
DEFAULT_NSE_API_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_nse_datetime(val: str | None) -> datetime:
    """Parse NSE Indian Standard Time strings into timezone-aware UTC datetime."""
    if not val:
        return datetime.now(UTC)
    val = val.strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%d-%b-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(val, fmt)  # noqa: DTZ007
            return dt.replace(tzinfo=IST).astimezone(UTC)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=IST).astimezone(UTC)
        return dt.astimezone(UTC)
    except (ValueError, TypeError):
        return datetime.now(UTC)


class NseAnnouncementFetcher:
    """Production-grade fetcher for NSE Corporate Announcements with retry and TLS enforcement."""

    def __init__(
        self,
        api_url: str = DEFAULT_NSE_API_URL,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
        fixture_path: Path | None = None,
    ) -> None:
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.fixture_path = fixture_path

    def fetch_announcements(self) -> list[dict[str, Any]]:
        """Fetch announcements array from live NSE endpoint or test fixture."""
        # 1. Test fixture override if configured
        fixture = self.fixture_path or os.getenv("QUAL_NSE_FIXTURE_PATH")
        if fixture:
            f_path = Path(fixture)
            if f_path.exists():
                with f_path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                    if not isinstance(data, list):
                        raise TypeError("Malformed NSE response: expected JSON array of announcements")
                    return data

        # 2. Live HTTP request with TLS verification (verify=True, trust_env=False)
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(
                    verify=True,
                    trust_env=False,
                    timeout=self.timeout_seconds,
                    headers=DEFAULT_HEADERS,
                    follow_redirects=True,
                ) as client:
                    response = client.get(self.api_url)
                    if response.status_code == 429:
                        delay = self.backoff_seconds * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5)
                        time.sleep(delay)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, list):
                        raise TypeError("Malformed NSE response: expected JSON array of announcements")
                    return data
            except (httpx.HTTPError, OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    delay = self.backoff_seconds * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5)
                    time.sleep(delay)

        raise RuntimeError(f"Failed to fetch live NSE announcements after {self.max_retries} attempts: {last_exc}") from last_exc

    def download_attachment(self, url: str) -> bytes | None:
        """Download document attachment bytes from NSE archives with TLS verification."""
        if not url or not url.startswith("http"):
            return None
        try:
            with httpx.Client(
                verify=True,
                trust_env=False,
                timeout=self.timeout_seconds,
                headers=DEFAULT_HEADERS,
                follow_redirects=True,
            ) as client:
                res = client.get(url)
                if res.status_code == 200 and len(res.content) > 0:
                    return res.content
        except (httpx.HTTPError, OSError):
            return None
        return None

    def item_to_manual_event(
        self, item: dict[str, Any], drop_root: Path
    ) -> ManualEvent:
        """Transform raw NSE announcement item into a canonical ManualEvent with saved document."""
        seq_id = str(item.get("seq_id") or "").strip()
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            symbol = "UNRESOLVED"
        isin = item.get("sm_isin")
        legal_name = str(item.get("sm_name") or symbol).strip()
        sector = item.get("smIndustry")
        category = str(item.get("desc") or "Updates").strip()
        headline = str(item.get("attchmntText") or category).strip()
        att_url_raw = str(item.get("attchmntFile") or "").strip()

        # Deterministic native ID fallback if seq_id missing (§6 Case D)
        if not seq_id:
            h_input = f"{symbol}:{category}:{headline}"
            seq_id = f"NSE_{hashlib.sha256(h_input.encode()).hexdigest()[:16]}"

        sort_date_str = item.get("sort_date") or item.get("an_dt")
        published_dt = parse_nse_datetime(sort_date_str)

        exch_disstime_str = item.get("exchdisstime")
        exch_seen_dt = parse_nse_datetime(exch_disstime_str) if exch_disstime_str else published_dt

        # Classify event and firmness using existing deterministic rules
        event_type = EventTaxonomy.classify(category, headline).value
        firmness_level = FirmnessEvaluator.evaluate(event_type, headline).score

        # Download attachment or persist structured JSON as source document
        downloads_dir = drop_root / "exchange" / "live_downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)

        doc_bytes: bytes | None = None
        doc_filename: str = f"{seq_id}.json"
        if att_url_raw.startswith("http"):
            ext = Path(att_url_raw.split("?")[0]).suffix.lower()
            if not ext:
                ext = ".pdf"
            doc_filename = f"{seq_id}{ext}"
            doc_bytes = self.download_attachment(att_url_raw)

        doc_path = downloads_dir / doc_filename
        if doc_bytes and len(doc_bytes) > 0:
            doc_path.write_bytes(doc_bytes)
        else:
            # Fallback to saving announcement payload JSON
            doc_filename = f"{seq_id}.json"
            doc_path = downloads_dir / doc_filename
            doc_path.write_text(json.dumps(item, indent=2), encoding="utf-8")

        # Ensure valid HttpUrl
        source_url = att_url_raw if att_url_raw.startswith("http") else DEFAULT_NSE_BASE_URL

        return ManualEvent(
            source_native_id=seq_id,
            source_url=source_url,  # type: ignore[arg-type]
            source_published_at_utc=published_dt,
            exchange_first_seen_at_utc=exch_seen_dt,
            document_path=f"exchange/live_downloads/{doc_filename}",
            event_type=event_type,
            symbol=symbol,
            isin=isin,
            legal_name=legal_name,
            headline=headline,
            event_status="ANNOUNCED",
            firmness_level=firmness_level,
            event_value_inr=None,
            ttm_revenue_inr=None,
            sector=sector,
            entity_verified=bool(isin),
            evidence_pages=[],
        )


class ExchangeAdapter(StandardSourceAdapter):
    """Adapter for NSE Corporate Announcements supporting LIVE_POLL and MANIFEST_DROP."""

    source_id = "exchange"

    def __init__(
        self,
        base_url: str = DEFAULT_NSE_BASE_URL,
        api_url: str = DEFAULT_NSE_API_URL,
        drop_root: Path | None = None,
        mode: Literal["LIVE_POLL", "MANIFEST_DROP"] = "LIVE_POLL",
        fetcher: NseAnnouncementFetcher | None = None,
    ) -> None:
        super().__init__(base_url=base_url, drop_root=drop_root)
        self.api_url = api_url
        self.mode = mode
        self.fetcher = fetcher or NseAnnouncementFetcher(api_url=api_url)

    async def health_check(self) -> SourceHealth:
        """Verify endpoint connectivity and TLS certificate verification."""
        now_utc = datetime.now(UTC).isoformat()
        start = time.perf_counter()
        target_url = self.api_url if self.mode == "LIVE_POLL" else self.base_url
        try:
            async with httpx.AsyncClient(
                verify=True, timeout=10.0, trust_env=False, headers=DEFAULT_HEADERS
            ) as client:
                response = await client.get(target_url, follow_redirects=True)
                latency = (time.perf_counter() - start) * 1000.0
                if response.status_code in (200, 201):
                    return SourceHealth(
                        source_id=self.source_id,
                        status="OK",
                        latency_ms=round(latency, 2),
                        message=f"HTTP {response.status_code} TLS verified",
                        timestamp_utc=now_utc,
                    )
                return SourceHealth(
                    source_id=self.source_id,
                    status="DEGRADED",
                    latency_ms=round(latency, 2),
                    message=f"HTTP {response.status_code}",
                    timestamp_utc=now_utc,
                )
        except (httpx.HTTPError, OSError) as exc:
            latency = (time.perf_counter() - start) * 1000.0
            return SourceHealth(
                source_id=self.source_id,
                status="DOWN",
                latency_ms=round(latency, 2),
                message=f"Network unreachable: {exc}",
                timestamp_utc=now_utc,
            )

    async def fetch(self, cursor: SourceCursor) -> FetchResult:
        """Fetch items using LIVE_POLL or fall back to MANIFEST_DROP."""
        if self.mode == "MANIFEST_DROP":
            return await super().fetch(cursor)

        # LIVE_POLL mode
        items_data = self.fetcher.fetch_announcements()
        raw_items: list[RawSourceItem] = []
        max_ts = cursor.cursor_value

        for raw in items_data:
            seq_id = str(raw.get("seq_id") or "")
            symbol = str(raw.get("symbol") or "").strip().upper()
            headline = str(raw.get("attchmntText") or raw.get("desc") or "")
            if not seq_id:
                seq_id = f"NSE_{hashlib.sha256(f'{symbol}:{headline}'.encode()).hexdigest()[:16]}"

            pub_dt = parse_nse_datetime(raw.get("sort_date") or raw.get("an_dt"))
            pub_iso = pub_dt.isoformat()

            if cursor.cursor_value and pub_iso <= cursor.cursor_value:
                continue

            max_ts = pub_iso if max_ts is None else max(max_ts, pub_iso)

            url = str(raw.get("attchmntFile") or self.base_url)
            raw_items.append(
                RawSourceItem(
                    source_id=self.source_id,
                    native_id=seq_id,
                    url=url,
                    published_at_utc=pub_iso,
                    payload=raw,
                )
            )

        new_cursor = SourceCursor(
            source_id=self.source_id,
            cursor_value=max_ts,
            updated_at_utc=datetime.now(UTC).isoformat(),
        )
        return FetchResult(items=raw_items, next_cursor=new_cursor, has_more=False)


class ExchangeConnector(SourceConnector):
    """Connector for NSE Corporate Announcements with live polling and manifest fallback."""

    source_id = "exchange"

    def __init__(
        self,
        drop_root: Path,
        mode: Literal["LIVE_POLL", "MANIFEST_DROP"] | None = None,
        fetcher: NseAnnouncementFetcher | None = None,
    ) -> None:
        self._drop_root = drop_root
        env_mode = os.getenv("QUAL_EXCHANGE_INGESTION_MODE", "LIVE_POLL").upper()
        self._mode: Literal["LIVE_POLL", "MANIFEST_DROP"] = (
            mode or ("MANIFEST_DROP" if env_mode == "MANIFEST_DROP" else "LIVE_POLL")
        )
        self._fetcher = fetcher or NseAnnouncementFetcher()

    def events(self) -> Iterable[ManualEvent]:
        """Yield events from live NSE corporate announcements or manifest."""
        if self._mode == "MANIFEST_DROP":
            return load_manifest(self._drop_root, self.source_id)

        # LIVE_POLL execution
        announcements = self._fetcher.fetch_announcements()
        events_list: list[ManualEvent] = []
        seen_native_ids: set[str] = set()

        for item in announcements:
            event = self._fetcher.item_to_manual_event(item, self._drop_root)
            # In-batch deduplication (§6 Case A)
            if event.source_native_id in seen_native_ids:
                continue
            seen_native_ids.add(event.source_native_id)
            events_list.append(event)

        return events_list
