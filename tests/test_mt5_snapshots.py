from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.mt5_snapshots import build_account_snapshot, build_symbol_snapshot  # noqa: E402


class MT5SnapshotTests(unittest.TestCase):
    def test_build_account_snapshot_from_mapping(self) -> None:
        snapshot = build_account_snapshot(
            {
                "equity": 1234.5,
                "balance": 1200.0,
                "margin_free": 900.0,
                "margin_level": 456.0,
            }
        )
        self.assertEqual(snapshot.equity, 1234.5)
        self.assertEqual(snapshot.free_margin, 900.0)

    def test_build_symbol_snapshot_infers_class(self) -> None:
        snapshot = build_symbol_snapshot(
            {
                "name": "XAUUSD",
                "point": 0.01,
                "trade_tick_size": 0.01,
                "trade_tick_value": 1.0,
                "volume_min": 0.01,
                "volume_max": 50.0,
                "volume_step": 0.01,
                "spread": 25,
                "trade_stops_level": 50,
                "trade_freeze_level": 10,
                "visible": True,
            },
            quote_session_active=True,
            trade_session_active=True,
            volatility_points=400.0,
        )
        self.assertEqual(snapshot.instrument_class, "metal")
        self.assertGreater(snapshot.risk_weight, 1.0)
        self.assertEqual(snapshot.spread_points, 25.0)


if __name__ == "__main__":
    unittest.main()
