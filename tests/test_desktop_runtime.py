from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.codex_cli_engine import CodexContractError, CodexTimeoutError  # noqa: E402
from bot_ea.desktop_runtime import DesktopRuntimeConfig, DesktopRuntimeCoordinator  # noqa: E402
from bot_ea.models import (  # noqa: E402
    AccountSnapshot,
    CapitalAllocation,
    CapitalAllocationMode,
    RiskPolicy,
    SymbolSnapshot,
    TradingStyle,
)
from bot_ea.mt5_adapter import PriceTickSnapshot, TerminalStatusSnapshot  # noqa: E402
from bot_ea.polling_runtime import AIIntent, DecisionAction  # noqa: E402


class FakeAdapter:
    def load_account_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(
            equity=1000.0,
            balance=1000.0,
            free_margin=900.0,
            margin_level=400.0,
            trade_allowed=True,
            trade_expert=True,
        )

    def load_symbol_snapshot(self, symbol: str) -> SymbolSnapshot:
        return SymbolSnapshot(
            name=symbol,
            instrument_class="forex_major",
            risk_weight=1.0,
            point=0.0001,
            tick_size=0.0001,
            tick_value=10.0,
            volume_min=0.01,
            volume_max=10.0,
            volume_step=0.01,
            spread_points=2.0,
            stops_level_points=10.0,
            freeze_level_points=0.0,
            volatility_points=100.0,
            trade_allowed=True,
            trade_mode="full",
            order_mode="market",
            execution_mode="market",
            filling_mode="fok",
            bid=1.1000,
            ask=1.1002,
            price=1.1002,
        )

    def load_price_tick(self, symbol: str) -> PriceTickSnapshot:
        return PriceTickSnapshot(symbol=symbol, bid=1.1000, ask=1.1002, time="2026-04-20T00:00:00+00:00")

    def load_terminal_status(self) -> TerminalStatusSnapshot:
        return TerminalStatusSnapshot(
            connected=True,
            trade_allowed=True,
            tradeapi_disabled=False,
            path="C:\\Program Files\\MetaTrader 5",
            server="Demo-Server",
            company="Demo Broker",
            account_trade_allowed=True,
            account_trade_expert=True,
        )

    def load_available_symbols(self) -> list[str]:
        return ["AUDUSD", "EURUSD", "GBPUSD"]

    def validate_order(self, request: dict) -> dict:
        _ = request
        from bot_ea.mt5_adapter import OrderValidationResult

        return OrderValidationResult(
            accepted=True,
            detail="mock precheck",
            projected_margin_free=850.0,
            projected_margin_level=350.0,
            retcode=0,
        )

    def send_order(self, request: dict):
        _ = request
        from bot_ea.mt5_adapter import OrderSendResult

        return OrderSendResult(
            accepted=True,
            detail="mock fill",
            retcode=0,
            order=900001,
            deal=800001,
            volume=0.01,
            price=1.1002,
            bid=1.1000,
            ask=1.1002,
        )

    def shutdown(self) -> None:
        return None


class BrokenIPCAdapter(FakeAdapter):
    def __init__(self, *, fail_account_info: bool = False) -> None:
        self.fail_account_info = fail_account_info
        self.shutdown_calls = 0

    def load_account_snapshot(self) -> AccountSnapshot:
        if self.fail_account_info:
            raise RuntimeError("MT5 account_info() failed: (-10004, 'No IPC connection')")
        return super().load_account_snapshot()

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class FakeCodexEngine:
    def __init__(self, **_: object) -> None:
        pass

    def probe(self) -> str:
        return "codex-cli fake"

    def decide(self, snapshot) -> AIIntent:
        return AIIntent(
            action=DecisionAction.NO_TRADE,
            side=None,
            confidence=0.5,
            reason=f"hold for {snapshot.symbol}",
            stop_distance_points=snapshot.stop_distance_points,
        )


class OpenCodexEngine:
    def __init__(self, **_: object) -> None:
        pass

    def probe(self) -> str:
        return "codex-cli fake"

    def decide(self, snapshot) -> AIIntent:
        return AIIntent(
            action=DecisionAction.OPEN,
            side="buy",
            confidence=0.75,
            reason=f"open for {snapshot.symbol}",
            stop_distance_points=snapshot.stop_distance_points,
            entry_price=snapshot.ask,
        )


class TimeoutingCodexEngine:
    def __init__(self, **_: object) -> None:
        self.decide_calls = 0

    def probe(self) -> str:
        return "codex-cli fake"

    def decide(self, snapshot) -> AIIntent:
        self.decide_calls += 1
        raise CodexTimeoutError("codex exec timed out after 60 seconds")


class InvalidContractCodexEngine:
    def __init__(self, **_: object) -> None:
        self.decide_calls = 0

    def probe(self) -> str:
        return "codex-cli fake"

    def decide(self, snapshot) -> AIIntent:
        self.decide_calls += 1
        raise CodexContractError("codex response missing required keys ACTION, SIDE")


class DesktopRuntimeCoordinatorTests(unittest.TestCase):
    def test_probe_methods_return_runtime_readiness(self) -> None:
        coordinator = DesktopRuntimeCoordinator(
            adapter_factory=FakeAdapter,
            codex_engine_factory=FakeCodexEngine,
            risk_policy=RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0),
        )

        codex_version = coordinator.probe_codex(executable="codex")
        mt5_probe = coordinator.probe_mt5(
            symbol="EURUSD",
            timeframe="M5",
            trading_style=TradingStyle.INTRADAY,
            stop_distance_points=50.0,
            capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.FIXED_CASH, value=250.0),
        )

        self.assertEqual(codex_version, "codex-cli fake")
        self.assertTrue(mt5_probe["terminal"]["connected"])
        self.assertEqual(mt5_probe["snapshot"]["symbol"], "EURUSD")

    def test_background_runtime_starts_cycles_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            coordinator = DesktopRuntimeCoordinator(
                adapter_factory=FakeAdapter,
                codex_engine_factory=FakeCodexEngine,
                risk_policy=RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0),
            )
            config = DesktopRuntimeConfig(
                symbol="EURUSD",
                timeframe="M5",
                trading_style=TradingStyle.INTRADAY,
                stop_distance_points=20.0,
                capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.FIXED_CASH, value=1000.0),
                db_path=str(Path(tmpdir) / "runtime.db"),
                poll_interval_seconds=1,
            )

            run_id = coordinator.start(config)
            deadline = time.time() + 3.0
            seen_kinds: set[str] = set()
            last_cycle_payload = None
            while time.time() < deadline and "runtime_cycle" not in seen_kinds:
                for event in coordinator.drain_events():
                    seen_kinds.add(event.kind)
                    if event.kind == "runtime_cycle":
                        last_cycle_payload = event.payload
                time.sleep(0.05)
            coordinator.set_live_enabled(True)
            coordinator.stop()
            time.sleep(0.1)
            for event in coordinator.drain_events():
                seen_kinds.add(event.kind)

            self.assertTrue(run_id)
            self.assertIn("runtime_started", seen_kinds)
            self.assertIn("runtime_cycle", seen_kinds)
            self.assertIn("runtime_stopped", seen_kinds)
            self.assertFalse(coordinator.is_running)
            self.assertFalse(coordinator.live_enabled)
            assert last_cycle_payload is not None
            self.assertEqual(last_cycle_payload["snapshot"]["symbol"], "EURUSD")

    def test_live_mode_requires_operator_approval_before_submission(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            coordinator = DesktopRuntimeCoordinator(
                adapter_factory=FakeAdapter,
                codex_engine_factory=OpenCodexEngine,
                risk_policy=RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0),
            )
            coordinator.set_live_enabled(True)
            config = DesktopRuntimeConfig(
                symbol="EURUSD",
                timeframe="M5",
                trading_style=TradingStyle.INTRADAY,
                stop_distance_points=20.0,
                capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.FIXED_CASH, value=1000.0),
                db_path=str(Path(tmpdir) / "runtime.db"),
                poll_interval_seconds=1,
            )

            try:
                coordinator.start(config)
                deadline = time.time() + 3.0
                seen_kinds: set[str] = set()
                while time.time() < deadline and coordinator.pending_approval is None:
                    for event in coordinator.drain_events():
                        seen_kinds.add(event.kind)
                    time.sleep(0.05)
                for event in coordinator.drain_events():
                    seen_kinds.add(event.kind)

                self.assertIsNotNone(coordinator.pending_approval)
                assert coordinator.pending_approval is not None
                self.assertIn("approval_pending", seen_kinds)
                pending = coordinator.approve_pending_live_order()
                self.assertEqual(pending.symbol, "EURUSD")
                self.assertIsNotNone(coordinator.pending_approval)
            finally:
                coordinator.stop()

    def test_runtime_reconnects_after_transient_mt5_ipc_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapters: list[BrokenIPCAdapter] = []

            def adapter_factory() -> BrokenIPCAdapter:
                adapter = BrokenIPCAdapter(fail_account_info=len(adapters) == 0)
                adapters.append(adapter)
                return adapter

            coordinator = DesktopRuntimeCoordinator(
                adapter_factory=adapter_factory,
                codex_engine_factory=FakeCodexEngine,
                risk_policy=RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0),
            )
            config = DesktopRuntimeConfig(
                symbol="EURUSD",
                timeframe="M5",
                trading_style=TradingStyle.INTRADAY,
                stop_distance_points=20.0,
                capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.FIXED_CASH, value=1000.0),
                db_path=str(Path(tmpdir) / "runtime.db"),
                poll_interval_seconds=1,
            )

            try:
                coordinator.start(config)
                deadline = time.time() + 4.0
                seen_kinds: list[str] = []
                while time.time() < deadline and "runtime_cycle" not in seen_kinds:
                    for event in coordinator.drain_events():
                        seen_kinds.append(event.kind)
                    time.sleep(0.05)
                self.assertIn("runtime_started", seen_kinds)
                self.assertIn("runtime_recovering", seen_kinds)
                self.assertIn("runtime_cycle", seen_kinds)
                self.assertNotIn("runtime_error", seen_kinds)
                self.assertGreaterEqual(len(adapters), 2)
                self.assertEqual(adapters[0].shutdown_calls, 1)
            finally:
                coordinator.stop()

    def test_runtime_codex_timeout_uses_bounded_cooldown_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engines: list[TimeoutingCodexEngine] = []

            def codex_engine_factory(**_: object) -> TimeoutingCodexEngine:
                engine = TimeoutingCodexEngine()
                engines.append(engine)
                return engine

            coordinator = DesktopRuntimeCoordinator(
                adapter_factory=FakeAdapter,
                codex_engine_factory=codex_engine_factory,
                risk_policy=RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0),
            )
            config = DesktopRuntimeConfig(
                symbol="EURUSD",
                timeframe="M5",
                trading_style=TradingStyle.INTRADAY,
                stop_distance_points=20.0,
                capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.FIXED_CASH, value=1000.0),
                db_path=str(Path(tmpdir) / "runtime.db"),
                codex_timeout_cooldown_seconds=2,
                poll_interval_seconds=1,
            )

            try:
                coordinator.start(config)
                deadline = time.time() + 3.5
                cycle_count = 0
                seen_kinds: list[str] = []
                while time.time() < deadline and cycle_count < 2:
                    for event in coordinator.drain_events():
                        seen_kinds.append(event.kind)
                        if event.kind == "runtime_cycle":
                            cycle_count += 1
                    time.sleep(0.05)

                self.assertEqual(len(engines), 1)
                self.assertEqual(engines[0].decide_calls, 1)
                self.assertIn("codex_timeout", seen_kinds)
                self.assertGreaterEqual(cycle_count, 2)
                self.assertNotIn("runtime_error", seen_kinds)
            finally:
                coordinator.stop()

    def test_runtime_invalid_codex_contract_uses_no_trade_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engines: list[InvalidContractCodexEngine] = []

            def codex_engine_factory(**_: object) -> InvalidContractCodexEngine:
                engine = InvalidContractCodexEngine()
                engines.append(engine)
                return engine

            coordinator = DesktopRuntimeCoordinator(
                adapter_factory=FakeAdapter,
                codex_engine_factory=codex_engine_factory,
                risk_policy=RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0),
            )
            config = DesktopRuntimeConfig(
                symbol="EURUSD",
                timeframe="M5",
                trading_style=TradingStyle.INTRADAY,
                stop_distance_points=20.0,
                capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.FIXED_CASH, value=1000.0),
                db_path=str(Path(tmpdir) / "runtime.db"),
                poll_interval_seconds=1,
            )

            try:
                coordinator.start(config)
                deadline = time.time() + 2.5
                seen_kinds: list[str] = []
                cycle_payload = None
                contract_payload = None
                while time.time() < deadline and cycle_payload is None:
                    for event in coordinator.drain_events():
                        seen_kinds.append(event.kind)
                        if event.kind == "codex_contract_invalid":
                            contract_payload = event.payload
                        if event.kind == "runtime_cycle":
                            cycle_payload = event.payload
                    time.sleep(0.05)

                self.assertEqual(len(engines), 1)
                self.assertEqual(engines[0].decide_calls, 1)
                self.assertIn("codex_contract_invalid", seen_kinds)
                self.assertIsNotNone(cycle_payload)
                assert cycle_payload is not None
                self.assertEqual(cycle_payload["action"], "NO_TRADE")
                self.assertIn("contract invalid", cycle_payload["detail"])
                self.assertNotIn("runtime_error", seen_kinds)
                self.assertIsNotNone(contract_payload)
                assert contract_payload is not None
                self.assertIn("raw_response", contract_payload)
            finally:
                coordinator.stop()


if __name__ == "__main__":
    unittest.main()
