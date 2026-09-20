# Runbook: Stale Data (RB-02)

## 1. Detection
- System detects that market price bars, corporate action adjustments, or universe membership timestamps exceed staleness threshold (e.g. price bar age > 24 hours on a trading day).
- Universe membership `effective_to_utc` is in the past without a succeeding record.
- Fundamental data `as_of_date` has not advanced after known quarterly reporting deadlines.

## 2. Immediate Freeze Action
- Block new paper order creation across all strategies.
- Flag universe status as `STALE_DATA_FREEZE`.
- Prevent execution simulator from marking positions to stale closing prices.
- Record incident in `incident` table with severity `HIGH`.

## 3. Diagnosis
1. Query `SELECT symbol, max(close_time_utc) FROM price_bar GROUP BY symbol` to identify lagging symbols.
2. Check upstream market data feed ingestion logs in `data/logs/YYYY/MM/DD/`.
3. Verify if trading holiday occurred (check exchange holiday calendar).
4. Check if upstream vendor FTP/API failed to deliver end-of-day file.

## 4. Recovery
1. Ingest missing market bars: `uv run qual-engine import-bars --path <path_to_bars>`.
2. Ingest updated membership: `uv run qual-engine import-reference --kind membership --path <path>`.
3. Ingest updated fundamentals: `uv run qual-engine import-reference --kind fundamentals --path <path>`.

## 5. Reconciliation
1. Check continuity: verify no gap in daily OHLC bars for all active universe securities.
2. Verify all pending paper orders were either cancelled as expired or held pending valid quotes.
3. Check cash ledger balance matches expected marks.

## 6. Closure Evidence
- Data freshness query confirms latest price bar timestamp equals current market session close.
- Incident report updated in `incident` table with resolution details.
- System unfreezes automated paper execution.

## 7. Prevention Action
- Add automated pre-market alert at 08:30 IST if previous day's close is missing.
- Maintain secondary reference data vendor feed.
