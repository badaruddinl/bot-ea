from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldm_signal.strategy import (
    Candle,
    evaluate_fibonacci_projection,
    evaluate_m5_confluence,
    is_evening_doji_star,
    is_morning_doji_star,
)


class GoldMConfluenceTests(unittest.TestCase):
    def test_morning_doji_star(self) -> None:
        first = Candle(open=101.0, high=101.2, low=98.8, close=99.0)
        middle = Candle(open=98.7, high=99.0, low=98.2, close=98.75)
        third = Candle(open=98.8, high=100.5, low=98.6, close=100.2)

        self.assertTrue(is_morning_doji_star(first, middle, third))
        self.assertFalse(is_evening_doji_star(first, middle, third))

    def test_evening_doji_star(self) -> None:
        first = Candle(open=99.0, high=101.2, low=98.8, close=101.0)
        middle = Candle(open=101.25, high=101.8, low=101.1, close=101.3)
        third = Candle(open=101.1, high=101.3, low=99.4, close=99.8)

        self.assertTrue(is_evening_doji_star(first, middle, third))
        self.assertFalse(is_morning_doji_star(first, middle, third))

    def test_two_votes_pass_when_price_action_anchors_them(self) -> None:
        result = evaluate_m5_confluence(
            price_action=True,
            rsi=True,
            stochastic=False,
            bollinger=False,
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.votes, 2)

    def test_indicators_strengthen_without_becoming_four_hard_gates(self) -> None:
        three_votes = evaluate_m5_confluence(
            price_action=False,
            rsi=True,
            stochastic=True,
            bollinger=True,
        )
        momentum_only = evaluate_m5_confluence(
            price_action=False,
            rsi=True,
            stochastic=True,
            bollinger=False,
        )

        self.assertTrue(three_votes.passed)
        self.assertFalse(momentum_only.passed)

    def test_fibonacci_retracement_alignment_and_extensions(self) -> None:
        projection = evaluate_fibonacci_projection(
            side="BUY",
            impulse_start=100.0,
            impulse_end=120.0,
            price=107.64,
        )

        self.assertTrue(projection.aligned)
        self.assertAlmostEqual(projection.retracement, 0.618)
        self.assertEqual(projection.nearest_level, 0.618)
        self.assertEqual(projection.extensions, (125.44, 132.36, 140.0))

    def test_fibonacci_is_a_bonus_not_a_standalone_entry(self) -> None:
        projection = evaluate_fibonacci_projection(
            side="SELL",
            impulse_start=120.0,
            impulse_end=100.0,
            price=112.36,
        )
        confluence = evaluate_m5_confluence(
            price_action=False,
            rsi=False,
            stochastic=False,
            bollinger=False,
        )

        self.assertTrue(projection.aligned)
        self.assertFalse(confluence.passed)


if __name__ == "__main__":
    unittest.main()
