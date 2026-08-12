from __future__ import annotations

import unittest
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldm_signal.config import SignalPolicy, gold_i_profile
from goldm_signal.market import DataHealthInput, evaluate_data_health
from goldm_signal.risk import evaluate_m15_risk_geometry, evaluate_reward_space, suggest_position_size


class GoldMHealthAndRiskTests(unittest.TestCase):
    def test_healthy_snapshot_passes(self) -> None:
        now = datetime(2026, 8, 12, 14, 15, tzinfo=timezone.utc)
        snapshot = DataHealthInput(
            now=now,
            last_tick_at=now - timedelta(seconds=2),
            server_time=now,
            available_timeframes=frozenset({"D1", "H4", "H1", "M15", "M5"}),
            terminal_connected=True,
            quote_session_active=True,
            trade_session_active=True,
            spread_price=0.2,
            atr_m15=5.0,
        )

        result = evaluate_data_health(snapshot, gold_i_profile(), SignalPolicy())

        self.assertTrue(result.passed)

    def test_missing_htf_stale_tick_and_wide_spread_are_hard_failures(self) -> None:
        now = datetime(2026, 8, 12, 14, 15, tzinfo=timezone.utc)
        snapshot = DataHealthInput(
            now=now,
            last_tick_at=now - timedelta(minutes=5),
            server_time=now,
            available_timeframes=frozenset({"M15", "M5"}),
            terminal_connected=True,
            quote_session_active=True,
            trade_session_active=True,
            spread_price=1.0,
            atr_m15=5.0,
        )

        result = evaluate_data_health(snapshot, gold_i_profile(), SignalPolicy())

        self.assertFalse(result.passed)
        self.assertTrue(any("data incomplete" in reason for reason in result.reasons))
        self.assertTrue(any("stale" in reason for reason in result.reasons))
        self.assertTrue(any("too wide" in reason for reason in result.reasons))

    def test_position_size_never_rounds_up_to_an_unsafe_minimum(self) -> None:
        suggestion = suggest_position_size(
            equity=100.0,
            risk_pct=0.005,
            stop_distance_price=10.0,
            tick_size=0.01,
            tick_value_loss=1.0,
            volume_step=0.01,
            profile=gold_i_profile(),
            policy=SignalPolicy(),
        )

        self.assertFalse(suggestion.safe)
        self.assertEqual(suggestion.volume, 0.0)
        self.assertIn("NO SAFE POSITION SIZE", suggestion.reason)

    def test_room_to_profit_requires_three_r(self) -> None:
        rejected = evaluate_reward_space(side="BUY", entry=4322.0, stop=4318.0, target=4330.0)
        accepted = evaluate_reward_space(side="BUY", entry=4322.0, stop=4318.0, target=4335.0)

        self.assertFalse(rejected.passed)
        self.assertEqual(rejected.projected_r, 2.0)
        self.assertTrue(accepted.passed)
        self.assertGreaterEqual(accepted.projected_r, 3.0)

    def test_m15_structural_stop_ignores_m1_micro_extreme(self) -> None:
        geometry = evaluate_m15_risk_geometry(
            side="BUY",
            entry=4002.0,
            level=4000.0,
            retest_extreme=3999.0,
            atr_m15=10.0,
        )

        self.assertTrue(geometry.passed)
        self.assertEqual(geometry.stop, 3996.5)
        self.assertEqual(geometry.risk, 5.5)
        self.assertEqual(geometry.entry_distance_atr, 0.2)

    def test_m15_entry_distance_rejects_chasing_move(self) -> None:
        geometry = evaluate_m15_risk_geometry(
            side="SELL",
            entry=3998.78,
            level=4007.10,
            retest_extreme=4008.0,
            atr_m15=10.0,
        )

        self.assertFalse(geometry.passed)
        self.assertAlmostEqual(geometry.entry_distance_atr, 0.832)
        self.assertIn("chasing", geometry.reason)


if __name__ == "__main__":
    unittest.main()
