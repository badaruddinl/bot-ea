from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.models import AccountSnapshot, CapitalAllocation, CapitalAllocationMode, RiskPolicy, SymbolSnapshot, TradingStyle  # noqa: E402
from bot_ea.polling_runtime import AIIntent, DecisionAction, PollingRuntime, RuntimeSnapshot  # noqa: E402
from bot_ea.risk_engine import RiskEngine  # noqa: E402
from bot_ea.runtime_store import RuntimeStore  # noqa: E402
from bot_ea.stop_policy import SessionPerformance, StopPolicy  # noqa: E402


class FakeSnapshotProvider:
    def __init__(self, snapshot: RuntimeSnapshot) -> None:
        self.snapshot = snapshot

    def get_snapshot(self) -> RuntimeSnapshot:
        return self.snapshot


class FakeDecisionEngine:
    def decide(self, snapshot: RuntimeSnapshot) -> AIIntent:
        return AIIntent(
            action=DecisionAction.OPEN,
            side="buy",
            confidence=0.8,
            reason="open test trade",
            stop_distance_points=50.0,
            entry_price=snapshot.ask,
        )


class FakeExecutionRuntime:
    def preflight(self, snapshot: RuntimeSnapshot, intent: AIIntent, size_result) -> dict:
        if not snapshot.account.trade_expert:
            return {"status": "GUARD_REJECTED", "detail": "account expert trading disabled", "retcode": "", "request": {"price": snapshot.ask}}
        return {"status": "PRECHECK_OK", "detail": "mock precheck", "retcode": "0", "request": {"price": snapshot.ask}}

    def execute(self, snapshot: RuntimeSnapshot, intent: AIIntent, size_result, preflight_result: dict | None = None) -> dict:
        return {"status": "FILLED", "retcode": "0", "detail": "mock fill", "volume": size_result.normalized_volume}


class RaisingExecutionRuntime:
    def preflight(self, snapshot: RuntimeSnapshot, intent: AIIntent, size_result) -> dict:
        return {"status": "PRECHECK_OK", "detail": "mock precheck", "retcode": "0", "request": {"price": snapshot.ask}}

    def execute(self, snapshot: RuntimeSnapshot, intent: AIIntent, size_result, preflight_result: dict | None = None) -> dict:
        raise RuntimeError("boom")


class CloseDecisionEngine:
    def decide(self, snapshot: RuntimeSnapshot) -> AIIntent:
        return AIIntent(
            action=DecisionAction.CLOSE,
            side="buy",
            confidence=0.9,
            reason="close open position",
            payload={"position_ticket": "900001", "volume": 0.01},
        )


class CancelPendingDecisionEngine:
    def decide(self, snapshot: RuntimeSnapshot) -> AIIntent:
        return AIIntent(
            action=DecisionAction.CANCEL_PENDING,
            side=None,
            confidence=0.9,
            reason="cancel pending order",
            payload={"order_ticket": "700001"},
        )


class LifecycleExecutionRuntime:
    def preflight(self, snapshot: RuntimeSnapshot, intent: AIIntent, size_result) -> dict:
        return {
            "status": "PRECHECK_OK",
            "detail": "mock lifecycle precheck",
            "retcode": "0",
            "request": {"price": snapshot.bid, **intent.payload, "action": intent.action.value.lower()},
        }

    def execute(self, snapshot: RuntimeSnapshot, intent: AIIntent, size_result, preflight_result: dict | None = None) -> dict:
        payload = {
            "status": "FILLED",
            "retcode": "0",
            "detail": "mock lifecycle fill",
            "order": 900001,
            "deal": 800001,
            "volume": size_result.normalized_volume,
            "price": snapshot.bid,
        }
        payload.update(intent.payload)
        return payload


class PollingRuntimeTests(unittest.TestCase):
    def test_run_cycle_records_trade_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime.db"
            store = RuntimeStore(db_path)
            store.initialize()
            store.start_run(run_id="run-1", started_at="2026-04-20T00:00:00Z", status="RUNNING", symbol="EURUSD")

            snapshot = RuntimeSnapshot(
                symbol="EURUSD",
                timeframe="M5",
                bid=1.1000,
                ask=1.1002,
                spread_points=2.0,
                account=AccountSnapshot(equity=1000.0, balance=1000.0, free_margin=900.0, margin_level=500.0),
                symbol_snapshot=SymbolSnapshot(
                    name="EURUSD",
                    instrument_class="forex_major",
                    risk_weight=1.0,
                    point=0.0001,
                    tick_size=0.0001,
                    tick_value=1.0,
                    volume_min=0.01,
                    volume_max=10.0,
                    volume_step=0.01,
                    spread_points=2.0,
                    stops_level_points=10.0,
                    freeze_level_points=0.0,
                    volatility_points=100.0,
                ),
                risk_policy=RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0),
                trading_style=TradingStyle.INTRADAY,
                stop_distance_points=50.0,
                capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.PERCENT_EQUITY, value=25.0),
                session_state="london",
                news_state="clear",
            )

            runtime = PollingRuntime(
                store=store,
                snapshot_provider=FakeSnapshotProvider(snapshot),
                decision_engine=FakeDecisionEngine(),
                execution_runtime=FakeExecutionRuntime(),
                risk_engine=RiskEngine(),
                stop_policy=StopPolicy(),
            )
            result = runtime.run_cycle(run_id="run-1", performance=SessionPerformance())
            counts = store.fetch_counts()
            self.assertFalse(result.halted)
            self.assertEqual(counts["polling_cycles"], 1)
            self.assertEqual(counts["market_snapshots"], 1)
            self.assertEqual(counts["ai_decisions"], 1)
            self.assertEqual(counts["risk_guard_events"], 1)
            self.assertEqual(counts["execution_events"], 3)
            events = store.fetch_recent_execution_events(limit=5)
            self.assertEqual([event["phase"] for event in reversed(events)], ["INTENT", "PRECHECK", "FILL"])
            self.assertEqual(len({event["attempt_id"] for event in events}), 1)
            latest_guard = store.fetch_latest_risk_guard()
            self.assertIsNotNone(latest_guard)
            assert latest_guard is not None
            self.assertEqual(latest_guard["payload_json"]["capital_base_cash"], 250.0)

    def test_execution_guard_rejection_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime.db"
            store = RuntimeStore(db_path)
            store.initialize()
            store.start_run(run_id="run-2", started_at="2026-04-20T00:00:00Z", status="RUNNING", symbol="EURUSD")

            snapshot = RuntimeSnapshot(
                symbol="EURUSD",
                timeframe="M5",
                bid=1.1000,
                ask=1.1002,
                spread_points=2.0,
                account=AccountSnapshot(equity=1000.0, balance=1000.0, free_margin=900.0, margin_level=500.0, trade_expert=False),
                symbol_snapshot=SymbolSnapshot(
                    name="EURUSD",
                    instrument_class="forex_major",
                    risk_weight=1.0,
                    point=0.0001,
                    tick_size=0.0001,
                    tick_value=1.0,
                    volume_min=0.01,
                    volume_max=10.0,
                    volume_step=0.01,
                    spread_points=2.0,
                    stops_level_points=10.0,
                    freeze_level_points=0.0,
                    volatility_points=100.0,
                ),
                risk_policy=RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0),
                trading_style=TradingStyle.INTRADAY,
                stop_distance_points=50.0,
                capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.PERCENT_EQUITY, value=25.0),
            )

            runtime = PollingRuntime(
                store=store,
                snapshot_provider=FakeSnapshotProvider(snapshot),
                decision_engine=FakeDecisionEngine(),
                execution_runtime=FakeExecutionRuntime(),
                risk_engine=RiskEngine(),
                stop_policy=StopPolicy(),
            )
            result = runtime.run_cycle(run_id="run-2", performance=SessionPerformance())
            counts = store.fetch_counts()

            self.assertEqual(result.action, "EXECUTION_GUARD_REJECTED")
            self.assertEqual(counts["execution_events"], 2)
            events = store.fetch_recent_execution_events(limit=5)
            self.assertEqual([event["phase"] for event in reversed(events)], ["INTENT", "GUARD"])

    def test_execution_runtime_failure_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime.db"
            store = RuntimeStore(db_path)
            store.initialize()
            store.start_run(run_id="run-3", started_at="2026-04-20T00:00:00Z", status="RUNNING", symbol="EURUSD")

            snapshot = RuntimeSnapshot(
                symbol="EURUSD",
                timeframe="M5",
                bid=1.1000,
                ask=1.1002,
                spread_points=2.0,
                account=AccountSnapshot(equity=1000.0, balance=1000.0, free_margin=900.0, margin_level=500.0),
                symbol_snapshot=SymbolSnapshot(
                    name="EURUSD",
                    instrument_class="forex_major",
                    risk_weight=1.0,
                    point=0.0001,
                    tick_size=0.0001,
                    tick_value=1.0,
                    volume_min=0.01,
                    volume_max=10.0,
                    volume_step=0.01,
                    spread_points=2.0,
                    stops_level_points=10.0,
                    freeze_level_points=0.0,
                    volatility_points=100.0,
                ),
                risk_policy=RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0),
                trading_style=TradingStyle.INTRADAY,
                stop_distance_points=50.0,
                capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.PERCENT_EQUITY, value=25.0),
            )

            runtime = PollingRuntime(
                store=store,
                snapshot_provider=FakeSnapshotProvider(snapshot),
                decision_engine=FakeDecisionEngine(),
                execution_runtime=RaisingExecutionRuntime(),
                risk_engine=RiskEngine(),
                stop_policy=StopPolicy(),
            )
            result = runtime.run_cycle(run_id="run-3", performance=SessionPerformance())
            counts = store.fetch_counts()

            self.assertFalse(result.halted)
            self.assertEqual(result.action, DecisionAction.OPEN.value)
            self.assertEqual(counts["execution_events"], 3)
            events = store.fetch_recent_execution_events(limit=5)
            self.assertEqual([event["phase"] for event in reversed(events)], ["INTENT", "PRECHECK", "FILL"])
            self.assertEqual(events[0]["status"], "ERROR")

    def test_close_cycle_records_closed_position_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime.db"
            store = RuntimeStore(db_path)
            store.initialize()
            store.start_run(run_id="run-close", started_at="2026-04-20T00:00:00Z", status="RUNNING", symbol="EURUSD")

            snapshot = RuntimeSnapshot(
                symbol="EURUSD",
                timeframe="M5",
                bid=1.1000,
                ask=1.1002,
                spread_points=2.0,
                account=AccountSnapshot(equity=1000.0, balance=1000.0, free_margin=900.0, margin_level=500.0),
                symbol_snapshot=SymbolSnapshot(
                    name="EURUSD",
                    instrument_class="forex_major",
                    risk_weight=1.0,
                    point=0.0001,
                    tick_size=0.0001,
                    tick_value=1.0,
                    volume_min=0.01,
                    volume_max=10.0,
                    volume_step=0.01,
                    spread_points=2.0,
                    stops_level_points=10.0,
                    freeze_level_points=0.0,
                    volatility_points=100.0,
                ),
                risk_policy=RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0),
                trading_style=TradingStyle.INTRADAY,
                stop_distance_points=50.0,
                capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.PERCENT_EQUITY, value=25.0),
            )

            runtime = PollingRuntime(
                store=store,
                snapshot_provider=FakeSnapshotProvider(snapshot),
                decision_engine=CloseDecisionEngine(),
                execution_runtime=LifecycleExecutionRuntime(),
                risk_engine=RiskEngine(),
                stop_policy=StopPolicy(),
            )
            result = runtime.run_cycle(run_id="run-close", performance=SessionPerformance())
            positions = store.fetch_recent_position_events(run_id="run-close", limit=5)

            self.assertFalse(result.halted)
            self.assertEqual(result.action, DecisionAction.CLOSE.value)
            self.assertEqual(positions[0]["status"], "CLOSED")

    def test_cancel_pending_cycle_records_execution_without_position_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime.db"
            store = RuntimeStore(db_path)
            store.initialize()
            store.start_run(run_id="run-cancel", started_at="2026-04-20T00:00:00Z", status="RUNNING", symbol="EURUSD")

            snapshot = RuntimeSnapshot(
                symbol="EURUSD",
                timeframe="M5",
                bid=1.1000,
                ask=1.1002,
                spread_points=2.0,
                account=AccountSnapshot(equity=1000.0, balance=1000.0, free_margin=900.0, margin_level=500.0),
                symbol_snapshot=SymbolSnapshot(
                    name="EURUSD",
                    instrument_class="forex_major",
                    risk_weight=1.0,
                    point=0.0001,
                    tick_size=0.0001,
                    tick_value=1.0,
                    volume_min=0.01,
                    volume_max=10.0,
                    volume_step=0.01,
                    spread_points=2.0,
                    stops_level_points=10.0,
                    freeze_level_points=0.0,
                    volatility_points=100.0,
                ),
                risk_policy=RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0),
                trading_style=TradingStyle.INTRADAY,
                stop_distance_points=50.0,
                capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.PERCENT_EQUITY, value=25.0),
            )

            runtime = PollingRuntime(
                store=store,
                snapshot_provider=FakeSnapshotProvider(snapshot),
                decision_engine=CancelPendingDecisionEngine(),
                execution_runtime=LifecycleExecutionRuntime(),
                risk_engine=RiskEngine(),
                stop_policy=StopPolicy(),
            )
            result = runtime.run_cycle(run_id="run-cancel", performance=SessionPerformance())
            positions = store.fetch_recent_position_events(run_id="run-cancel", limit=5)
            events = store.fetch_recent_execution_events(run_id="run-cancel", limit=5)

            self.assertFalse(result.halted)
            self.assertEqual(result.action, DecisionAction.CANCEL_PENDING.value)
            self.assertEqual(len(positions), 0)
            self.assertEqual(events[0]["status"], "FILLED")
