from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.mt5_adapter import MockMT5Adapter  # noqa: E402


class MockMT5AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = MockMT5Adapter(
            account_info={
                "equity": 1000.0,
                "balance": 1000.0,
                "margin_free": 800.0,
                "margin_level": 400.0,
            },
            symbols={
                "EURUSD": {
                    "name": "EURUSD",
                    "point": 0.0001,
                    "trade_tick_size": 0.0001,
                    "trade_tick_value": 10.0,
                    "volume_min": 0.01,
                    "volume_max": 10.0,
                    "volume_step": 0.01,
                    "spread": 12,
                    "trade_stops_level": 15,
                    "trade_freeze_level": 0,
                    "volatility_points": 200.0,
                    "visible": True,
                }
            },
            capabilities={
                "EURUSD": {
                    "trade_mode": "full",
                    "order_mode": "market",
                    "execution_mode": "market",
                    "filling_mode": "fok",
                    "quote_session_active": True,
                    "trade_session_active": True,
                    "server_time": "2026-04-20T09:00:00",
                }
            },
        )

    def test_load_symbol_capabilities(self) -> None:
        capabilities = self.adapter.load_symbol_capabilities("EURUSD")
        self.assertEqual(capabilities.trade_mode, "full")
        self.assertTrue(capabilities.trade_session_active)

    def test_validate_order_rejects_stop_level_violation(self) -> None:
        result = self.adapter.validate_order(
            {
                "symbol": "EURUSD",
                "volume": 0.10,
                "price": 1.1000,
                "order_type": "buy",
                "stop_distance_points": 5,
            }
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.retcode, 10016)

    def test_validate_order_accepts_valid_request(self) -> None:
        result = self.adapter.validate_order(
            {
                "symbol": "EURUSD",
                "volume": 0.10,
                "price": 1.1000,
                "order_type": "buy",
                "stop_distance_points": 25,
            }
        )
        self.assertTrue(result.accepted)
        self.assertGreater(result.projected_margin_free, 0)


if __name__ == "__main__":
    unittest.main()
