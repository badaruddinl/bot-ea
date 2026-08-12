from __future__ import annotations

import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldm_signal.mt5 import ReadOnlyMT5Client, Timeframe


class FakeMT5:
    TIMEFRAME_M15 = 15

    def __init__(self) -> None:
        self.copy_args: tuple[object, ...] | None = None
        self.shutdown_called = False

    def initialize(self, **kwargs: object) -> bool:
        return True

    def shutdown(self) -> None:
        self.shutdown_called = True

    def last_error(self) -> tuple[int, str]:
        return (0, "ok")

    def symbol_info(self, symbol: str) -> SimpleNamespace:
        return SimpleNamespace(name=symbol, visible=True)

    def copy_rates_from_pos(self, *args: object) -> list[dict[str, float]]:
        self.copy_args = args
        return [
            {
                "time": 1_700_000_000,
                "open": 2300.0,
                "high": 2302.0,
                "low": 2299.0,
                "close": 2301.5,
                "tick_volume": 120,
                "spread": 20,
                "real_volume": 0,
            }
        ]


class ReadOnlyMT5ClientTests(unittest.TestCase):
    def test_requests_closed_bars_starting_at_position_one(self) -> None:
        fake = FakeMT5()
        client = ReadOnlyMT5Client(mt5_module=fake)

        bars = client.copy_closed_bars("GOLD.i#", Timeframe.M15, 50)

        self.assertEqual(fake.copy_args, ("GOLD.i#", 15, 1, 50))
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].close, 2301.5)
        self.assertFalse(hasattr(client, "send_order"))


if __name__ == "__main__":
    unittest.main()
