from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.models import Bar, SymbolSnapshot  # noqa: E402
from bot_ea.strategies.session_breakout import SessionBreakoutConfig, SignalSide, evaluate_session_breakout  # noqa: E402


class SessionBreakoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.symbol = SymbolSnapshot(
            name="EURUSD",
            instrument_class="forex_major",
            risk_weight=1.0,
            point=0.0001,
            tick_size=0.0001,
            tick_value=10.0,
            volume_min=0.01,
            volume_max=10.0,
            volume_step=0.01,
            spread_points=10.0,
            stops_level_points=15.0,
            freeze_level_points=0.0,
            quote_session_active=True,
            trade_session_active=True,
            trade_allowed=True,
            volatility_points=200.0,
        )
        self.config = SessionBreakoutConfig(
            opening_range_bars=4,
            min_range_points=0.0010,
            max_range_points=0.0200,
            breakout_buffer_points=0.0002,
            min_body_fraction=0.50,
            max_spread_to_volatility_ratio=0.10,
        )

    def test_detects_buy_breakout(self) -> None:
        start = datetime(2026, 4, 20, 9, 0, 0)
        bars = [
            Bar(start + timedelta(minutes=5 * i), 1.1000, 1.1010, 1.0998, 1.1008)
            for i in range(4)
        ]
        bars.append(Bar(start + timedelta(minutes=20), 1.1009, 1.1040, 1.1007, 1.1038))
        signal = evaluate_session_breakout(bars, self.symbol, self.config, session_active=True, news_blocked=False)
        self.assertTrue(signal.valid)
        self.assertEqual(signal.side, SignalSide.BUY)

    def test_stands_down_during_news(self) -> None:
        start = datetime(2026, 4, 20, 9, 0, 0)
        bars = [
            Bar(start + timedelta(minutes=5 * i), 1.1000, 1.1010, 1.0998, 1.1008)
            for i in range(4)
        ]
        bars.append(Bar(start + timedelta(minutes=20), 1.1009, 1.1040, 1.1007, 1.1038))
        signal = evaluate_session_breakout(bars, self.symbol, self.config, session_active=True, news_blocked=True)
        self.assertFalse(signal.valid)
        self.assertIn("news blackout active", signal.reasons)


if __name__ == "__main__":
    unittest.main()
