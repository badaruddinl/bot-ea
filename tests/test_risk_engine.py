from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.models import (  # noqa: E402
    AccountSnapshot,
    OperatingMode,
    PositionSizeRequest,
    RiskPolicy,
    SymbolSnapshot,
)
from bot_ea.risk_engine import RiskEngine  # noqa: E402


class RiskEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RiskEngine()
        self.policy = RiskPolicy(
            base_risk_pct=1.0,
            max_total_open_risk_pct=2.0,
            daily_loss_limit_pct=3.0,
        )
        self.account = AccountSnapshot(
            equity=1_000.0,
            balance=1_000.0,
            free_margin=900.0,
            margin_level=500.0,
            current_open_risk_pct=0.0,
            daily_realized_loss_pct=0.0,
        )
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
            volatility_points=200.0,
        )

    def test_strict_mode_reduces_risk_budget(self) -> None:
        recommend_request = PositionSizeRequest(
            account=self.account,
            symbol=self.symbol,
            policy=self.policy,
            stop_distance_points=50.0,
        )
        strict_request = PositionSizeRequest(
            account=self.account,
            symbol=self.symbol,
            policy=self.policy,
            stop_distance_points=50.0,
            force_symbol=True,
        )

        recommend_result = self.engine.compute_position_size(recommend_request)
        strict_result = self.engine.compute_position_size(strict_request)

        self.assertTrue(recommend_result.accepted)
        self.assertTrue(strict_result.accepted)
        self.assertEqual(recommend_result.mode, OperatingMode.RECOMMEND)
        self.assertEqual(strict_result.mode, OperatingMode.STRICT)
        self.assertLess(strict_result.risk_cash_budget, recommend_result.risk_cash_budget)
        self.assertLess(strict_result.normalized_volume, recommend_result.normalized_volume)

    def test_volume_rounds_down_to_step(self) -> None:
        request = PositionSizeRequest(
            account=self.account,
            symbol=self.symbol,
            policy=self.policy,
            stop_distance_points=33.0,
        )
        result = self.engine.compute_position_size(request)

        self.assertTrue(result.accepted)
        self.assertAlmostEqual(result.normalized_volume / 0.01, round(result.normalized_volume / 0.01), places=8)

    def test_daily_loss_exhaustion_blocks_trade(self) -> None:
        tired_account = AccountSnapshot(
            equity=1_000.0,
            balance=1_000.0,
            free_margin=900.0,
            margin_level=500.0,
            current_open_risk_pct=0.0,
            daily_realized_loss_pct=3.0,
        )
        request = PositionSizeRequest(
            account=tired_account,
            symbol=self.symbol,
            policy=self.policy,
            stop_distance_points=50.0,
        )
        result = self.engine.compute_position_size(request)

        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, "no remaining risk budget")

    def test_stop_level_rejection(self) -> None:
        request = PositionSizeRequest(
            account=self.account,
            symbol=self.symbol,
            policy=self.policy,
            stop_distance_points=10.0,
        )
        result = self.engine.compute_position_size(request)

        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, "stop distance below broker stop level")


if __name__ == "__main__":
    unittest.main()
