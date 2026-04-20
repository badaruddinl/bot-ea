from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.runtime_store import RuntimeStore  # noqa: E402


class RuntimeStoreTests(unittest.TestCase):
    def test_runtime_store_initializes_and_records_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime.db"
            store = RuntimeStore(db_path)
            store.initialize()
            store.start_run(run_id="run-1", started_at="2026-04-20T00:00:00Z", status="RUNNING", symbol="EURUSD")
            cycle_id = store.start_cycle(run_id="run-1", polled_at="2026-04-20T00:01:00Z", status="STARTED")
            store.record_market_snapshot(
                run_id="run-1",
                cycle_id=cycle_id,
                symbol="EURUSD",
                timeframe="M5",
                bid=1.1,
                ask=1.1002,
                spread_points=2.0,
                equity=1000.0,
                free_margin=900.0,
                session_state="london",
                news_state="clear",
                payload={"foo": "bar"},
            )
            store.record_ai_decision(
                run_id="run-1",
                cycle_id=cycle_id,
                action="OPEN",
                side="buy",
                confidence=0.8,
                reason="test decision",
                payload={"confidence_band": "high"},
            )
            store.record_risk_guard(
                run_id="run-1",
                cycle_id=cycle_id,
                allowed=False,
                mode="RECOMMEND",
                rejection_reason="allocation below recommended minimum",
                normalized_volume=0.1,
                risk_cash_budget=2.0,
                payload={"recommended_minimum_allocation_cash": 250.0},
            )
            store.record_stop_event(
                run_id="run-1",
                cycle_id=cycle_id,
                stop_code="profit_target",
                severity="hard",
                detail="profit target reached",
            )
            store.record_execution_event(
                run_id="run-1",
                cycle_id=cycle_id,
                attempt_id="attempt-1",
                event_type="ORDER_INTENT",
                status="DRY_RUN_OK",
                symbol="EURUSD",
                side="buy",
                volume=0.1,
                price=1.1002,
                retcode="",
                detail="dry-run ok",
                payload={"fill_latency_ms": 0.0},
            )
            store.record_position_event(
                run_id="run-1",
                cycle_id=cycle_id,
                broker_position_id="123",
                symbol="EURUSD",
                side="buy",
                volume=0.1,
                status="OPENED",
                entry_price=1.1002,
                payload={"quoted_price": 1.1002},
            )
            counts = store.fetch_counts()
            self.assertEqual(counts["runs"], 1)
            self.assertEqual(counts["polling_cycles"], 1)
            self.assertEqual(counts["market_snapshots"], 1)
            self.assertEqual(counts["ai_decisions"], 1)
            self.assertEqual(counts["risk_guard_events"], 1)
            self.assertEqual(counts["execution_events"], 1)
            self.assertEqual(counts["position_events"], 1)
            self.assertEqual(counts["stop_events"], 1)
            execution_events = store.fetch_recent_execution_events(limit=5)
            self.assertEqual(len(execution_events), 1)
            self.assertEqual(execution_events[0]["polled_at"], "2026-04-20T00:01:00Z")
            self.assertEqual(execution_events[0]["attempt_id"], "attempt-1")
            position_events = store.fetch_recent_position_events(limit=5)
            self.assertEqual(len(position_events), 1)
            self.assertEqual(position_events[0]["polled_at"], "2026-04-20T00:01:00Z")
            self.assertEqual(len(store.fetch_recent_runs(limit=5)), 1)
            health = store.fetch_execution_health_summary(limit=5)
            self.assertEqual(health["total_events"], 1)
            self.assertEqual(health["dry_run_events"], 1)
            self.assertEqual(health["filled_events"], 0)
            latest_guard = store.fetch_latest_risk_guard()
            self.assertIsNotNone(latest_guard)
            assert latest_guard is not None
            self.assertEqual(latest_guard["rejection_reason"], "allocation below recommended minimum")
            rejections = store.fetch_recent_rejections(limit=5)
            self.assertEqual(len(rejections), 1)
            self.assertEqual(rejections[0]["source"], "risk_guard")

    def test_fetch_trade_lifecycle_rows_reconstructs_trade_summaries_and_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime.db"
            store = RuntimeStore(db_path)
            store.initialize()

            store.start_run(run_id="run-1", started_at="2026-04-20T00:00:00Z", status="RUNNING", symbol="EURUSD")
            store.start_run(run_id="run-2", started_at="2026-04-20T01:00:00Z", status="RUNNING", symbol="GBPUSD")

            cycle_1 = store.start_cycle(run_id="run-1", polled_at="2026-04-20T00:01:00Z", status="STARTED")
            cycle_2 = store.start_cycle(run_id="run-1", polled_at="2026-04-20T00:15:00Z", status="STARTED")
            cycle_3 = store.start_cycle(run_id="run-1", polled_at="2026-04-20T00:25:00Z", status="STARTED")
            cycle_4 = store.start_cycle(run_id="run-2", polled_at="2026-04-20T01:05:00Z", status="STARTED")

            store.record_execution_event(
                run_id="run-1",
                cycle_id=cycle_1,
                attempt_id="attempt-closed",
                event_type="ORDER_ATTEMPT",
                phase="FILL",
                status="FILLED",
                symbol="EURUSD",
                side="buy",
                volume=0.2,
                price=1.1002,
                quoted_price=1.1002,
                executed_price=1.1003,
                slippage_points=1.0,
                fill_latency_ms=120.0,
                order_ticket="1001",
                deal_ticket="5001",
                retcode="0",
                detail="fill ok",
                payload={"source": "test"},
            )
            store.record_position_event(
                run_id="run-1",
                cycle_id=cycle_1,
                broker_position_id="1001",
                symbol="EURUSD",
                side="buy",
                volume=0.2,
                status="OPENED",
                entry_price=1.1003,
                opened_at="2026-04-20T00:01:02Z",
                commission_cash=-0.2,
                payload={"deal": "5001", "quoted_price": 1.1002},
            )
            store.record_position_event(
                run_id="run-1",
                cycle_id=cycle_2,
                broker_position_id="1001",
                symbol="EURUSD",
                side="buy",
                volume=0.2,
                status="CLOSED",
                entry_price=1.1003,
                exit_price=1.101,
                closed_at="2026-04-20T00:15:03Z",
                realized_pnl_cash=14.0,
                commission_cash=-0.4,
                swap_cash=-0.1,
                payload={"deal": "5001"},
            )

            store.record_execution_event(
                run_id="run-1",
                cycle_id=cycle_2,
                attempt_id="attempt-deal-fallback",
                event_type="ORDER_ATTEMPT",
                phase="FILL",
                status="FILLED",
                symbol="USDJPY",
                side="sell",
                volume=0.1,
                price=151.2,
                quoted_price=151.2,
                executed_price=151.18,
                slippage_points=-2.0,
                fill_latency_ms=95.0,
                order_ticket=None,
                deal_ticket="5002",
                retcode="0",
                detail="fill ok",
                payload={"source": "test"},
            )
            store.record_position_event(
                run_id="run-1",
                cycle_id=cycle_2,
                broker_position_id=None,
                symbol="USDJPY",
                side="sell",
                volume=0.1,
                status="OPENED",
                entry_price=151.18,
                opened_at="2026-04-20T00:15:10Z",
                payload={"deal": "5002", "slippage_points": -2.0},
            )

            store.record_position_event(
                run_id="run-1",
                cycle_id=cycle_3,
                broker_position_id="manual-1",
                symbol="XAUUSD",
                side="buy",
                volume=0.05,
                status="CLOSED",
                entry_price=2320.0,
                exit_price=2325.0,
                opened_at="2026-04-20T00:20:00Z",
                closed_at="2026-04-20T00:25:05Z",
                realized_pnl_cash=25.0,
                commission_cash=-0.3,
                swap_cash=0.0,
                payload={"note": "manual close"},
            )

            store.record_execution_event(
                run_id="run-2",
                cycle_id=cycle_4,
                attempt_id="attempt-run-2",
                event_type="ORDER_ATTEMPT",
                phase="FILL",
                status="FILLED",
                symbol="GBPUSD",
                side="buy",
                volume=0.15,
                price=1.25,
                quoted_price=1.25,
                executed_price=1.2501,
                slippage_points=1.0,
                fill_latency_ms=110.0,
                order_ticket="2001",
                deal_ticket="6001",
                retcode="0",
                detail="fill ok",
                payload={"source": "test"},
            )
            store.record_position_event(
                run_id="run-2",
                cycle_id=cycle_4,
                broker_position_id="2001",
                symbol="GBPUSD",
                side="buy",
                volume=0.15,
                status="OPENED",
                entry_price=1.2501,
                opened_at="2026-04-20T01:05:02Z",
                payload={"deal": "6001"},
            )

            rows = store.fetch_trade_lifecycle_rows(limit=10)
            self.assertEqual([row["trade_key"] for row in rows], ["2001", "manual-1", "5002", "1001"])

            closed_trade = rows[-1]
            self.assertEqual(closed_trade["run_id"], "run-1")
            self.assertEqual(closed_trade["attempt_id"], "attempt-closed")
            self.assertEqual(closed_trade["broker_position_id"], "1001")
            self.assertEqual(closed_trade["order_ticket"], "1001")
            self.assertEqual(closed_trade["deal_ticket"], "5001")
            self.assertEqual(closed_trade["lifecycle_status"], "CLOSED")
            self.assertEqual(closed_trade["entry_price"], 1.1003)
            self.assertEqual(closed_trade["exit_price"], 1.101)
            self.assertEqual(closed_trade["filled_at"], "2026-04-20T00:01:00Z")
            self.assertEqual(closed_trade["opened_at"], "2026-04-20T00:01:02Z")
            self.assertEqual(closed_trade["closed_at"], "2026-04-20T00:15:03Z")
            self.assertEqual(closed_trade["realized_pnl_cash"], 14.0)
            self.assertAlmostEqual(closed_trade["commission_cash"], -0.6)
            self.assertEqual(closed_trade["swap_cash"], -0.1)
            self.assertEqual(
                [(entry["event_kind"], entry["event_name"]) for entry in closed_trade["ledger"]],
                [("execution", "FILLED"), ("position", "OPENED"), ("position", "CLOSED")],
            )

            fallback_trade = rows[2]
            self.assertEqual(fallback_trade["trade_key"], "5002")
            self.assertIsNone(fallback_trade["broker_position_id"])
            self.assertEqual(fallback_trade["deal_ticket"], "5002")
            self.assertEqual(fallback_trade["attempt_id"], "attempt-deal-fallback")
            self.assertEqual(fallback_trade["lifecycle_status"], "OPEN")
            self.assertEqual(len(fallback_trade["ledger"]), 2)
            self.assertEqual([entry["event_name"] for entry in fallback_trade["ledger"]], ["FILLED", "OPENED"])

            orphan_trade = rows[1]
            self.assertEqual(orphan_trade["trade_key"], "manual-1")
            self.assertIsNone(orphan_trade["fill_execution_id"])
            self.assertEqual(orphan_trade["lifecycle_status"], "CLOSED")
            self.assertEqual(orphan_trade["realized_pnl_cash"], 25.0)
            self.assertEqual([entry["event_name"] for entry in orphan_trade["ledger"]], ["CLOSED"])

            filtered_rows = store.fetch_trade_lifecycle_rows(run_id="run-1", limit=10)
            self.assertEqual([row["trade_key"] for row in filtered_rows], ["manual-1", "5002", "1001"])

            ledger = store.fetch_trade_lifecycle_ledger(run_id="run-1", limit=10)
            self.assertEqual([entry["trade_key"] for entry in ledger], ["1001", "1001", "5002", "1001", "5002", "manual-1"])
            self.assertEqual(
                [entry["event_name"] for entry in ledger],
                ["FILLED", "OPENED", "FILLED", "CLOSED", "OPENED", "CLOSED"],
            )

    def test_trade_lifecycle_keeps_earliest_opened_at_and_accumulates_split_fees(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime.db"
            store = RuntimeStore(db_path)
            store.initialize()
            store.start_run(run_id="run-1", started_at="2026-04-20T00:00:00Z", status="RUNNING", symbol="EURUSD")

            cycle_1 = store.start_cycle(run_id="run-1", polled_at="2026-04-20T00:01:00Z", status="STARTED")
            cycle_2 = store.start_cycle(run_id="run-1", polled_at="2026-04-20T00:02:00Z", status="STARTED")
            cycle_3 = store.start_cycle(run_id="run-1", polled_at="2026-04-20T00:05:00Z", status="STARTED")

            store.record_execution_event(
                run_id="run-1",
                cycle_id=cycle_1,
                attempt_id="attempt-1",
                event_type="ORDER_ATTEMPT",
                phase="FILL",
                status="FILLED",
                symbol="EURUSD",
                side="buy",
                volume=0.2,
                price=1.1002,
                quoted_price=1.1002,
                executed_price=1.1003,
                slippage_points=1.0,
                fill_latency_ms=120.0,
                order_ticket="1001",
                deal_ticket="5001",
                retcode="0",
                detail="fill ok",
            )
            store.record_position_event(
                run_id="run-1",
                cycle_id=cycle_1,
                broker_position_id="1001",
                symbol="EURUSD",
                side="buy",
                volume=0.2,
                status="OPENED",
                entry_price=1.1003,
                opened_at="2026-04-20T00:01:02Z",
                commission_cash=-0.2,
                swap_cash=-0.01,
                payload={"deal": "5001"},
            )
            store.record_position_event(
                run_id="run-1",
                cycle_id=cycle_2,
                broker_position_id="1001",
                symbol="EURUSD",
                side="buy",
                volume=0.2,
                status="OPENED",
                entry_price=1.1003,
                opened_at="2026-04-20T00:01:05Z",
                commission_cash=-0.1,
                swap_cash=-0.02,
                payload={"deal": "5001", "note": "sync refresh"},
            )
            store.record_position_event(
                run_id="run-1",
                cycle_id=cycle_3,
                broker_position_id="1001",
                symbol="EURUSD",
                side="buy",
                volume=0.2,
                status="CLOSED",
                entry_price=1.1003,
                exit_price=1.101,
                opened_at="2026-04-20T00:01:08Z",
                closed_at="2026-04-20T00:05:03Z",
                realized_pnl_cash=14.0,
                commission_cash=-0.3,
                swap_cash=-0.04,
                payload={"deal": "5001"},
            )

            rows = store.fetch_trade_lifecycle_rows(run_id="run-1", limit=5)
            self.assertEqual(len(rows), 1)
            trade = rows[0]

            self.assertEqual(trade["opened_at"], "2026-04-20T00:01:02Z")
            self.assertEqual(trade["closed_at"], "2026-04-20T00:05:03Z")
            self.assertAlmostEqual(trade["commission_cash"], -0.6)
            self.assertAlmostEqual(trade["swap_cash"], -0.07)
            self.assertEqual(
                [entry["event_name"] for entry in trade["ledger"]],
                ["FILLED", "OPENED", "OPENED", "CLOSED"],
            )
