from __future__ import annotations

import tempfile
import unittest
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.mt5_adapter import (
    DealSnapshot,
    MockMT5Adapter,
    OpenPositionSnapshot,
)
from goldm_signal.config import EntrySidePolicy
from goldm_signal.notify.mt5_log import Mt5LogBridge
from goldm_signal.notify.trade_lifecycle import TradeLifecycleConfig, TradeLifecycleWorker
from goldm_signal.storage import SignalStore


NOW = datetime(2026, 8, 13, 12, 1, tzinfo=timezone.utc)
SIGNAL = (
    "SNIPER_SIGNAL id=GOLD.i#-BUY-4379.22-2026.08.13 15:00 status=ENTRY_READY "
    "strategy=GOLDM_SNIPER_PARITY strategyVersion=1.72 directionProfile=ALL "
    "accountScope=demo accountLogin=123456 originServerB64=QnJva2VyLURlbW8 "
    "strategyMode=0 autoEntryEligible=true side=BUY level=4379.22 entry=4380.10 stop=4374.20 "
    "target=4397.80 projectedR=3.000 score=78 m5Votes=3 m1Confirmed=true "
    f"setupUtcEpoch={int(NOW.timestamp()) - 60} generatedUtcEpoch={int(NOW.timestamp())} "
    f"serverUtcOffsetMinutes=180 validUntilUtcEpoch={int(NOW.timestamp()) + 300} maxHoldingMinutes=1440"
)
SELL_SIGNAL = (
    SIGNAL.replace("-BUY-", "-SELL-")
    .replace("side=BUY", "side=SELL")
    .replace("stop=4374.20", "stop=4386.00")
    .replace("target=4397.80", "target=4362.40")
)
OUTCOME = (
    "SNIPER_OUTCOME id=GOLD.i#-BUY-4379.22-2026.08.13 15:00 "
    "status=CLOSED side=BUY result=TARGET outcomeR=3.0 entry=4380.10 "
    "exitPrice=4397.80 durationMinutes=42 "
    "accountScope=demo accountLogin=123456 originServerB64=QnJva2VyLURlbW8 "
    f"setupUtcEpoch={int(NOW.timestamp()) - 60} "
    f"generatedUtcEpoch={int(NOW.timestamp())} serverUtcOffsetMinutes=180 "
    "source=MODEL_SIMULATION"
)
CANCELLED = (
    "SNIPER_EARLY_CANCELLED id=GOLD.i#-BUY-4379.22-2026.08.13 15:00 "
    "status=CANCELLED side=BUY autoEntry=false confidenceEarly=62 "
    "reason=ENTRY_DISTANCE_EXCEEDED "
    "accountScope=demo accountLogin=123456 originServerB64=QnJva2VyLURlbW8 "
    f"setupUtcEpoch={int(NOW.timestamp()) - 60} "
    f"generatedUtcEpoch={int(NOW.timestamp())} serverUtcOffsetMinutes=180"
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
                "margin_mode": "HEDGING",
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


class PositionOpeningAdapter(CountingAdapter):
    def send_order(self, request):
        result = super().send_order(request)
        if request.get("action") == "open" and result.accepted:
            self._open_positions.append(
                OpenPositionSnapshot(
                    ticket=321,
                    position_identifier=7001,
                    symbol=str(request["symbol"]),
                    side=str(request["order_type"]),
                    volume=float(request["volume"]),
                    price_open=float(request["price"]),
                    sl=float(request["sl"]),
                    tp=float(request["tp"]),
                    profit=0.0,
                    opened_at=NOW.isoformat(),
                    magic=int(request["magic"]),
                    comment=str(request["comment"]),
                )
            )
        return result


class GoldMTradeLifecycleTests(unittest.TestCase):
    def _fixture(
        self, root: Path, signal: str = SIGNAL
    ) -> tuple[SignalStore, CountingAdapter]:
        log_path = root / "signal.log"
        log_path.write_text(signal + "\n", encoding="utf-8")
        store = SignalStore(root / "signal.db")
        store.initialize()
        self.assertEqual(
            Mt5LogBridge(
                store,
                log_paths=[log_path],
                expected_symbol="GOLD.i#",
                account_context_provider=lambda: {
                    "login": 123456,
                    "server": "Broker-Demo",
                    "is_live": False,
                },
            ).run_once(),
            (1, 1, 1),
        )
        return store, CountingAdapter()

    def test_noncanonical_symbol_is_rejected_before_any_broker_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wrong_symbol_signal = SIGNAL.replace("GOLD.i#", "XAUUSD")
            store, adapter = self._fixture(Path(tmpdir), wrong_symbol_signal)
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="demo",
                    max_entry_drift_r=0.2,
                ),
                now_fn=lambda: NOW,
            )

            self.assertEqual(worker.run_once(), (1, 0, 0))
            execution = store.trade_execution(
                "XAUUSD-BUY-4379.22-2026.08.13 15:00"
            )
            assert execution is not None
            self.assertEqual(execution["status"], "PRECHECK_REJECTED")
            self.assertIn("canonical GOLD.i#", execution["last_error"])
            self.assertEqual(adapter.send_count, 0)
            signal = next(
                row
                for row in store.pending()
                if row["event_type"] == "SNIPER_SIGNAL"
            )
            self.assertEqual(signal["payload"]["audience"], "admin_only")
            self.assertFalse(
                signal["payload"]["event_account_binding_verified"]
            )

    def _assert_precheck_rejected(self, signal: str, expected_detail: str) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter = self._fixture(Path(tmpdir), signal)
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True, execution_mode="demo", max_entry_drift_r=0.2
                ),
                now_fn=lambda: NOW,
            )

            self.assertEqual(worker.run_once(), (1, 0, 0))

            execution = store.trade_execution(
                "GOLD.i#-BUY-4379.22-2026.08.13 15:00"
            )
            assert execution is not None
            self.assertEqual(execution["status"], "PRECHECK_REJECTED")
            self.assertIn(expected_detail, execution["last_error"])
            self.assertEqual(adapter.send_count, 0)

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

    def test_signal_origin_binding_is_immutable_when_account_changes(self) -> None:
        cases = (
            ("Broker-Live", "Broker"),
            ("broker-demo", "Broker"),
            ("", ""),
        )
        for server, company in cases:
            with self.subTest(server=server), tempfile.TemporaryDirectory() as tmpdir:
                store, adapter = self._fixture(Path(tmpdir))
                adapter._account_info["server"] = server
                adapter._account_info["company"] = company
                worker = TradeLifecycleWorker(
                    store=store,
                    adapter=adapter,
                    config=TradeLifecycleConfig(
                        enabled=True,
                        execution_mode="off",
                        max_entry_drift_r=0.2,
                    ),
                    now_fn=lambda: NOW,
                )

                self.assertEqual(worker.run_once(), (1, 0, 0))

                setup_id = "GOLD.i#-BUY-4379.22-2026.08.13 15:00"
                execution = store.trade_execution(setup_id)
                assert execution is not None
                self.assertEqual(execution["execution_mode"], "off")
                self.assertEqual(execution["status"], "PRECHECK_REJECTED")
                self.assertEqual(execution["account_scope"], "demo")
                self.assertEqual(execution["account_login"], "123456")
                self.assertEqual(execution["account_server"], "Broker-Demo")
                signal = next(
                    row
                    for row in store.pending()
                    if row["event_type"] == "SNIPER_SIGNAL"
                )
                self.assertEqual(signal["payload"]["account_scope"], "demo")
                self.assertEqual(signal["payload"]["audience"], "admin_only")
                self.assertFalse(adapter.send_count)

    def test_broker_fill_response_without_position_stays_pending(self) -> None:
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
            self.assertEqual(execution["status"], "OPEN_SUBMITTED")
            self.assertEqual(adapter.send_count, 1)
            self.assertFalse(
                any(row["event_type"] == "POSITION_OPENED" for row in store.pending())
            )
            action = store.position_actions(setup_id=execution["setup_id"])[0]
            self.assertEqual(action["status"], "UNKNOWN")

    def test_exact_protected_broker_position_is_confirmed_filled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, _ = self._fixture(Path(tmpdir))
            adapter = PositionOpeningAdapter()
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="demo",
                    max_entry_drift_r=0.2,
                ),
                now_fn=lambda: NOW,
            )

            self.assertEqual(worker.run_once(), (1, 0, 0))

            execution = store.trade_execution(
                "GOLD.i#-BUY-4379.22-2026.08.13 15:00"
            )
            assert execution is not None
            self.assertEqual(execution["status"], "FILLED")
            self.assertEqual(execution["position_identifier"], 7001)
            self.assertEqual(execution["initial_volume"], execution["volume"])
            self.assertEqual(execution["initial_stop_price"], 4374.2)
            self.assertEqual(execution["magic"], 260814)
            self.assertEqual(execution["management_policy"], "M1_R_LOCK")
            opened = next(
                row for row in store.pending() if row["event_type"] == "POSITION_OPENED"
            )
            self.assertEqual(opened["payload"]["account_scope"], "demo")
            self.assertEqual(opened["payload"]["audience"], "approved")

    def test_non_hedging_or_unknown_account_is_rejected_before_open(self) -> None:
        for margin_mode in ("NETTING", "EXCHANGE", "UNKNOWN"):
            with self.subTest(margin_mode=margin_mode), tempfile.TemporaryDirectory() as tmpdir:
                store, adapter = self._fixture(Path(tmpdir))
                adapter._account_info["margin_mode"] = margin_mode
                worker = TradeLifecycleWorker(
                    store=store,
                    adapter=adapter,
                    config=TradeLifecycleConfig(
                        enabled=True,
                        execution_mode="demo",
                        max_entry_drift_r=0.2,
                    ),
                    now_fn=lambda: NOW,
                )

                self.assertEqual(worker.run_once(), (1, 0, 0))

                execution = store.trade_execution(
                    "GOLD.i#-BUY-4379.22-2026.08.13 15:00"
                )
                assert execution is not None
                self.assertEqual(execution["status"], "GUARD_REJECTED")
                self.assertEqual(execution["account_margin_mode"], margin_mode)
                self.assertIn("HEDGING", execution["last_error"])
                self.assertEqual(adapter.send_count, 0)

    def test_same_batch_signal_then_outcome_never_creates_open_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "signal.log"
            log_path.write_text(f"{SIGNAL}\n{OUTCOME}\n", encoding="utf-8")
            store = SignalStore(root / "signal.db")
            store.initialize()
            self.assertEqual(
                Mt5LogBridge(store, log_paths=[log_path]).run_once(), (1, 2, 2)
            )
            adapter = CountingAdapter()
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="demo",
                    max_entry_drift_r=0.2,
                ),
                now_fn=lambda: NOW,
            )

            self.assertEqual(worker.run_once(), (1, 1, 0))

            execution = store.trade_execution(
                "GOLD.i#-BUY-4379.22-2026.08.13 15:00"
            )
            assert execution is not None
            self.assertEqual(execution["status"], "CANCELLED")
            self.assertEqual(adapter.send_count, 0)
            self.assertEqual(store.position_actions(setup_id=execution["setup_id"]), [])

    def test_same_batch_signal_then_early_cancel_never_creates_open_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "signal.log"
            log_path.write_text(f"{SIGNAL}\n{CANCELLED}\n", encoding="utf-8")
            store = SignalStore(root / "signal.db")
            store.initialize()
            self.assertEqual(
                Mt5LogBridge(store, log_paths=[log_path]).run_once(), (1, 2, 2)
            )
            adapter = CountingAdapter()
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="demo",
                    max_entry_drift_r=0.2,
                ),
                now_fn=lambda: NOW,
            )

            self.assertEqual(worker.run_once(), (1, 1, 0))

            execution = store.trade_execution(
                "GOLD.i#-BUY-4379.22-2026.08.13 15:00"
            )
            assert execution is not None
            self.assertEqual(execution["status"], "CANCELLED")
            self.assertEqual(adapter.send_count, 0)
            self.assertEqual(store.position_actions(setup_id=execution["setup_id"]), [])

    def test_terminal_event_atomically_cancels_staged_pending_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store, adapter = self._fixture(root)
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="demo",
                    max_entry_drift_r=0.2,
                ),
                now_fn=lambda: NOW,
            )
            signal_row = store.execution_candidates()[0]
            self.assertEqual(worker._process_signal(signal_row), 1)
            execution = store.trade_execution(signal_row["setup_id"])
            assert execution is not None
            self.assertEqual(execution["status"], "OPEN_PENDING")

            terminal_path = root / "terminal.log"
            terminal_path.write_text(CANCELLED + "\n", encoding="utf-8")
            self.assertEqual(
                Mt5LogBridge(
                    store,
                    log_paths=[terminal_path],
                    account_context_provider=lambda: {
                        "login": 123456,
                        "server": "Broker-Demo",
                        "is_live": False,
                    },
                ).run_once(),
                (1, 1, 1),
            )
            terminal_row = store.execution_candidates(
                event_type="SNIPER_EARLY_CANCELLED"
            )[0]
            self.assertEqual(worker._process_terminal_event(terminal_row), 1)

            execution = store.trade_execution(signal_row["setup_id"])
            assert execution is not None
            action = store.position_actions(setup_id=execution["setup_id"])[0]
            self.assertEqual(execution["status"], "CANCELLED")
            self.assertEqual(action["status"], "FAILED")
            worker.manage_positions_once()
            self.assertEqual(adapter.send_count, 0)

    def test_terminal_after_ambiguous_open_defers_then_closes_exact_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store, adapter = self._fixture(root)
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="demo",
                    max_entry_drift_r=0.2,
                ),
                now_fn=lambda: NOW,
            )
            self.assertEqual(worker.run_once(), (1, 0, 0))
            setup_id = "GOLD.i#-BUY-4379.22-2026.08.13 15:00"
            pending = store.trade_execution(setup_id)
            assert pending is not None
            self.assertEqual(pending["status"], "OPEN_SUBMITTED")
            self.assertEqual(adapter.send_count, 1)

            terminal_path = root / "terminal.log"
            terminal_path.write_text(OUTCOME + "\n", encoding="utf-8")
            self.assertEqual(
                Mt5LogBridge(
                    store,
                    log_paths=[terminal_path],
                    account_context_provider=lambda: {
                        "login": 123456,
                        "server": "Broker-Demo",
                        "is_live": False,
                    },
                ).run_once(),
                (1, 1, 1),
            )
            adapter._open_positions.append(
                OpenPositionSnapshot(
                    ticket=321,
                    position_identifier=7001,
                    symbol=str(pending["symbol"]),
                    side=str(pending["side"]).lower(),
                    volume=float(pending["volume"]),
                    price_open=float(pending["requested_entry"]),
                    sl=float(pending["stop_price"]),
                    tp=float(pending["target_price"]),
                    profit=0.0,
                    opened_at=NOW.isoformat(),
                    magic=int(pending["magic"]),
                    comment=f"GMS: {pending['client_tag']}",
                )
            )

            self.assertEqual(worker.run_once(), (0, 1, 0))
            confirmed = store.trade_execution(setup_id)
            assert confirmed is not None
            self.assertEqual(confirmed["status"], "CLOSE_UNKNOWN")
            self.assertEqual(confirmed["deferred_close_reason"], "TARGET")

            worker.manage_positions_once()

            actions = store.position_actions(setup_id=setup_id, limit=20)
            self.assertEqual(
                len([row for row in actions if row["action_type"] == "OPEN"]), 1
            )
            self.assertEqual(
                len([row for row in actions if row["action_type"] == "CLOSE_FULL"]),
                1,
            )
            self.assertEqual(adapter.send_count, 2)

    def test_other_demo_terminal_cannot_cancel_pending_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store, adapter = self._fixture(root)
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="demo",
                    max_entry_drift_r=0.2,
                ),
                now_fn=lambda: NOW,
            )
            signal_row = store.execution_candidates()[0]
            self.assertEqual(worker._process_signal(signal_row), 1)
            setup_id = str(signal_row["setup_id"])
            before = store.trade_execution(setup_id)
            assert before is not None
            self.assertEqual(before["status"], "OPEN_PENDING")

            other_demo = (
                CANCELLED.replace("accountLogin=123456", "accountLogin=654321")
                .replace(
                    "originServerB64=QnJva2VyLURlbW8",
                    "originServerB64=QnJva2VyLURlbW8tQg",
                )
            )
            terminal_path = root / "other-demo-terminal.log"
            terminal_path.write_text(other_demo + "\n", encoding="utf-8")
            self.assertEqual(
                Mt5LogBridge(
                    store,
                    log_paths=[terminal_path],
                    account_context_provider=lambda: {
                        "login": 654321,
                        "server": "Broker-Demo-B",
                        "is_live": False,
                    },
                ).run_once(),
                (1, 1, 1),
            )
            terminal_row = store.execution_candidates(
                event_type="SNIPER_EARLY_CANCELLED"
            )[0]
            self.assertTrue(
                terminal_row["payload"]["event_account_binding_verified"]
            )
            self.assertEqual(terminal_row["payload"]["audience"], "approved")

            self.assertEqual(worker._process_terminal_event(terminal_row), 1)
            self.assertEqual(worker._process_terminal_event(terminal_row), 1)

            after = store.trade_execution(setup_id)
            assert after is not None
            self.assertEqual(after["status"], "OPEN_PENDING")
            self.assertIsNone(after["cancelled_by_terminal_outbox_id"])
            self.assertIsNone(after["deferred_close_terminal_outbox_id"])
            action = store.position_actions(setup_id=setup_id)[0]
            self.assertEqual(action["status"], "PENDING")
            self.assertEqual(adapter.send_count, 0)
            self.assertEqual(
                store.execution_candidates(event_type="SNIPER_EARLY_CANCELLED"),
                [],
            )
            audits = [
                row
                for row in store.pending(limit=20)
                if row["event_type"] == "TERMINAL_ACCOUNT_BINDING_REJECTED"
            ]
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0]["payload"]["audience"], "admin_only")
            self.assertFalse(
                audits[0]["payload"]["event_account_binding_verified"]
            )

    def test_real_terminal_cannot_defer_or_close_filled_demo_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store, _ = self._fixture(root)
            adapter = PositionOpeningAdapter()
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="demo",
                    max_entry_drift_r=0.2,
                ),
                now_fn=lambda: NOW,
            )
            self.assertEqual(worker.run_once(), (1, 0, 0))
            setup_id = "GOLD.i#-BUY-4379.22-2026.08.13 15:00"
            before = store.trade_execution(setup_id)
            assert before is not None
            self.assertEqual(before["status"], "FILLED")
            self.assertEqual(adapter.send_count, 1)

            real_outcome = (
                OUTCOME.replace("accountScope=demo", "accountScope=live")
                .replace("accountLogin=123456", "accountLogin=987654")
                .replace(
                    "originServerB64=QnJva2VyLURlbW8",
                    "originServerB64=QnJva2VyLUxpdmU",
                )
            )
            terminal_path = root / "real-terminal.log"
            terminal_path.write_text(real_outcome + "\n", encoding="utf-8")
            self.assertEqual(
                Mt5LogBridge(
                    store,
                    log_paths=[terminal_path],
                    account_context_provider=lambda: {
                        "login": 987654,
                        "server": "Broker-Live",
                        "is_live": True,
                    },
                ).run_once(),
                (1, 1, 1),
            )
            terminal_row = store.execution_candidates(
                event_type="SNIPER_OUTCOME"
            )[0]
            self.assertFalse(
                terminal_row["payload"]["event_account_binding_verified"]
            )
            self.assertEqual(worker._process_terminal_event(terminal_row), 1)

            after = store.trade_execution(setup_id)
            assert after is not None
            self.assertEqual(after["status"], "FILLED")
            self.assertIsNone(after["deferred_close_reason"])
            self.assertIsNone(after["deferred_close_terminal_outbox_id"])
            actions = store.position_actions(setup_id=setup_id, limit=20)
            self.assertEqual(
                [row["action_type"] for row in actions],
                ["OPEN"],
            )
            self.assertEqual(adapter.send_count, 1)
            audit = next(
                row
                for row in store.pending(limit=20)
                if row["event_type"] == "TERMINAL_ACCOUNT_BINDING_REJECTED"
            )
            self.assertEqual(audit["payload"]["audience"], "admin_only")
            self.assertIn("terminal event binding ditolak", audit["payload"]["text"])

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

    def test_sell_only_runtime_policy_rejects_buy_before_order_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter = self._fixture(Path(tmpdir))
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="demo",
                    entry_side_policy=EntrySidePolicy.SELL_ONLY,
                    max_entry_drift_r=0.2,
                ),
                now_fn=lambda: NOW,
            )

            self.assertEqual(worker.run_once(), (1, 0, 0))

            execution = store.trade_execution(
                "GOLD.i#-BUY-4379.22-2026.08.13 15:00"
            )
            assert execution is not None
            self.assertEqual(execution["status"], "SIDE_POLICY_REJECTED")
            self.assertIn("SELL_ONLY", execution["last_error"])
            self.assertEqual(adapter.send_count, 0)
            fields = store.pending()[0]["payload"]["fields"]
            self.assertEqual(fields["executionEntrySidePolicy"], "SELL_ONLY")

    def test_buy_only_runtime_policy_rejects_sell(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter = self._fixture(Path(tmpdir), SELL_SIGNAL)
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="demo",
                    entry_side_policy=EntrySidePolicy.BUY_ONLY,
                ),
                now_fn=lambda: NOW,
            )

            self.assertEqual(worker.run_once(), (1, 0, 0))

            execution = store.trade_execution(
                "GOLD.i#-SELL-4379.22-2026.08.13 15:00"
            )
            assert execution is not None
            self.assertEqual(execution["status"], "SIDE_POLICY_REJECTED")
            self.assertEqual(adapter.send_count, 0)

    def test_invalid_runtime_direction_setting_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter = self._fixture(Path(tmpdir))
            store.set_runtime_settings(
                {"trade.entry_side_policy": "SIDEWAYS"}, updated_by="100"
            )
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="demo",
                    entry_side_policy=EntrySidePolicy.ALL,
                ),
                now_fn=lambda: NOW,
            )

            self.assertEqual(worker.run_once(), (1, 0, 0))

            execution = store.trade_execution(
                "GOLD.i#-BUY-4379.22-2026.08.13 15:00"
            )
            assert execution is not None
            self.assertEqual(execution["status"], "SIDE_POLICY_REJECTED")
            self.assertIn("fail-closed", execution["last_error"])
            self.assertEqual(adapter.send_count, 0)
            fields = store.pending()[0]["payload"]["fields"]
            self.assertEqual(fields["executionEntrySidePolicy"], "INVALID")

    def test_signal_direction_metadata_mismatch_fails_closed(self) -> None:
        mismatched = SELL_SIGNAL.replace(
            "directionProfile=ALL",
            "directionProfile=BULL_ONLY",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter = self._fixture(Path(tmpdir), mismatched)
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="demo",
                    entry_side_policy=EntrySidePolicy.ALL,
                ),
                now_fn=lambda: NOW,
            )

            self.assertEqual(worker.run_once(), (1, 0, 0))

            execution = store.trade_execution(
                "GOLD.i#-SELL-4379.22-2026.08.13 15:00"
            )
            assert execution is not None
            self.assertEqual(execution["status"], "ENGINE_LINEAGE_REJECTED")
            self.assertIn("immutable directionProfile=ALL", execution["last_error"])
            self.assertEqual(adapter.send_count, 0)

    def test_signal_side_mismatch_is_not_executable(self) -> None:
        self._assert_precheck_rejected(
            SIGNAL.replace("side=BUY", "side=SELL"),
            "metadata side tidak cocok",
        )

    def test_unknown_strategy_version_is_not_executable(self) -> None:
        self._assert_precheck_rejected(
            SIGNAL.replace("strategyVersion=1.72", "strategyVersion=9.99"),
            "strategyVersion tidak didukung",
        )

    def test_unknown_strategy_id_is_not_executable(self) -> None:
        self._assert_precheck_rejected(
            SIGNAL.replace("strategy=GOLDM_SNIPER_PARITY", "strategy=LEGACY"),
            "strategy executable wajib exact",
        )

    def test_max_holding_minutes_must_be_positive_and_bounded(self) -> None:
        for replacement in ("", "0", "-1", "10081", "1.5"):
            signal = SIGNAL.replace(
                "maxHoldingMinutes=1440",
                (
                    "maxHoldingMinutes=" + replacement
                    if replacement
                    else "maxHoldingMinutesMissing=true"
                ),
            )
            with self.subTest(value=replacement or "missing"):
                self._assert_precheck_rejected(signal, "maxHoldingMinutes")

    def test_real_origin_read_on_demo_is_admin_only_and_never_executes(self) -> None:
        real_origin = (
            SIGNAL.replace("accountScope=demo", "accountScope=live")
            .replace("accountLogin=123456", "accountLogin=987654")
            .replace(
                "originServerB64=QnJva2VyLURlbW8",
                "originServerB64=QnJva2VyLUxpdmU",
            )
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter = self._fixture(Path(tmpdir), real_origin)
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="demo",
                    max_entry_drift_r=0.2,
                ),
                now_fn=lambda: NOW,
            )

            self.assertEqual(worker.run_once(), (1, 0, 0))

            execution = store.trade_execution(
                "GOLD.i#-BUY-4379.22-2026.08.13 15:00"
            )
            assert execution is not None
            self.assertEqual(execution["status"], "PRECHECK_REJECTED")
            self.assertEqual(execution["account_scope"], "live")
            self.assertEqual(adapter.send_count, 0)
            signal = next(
                row
                for row in store.pending()
                if row["event_type"] == "SNIPER_SIGNAL"
            )
            self.assertEqual(signal["payload"]["audience"], "admin_only")
            self.assertFalse(signal["payload"]["event_account_binding_verified"])

    def test_missing_auto_entry_eligibility_is_not_executable(self) -> None:
        self._assert_precheck_rejected(
            SIGNAL.replace("autoEntryEligible=true ", ""),
            "autoEntryEligible=true wajib eksplisit",
        )

    def test_missing_lineage_epoch_is_not_executable(self) -> None:
        setup_epoch = f"setupUtcEpoch={int(NOW.timestamp()) - 60} "
        self._assert_precheck_rejected(
            SIGNAL.replace(setup_epoch, ""),
            "setupUtcEpoch dan generatedUtcEpoch valid wajib",
        )

    def test_duplicate_lineage_field_is_not_executable(self) -> None:
        self._assert_precheck_rejected(
            SIGNAL + " strategyVersion=1.72",
            "field duplikat: strategyVersion",
        )

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
            store, _ = self._fixture(Path(tmpdir))
            adapter = PositionOpeningAdapter()
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(enabled=True, execution_mode="demo", max_entry_drift_r=0.2),
                now_fn=lambda: NOW,
            )
            worker.run_once()
            adapter._open_positions.clear()
            adapter.deals = [
                DealSnapshot(
                    ticket=777, position_ticket=7001, symbol="GOLD.i#", side="sell",
                    entry="out", volume=0.08, price=4385.0, profit=39.2,
                    commission=-0.8, swap=0.0, fee=-0.2, reason="manual_mobile",
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
            self.assertIn("P/L aktual: 38.20", close["payload"]["text"])
            self.assertIn("not predicted", close["payload"]["text"])


if __name__ == "__main__":
    unittest.main()
