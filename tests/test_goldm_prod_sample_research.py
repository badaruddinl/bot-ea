from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "research-goldm-prod-samples-mt5.py"
)
SPEC = importlib.util.spec_from_file_location("goldm_prod_sample_research", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GoldMProductionSampleResearchTests(unittest.TestCase):
    def test_psychological_level_is_strictly_above_buy_entry(self) -> None:
        self.assertEqual(MODULE._nearest_psychological_above(4392.23, 10.0), 4400.0)
        self.assertEqual(MODULE._nearest_psychological_above(4400.0, 10.0), 4410.0)

    def test_first_touch_reports_target_stop_and_same_bar_ambiguity(self) -> None:
        first = datetime(2026, 8, 18, tzinfo=timezone.utc)
        target = [{"time": first, "high": 4401.0, "low": 4395.0}]
        stop = [{"time": first, "high": 4399.0, "low": 4390.0}]
        ambiguous = [{"time": first, "high": 4401.0, "low": 4390.0}]
        self.assertEqual(
            MODULE._first_touch(target, side="BUY", stop=4392.0, target=4400.0)["event"],
            "TARGET",
        )
        self.assertEqual(
            MODULE._first_touch(stop, side="BUY", stop=4392.0, target=4400.0)["event"],
            "STOP",
        )
        self.assertEqual(
            MODULE._first_touch(
                ambiguous,
                side="BUY",
                stop=4392.0,
                target=4400.0,
            )["event"],
            "AMBIGUOUS_SAME_BAR",
        )

    def test_swing_high_requires_bars_on_both_sides(self) -> None:
        bars = [
            {"high": 1.0},
            {"high": 2.0},
            {"high": 5.0},
            {"high": 3.0},
            {"high": 2.0},
        ]
        self.assertEqual(MODULE._swing_highs(bars), [5.0])

    def test_tick_touch_uses_bid_for_buy_and_preserves_order(self) -> None:
        first = datetime(2026, 8, 18, tzinfo=timezone.utc)
        ticks = [
            {"time": first, "bid": 4398.0, "ask": 4398.2},
            {"time": first, "bid": 4400.0, "ask": 4400.2},
        ]
        result = MODULE._first_tick_touch(
            ticks,
            side="BUY",
            stop=4390.0,
            target=4400.0,
        )
        self.assertEqual(result, {"event": "TARGET", "time": first})

    def test_m1_features_distinguish_full_confirmation(self) -> None:
        first = datetime(2026, 8, 18, tzinfo=timezone.utc)
        bars = [
            {
                "time": first,
                "open": 99.0,
                "high": 100.0,
                "low": 98.0,
                "close": 99.5,
            },
            {
                "time": first,
                "open": 99.4,
                "high": 100.2,
                "low": 99.2,
                "close": 100.1,
            },
        ]
        features = MODULE._m1_confirmation_features(bars, side="BUY")
        self.assertTrue(features["directional_candle"])
        self.assertTrue(features["micro_break"])
        self.assertGreaterEqual(features["close_location_directional"], 0.8)


if __name__ == "__main__":
    unittest.main()
