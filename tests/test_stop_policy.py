from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.stop_policy import SessionPerformance, StopPolicy, StopReason, evaluate_stop_policy  # noqa: E402


class StopPolicyTests(unittest.TestCase):
    def test_profit_target_halts_runtime(self) -> None:
        policy = StopPolicy(profit_target_cash=50.0)
        performance = SessionPerformance(realized_pnl_cash=60.0, peak_pnl_cash=60.0)
        decision = evaluate_stop_policy(policy, performance)
        self.assertTrue(decision.should_halt)
        self.assertEqual(decision.reason, StopReason.PROFIT_TARGET)

    def test_consecutive_losses_halt_runtime(self) -> None:
        policy = StopPolicy(max_consecutive_losses=3)
        performance = SessionPerformance(consecutive_losses=3)
        decision = evaluate_stop_policy(policy, performance)
        self.assertTrue(decision.should_halt)
        self.assertEqual(decision.reason, StopReason.CONSECUTIVE_LOSSES)
