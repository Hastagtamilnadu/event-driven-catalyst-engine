# Permitted Feed Handoff Contract

The engine accepts a JSONL manifest at:

~~~
D:\02_Trading\data\manual_drop\<source-id>\manifest.jsonl
~~~

The source ID is one of `exchange`, `ratings`, `tenders`, `usfda`, `parivesh`,
`transcripts`, `ownership`, `surveillance`, or `calendar`.

Each line is one event. `document_path` is relative to `D:\02_Trading\data\manual_drop`
and must point to the evidence document you collected through permitted access.

~~~json
{
  "source_native_id": "agency-doc-123",
  "source_url": "https://permitted.example/document/123",
  "source_published_at_utc": "2026-09-20T05:00:00Z",
  "document_path": "ratings/documents/agency-doc-123.pdf",
  "event_type": "CREDIT_UPGRADE",
  "symbol": "EXAMPLE",
  "isin": "INE000A01000",
  "legal_name": "Example Limited",
  "headline": "Rating upgraded from A to AA",
  "event_status": "FINAL",
  "firmness_level": 4,
  "event_value_inr": null,
  "ttm_revenue_inr": null,
  "sector": "Industrials",
  "previous_rating": "A",
  "new_rating": "AA",
  "counterparty": null,
  "entity_verified": true,
  "evidence_pages": [1]
}
~~~

Required fields are validated before archival. The engine stores the source URL, publication
timestamp, local document hash, parser result, and imported event. It refuses a document path
outside the manual-drop root.

For intraday bars, supply a JSONL file and import it with:

~~~
qual-engine import-bars --path D:\path\to\bars.jsonl
~~~

Each bar requires `symbol`, `interval`, UTC open/close timestamps, OHLC, share volume, INR
turnover, completeness, and provider/source identifier.
