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
