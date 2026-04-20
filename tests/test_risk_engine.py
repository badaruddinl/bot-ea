from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.models import (  # noqa: E402
    AccountSnapshot,
    CapitalAllocation,
    CapitalAllocationMode,
    OperatingMode,
    PositionSizeRequest,
    RiskPolicy,
    SymbolSnapshot,
    TradingStyle,
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

    def test_percent_allocation_changes_capital_base(self) -> None:
        micro_symbol = SymbolSnapshot(
            name="EURUSD",
            instrument_class="forex_major",
            risk_weight=1.0,
            point=0.0001,
            tick_size=0.0001,
            tick_value=1.0,
            volume_min=0.01,
            volume_max=10.0,
            volume_step=0.01,
            spread_points=10.0,
            stops_level_points=15.0,
            freeze_level_points=0.0,
            volatility_points=200.0,
        )
        request = PositionSizeRequest(
            account=self.account,
            symbol=micro_symbol,
            policy=self.policy,
            stop_distance_points=50.0,
            capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.PERCENT_EQUITY, value=10.0),
        )
        result = self.engine.compute_position_size(request)

        self.assertTrue(result.accepted)
        self.assertEqual(result.capital_base_cash, 100.0)
        self.assertEqual(result.recommended_minimum_allocation_cash, 100.0)
        self.assertAlmostEqual(result.risk_cash_budget, 1.0)

    def test_tiny_fixed_allocation_is_rejected_by_hard_floor(self) -> None:
        request = PositionSizeRequest(
            account=self.account,
            symbol=self.symbol,
            policy=self.policy,
            stop_distance_points=50.0,
            trading_style=TradingStyle.SCALPING,
            capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.FIXED_CASH, value=10.0),
        )
        result = self.engine.compute_position_size(request)

        self.assertFalse(result.accepted)
        self.assertEqual(result.capital_base_cash, 10.0)
        self.assertEqual(result.recommended_minimum_allocation_cash, 50.0)
        self.assertIn("ditolak", result.rejection_reason)

    def test_warning_contains_recommended_minimum_for_symbol_and_style(self) -> None:
        micro_symbol = SymbolSnapshot(
            name="XAUUSD",
            instrument_class="metal",
            risk_weight=1.3,
            point=0.01,
            tick_size=0.01,
            tick_value=0.1,
            volume_min=0.01,
            volume_max=50.0,
            volume_step=0.01,
            spread_points=25.0,
            stops_level_points=50.0,
            freeze_level_points=10.0,
            volatility_points=500.0,
        )
        request = PositionSizeRequest(
            account=self.account,
            symbol=micro_symbol,
            policy=self.policy,
            stop_distance_points=100.0,
            trading_style=TradingStyle.INTRADAY,
            capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.FIXED_CASH, value=125.0),
        )
        result = self.engine.compute_position_size(request)

        self.assertTrue(result.accepted)
        self.assertEqual(result.recommended_minimum_allocation_cash, 250.0)
        self.assertTrue(any("kurang realistis" in warning for warning in result.warnings))

    def test_price_aware_hard_floor_rejects_underfunded_xauusd(self) -> None:
        xau_symbol = SymbolSnapshot(
            name="XAUUSD",
            instrument_class="metal",
            risk_weight=1.3,
            point=0.01,
            tick_size=0.01,
            tick_value=0.1,
            volume_min=0.01,
            volume_max=50.0,
            volume_step=0.01,
            spread_points=25.0,
            stops_level_points=50.0,
            freeze_level_points=10.0,
            volatility_points=500.0,
            price=4_800.0,
            contract_size=100.0,
            margin_rate=0.005,
        )
        request = PositionSizeRequest(
            account=self.account,
            symbol=xau_symbol,
            policy=self.policy,
            stop_distance_points=100.0,
            trading_style=TradingStyle.SCALPING,
            capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.FIXED_CASH, value=25.0),
        )

        result = self.engine.compute_position_size(request)

        self.assertFalse(result.accepted)
        self.assertEqual(result.recommended_minimum_allocation_cash, 150.0)
        self.assertIn("tidak realistis", result.rejection_reason)

    def test_practical_risk_pressure_can_reject_index_intraday(self) -> None:
        request = PositionSizeRequest(
            account=self.account,
            symbol=SymbolSnapshot(
                name="NAS100",
                instrument_class="index_cfd",
                risk_weight=1.5,
                point=1.0,
                tick_size=1.0,
                tick_value=0.1,
                volume_min=0.1,
                volume_max=100.0,
                volume_step=0.1,
                spread_points=10.0,
                stops_level_points=5.0,
                freeze_level_points=0.0,
                volatility_points=200.0,
            ),
            policy=self.policy,
            stop_distance_points=20.0,
            trading_style=TradingStyle.INTRADAY,
            capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.FIXED_CASH, value=80.0),
        )

        result = self.engine.compute_position_size(request)

        self.assertFalse(result.accepted)
        self.assertEqual(result.recommended_minimum_allocation_cash, 200.0)
        self.assertIn("ditolak", result.rejection_reason)


if __name__ == "__main__":
    unittest.main()
