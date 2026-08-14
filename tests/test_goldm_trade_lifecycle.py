from __future__ import annotations

import tempfile
import unittest
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.mt5_adapter import DealSnapshot, MockMT5Adapter
from goldm_signal.notify.mt5_log import Mt5LogBridge
from goldm_signal.notify.trade_lifecycle import TradeLifecycleConfig, TradeLifecycleWorker
from goldm_signal.storage import SignalStore


NOW = datetime(2026, 8, 13, 12, 1, tzinfo=timezone.utc)
SIGNAL = (
    "SNIPER_SIGNAL id=GOLD.i#-BUY-4379.22-2026.08.13 15:00 status=ENTRY_READY "
    "autoEntryEligible=true side=BUY level=4379.22 entry=4380.10 stop=4374.20 "
    "target=4397.80 projectedR=3.000 score=78 m5Votes=3 m1Confirmed=true "
    f"setupUtcEpoch={int(NOW.timestamp()) - 60} generatedUtcEpoch={int(NOW.timestamp())} "
    f"serverUtcOffsetMinutes=180 validUntilUtcEpoch={int(NOW.timestamp()) + 300} maxHoldingMinutes=1440"
)


class CountingAdapter(MockMT5Adapter):
    def __init__(self) -> None:
        super().__init__(
            account_info={
                "equity": 10_000.0,
                "balance": 10_000.0,
                "margin_free": 9_000.0,
                "margin_level": 500.0,
                "trade_allowed": True,
                "trade_expert": True,
                "login": 123456,
                "server": "Broker-Demo",
                "company": "Broker",
            },
            symbols={
                "GOLD.i#": {
                    "name": "GOLD.i#",
                    "point": 0.01,
                    "trade_tick_size": 0.01,
                    "trade_tick_value": 1.0,
                    "volume_min": 0.01,
                    "volume_max": 50.0,
                    "volume_step": 0.01,
                    "spread": 20,
                    "trade_stops_level": 10,
                    "trade_freeze_level": 0,
                    "volatility_points": 1_000.0,
                    "visible": True,
                    "bid": 4379.90,
                    "ask": 4380.10,
                    "price": 4380.10,
                }
            },
            capabilities={
                "GOLD.i#": {
                    "trade_mode": "full",
                    "order_mode": "market|sl|tp",
                    "execution_mode": "market",
                    "filling_mode": "fok",
                    "quote_session_active": True,
                    "trade_session_active": True,
                }
            },
        )
        self.send_count = 0
        self.deals = []

    def send_order(self, request):
        self.send_count += 1
        return super().send_order(request)

    def load_deals(self, *, since, symbol=None):
        return list(self.deals)


class GoldMTradeLifecycleTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[SignalStore, CountingAdapter]:
        log_path = root / "signal.log"
        log_path.write_text(SIGNAL + "\n", encoding="utf-8")
        store = SignalStore(root / "signal.db")
        store.initialize()
        self.assertEqual(Mt5LogBridge(store, log_paths=[log_path]).run_once(), (1, 1, 1))
        return store, CountingAdapter()

    def test_off_mode_sizes_but_never_sends_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter = self._fixture(Path(tmpdir))
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(enabled=True, execution_mode="off", max_entry_drift_r=0.2),
                now_fn=lambda: NOW,
            )
            self.assertEqual(worker.run_once(), (1, 0, 0))
            execution = store.trade_execution("GOLD.i#-BUY-4379.22-2026.08.13 15:00")
            assert execution is not None
            self.assertEqual(execution["status"], "READY_MANUAL")
            self.assertGreater(execution["volume"], 0)
            self.assertEqual(adapter.send_count, 0)
            text = store.pending()[0]["payload"]["text"]
            self.assertIn("Mode eksekusi OFF", text)
            self.assertNotIn("menunggu sizing MT5", text)

    def test_demo_mode_requires_identified_demo_and_sends_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter = self._fixture(Path(tmpdir))
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(enabled=True, execution_mode="demo", max_entry_drift_r=0.2),
                now_fn=lambda: NOW,
            )
            self.assertEqual(worker.run_once(), (1, 0, 0))
            execution = store.trade_execution("GOLD.i#-BUY-4379.22-2026.08.13 15:00")
            assert execution is not None
            self.assertEqual(execution["status"], "FILLED")
            self.assertEqual(adapter.send_count, 1)
            self.assertIn("Order broker terisi", store.pending()[0]["payload"]["text"])
            self.assertTrue(any(row["event_type"] == "POSITION_OPENED" for row in store.pending()))

    def test_runtime_settings_override_worker_config_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter = self._fixture(Path(tmpdir))
            store.set_runtime_settings(
                {
                    "trade.execution_mode": "off",
                    "trade.risk_pct": 0.25,
                },
                updated_by="100",
            )
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="demo",
                    risk_pct=0.5,
                    max_entry_drift_r=0.2,
                ),
                now_fn=lambda: NOW,
            )

            self.assertEqual(worker.run_once(), (1, 0, 0))

            self.assertEqual(worker.config.execution_mode, "off")
            self.assertEqual(worker.config.risk_pct, 0.25)
            self.assertEqual(adapter.send_count, 0)

    def test_expired_signal_is_persisted_and_not_sent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter = self._fixture(Path(tmpdir))
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(enabled=True, execution_mode="demo"),
                now_fn=lambda: datetime(2026, 8, 13, 13, 0, tzinfo=timezone.utc),
            )
            worker.run_once()
            execution = store.trade_execution("GOLD.i#-BUY-4379.22-2026.08.13 15:00")
            assert execution is not None
            self.assertEqual(execution["status"], "EXPIRED")
            self.assertEqual(adapter.send_count, 0)

    def test_broker_history_emits_actual_manual_close_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter = self._fixture(Path(tmpdir))
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(enabled=True, execution_mode="demo", max_entry_drift_r=0.2),
                now_fn=lambda: NOW,
            )
            worker.run_once()
            adapter.deals = [
                DealSnapshot(
                    ticket=777, position_ticket=321, symbol="GOLD.i#", side="sell",
                    entry="out", volume=0.08, price=4385.0, profit=39.2,
                    commission=-0.8, swap=0.0, reason="manual_mobile",
                    occurred_at="2026-08-13T12:11:00+00:00", magic=260814,
                    comment="GMS: " + store.trade_execution(
                        "GOLD.i#-BUY-4379.22-2026.08.13 15:00"
                    )["client_tag"],
                )
            ]
            self.assertEqual(worker.run_once(), (0, 0, 1))
            execution = store.trade_execution("GOLD.i#-BUY-4379.22-2026.08.13 15:00")
            assert execution is not None
            self.assertEqual(execution["status"], "CLOSED")
            self.assertEqual(execution["closed_by"], "manual_mobile")
            close = next(row for row in store.pending() if row["event_type"] == "POSITION_CLOSED")
            self.assertIn("P/L aktual: 38.40", close["payload"]["text"])
            self.assertIn("not predicted", close["payload"]["text"])


if __name__ == "__main__":
    unittest.main()
