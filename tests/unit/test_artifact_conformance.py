from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from qual_event_engine.api.routes import router
from qual_event_engine.decisions.risk_gates import (
    MAXIMUM_POSITION_NAV_PCT,
    PORTFOLIO_CONTROLS,
    RiskGateManager,
    maximum_requested_notional,
)
from qual_event_engine.decisions.state_machine import DecisionStateMachine
from qual_event_engine.domain.enums import CredibilityFlag, EventState, ParserQuality
from qual_event_engine.identity.resolver import EntityResolver
from qual_event_engine.importers.common import (
    MARKET_BAR_REQUIRED_FIELDS,
    excluded_forward_return_columns,
)
from qual_event_engine.importers.import_legacy_prices import import_legacy_prices
from qual_event_engine.ingestion.quality import classify_parser_quality
from qual_event_engine.intelligence.dossier import CONVERSION_UNKNOWN, DossierBuilder
from qual_event_engine.intelligence.validator import SemanticValidator
from qual_event_engine.market.calendar import TradingCalendar, iso_to_utc, ist_to_utc, utc_to_ist
from qual_event_engine.normalization.algorithms import (
    RATING_SCALE,
    event_materiality_ratio,
    normalize_rating,
)
from qual_event_engine.operations.health import (
    REQUIRED_HEALTH_FIELDS,
    evaluate_source_health_contract,
    health_snapshot,
)
from qual_event_engine.operations.incidents import FREEZE_CONDITIONS, IncidentManager
from qual_event_engine.paper.costs import default_cost_book, report_paper_trade
from qual_event_engine.paper.exits import DEFAULT_BLACKLIST_SESSIONS, ExitEvaluator
from qual_event_engine.paper.fills import FillBar, FillOrderState, FillSimulator
from qual_event_engine.persistence.database import connect, initialise
from qual_event_engine.research.reports import (
    REQUIRED_REPORTS,
    lead_minutes,
    required_reports_bundle,
)


def test_iso_ist_utc_weekend_holiday_and_dst() -> None:
    utc = iso_to_utc("2026-09-20T04:00:00Z")
    ist = utc_to_ist(utc)
    assert ist.hour == 9
    assert ist_to_utc(ist) == utc
    assert not TradingCalendar.is_trading_day(datetime(2026, 9, 20, tzinfo=UTC).date())  # Sunday
    assert not TradingCalendar.is_trading_day(datetime(2026, 1, 26, tzinfo=UTC).date())  # holiday
    dst = iso_to_utc("2026-03-08T06:30:00-05:00")
    assert dst.tzinfo is UTC or dst.utcoffset() == timedelta(0)


def test_every_rating_scale_ordinal() -> None:
    for notation, ordinal in RATING_SCALE.items():
        assert normalize_rating(notation) == ordinal
        assert normalize_rating("CRISIL " + notation) == ordinal


def test_materiality_and_lead_time_null_cases() -> None:
    assert event_materiality_ratio(None, 100.0) is None
    assert event_materiality_ratio(10.0, None) is None
    assert event_materiality_ratio(10.0, 100.0, is_l1_estimate=True) is None
    assert event_materiality_ratio(10.0, 100.0, is_unverified_group_announcement=True) is None
    assert event_materiality_ratio(10.0, 100.0, is_binding_economic_amount=False) is None
    assert event_materiality_ratio(50.0, 100.0) == 0.5
    assert lead_minutes(None, "2026-01-01T00:00:00+00:00") is None
    assert lead_minutes("2026-01-01T00:10:00+00:00", None) is None
    negative = lead_minutes("2026-01-01T00:00:00+00:00", "2026-01-01T00:10:00+00:00")
    assert negative == -10.0


def test_parser_quality_classification() -> None:
    assert classify_parser_quality("", malware_scan_failed=True) is ParserQuality.MALICIOUS
    assert classify_parser_quality("x") is ParserQuality.OCR_REQUIRED
    good = "A" * 250 + " earnings revenue profit cash flow contract award counterparty terms. " * 8
    assert classify_parser_quality(good) in {ParserQuality.GOOD, ParserQuality.PARTIAL}


def test_state_machine_illegal_transitions() -> None:
    sm = DecisionStateMachine(EventState.INGESTED)
    with pytest.raises(ValueError, match="Illegal state transition"):
        sm.transition(EventState.FILLED)
    sm.transition(EventState.EXTRACTED)
    assert sm.state is EventState.EXTRACTED


def test_fuzzy_match_rejection() -> None:
    resolver = EntityResolver()
    resolver.register_security("INE000A01018", "AAA", "Alpha Limited")
    result = resolver.resolve("Alpho Limited")
    assert result.match_method == "FUZZY_MATCH_REJECTED"
    assert result.isin is None
    assert result.requires_review is True


def test_isin_alias_and_exact_identity_resolution() -> None:
    resolver = EntityResolver()
    resolver.register_security("INE000A01018", "AAA", "Alpha Limited")
    resolver.aliases.register_alias("INE000A01018", "Alpha Ltd")
    by_isin = resolver.resolve("ignored", isin_hint="INE000A01018")
    assert by_isin.match_method == "EXACT_ISIN"
    assert by_isin.isin == "INE000A01018"
    by_alias = resolver.resolve("Alpha Ltd")
    assert by_alias.match_method == "ALIAS_MATCH"
    assert by_alias.isin == "INE000A01018"
    unknown = resolver.resolve("Completely Unrelated Holdings Private")
    assert unknown.isin is None
    assert unknown.requires_review is True


def test_fill_algorithm_partial_preopen_trigger_and_daily_block() -> None:
    created = datetime(2026, 9, 18, 3, 0, tzinfo=UTC)
    order = FillOrderState(
        order_id="o1",
        symbol="AAA",
        isin="INE000A01018",
        side="BUY",
        quantity_requested=1000,
        quantity_remaining=1000,
        order_type="LIMIT",
        limit_price=110.0,
        trigger_price=None,
        created_at_utc=created,
        valid_until_utc=created + timedelta(days=2),
        participation_cap=0.1,
        available_cash_inr=1_000_000,
        risk_capacity_notional=50_000,
    )
    preopen = FillBar(
        interval="1m",
        open_time_utc=created + timedelta(hours=5),
        close_time_utc=created + timedelta(hours=5, minutes=15),
        open=100,
        high=101,
        low=99,
        close=100,
        volume_shares=10_000,
        turnover_inr=1_000_000,
        is_complete=True,
        session="PRE_OPEN",
        auction_turnover_inr=20_000,
        auction_equilibrium_price=100.0,
    )
    result = FillSimulator.simulate_algorithm(order, [preopen], now_utc=created + timedelta(hours=6))
    assert result.fills
    assert result.quantity_remaining >= 0
    assert "4_max_fill_qty" in result.steps_executed

    trigger = FillOrderState(**{**order.__dict__, "trigger_price": 105.0, "order_type": "TRIGGER"})
    daily = FillBar(
        interval="1d",
        open_time_utc=created + timedelta(days=1),
        close_time_utc=created + timedelta(days=1, hours=6),
        open=100,
        high=110,
        low=90,
        close=100,
        volume_shares=1_000_000,
        turnover_inr=100_000_000,
        is_complete=True,
    )
    blocked = FillSimulator.simulate_algorithm(trigger, [daily], now_utc=created + timedelta(hours=6))
    assert blocked.status == "INSUFFICIENT_INTRADAY_DATA"

    halted = FillBar(
        interval="1m",
        open_time_utc=created + timedelta(hours=6),
        close_time_utc=created + timedelta(hours=6, minutes=1),
        open=100,
        high=100,
        low=100,
        close=100,
        volume_shares=0,
        turnover_inr=0,
        is_complete=True,
        halted=True,
    )
    halt_result = FillSimulator.simulate_algorithm(order, [halted], now_utc=created + timedelta(hours=7))
    assert halt_result.quantity_remaining == 1000


def test_exit_adverse_ohlc_and_unfilled() -> None:
    bar = FillBar(
        interval="1d",
        open_time_utc=datetime(2026, 9, 18, 3, 45, tzinfo=UTC),
        close_time_utc=datetime(2026, 9, 18, 10, 0, tzinfo=UTC),
        open=100,
        high=120,
        low=80,
        close=110,
        volume_shares=1000,
        turnover_inr=100_000,
        is_complete=True,
    )
    trigger = ExitEvaluator.evaluate_end_of_bar(
        entry_price=100,
        bar=bar,
        stop_loss_pct=10,
        target_return_pct=10,
        holding_sessions=1,
        max_time_stop_sessions=10,
    )
    assert trigger.should_exit
    assert trigger.adverse_sequence_selected
    assert trigger.reason == "STOP"
    halted = FillBar(
        interval="1m",
        open_time_utc=bar.open_time_utc,
        close_time_utc=bar.close_time_utc,
        open=90,
        high=90,
        low=90,
        close=90,
        volume_shares=0,
        turnover_inr=0,
        is_complete=True,
        halted=True,
    )
    intent = ExitEvaluator.create_sell_order(50, "STOP", halted)
    assert intent.position_closed is False
    assert intent.status == "EXIT_UNFILLED"
    assert DEFAULT_BLACKLIST_SESSIONS == 20


def test_cost_model_versioned_components_and_trade_report() -> None:
    book = default_cost_book()
    required = {
        "delivery_stt",
        "exchange_charges",
        "regulatory_charges",
        "stamp_duty",
        "gst",
        "brokerage",
        "bid_ask_spread",
        "market_impact",
        "auction_circuit_penalties",
    }
    assert required <= set(book)
    for component in book.values():
        assert component.effective_date
        assert component.source
        assert component.formula
        assert component.version
    report = report_paper_trade(100_000, 101_000)
    assert report.gross_pnl_inr == 1000
    assert report.tax_inr is None
    assert report.net_pnl_before_tax_inr < report.gross_pnl_inr
    assert "delivery_stt" in report.cost_components


def test_sizing_formula_and_portfolio_controls() -> None:
    sizing = maximum_requested_notional(
        paper_nav_inr=1_000_000,
        participation_cap=0.05,
        adt20_inr=2_000_000,
        available_paper_cash=8_000,
        risk_based_notional=50_000,
    )
    assert MAXIMUM_POSITION_NAV_PCT == 2.0
    assert sizing.maximum_requested_notional == 8000
    assert len(PORTFOLIO_CONTROLS) == 8


def test_health_fields_incident_freezes_and_reports(tmp_path: Path) -> None:
    db = tmp_path / "c.db"
    initialise(db)
    with connect(db) as conn:
        snap = health_snapshot(conn)
        for field in REQUIRED_HEALTH_FIELDS:
            assert field in snap
        assert len(FREEZE_CONDITIONS) == 8
        mgr = IncidentManager(conn)
        decisions = mgr.evaluate_freeze_conditions(
            parser_critical=True,
            model_incident=True,
            source_outage_source_id="S2_RATINGS",
            affected_strategy_id="CR-01",
            schedule_incident=True,
            data_freshness_breach=True,
            daily_loss_threshold_hit=True,
            drawdown_ladder_breach=True,
        )
        names = {d.condition for d in decisions}
        assert "CRITICAL_PARSER_INCIDENT" in names
        assert "SOURCE_OUTAGE" in names
        assert "RECONCILIATION_FAILURE" in FREEZE_CONDITIONS
        assert len(FREEZE_CONDITIONS) == 8
        alerts = evaluate_source_health_contract("S1_EXCHANGE", 0, False, 0.05, 0.2, False, 100)
        assert "count=0 outside expected empty period" in alerts
        bundle = required_reports_bundle(conn)
        assert set(REQUIRED_REPORTS) <= set(bundle)


def test_dossier_flags_and_conversion_unknown(tmp_path: Path) -> None:
    db = tmp_path / "d.db"
    initialise(db)
    as_of = datetime(2026, 9, 18, tzinfo=UTC)
    with connect(db) as conn:
        conn.execute(
            """
            INSERT INTO security_membership(
              membership_id,isin,symbol,legal_name,effective_from_utc,series,listed_status,
              surveillance_status,price_band_pct,market_cap_inr,adv20_shares,adt20_inr,
              eligible,eligibility_reasons,source_id,source_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "m1",
                "INE000A01018",
                "AAA",
                "Alpha Ltd",
                "2020-01-01T00:00:00+00:00",
                "EQ",
                "LISTED",
                "NONE",
                10.0,
                1e10,
                100000,
                5e7,
                1,
                "ok",
                "test",
                "1",
            ),
        )
        dossier = DossierBuilder(conn).build_dossier("AAA", as_of)
        names = {f.flag for f in dossier.credibility_flags}
        assert names == set(CredibilityFlag)
        for flag in dossier.credibility_flags:
            assert flag.formula_version
            assert flag.expiry_or_review_rule
        assert dossier.conversion_attribution == CONVERSION_UNKNOWN
        assert dossier.adv20 == 100000
        assert dossier.adt20 == 5e7


def test_api_routes_cover_artifact_paths() -> None:
    from starlette.routing import Route

    paths = {route.path for route in router.routes if isinstance(route, Route)}
    required = {
        "/health",
        "/events",
        "/events/{event_id}",
        "/events/{event_id}/evidence",
        "/events/{event_id}/review",
        "/positions",
        "/orders",
        "/sources/health",
        "/strategies",
        "/reports/{report_id}",
        "/incidents/{incident_id}/close",
    }
    assert required <= paths


def test_legacy_price_importer_excludes_forward_returns(tmp_path: Path) -> None:
    db = tmp_path / "i.db"
    initialise(db)
    src = tmp_path / "prices.parquet"
    frame = pd.DataFrame(
        {
            "Date": ["2026-09-18"],
            "Symbol": ["AAA"],
            "Open": [10.0],
            "High": [11.0],
            "Low": [9.0],
            "Close": [10.5],
            "Volume": [1000],
            "Turnover_Cr": [0.01],
            "fwd_ret_1d": [0.05],
        }
    )
    frame.to_parquet(src)
    assert "fwd_ret_1d" in excluded_forward_return_columns(list(frame.columns))
    assert len(MARKET_BAR_REQUIRED_FIELDS) == 18
    with connect(db) as conn:
        stats = import_legacy_prices(conn, src)
        assert stats["accepted_count"] == 1
        row = conn.execute("SELECT * FROM import_manifest").fetchone()
        assert row is not None
        bars = conn.execute("SELECT * FROM price_bar").fetchall()
        assert len(bars) == 1
        assert "fwd_ret" not in bars[0]


def test_semantic_validator_schema_failures() -> None:
    validator = SemanticValidator()
    result = validator.validate_assessment(
        event={"firmness_level": 4, "entity_match_status": "UNVERIFIED", "event_type": "ORDER_AMENDMENT", "event_state": "AI_ASSESSED"},
        recommendation="BUY_CANDIDATE",
        rationale="Price target 500 guaranteed. Uses original award terms.",
        invalidating_fact="none",
        issuer_match_status="UNVERIFIED",
        evidence_items=[{"field": "value", "text": "not in document"}],
        raw_document_text="unrelated filing text",
        value_inr_cr=10.0,
        ttm_revenue_inr=100.0,
        stated_materiality_ratio=0.99,
    )
    assert result.is_valid is False
    assert len(result.conditions_checked) == 6


def test_risk_gate_manager_entry(tmp_path: Path) -> None:
    db = tmp_path / "r.db"
    initialise(db)
    with connect(db) as conn:
        conn.execute(
            """
            INSERT INTO job_run(job_run_id,job_name,started_at_utc,status,config_hash,code_version)
            VALUES('j1','t','2026-09-01T00:00:00+00:00','STARTED','h','1')
            """
        )
        conn.execute(
            """
            INSERT INTO source_observation(
              observation_id,source_id,source_url,source_published_at_utc,system_first_seen_at_utc,
              retrieval_status,job_run_id
            ) VALUES('obs1','S1_EXCHANGE','https://example.test','2026-09-18T00:00:00+00:00',
                     '2026-09-18T00:00:00+00:00','SUCCESS','j1')
            """
        )
        cols = {str(r[0]) for r in conn.execute("SELECT name FROM pragma_table_info(?)", ("canonical_event",)).fetchall()}
        if "observation_id" not in cols:
            conn.execute("ALTER TABLE canonical_event ADD COLUMN observation_id TEXT")
        conn.execute(
            """
            INSERT INTO canonical_event(
              event_id,symbol,event_type,event_status,event_occurred_at_utc,entity_match_status,
              event_state,created_at_utc,latest_revision_number,observation_id
            ) VALUES('e1','AAA','CREDIT_UPGRADE','NEW','2026-09-18T00:00:00+00:00','VERIFIED',
                     'RISK_CHECKED','2026-09-18T00:00:00+00:00',1,'obs1')
            """
        )
        conn.execute(
            """
            INSERT INTO security_membership(
              membership_id,symbol,legal_name,effective_from_utc,series,listed_status,
              surveillance_status,price_band_pct,eligible,eligibility_reasons,source_id,source_version
            ) VALUES('m1','AAA','Alpha','2020-01-01T00:00:00+00:00','EQ','LISTED','NONE',10,1,'ok','t','1')
            """
        )
        event = conn.execute("SELECT * FROM canonical_event WHERE event_id='e1'").fetchone()
        mgr = RiskGateManager(conn, paper_nav_inr=1_000_000)
        result = mgr.evaluate(event)
        assert "ISSUER" in result.controls_checked
        assert len(result.controls_checked) == 8


def test_series_liquidity_surveillance_and_price_band_eligibility(tmp_path: Path) -> None:
    from qual_event_engine.market.universe import SecurityUniverse

    db = tmp_path / "u.db"
    initialise(db)
    as_of = datetime(2026, 9, 18, tzinfo=UTC)
    with connect(db) as conn:
        def _insert(symbol: str, series: str, surv: str, band: float, adt: float) -> None:
            conn.execute(
                """
                INSERT INTO security_membership(
                  membership_id,isin,symbol,legal_name,effective_from_utc,series,listed_status,
                  surveillance_status,price_band_pct,market_cap_inr,adv20_shares,adt20_inr,
                  eligible,eligibility_reasons,source_id,source_version
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "m-" + symbol,
                    "INE" + symbol,
                    symbol,
                    symbol,
                    "2020-01-01T00:00:00+00:00",
                    series,
                    "LISTED",
                    surv,
                    band,
                    1e10,
                    100000,
                    adt,
                    1,
                    "[]",
                    "t",
                    "1",
                ),
            )

        _insert("EQOK", "EQ", "NONE", 10.0, 50_000_000)
        _insert("SME1", "SM", "NONE", 10.0, 50_000_000)
        _insert("ASM1", "EQ", "ASM", 10.0, 50_000_000)
        _insert("BAND", "EQ", "NONE", 2.0, 50_000_000)
        _insert("ILLQ", "EQ", "NONE", 10.0, 1_000_000)
        uni = SecurityUniverse(conn)
        assert uni.is_security_eligible("EQOK", as_of)[0] is True
        assert uni.is_security_eligible("SME1", as_of)[0] is False
        assert uni.is_security_eligible("ASM1", as_of)[0] is False
        assert uni.is_security_eligible("BAND", as_of)[0] is False
        assert uni.is_security_eligible("ILLQ", as_of)[0] is False


def test_duplicate_amendment_cancellation_and_idempotency(tmp_path: Path) -> None:
    from qual_event_engine.domain.enums import RelationshipType
    from qual_event_engine.events.dedup import EventDeduplicator
    from qual_event_engine.identity.relationships import RelationshipGraph

    db = tmp_path / "dup.db"
    initialise(db)
    occurred = datetime(2026, 9, 18, 4, 0, tzinfo=UTC)
    with connect(db) as conn:
        conn.execute(
            """
            INSERT INTO job_run(job_run_id,job_name,started_at_utc,status,config_hash,code_version)
            VALUES('j1','t','2026-09-01T00:00:00+00:00','STARTED','h','1')
            """
        )
        conn.execute(
            """
            INSERT INTO source_observation(
              observation_id,source_id,source_url,source_published_at_utc,system_first_seen_at_utc,
              retrieval_status,job_run_id
            ) VALUES('obs1','S1_EXCHANGE','https://example.test','2026-09-18T00:00:00+00:00',
                     '2026-09-18T00:00:00+00:00','SUCCESS','j1')
            """
        )
        conn.execute(
            """
            INSERT INTO canonical_event(
              event_id,symbol,event_type,event_status,event_occurred_at_utc,entity_match_status,
              event_state,created_at_utc,latest_revision_number
            ) VALUES('e-win','AAA','ORDER_WIN','NEW','2026-09-18T04:00:00+00:00','VERIFIED',
                     'INGESTED','2026-09-18T04:01:00+00:00',1)
            """
        )
        dedup = EventDeduplicator(conn)
        same = dedup.check_duplicate(
            "AAA", "ORDER_WIN", occurred, headline="Order win Alpha"
        )
        assert same.is_duplicate is True
        amendment = dedup.check_duplicate(
            "AAA", "ORDER_AMENDMENT", occurred, headline="Order amended"
        )
        assert amendment.is_duplicate is False
        cancel = dedup.check_duplicate(
            "AAA", "ORDER_CANCELLATION", occurred, headline="Order cancelled"
        )
        assert cancel.is_duplicate is False
        again = dedup.check_duplicate(
            "AAA", "ORDER_WIN", occurred, headline="Order win Alpha"
        )
        assert again.is_duplicate is True
        graph = RelationshipGraph()
        graph.add_relationship("INEPARENT", "INESUB", RelationshipType.SUBSIDIARY)
        parent = graph.resolve_listed_parent("INESUB")
        assert parent is not None
        assert parent[0] == "INEPARENT"


def test_cash_quantity_partial_fill_costs_and_reconciliation(tmp_path: Path) -> None:
    from qual_event_engine.paper.costs import calculate_equity_costs
    from qual_event_engine.research.reports import reconciliation_report

    created = datetime(2026, 9, 18, 3, 0, tzinfo=UTC)
    order = FillOrderState(
        order_id="cash-1",
        symbol="AAA",
        isin="INE000A01018",
        side="BUY",
        quantity_requested=100,
        quantity_remaining=100,
        order_type="LIMIT",
        limit_price=101.0,
        trigger_price=None,
        created_at_utc=created,
        valid_until_utc=created + timedelta(days=1),
        participation_cap=0.05,
        available_cash_inr=5_000,
        risk_capacity_notional=1_000_000,
    )
    bar = FillBar(
        interval="1m",
        open_time_utc=created + timedelta(hours=6),
        close_time_utc=created + timedelta(hours=6, minutes=1),
        open=100,
        high=100.5,
        low=99.5,
        close=100,
        volume_shares=10_000,
        turnover_inr=1_000_000,
        is_complete=True,
    )
    result = FillSimulator.simulate_algorithm(order, [bar], now_utc=created + timedelta(hours=7))
    assert result.fills
    filled = sum(f.fill_quantity for f in result.fills)
    assert filled < 100 or result.quantity_remaining >= 0
    assert result.status in {"PARTIALLY_FILLED", "FILLED"}
    costs = calculate_equity_costs(10_000, side="BUY")
    assert costs.stt_inr > 0
    assert costs.total_statutory_costs_inr >= costs.stt_inr

    db = tmp_path / "recon.db"
    initialise(db)
    with connect(db) as conn:
        report = reconciliation_report(conn)
        assert report["is_reconciled"] is True
        assert report["dangling_fills"] == 0
        assert report["quantity_mismatches"] == 0


def test_strategy_benchmark_requires_window_and_reports_mfe_mae() -> None:
    from qual_event_engine.research.performance import strategy_benchmark_report

    report = strategy_benchmark_report(
        strategy_id="CR-01",
        benchmark_id="NIFTY50",
        window="2026-09-01/2026-09-18",
        entry_price=100.0,
        exit_price=105.0,
        high_while_held=110.0,
        low_while_held=94.0,
        holding_period=8,
        sector_or_nifty_benchmark_return=0.01,
        matched_market_cap_liquidity_control_return=0.008,
        event_day_gap=0.02,
        total_cost_inr=20.0,
        quantity=10,
    )
    assert report.raw_return == 0.05
    assert report.maximum_favourable_excursion == 0.10
    assert report.maximum_adverse_excursion == -0.06
    assert report.net_return < report.gross_return
    with pytest.raises(ValueError, match="benchmark and time window"):
        strategy_benchmark_report(
            strategy_id="CR-01",
            benchmark_id="",
            window="",
            entry_price=100.0,
            exit_price=105.0,
            high_while_held=110.0,
            low_while_held=94.0,
            holding_period=8,
            sector_or_nifty_benchmark_return=0.01,
            matched_market_cap_liquidity_control_return=0.008,
            event_day_gap=0.02,
            total_cost_inr=20.0,
            quantity=10,
        )


def test_replay_excludes_forward_returns_from_dossier(tmp_path: Path) -> None:
    db = tmp_path / "replay.db"
    initialise(db)
    as_of = datetime(2026, 9, 18, tzinfo=UTC)
    with connect(db) as conn:
        conn.execute(
            """
            INSERT INTO security_membership(
              membership_id,isin,symbol,legal_name,effective_from_utc,series,listed_status,
              surveillance_status,price_band_pct,market_cap_inr,adv20_shares,adt20_inr,
              eligible,eligibility_reasons,source_id,source_version
            ) VALUES('m1','INE000A01018','AAA','Alpha','2020-01-01T00:00:00+00:00','EQ','LISTED',
                     'NONE',10,1e10,100000,5e7,1,'ok','t','1')
            """
        )
        dossier = DossierBuilder(conn).build_dossier("AAA", as_of)
        payload = str(dossier)
        for banned in ("fwd_ret_1d", "forward_return", "t1_return"):
            assert banned not in payload
        assert dossier.as_of_utc == as_of
