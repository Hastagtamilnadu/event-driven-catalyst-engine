from __future__ import annotations

import argparse
import json
from pathlib import Path

from qual_event_engine.config import load_risk_config, load_strategy_book
from qual_event_engine.decisions.service import (
    create_paper_intents,
    process_unassessed_events,
    record_review,
)
from qual_event_engine.events.service import ingest_event
from qual_event_engine.ingestion.manual import load_manifest
from qual_event_engine.intelligence.analyst import Analyst
from qual_event_engine.market.legacy import import_daily_turnover_parquet
from qual_event_engine.market.reference import (
    import_corporate_actions,
    import_fundamentals,
    import_membership,
)
from qual_event_engine.operations.hashing import sha256_json
from qual_event_engine.operations.health import health_snapshot, record_source_health
from qual_event_engine.paper.service import (
    create_exit_intents,
    import_market_bars,
    process_pending_orders,
)
from qual_event_engine.persistence.database import connect, initialise, transaction
from qual_event_engine.persistence.repositories import finish_job, insert_job
from qual_event_engine.research.reports import (
    lead_time_report,
    reconciliation_report,
    strategy_performance_report,
)
from qual_event_engine.runtime import project_root
from qual_event_engine.settings import Settings
from qual_event_engine.sources.registry import validate_source_id


def _settings() -> Settings:
    settings = Settings.from_env()
    settings.ensure_directories()
    return settings


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, default=str))


def command_initialise(_: argparse.Namespace) -> None:
    settings = _settings()
    initialise(settings.db_path)
    _print({"database": str(settings.db_path), "status": "initialised"})


def command_verify(_: argparse.Namespace) -> None:
    settings = _settings()
    required = {
        "data_root": settings.data_root.exists(),
        "archive_root": settings.archive_root.exists(),
        "manual_drop_root": settings.manual_drop_root.exists(),
        "log_root": settings.log_root.exists(),
        "backup_root": settings.backup_root.exists(),
        "database_parent": settings.db_path.parent.exists(),
    }
    _print({"status": "OK" if all(required.values()) else "BLOCKED", "checks": required})
    if not all(required.values()):
        raise SystemExit(2)


def command_ingest(args: argparse.Namespace) -> None:
    settings = _settings()
    initialise(settings.db_path)
    source_id = validate_source_id(args.source)
    inserted = 0
    skipped = 0
    with transaction(settings.db_path) as connection:
        job_id = insert_job(connection, f"ingest:{source_id}", sha256_json({"source": source_id}))
        try:
            for event in load_manifest(settings.manual_drop_root, source_id):
                _, created = ingest_event(
                    connection,
                    event,
                    source_id,
                    settings.manual_drop_root,
                    settings.archive_root,
                    job_id,
                )
                inserted += int(created)
                skipped += int(not created)
            record_source_health(
                connection,
                source_id,
                "OK",
                inserted + skipped,
                f"inserted={inserted}; duplicates_skipped={skipped}",
            )
            finish_job(connection, job_id, "SUCCEEDED")
        except Exception as exc:
            finish_job(connection, job_id, "FAILED", str(exc))
            raise
    _print({"source": source_id, "inserted": inserted, "duplicates_skipped": skipped})


def command_process(_: argparse.Namespace) -> None:
    settings = _settings()
    initialise(settings.db_path)
    strategies, config_hash = load_strategy_book(project_root())
    analyst = Analyst(
        settings.gemini_api_key, settings.gemini_model_id, settings.gemini_timeout_seconds
    )
    with transaction(settings.db_path) as connection:
        job_id = insert_job(connection, "process-events", config_hash)
        try:
            count = process_unassessed_events(connection, analyst, strategies.strategies)
            finish_job(connection, job_id, "SUCCEEDED")
        except Exception as exc:
            finish_job(connection, job_id, "FAILED", str(exc))
            raise
    _print({"processed": count})


def command_review(args: argparse.Namespace) -> None:
    settings = _settings()
    with transaction(settings.db_path) as connection:
        review_id = record_review(
            connection, args.event_id, args.reviewer, args.decision, args.rationale
        )
    _print({"review_id": review_id, "status": "recorded"})


def command_create_intents(_: argparse.Namespace) -> None:
    settings = _settings()
    strategies, _strat_hash = load_strategy_book(project_root())
    risk, _risk_hash = load_risk_config(project_root())
    with transaction(settings.db_path) as connection:
        count = create_paper_intents(connection, strategies.strategies, risk.paper_nav_inr)
    _print({"paper_intents_created": count})


def command_import_bars(args: argparse.Namespace) -> None:
    settings = _settings()
    with transaction(settings.db_path) as connection:
        count = import_market_bars(connection, Path(args.path))
    _print({"bars_imported": count})


def command_import_reference(args: argparse.Namespace) -> None:
    settings = _settings()
    handlers = {
        "membership": import_membership,
        "fundamentals": import_fundamentals,
        "corporate-actions": import_corporate_actions,
    }
    with transaction(settings.db_path) as connection:
        count = handlers[args.kind](connection, Path(args.path))
    _print({"kind": args.kind, "records_imported": count})


def command_import_legacy_daily(args: argparse.Namespace) -> None:
    settings = _settings()
    with transaction(settings.db_path) as connection:
        count = import_daily_turnover_parquet(connection, Path(args.path))
    _print({"legacy_daily_bars_imported": count})


def command_run_paper(_: argparse.Namespace) -> None:
    settings = _settings()
    strategies, _strat_hash = load_strategy_book(project_root())
    risk, _risk_hash = load_risk_config(project_root())
    with transaction(settings.db_path) as connection:
        exit_intents = create_exit_intents(connection)
        stats = process_pending_orders(connection, strategies.strategies, risk.paper_nav_inr)
    _print({"exit_intents_created": exit_intents, **stats})


def command_health(_: argparse.Namespace) -> None:
    settings = _settings()
    initialise(settings.db_path)
    with connect(settings.db_path) as connection:
        _print(health_snapshot(connection))


def command_reconcile(args: argparse.Namespace) -> None:
    settings = _settings()
    with connect(settings.db_path) as connection:
        _print(reconciliation_report(connection, as_of_date=args.date))


def command_report(args: argparse.Namespace) -> None:
    settings = _settings()
    with connect(settings.db_path) as connection:
        reports = {
            "performance": {
                "strategy_performance": strategy_performance_report(connection),
                "reconciliation": reconciliation_report(connection),
            },
            "lead-time": lead_time_report(connection),
        }
        _print(reports[args.report])


def main() -> None:
    parser = argparse.ArgumentParser(prog="qual-engine")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("initialise-db").set_defaults(handler=command_initialise)
    commands.add_parser("verify-environment").set_defaults(handler=command_verify)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("--source", required=True)
    ingest.set_defaults(handler=command_ingest)
    commands.add_parser("process-events").set_defaults(handler=command_process)
    review = commands.add_parser("review")
    review.add_argument("--event-id", required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument(
        "--decision",
        required=True,
        choices=["APPROVE", "REJECT", "REQUEST_MORE_EVIDENCE", "OVERRIDE_TO_WATCH"],
    )
    review.add_argument("--rationale", required=True)
    review.set_defaults(handler=command_review)
    commands.add_parser("create-paper-intents").set_defaults(handler=command_create_intents)
    bars = commands.add_parser("import-bars")
    bars.add_argument("--path", required=True)
    bars.set_defaults(handler=command_import_bars)
    reference = commands.add_parser("import-reference")
    reference.add_argument(
        "--kind", required=True, choices=["membership", "fundamentals", "corporate-actions"]
    )
    reference.add_argument("--path", required=True)
    reference.set_defaults(handler=command_import_reference)
    legacy_daily = commands.add_parser("import-legacy-daily-bars")
    legacy_daily.add_argument("--path", required=True)
    legacy_daily.set_defaults(handler=command_import_legacy_daily)
    commands.add_parser("run-paper").set_defaults(handler=command_run_paper)
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--date", required=False, default=None)
    reconcile.set_defaults(handler=command_reconcile)
    commands.add_parser("health").set_defaults(handler=command_health)
    report = commands.add_parser("report")
    report.add_argument("--report", required=True, choices=["performance", "lead-time"])
    report.set_defaults(handler=command_report)
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
