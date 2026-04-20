from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.models import AccountSnapshot, SymbolSnapshot  # noqa: E402
from bot_ea.mt5_adapter import PriceTickSnapshot, TerminalStatusSnapshot  # noqa: E402
from bot_ea.websocket_service import BotEaWebSocketService  # noqa: E402


class FakeAdapter:
    def __init__(self, ticks: list[tuple[float, float]] | None = None) -> None:
        self._ticks = list(ticks or [(4800.0, 4800.2)])
        self._tick_index = 0
        self.validated_requests: list[dict] = []
        self.sent_requests: list[dict] = []

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
            instrument_class="metal",
            risk_weight=1.0,
            point=0.01,
            tick_size=0.01,
            tick_value=0.1,
            volume_min=0.01,
            volume_max=50.0,
            volume_step=0.01,
            spread_points=17.0,
            stops_level_points=10.0,
            freeze_level_points=0.0,
            trade_allowed=True,
            trade_mode="full",
            order_mode="market",
            execution_mode="market",
            filling_mode="fok",
            bid=4700.0,
            ask=4700.2,
            price=4700.2,
        )

    def load_price_tick(self, symbol: str) -> PriceTickSnapshot:
        index = min(self._tick_index, len(self._ticks) - 1)
        bid, ask = self._ticks[index]
        self._tick_index += 1
        return PriceTickSnapshot(symbol=symbol, bid=bid, ask=ask, time=f"2026-04-21T00:00:0{self._tick_index}+00:00")

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
        return ["EURUSD", "XAUUSD"]

    def estimate_margin(self, symbol: str, volume: float, order_type: str, price: float):
        _ = symbol, order_type
        required = volume * price * 0.02
        return type("Margin", (), {"required_margin": required, "success": True, "detail": "ok"})()

    def validate_order(self, request: dict):
        self.validated_requests.append(dict(request))
        return type(
            "Validation",
            (),
            {
                "accepted": True,
                "detail": "ok",
                "projected_margin_free": 850.0,
                "projected_margin_level": 350.0,
                "retcode": 0,
            },
        )()

    def send_order(self, request: dict):
        self.sent_requests.append(dict(request))
        return type(
            "Send",
            (),
            {
                "accepted": True,
                "detail": "filled",
                "retcode": 0,
                "order": 123,
                "deal": 456,
                "volume": request.get("volume"),
                "price": request.get("price"),
                "bid": 4800.0,
                "ask": 4800.2,
                "request_id": 1,
                "retcode_external": 0,
            },
        )()

    def shutdown(self) -> None:
        return None


class WebSocketServiceTests(unittest.TestCase):
    def _manual_params(self, tmpdir: str, **overrides) -> dict[str, object]:
        params: dict[str, object] = {
            "symbol": "XAUUSD",
            "timeframe": "M15",
            "trading_style": "intraday",
            "stop_distance_points": 10,
            "capital_mode": "fixed_cash",
            "capital_value": 100,
            "lot_mode": "manual",
            "manual_lot": 1.0,
            "side": "buy",
            "db_path": str(Path(tmpdir) / "runtime.db"),
        }
        params.update(overrides)
        return params

    def test_refresh_manual_command_returns_latest_tick_snapshot(self) -> None:
        async def run_test() -> None:
            adapter = FakeAdapter(ticks=[(4800.0, 4800.2), (4801.0, 4801.3)])
            service = BotEaWebSocketService(adapter_factory=lambda: adapter)
            with tempfile.TemporaryDirectory() as tmpdir:
                response = await service._handle_command(
                    {
                        "id": "1",
                        "name": "refresh_manual",
                        "params": self._manual_params(tmpdir),
                    }
                )
                self.assertTrue(response["ok"])
                result = response["result"]
                self.assertIn("snapshot", result)
                self.assertIn("manual_order_snapshot", result)
                self.assertEqual(result["snapshot"]["symbol"], "XAUUSD")
                self.assertEqual(result["snapshot"]["bid"], 4801.0)
                self.assertEqual(result["snapshot"]["ask"], 4801.3)
                self.assertEqual(result["snapshot"]["tick_time"], "2026-04-21T00:00:02+00:00")
                self.assertEqual(result["manual_order_snapshot"]["order_price"], 4801.3)

        asyncio.run(run_test())

    def test_preflight_manual_uses_latest_tick_for_request_price(self) -> None:
        async def run_test() -> None:
            adapter = FakeAdapter(ticks=[(4800.0, 4800.2), (4802.0, 4802.4)])
            service = BotEaWebSocketService(adapter_factory=lambda: adapter)
            with tempfile.TemporaryDirectory() as tmpdir:
                response = await service._handle_command(
                    {
                        "id": "2",
                        "name": "preflight_manual",
                        "params": self._manual_params(tmpdir),
                    }
                )
                self.assertTrue(response["ok"])
                result = response["result"]
                self.assertEqual(result["status"], "PRECHECK_OK")
                self.assertEqual(result["snapshot"]["tick_time"], "2026-04-21T00:00:02+00:00")
                self.assertEqual(result["request"]["price"], 4802.4)
                self.assertEqual(result["manual_order_snapshot"]["order_price"], 4802.4)
                self.assertEqual(adapter.validated_requests[0]["price"], 4802.4)

        asyncio.run(run_test())

    def test_execute_manual_uses_latest_tick_for_live_send_price(self) -> None:
        async def run_test() -> None:
            adapter = FakeAdapter(ticks=[(4800.0, 4800.2), (4803.0, 4803.5)])
            service = BotEaWebSocketService(adapter_factory=lambda: adapter)
            with tempfile.TemporaryDirectory() as tmpdir:
                response = await service._handle_command(
                    {
                        "id": "3",
                        "name": "execute_manual",
                        "params": self._manual_params(tmpdir, live_enabled=True),
                    }
                )
                self.assertTrue(response["ok"])
                result = response["result"]
                self.assertEqual(result["status"], "FILLED")
                self.assertEqual(result["snapshot"]["tick_time"], "2026-04-21T00:00:02+00:00")
                self.assertEqual(result["request"]["price"], 4803.5)
                self.assertEqual(result["manual_order_snapshot"]["order_price"], 4803.5)
                self.assertEqual(adapter.validated_requests[0]["price"], 4803.5)
                self.assertEqual(adapter.sent_requests[0]["price"], 4803.5)

        asyncio.run(run_test())

    def test_start_runtime_command_builds_runtime_config(self) -> None:
        class FakeCoordinator:
            def __init__(self) -> None:
                self.started_config = None
                self.is_running = False

            def start(self, config):
                self.started_config = config
                return "run-123"

            def drain_events(self):
                return []

        async def run_test() -> None:
            coordinator = FakeCoordinator()
            service = BotEaWebSocketService(adapter_factory=FakeAdapter, runtime_coordinator=coordinator)
            with tempfile.TemporaryDirectory() as tmpdir:
                response = await service._handle_command(
                    {
                        "id": "4",
                        "name": "start_runtime",
                        "params": {
                            **self._manual_params(tmpdir),
                            "codex_command": "codex",
                            "model": "gpt-5.4-mini",
                            "codex_cwd": str(Path(tmpdir)),
                            "codex_timeout_seconds": 60,
                            "poll_interval_seconds": 30,
                        },
                    }
                )
                self.assertTrue(response["ok"])
                self.assertEqual(response["result"], "run-123")
                self.assertIsNotNone(coordinator.started_config)
                self.assertEqual(coordinator.started_config.symbol, "XAUUSD")
                self.assertEqual(coordinator.started_config.codex_executable, "codex")

        asyncio.run(run_test())

    def test_manual_mt5_commands_rejected_while_runtime_running(self) -> None:
        class FakeCoordinator:
            is_running = True

            def drain_events(self):
                return []

        async def run_test() -> None:
            service = BotEaWebSocketService(adapter_factory=FakeAdapter, runtime_coordinator=FakeCoordinator())
            with tempfile.TemporaryDirectory() as tmpdir:
                with self.assertRaises(RuntimeError) as ctx:
                    await service._handle_command(
                        {
                            "id": "5",
                            "name": "refresh_manual",
                            "params": self._manual_params(tmpdir),
                        }
                    )
                self.assertIn("disabled while runtime is running", str(ctx.exception))

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
