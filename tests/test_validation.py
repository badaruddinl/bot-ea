from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.validation import TradeRecord, evaluate_cost_realism, summarize_trades  # noqa: E402


class ValidationTests(unittest.TestCase):
    def test_summary_metrics(self) -> None:
        start = datetime(2026, 4, 20, 9, 0, 0)
        trades = [
            TradeRecord("EURUSD", "session_breakout", "buy", start, start + timedelta(minutes=10), 50.0, 25.0, 10.0),
            TradeRecord("EURUSD", "session_breakout", "sell", start + timedelta(minutes=15), start + timedelta(minutes=25), -25.0, 25.0, 12.0),
        ]
        summary = summarize_trades(trades, starting_equity=1000.0)
        self.assertEqual(summary.total_trades, 2)
        self.assertAlmostEqual(summary.win_rate, 0.5)
        self.assertGreater(summary.profit_factor, 1.0)

    def test_cost_realism_warning(self) -> None:
        start = datetime(2026, 4, 20, 9, 0, 0)
        trades = [
            TradeRecord("EURUSD", "session_breakout", "buy", start, start + timedelta(minutes=10), 50.0, 25.0, 30.0),
        ]
        warnings = evaluate_cost_realism(trades, spread_threshold_points=20.0)
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
