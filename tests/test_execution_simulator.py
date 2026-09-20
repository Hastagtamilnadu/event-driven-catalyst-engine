from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from qual_event_engine.domain.models import StrategyConfig
from qual_event_engine.paper.service import (
    _costs,
    create_exit_intents,
    process_pending_orders,
)
from qual_event_engine.persistence.database import connect, initialise


def _setup_db(db_path: Path) -> None:
    initialise(db_path)
    with connect(db_path) as conn:
        # 1. Job run
        conn.execute(
            """INSERT INTO job_run(job_run_id, job_name, started_at_utc, status, config_hash, code_version)
               VALUES('job-1', 'test_job', '2026-09-01T00:00:00Z', 'STARTED', 'hash1', '1.0')"""
        )
        # 2. Raw document
        conn.execute(
            """INSERT INTO raw_document(
                raw_sha256, local_path, mime_type, bytes, page_count, extracted_characters,
                extraction_quality, archived_at_utc, parser_status
            ) VALUES('docsha1', 'test.pdf', 'application/pdf', 1000, 1, 100, 'GOOD', '2026-09-01T00:00:00Z', 'GOOD')"""
        )
        # 3. Source observation
        conn.execute(
            """INSERT INTO source_observation(
                observation_id, source_id, source_native_id, source_url, source_published_at_utc,
                system_first_seen_at_utc, downloaded_at_utc, raw_sha256, retrieval_status,
                parser_version, job_run_id
            ) VALUES('obs-1', 'exchange', 'nat-1', 'https://example.test', '2026-09-01T00:00:00Z',
                     '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z', 'docsha1', 'SUCCESS', '1.0', 'job-1')"""
        )
        # 4. Canonical event
        conn.execute(
            """INSERT INTO canonical_event(
                event_id, observation_id, isin, symbol, legal_name, sector, event_type,
                event_status, firmness_level, entity_match_status, event_state, headline, created_at_utc
            ) VALUES('ev-test-1', 'obs-1', 'INE000A01000', 'TESTSYM', 'Test Corp', 'Tech',
                     'ORDER_AWARD', 'FINAL', 4, 'VERIFIED', 'APPROVED', 'Test Headline', '2026-09-01T00:00:00Z')"""
        )
        # 5. Security membership
        conn.execute(
            """INSERT INTO security_membership(
                membership_id, isin, symbol, legal_name, effective_from_utc, series, listed_status,
                surveillance_status, price_band_pct, market_cap_inr, adv20_shares, adt20_inr,
                eligible, eligibility_reasons, source_id, source_version
            ) VALUES('mem-1', 'INE000A01000', 'TESTSYM', 'Test Corp', '2026-09-01T00:00:00Z',
                     'EQ', 'ACTIVE', 'NONE', 10.0, 1e10, 1e6, 1e8, 1, '[]', 'test', '1.0')"""
        )


def _strat() -> dict[str, StrategyConfig]:
    return {
        "CR-01": StrategyConfig.model_validate(
            {
                "enabled": True,
                "event_types": ["ORDER_AWARD"],
                "minimum_firmness_level": 4,
                "maximum_position_nav_pct": 5,
                "maximum_participation_pct": 1,
                "stop_loss_pct": 5,
                "time_stop_sessions": 20,
                "review_required": False,
            }
        )
    }


def test_costs_arithmetic() -> None:
    spread, impact, statutory = _costs(1_000_000.0, 0.01, side="BUY")
    assert spread == 500.0  # 5 bps
    assert impact > 500.0   # 5 bps + participation penalty
    assert statutory > 1000.0  # STT (0.10%) + exchange + SEBI + stamp duty (0.015%) + GST


def test_partial_fill_carryover(tmp_path: Path) -> None:
    db = tmp_path / "test_partial.db"
    _setup_db(db)
    now = datetime.now(UTC)

    with connect(db) as conn:
        # Insert a bar with limited liquidity: turnover = 100,000 INR
        # With participation_cap = 1%, max notional = 1,000 INR
        # Price = 100 INR -> Max fill = 10 shares
        conn.execute(
            """INSERT INTO price_bar(
                bar_id, isin, symbol, interval, open_time_utc, close_time_utc,
                open, high, low, close, volume_shares, turnover_inr, is_complete, source_id
            ) VALUES('bar-1', 'INE000A01000', 'TESTSYM', '1m', ?, ?, 100.0, 102.0, 99.0, 100.0, 1000.0, 100000.0, 1, 'test')""",
            ((now - timedelta(minutes=5)).isoformat(), (now + timedelta(minutes=5)).isoformat()),
        )

        # Place order requesting 50 shares
        conn.execute(
            """INSERT INTO paper_order(
                paper_order_id, client_order_id, event_id, strategy_id, strategy_version,
                symbol, isin, side, quantity_requested, quantity_remaining, order_type,
                participation_cap_pct, valid_from_utc, valid_until_utc, status,
                decision_snapshot_hash, created_at_utc
            ) VALUES('ord-1', 'cli-1', 'ev-test-1', 'CR-01', '1', 'TESTSYM', 'INE000A01000',
                     'BUY', 50, 50, 'PAPER_MARKET', 1.0, ?, ?, 'PENDING_PRICE', 'hash1', ?)""",
            ((now - timedelta(minutes=5)).isoformat(), (now + timedelta(hours=1)).isoformat(), (now - timedelta(minutes=10)).isoformat()),
        )

        # Process orders: should fill 10 shares and mark PARTIALLY_FILLED
        stats = process_pending_orders(conn, _strat(), 10_000_000.0)
        assert stats["partially_filled"] == 1
        assert stats["filled"] == 0

        order = conn.execute("SELECT * FROM paper_order WHERE paper_order_id='ord-1'").fetchone()
        assert order["status"] == "PARTIALLY_FILLED"
        assert order["quantity_remaining"] == 40

        fills = conn.execute("SELECT * FROM paper_fill WHERE paper_order_id='ord-1'").fetchall()
        assert len(fills) == 1
        assert fills[0]["quantity"] == 10


def test_gap_opening_model(tmp_path: Path) -> None:
    db = tmp_path / "test_gap.db"
    _setup_db(db)
    now = datetime.now(UTC)

    with connect(db) as conn:
        # Bar opened at 105 (gap up from previous 100), closed at 102
        bar_open_time = now + timedelta(minutes=1)
        bar_close_time = now + timedelta(minutes=2)
        conn.execute(
            """INSERT INTO price_bar(
                bar_id, isin, symbol, interval, open_time_utc, close_time_utc,
                open, high, low, close, volume_shares, turnover_inr, is_complete, source_id
            ) VALUES('bar-gap', 'INE000A01000', 'TESTSYM', '1m', ?, ?, 105.0, 106.0, 101.0, 102.0, 10000.0, 10000000.0, 1, 'test')""",
            (bar_open_time.isoformat(), bar_close_time.isoformat()),
        )

        # Order created BEFORE bar open (e.g. at `now`)
        conn.execute(
            """INSERT INTO paper_order(
                paper_order_id, client_order_id, event_id, strategy_id, strategy_version,
                symbol, isin, side, quantity_requested, quantity_remaining, order_type,
                participation_cap_pct, valid_from_utc, valid_until_utc, status,
                decision_snapshot_hash, created_at_utc
            ) VALUES('ord-gap', 'cli-gap', 'ev-test-1', 'CR-01', '1', 'TESTSYM', 'INE000A01000',
                     'BUY', 20, 20, 'PAPER_MARKET', 1.0, ?, ?, 'PENDING_PRICE', 'hash2', ?)""",
            (now.isoformat(), (now + timedelta(hours=1)).isoformat(), now.isoformat()),
        )

        stats = process_pending_orders(conn, _strat(), 10_000_000.0)
        assert stats["filled"] == 1

        fill = conn.execute("SELECT * FROM paper_fill WHERE paper_order_id='ord-gap'").fetchone()
        assert fill["raw_price"] == 105.0  # Uses open price due to gap model!
        assert fill["fill_reason"] == "GAP_OPEN_FILL"


def test_lower_circuit_and_exit_unfilled(tmp_path: Path) -> None:
    db = tmp_path / "test_circuit.db"
    _setup_db(db)
    now = datetime.now(UTC)

    with connect(db) as conn:
        # First create an order and fill to satisfy position_lot foreign key
        conn.execute(
            """INSERT INTO paper_order(
                paper_order_id, client_order_id, event_id, strategy_id, strategy_version,
                symbol, isin, side, quantity_requested, quantity_remaining, order_type,
                participation_cap_pct, valid_from_utc, valid_until_utc, status,
                decision_snapshot_hash, created_at_utc
            ) VALUES('ord-init', 'cli-init', 'ev-test-1', 'CR-01', '1', 'TESTSYM', 'INE000A01000',
                     'BUY', 100, 0, 'PAPER_MARKET', 1.0, '2026-09-01T00:00:00Z', '2026-09-01T01:00:00Z',
                     'FILLED', 'hash-init', '2026-09-01T00:00:00Z')"""
        )
        conn.execute(
            """INSERT INTO paper_fill(
                paper_fill_id, paper_order_id, filled_at_utc, quantity, raw_price, spread_cost_inr,
                impact_cost_inr, statutory_cost_inr, final_price, fill_reason, market_data_ref
            ) VALUES('fill-init', 'ord-init', '2026-09-01T00:30:00Z', 100, 100.0, 50.0, 50.0, 100.0,
                     102.0, 'INITIAL_FILL', 'bar-init')"""
        )
        # Now position lot satisfies opened_by_fill_id foreign key
        conn.execute(
            """INSERT INTO position_lot(
                position_lot_id, isin, symbol, strategy_id, event_id, opened_by_fill_id,
                opened_at_utc, quantity_open, average_cost, stop_price, status
            ) VALUES('lot-1', 'INE000A01000', 'TESTSYM', 'CR-01', 'ev-test-1', 'fill-init',
                     '2026-09-01T00:00:00Z', 100, 100.0, 95.0, 'OPEN')"""
        )

        # Bar locked in lower circuit: High == Low == 90.0, volume negligible (10 shares)
        conn.execute(
            """INSERT INTO price_bar(
                bar_id, isin, symbol, interval, open_time_utc, close_time_utc,
                open, high, low, close, volume_shares, turnover_inr, is_complete, source_id
            ) VALUES('bar-circuit', 'INE000A01000', 'TESTSYM', '1D', ?, ?, 90.0, 90.0, 90.0, 90.0, 10.0, 900.0, 1, 'test')""",
            ((now - timedelta(hours=2)).isoformat(), (now - timedelta(hours=1)).isoformat()),
        )

        # Stop triggered -> create exit intent
        exits_created = create_exit_intents(conn)
        assert exits_created == 1

        exit_order = conn.execute("SELECT * FROM paper_order WHERE status='PENDING_EXIT'").fetchone()
        assert exit_order is not None

        # Process orders during circuit lock: order cannot fill
        stats = process_pending_orders(conn, _strat(), 10_000_000.0)
        assert stats["unfilled"] >= 1

        # Now expire the exit order
        conn.execute(
            "UPDATE paper_order SET valid_until_utc=? WHERE paper_order_id=?",
            ((now - timedelta(minutes=1)).isoformat(), exit_order["paper_order_id"]),
        )
        stats2 = process_pending_orders(conn, _strat(), 10_000_000.0)
        assert stats2["exit_unfilled"] == 1

        updated_order = conn.execute(
            "SELECT * FROM paper_order WHERE paper_order_id=?", (exit_order["paper_order_id"],)
        ).fetchone()
        assert updated_order["status"] == "EXIT_UNFILLED"

        # Position lot remains OPEN so it can retry next session
        lot = conn.execute("SELECT * FROM position_lot WHERE position_lot_id='lot-1'").fetchone()
        assert lot["status"] == "OPEN"
        assert lot["quantity_open"] == 100
