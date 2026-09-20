# Qualitative Event Engine

The engine ingests manually supplied, permitted-source manifests; archives evidence; creates
point-in-time events; generates an evidence-bound assessment; manages separate paper portfolios;
and exposes review/health APIs.

## First run

1. Copy .env.example to a local .env or set the variables in Windows.
2. Run uv sync --extra dev.
3. Run uv run qual-engine initialise-db.
4. Put permitted-source manifests in D:\02_Trading\data\manual_drop\<source-id>.
5. Run uv run qual-engine ingest --source ratings.
6. Run uv run qual-engine process-events.
7. Start the review API with uv run uvicorn qual_event_engine.api.app:app --host 127.0.0.1 --port 8765.

Manual ingestion is deliberate: source access is supplied by the operator. The engine does not
scrape, evade source controls, or disable TLS verification.
