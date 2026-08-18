from __future__ import annotations

import inspect
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from goldm_bear.cli import load_bars, main
from goldm_bear.engine import (
    BearAction,
    BearBar,
    BearEngine,
    BearEngineConfig,
    BearExitAction,
    ShortPosition,
)
from goldm_bear.mt5_source import load_mt5_m15_bars
from goldm_bear.mt5_cli import signal_context, signal_outcome


SERVER_TIME = timezone(timedelta(hours=3))


def _bar(index: int, open_: float, high: float, low: float, close: float) -> BearBar:
    return BearBar(
        time=datetime(2026, 8, 18, 3, 0, tzinfo=SERVER_TIME)
        + timedelta(minutes=15 * index),
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_volume=100 + index,
        spread=0.20,
    )


def image_like_bear_bars(*, rejection: bool = True) -> list[BearBar]:
    bars: list[BearBar] = []
    price = 4434.0
    for index in range(10):
        close = price - 3.4
        bars.append(_bar(index, price, price + 0.8, close - 0.9, close))
        price = close

    range_closes = (
        4399.0,
        4396.0,
        4394.0,
        4392.0,
        4393.0,
        4391.5,
        4393.0,
        4395.0,
        4397.0,
        4399.0,
        4396.0,
        4393.0,
        4391.0,
        4394.0,
        4396.0,
        4393.0,
        4391.0,
        4394.0,
        4392.0,
        4395.0,
        4397.0,
        4399.0,
        4397.5,
    )
    for offset, close in enumerate(range_closes, start=len(bars)):
        open_ = bars[-1].close
        high = max(open_, close) + 0.8
        low = min(open_, close) - 0.8
        if offset == 19:
            high = 4400.0
        if offset in {15, 22, 26}:
            low = 4390.0
        bars.append(_bar(offset, open_, high, low, close))

    index = len(bars)
    if rejection:
        bars.append(_bar(index, 4399.0, 4400.2, 4394.2, 4395.0))
    else:
        bars.append(_bar(index, 4397.5, 4400.0, 4397.0, 4399.4))
    return bars


def broker_failed_breakout_bars() -> list[BearBar]:
    bars = image_like_bear_bars(rejection=False)[:-1]
    context = (
        (4399.39, 4400.14, 4395.14, 4397.11),
        (4397.13, 4399.29, 4397.13, 4398.89),
        (4398.87, 4400.84, 4396.83, 4397.59),
        (4397.55, 4403.39, 4397.43, 4403.05),
        (4403.15, 4403.58, 4396.31, 4401.45),
        (4401.56, 4402.60, 4395.47, 4395.55),
        (4395.88, 4396.11, 4387.95, 4392.62),
        (4392.55, 4393.50, 4386.80, 4389.31),
    )
    for values in context:
        bars.append(_bar(len(bars), *values))
    return bars


class StandaloneBearEngineTests(unittest.TestCase):
    def test_package_does_not_import_production_strategy(self) -> None:
        source = inspect.getsource(__import__("goldm_bear.engine", fromlist=["*"]))
        self.assertNotIn("goldm_signal", source)
        self.assertNotIn("GoldMSniperParity", source)

    def test_mt5_runner_bootstraps_only_the_standalone_package(self) -> None:
        runner = (
            Path(__file__).resolve().parents[1] / "scripts" / "run-goldm-bear-mt5.py"
        ).read_text(encoding="utf-8")
        self.assertIn("from goldm_bear.mt5_cli import main", runner)
        self.assertNotIn("goldm_signal", runner)

    def test_image_like_pullback_rejection_emits_sell(self) -> None:
        decision = BearEngine().evaluate(image_like_bear_bars())

        self.assertEqual(decision.action, BearAction.SELL)
        self.assertIsNotNone(decision.resistance)
        self.assertAlmostEqual(decision.resistance or 0.0, 4400.0, delta=0.25)
        self.assertIsNotNone(decision.take_profit)
        self.assertLess(decision.take_profit or 9999.0, decision.entry or 0.0)
        self.assertGreater(decision.take_profit or 0.0, 4390.0)
        self.assertGreaterEqual(decision.reward_risk or 0.0, 0.70)

    def test_touch_without_rejection_is_watch_not_sell(self) -> None:
        decision = BearEngine().evaluate(image_like_bear_bars(rejection=False))

        self.assertEqual(decision.action, BearAction.WATCH)
        self.assertIn("waiting_rejection", decision.reason)

    def test_broker_failed_breakout_waits_then_sells_confirmation(self) -> None:
        bars = broker_failed_breakout_bars()
        engine = BearEngine(BearEngineConfig(maximum_slope_atr_per_bar=0.0))
        first_rejection = engine.evaluate(bars[:-5])
        confirmed = engine.evaluate(bars[:-2])
        outcome = signal_outcome(confirmed, bars)

        self.assertNotEqual(first_rejection.action, BearAction.SELL)
        self.assertEqual(confirmed.action, BearAction.SELL)
        self.assertIn("continuation_through_near_support", confirmed.reason)
        self.assertAlmostEqual(confirmed.resistance or 0.0, 4400.0, delta=0.01)
        self.assertGreater(confirmed.take_profit or 0.0, 4390.0)
        self.assertLess(confirmed.take_profit or 9999.0, 4391.0)
        self.assertEqual(outcome["first_event"], "TP1")

    def test_psychological_target_is_placed_in_front_of_round_number(self) -> None:
        decision = BearEngine().evaluate(image_like_bear_bars())

        self.assertGreater(decision.take_profit or 0.0, 4390.0)
        self.assertLess(decision.take_profit or 9999.0, 4391.0)
        self.assertIn("target_capped_at_nearest_psychological_support", decision.reason)

    def test_ordinary_pullback_does_not_trigger_early_close(self) -> None:
        engine = BearEngine()
        position = ShortPosition(
            entry=4395.0,
            stop=4405.0,
            take_profit=4390.5,
            structural_resistance=4400.0,
        )
        bars = [
            _bar(0, 4395.0, 4398.0, 4393.0, 4397.0),
            _bar(1, 4397.0, 4399.5, 4395.0, 4398.5),
        ]

        decision = engine.evaluate_exit(position, bars)

        self.assertEqual(decision.action, BearExitAction.HOLD)
        self.assertIn("structure_intact", decision.reason)

    def test_two_closes_above_resistance_invalidate_short(self) -> None:
        engine = BearEngine()
        position = ShortPosition(
            entry=4395.0,
            stop=4405.0,
            take_profit=4390.5,
            structural_resistance=4400.0,
        )
        bars = [
            _bar(0, 4398.0, 4402.0, 4397.0, 4401.0),
            _bar(1, 4401.0, 4403.0, 4400.5, 4402.0),
        ]

        decision = engine.evaluate_exit(position, bars)

        self.assertEqual(decision.action, BearExitAction.INVALIDATED)

    def test_signal_outcome_uses_only_bars_after_signal_close(self) -> None:
        bars = image_like_bear_bars()
        signal = replace(
            BearEngine().evaluate(bars),
            take_profit=4394.0,
            take_profit_2=4390.0,
        )
        future = [
            _bar(len(bars), 4395.0, 4396.0, 4393.8, 4394.2),
            _bar(len(bars) + 1, 4394.2, 4394.5, 4389.8, 4390.2),
        ]

        outcome = signal_outcome(signal, bars + future)

        self.assertEqual(outcome["first_event"], "TP1")
        self.assertEqual(outcome["first_event_time"], future[0].time)
        self.assertEqual(outcome["tp2_time"], future[1].time)
        self.assertGreater(outcome["maximum_favorable_excursion"], 5.0)
        context = signal_context(signal, bars + future)
        self.assertEqual(context[2]["time"], signal.time)

    def test_session_guard_blocks_near_market_open(self) -> None:
        bars = image_like_bear_bars()
        start = datetime(2026, 8, 18, 0, 0, tzinfo=SERVER_TIME)
        shifted = [
            BearBar(
                time=start + timedelta(minutes=index),
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                tick_volume=bar.tick_volume,
                spread=bar.spread,
            )
            for index, bar in enumerate(bars)
        ]

        decision = BearEngine().evaluate(shifted)

        self.assertEqual(decision.action, BearAction.WAIT)
        self.assertEqual(decision.reason, "outside_trade_session")

    def test_cli_loads_naive_server_timestamps_and_emits_json(self) -> None:
        bars = image_like_bear_bars()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bars.csv"
            lines = ["time,open,high,low,close,tick_volume,spread"]
            lines.extend(
                f"{bar.time.replace(tzinfo=None).isoformat()},{bar.open},{bar.high},"
                f"{bar.low},{bar.close},{bar.tick_volume},{bar.spread}"
                for bar in bars
            )
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            loaded = load_bars(path, server_timezone=SERVER_TIME)
            exit_code = main([str(path), "--server-utc-offset", "+03:00"])

        self.assertEqual(loaded[-1].time.utcoffset(), timedelta(hours=3))
        self.assertEqual(exit_code, 0)

    def test_invalid_bar_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "contain open and close"):
            BearBar(
                time=datetime.now(tz=SERVER_TIME),
                open=4400.0,
                high=4399.0,
                low=4390.0,
                close=4395.0,
            )

    def test_mt5_source_is_read_only_and_converts_utc_to_server_time(self) -> None:
        class FakeMt5:
            TIMEFRAME_M15 = 15

            def __init__(self) -> None:
                self.shutdown_called = False
                self.range = None

            def initialize(self) -> bool:
                return True

            def shutdown(self) -> None:
                self.shutdown_called = True

            def last_error(self) -> tuple[int, str]:
                return (0, "ok")

            def symbol_select(self, symbol: str, selected: bool) -> bool:
                return symbol == "GOLD.i#" and selected

            def symbol_info(self, symbol: str) -> SimpleNamespace:
                return SimpleNamespace(point=0.01)

            def copy_rates_range(self, symbol, timeframe, start, end):
                self.range = (symbol, timeframe, start, end)
                return [
                    {
                        "time": int(
                            datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc).timestamp()
                        ),
                        "open": 4400.0,
                        "high": 4401.0,
                        "low": 4398.0,
                        "close": 4399.0,
                        "tick_volume": 100,
                        "spread": 20,
                    }
                ]

        fake = FakeMt5()
        bars = load_mt5_m15_bars(
            symbol="GOLD.i#",
            start=datetime(2026, 8, 18, 3, 0, tzinfo=SERVER_TIME),
            end=datetime(2026, 8, 18, 3, 15, tzinfo=SERVER_TIME),
            server_timezone=SERVER_TIME,
            mt5_module=fake,
        )

        self.assertTrue(fake.shutdown_called)
        self.assertEqual(fake.range[2].hour, 0)
        self.assertEqual(bars[0].time.hour, 3)
        self.assertAlmostEqual(bars[0].spread, 0.20)

    def test_configuration_rejects_too_short_structure_window(self) -> None:
        with self.assertRaisesRegex(ValueError, "regime_lookback"):
            BearEngineConfig(atr_period=14, regime_lookback=10)


if __name__ == "__main__":
    unittest.main()
