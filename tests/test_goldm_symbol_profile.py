from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldm_signal.config import gold_i_profile
from goldm_signal.mt5.symbol_spec import RuntimeSymbolSpec, check_symbol_spec


class GoldMSymbolProfileTests(unittest.TestCase):
    def test_gold_i_profile_preserves_supplied_broker_facts(self) -> None:
        profile = gold_i_profile()

        self.assertEqual(profile.symbol, "GOLD.i#")
        self.assertEqual(profile.contract_size_oz, 100.0)
        self.assertEqual(profile.volume_min, 0.01)
        self.assertEqual(profile.volume_max, 50.0)
        self.assertEqual(profile.price_increment, 0.01)
        self.assertEqual(profile.stops_level_points, 0.0)
        self.assertEqual(profile.leverage, 1000)
        self.assertIsNone(profile.server_timezone)
        self.assertIsNone(profile.volume_step)

    def test_runtime_spec_is_checked_without_inventing_volume_step(self) -> None:
        runtime = RuntimeSymbolSpec(
            symbol="GOLD.i#",
            point=0.01,
            tick_size=0.01,
            contract_size=100.0,
            volume_min=0.01,
            volume_max=50.0,
            volume_step=0.01,
            stops_level_points=0.0,
            profit_currency="USD",
            margin_currency="USD",
        )

        result = check_symbol_spec(gold_i_profile(), runtime)

        self.assertTrue(result.passed)
        self.assertEqual(result.errors, [])
        self.assertIn("volume_step learned from MT5 at runtime: 0.01", result.warnings)

    def test_runtime_mismatch_is_a_hard_failure(self) -> None:
        runtime = RuntimeSymbolSpec(
            symbol="GOLD",
            point=0.01,
            tick_size=0.1,
            contract_size=100.0,
            volume_min=0.1,
            volume_max=50.0,
            volume_step=0.1,
            stops_level_points=0.0,
            profit_currency="USD",
            margin_currency="USD",
        )

        result = check_symbol_spec(gold_i_profile(), runtime)

        self.assertFalse(result.passed)
        self.assertTrue(any("symbol mismatch" in error for error in result.errors))
        self.assertTrue(any("tick_size mismatch" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
