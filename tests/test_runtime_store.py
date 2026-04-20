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
            store.record_stop_event(
                run_id="run-1",
                cycle_id=cycle_id,
                stop_code="profit_target",
                severity="hard",
                detail="profit target reached",
            )
            counts = store.fetch_counts()
            self.assertEqual(counts["runs"], 1)
            self.assertEqual(counts["polling_cycles"], 1)
            self.assertEqual(counts["market_snapshots"], 1)
            self.assertEqual(counts["ai_decisions"], 1)
            self.assertEqual(counts["stop_events"], 1)
