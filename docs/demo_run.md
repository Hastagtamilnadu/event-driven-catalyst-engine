# Offline Demo Run

This uses only the synthetic files in `examples/`; it does not contact a source or create a live trade.

In PowerShell:

~~~powershell
$env:PYTHONPATH = "src"
$env:QUAL_ENGINE_DATA_ROOT = "D:\02_Trading\qual_event_engine\demo_runtime"
$env:QUAL_ENGINE_DB_PATH = "D:\02_Trading\qual_event_engine\demo_runtime\demo.db"
$env:QUAL_ENGINE_MANUAL_DROP_ROOT = "D:\02_Trading\qual_event_engine\examples"
$env:QUAL_ENGINE_ARCHIVE_ROOT = "D:\02_Trading\qual_event_engine\demo_runtime\archive"
$env:QUAL_ENGINE_LOG_ROOT = "D:\02_Trading\qual_event_engine\demo_runtime\logs"

python -m qual_event_engine initialise-db
python -m qual_event_engine import-reference --kind membership --path examples\membership.jsonl
python -m qual_event_engine ingest --source ratings
python -m qual_event_engine process-events
~~~

Copy the event ID from the API or database, then:

~~~powershell
python -m qual_event_engine review --event-id <event-id> --reviewer operator --decision APPROVE --rationale "Evidence checked."
python -m qual_event_engine create-paper-intents
python -m qual_event_engine import-bars --path examples\bars.jsonl
python -m qual_event_engine run-paper
python -m qual_event_engine report --report performance
~~~

For a real feed, the first eligible bar must be timestamped after the paper intent and before
its expiry. The engine refuses any earlier or expired bar.
