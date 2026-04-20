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
            bid=4800.0,
            ask=4800.2,
            price=4800.2,
        )

    def load_price_tick(self, symbol: str) -> PriceTickSnapshot:
        return PriceTickSnapshot(symbol=symbol, bid=4800.0, ask=4800.2, time="2026-04-21T00:00:00+00:00")

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
    def test_refresh_manual_command_returns_snapshot(self) -> None:
        async def run_test() -> None:
            service = BotEaWebSocketService(adapter_factory=FakeAdapter)
            with tempfile.TemporaryDirectory() as tmpdir:
                response = await service._handle_command(
                    {
                        "id": "1",
                        "name": "refresh_manual",
                        "params": {
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
                        },
                    }
                )
                self.assertTrue(response["ok"])
                result = response["result"]
                self.assertIn("snapshot", result)
                self.assertIn("manual_order_snapshot", result)
                self.assertEqual(result["snapshot"]["symbol"], "XAUUSD")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
