from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "simulate-goldm-combined-portfolio.py"


def _module():
    spec = importlib.util.spec_from_file_location("goldm_combined_portfolio", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shared_floating_profit_uses_one_market_price_for_both_sides() -> None:
    module = _module()
    buy = {"side": "BUY", "entry": 100.0, "lot": 0.02}
    sell = {"side": "SELL", "entry": 100.0, "lot": 0.02}

    assert module._floating_profit(buy, 101.0, 100.0) == 2.0
    assert module._floating_profit(sell, 99.0, 100.0) == 2.0
    assert (
        module._floating_profit(buy, 101.0, 100.0)
        + module._floating_profit(sell, 101.0, 100.0)
        == 0.0
    )


def test_adaptive_lot_steps_up_and_down_on_realized_balance() -> None:
    module = _module()

    assert module._select_trade_lot(99.99, 100.0, 0.01, 0.02, 0.05) == 0.01
    assert module._select_trade_lot(100.0, 100.0, 0.01, 0.02, 0.05) == 0.02
    assert module._select_trade_lot(95.0, 100.0, 0.01, 0.02, 0.05) == 0.01
    assert module._select_trade_lot(95.0, None, 0.01, 0.02, 0.05) == 0.05


def test_multi_tier_lot_uses_highest_realized_balance_threshold() -> None:
    module = _module()
    tiers = ((0.0, 0.1), (10.0, 0.2), (30.0, 0.5), (50.0, 1.0), (100.0, 2.0))

    assert module._select_trade_lot(9.99, None, 0.01, 0.02, 0.05, tiers) == 0.1
    assert module._select_trade_lot(10.0, None, 0.01, 0.02, 0.05, tiers) == 0.2
    assert module._select_trade_lot(30.0, None, 0.01, 0.02, 0.05, tiers) == 0.5
    assert module._select_trade_lot(50.0, None, 0.01, 0.02, 0.05, tiers) == 1.0
    assert module._select_trade_lot(100.0, None, 0.01, 0.02, 0.05, tiers) == 2.0


def test_dual_tp_outcome_releases_tp1_leg_at_causal_fill_time() -> None:
    module = _module()

    class FakeMt5:
        ORDER_TYPE_BUY = 0
        ORDER_TYPE_SELL = 1

        @staticmethod
        def order_calc_profit(order_type, symbol, lot, entry, exit_price):
            direction = 1.0 if order_type == FakeMt5.ORDER_TYPE_BUY else -1.0
            return direction * (exit_price - entry) * 100.0 * lot

        @staticmethod
        def order_calc_margin(order_type, symbol, lot, entry):
            return entry * 100.0 * lot / 1000.0

    outcome = {
        "opened_at": "2026-08-18T10:00:00+03:00",
        "closed_at": "2026-08-18T10:02:00+03:00",
        "entry": 100.0,
        "stop": 99.0,
        "result": "STOP_AFTER_TP1",
        "outcome_r": 0.1,
        "tp1_r": 0.8,
        "tp1_fraction": 0.5,
        "runner_fraction": 0.5,
        "tp1_taken": True,
        "tp1_taken_at": "2026-08-18T10:01:00+03:00",
    }

    positions = module._positions(
        FakeMt5,
        SimpleNamespace(name="GOLD.i#"),
        outcome,
        side="BUY",
        lot=0.02,
    )

    assert [position["leg"] for position in positions] == ["TP1", "RUNNER"]
    assert [position["lot"] for position in positions] == [0.01, 0.01]
    assert positions[0]["closed_at"].isoformat() == outcome["tp1_taken_at"]
    assert positions[1]["outcome_r"] == pytest.approx(-0.6)
    assert sum(position["profit"] for position in positions) == pytest.approx(0.2)


def test_non_executable_point_zero_one_partial_falls_back_to_full_runner() -> None:
    module = _module()

    class FakeMt5:
        ORDER_TYPE_BUY = 0
        ORDER_TYPE_SELL = 1

        @staticmethod
        def order_calc_profit(order_type, symbol, lot, entry, exit_price):
            return (exit_price - entry) * 100.0 * lot

        @staticmethod
        def order_calc_margin(order_type, symbol, lot, entry):
            return entry * 100.0 * lot / 1000.0

    outcome = {
        "opened_at": "2026-08-18T10:00:00+03:00",
        "closed_at": "2026-08-18T10:02:00+03:00",
        "entry": 100.0,
        "stop": 99.0,
        "result": "STOP_AFTER_TP1",
        "outcome_r": 0.1,
        "tp1_r": 0.8,
        "tp1_fraction": 0.5,
        "runner_fraction": 0.5,
        "tp1_taken": True,
        "tp1_taken_at": "2026-08-18T10:01:00+03:00",
    }

    positions = module._positions(
        FakeMt5,
        SimpleNamespace(name="GOLD.i#", volume_step=0.01),
        outcome,
        side="BUY",
        lot=0.01,
    )

    assert len(positions) == 1
    assert positions[0]["leg"] == "PARTIAL_FALLBACK_FULL_RUNNER"
    assert positions[0]["lot"] == 0.01
    assert positions[0]["outcome_r"] == pytest.approx(-0.6)


def test_goldm_point_one_cannot_split_below_point_one_minimum() -> None:
    module = _module()

    class FakeMt5:
        ORDER_TYPE_BUY = 0
        ORDER_TYPE_SELL = 1

        @staticmethod
        def order_calc_profit(order_type, symbol, lot, entry, exit_price):
            return (exit_price - entry) * lot

        @staticmethod
        def order_calc_margin(order_type, symbol, lot, entry):
            return entry * lot / 1000.0

    outcome = {
        "opened_at": "2026-08-18T10:00:00+03:00",
        "closed_at": "2026-08-18T10:02:00+03:00",
        "entry": 100.0,
        "stop": 99.0,
        "result": "TP2",
        "outcome_r": 1.4,
        "tp1_r": 0.8,
        "tp1_fraction": 0.5,
        "runner_fraction": 0.5,
        "tp1_taken": True,
        "tp1_taken_at": "2026-08-18T10:01:00+03:00",
    }

    positions = module._positions(
        FakeMt5,
        SimpleNamespace(
            name="GOLDm#",
            volume_min=0.1,
            volume_step=0.01,
        ),
        outcome,
        side="BUY",
        lot=0.1,
    )

    assert len(positions) == 1
    assert positions[0]["leg"] == "PARTIAL_FALLBACK_FULL_RUNNER"
    assert positions[0]["lot"] == pytest.approx(0.1)
    assert positions[0]["outcome_r"] == pytest.approx(2.0)


def test_execution_stress_costs_are_split_between_entry_and_exit() -> None:
    module = _module()

    class FakeMt5:
        ORDER_TYPE_BUY = 0
        ORDER_TYPE_SELL = 1

        @staticmethod
        def order_calc_profit(order_type, symbol, lot, entry, exit_price):
            return (exit_price - entry) * lot

        @staticmethod
        def order_calc_margin(order_type, symbol, lot, entry):
            return entry * lot / 1000.0

    position = module._position(
        FakeMt5,
        SimpleNamespace(name="GOLDm#", trade_contract_size=1.0),
        {
            "opened_at": "2026-08-18T10:00:00+03:00",
            "closed_at": "2026-08-18T10:02:00+03:00",
            "entry": 100.0,
            "stop": 99.0,
            "result": "TP2",
            "outcome_r": 2.0,
        },
        side="BUY",
        lot=0.2,
        round_trip_spread_usd=0.3,
        slippage_per_side_usd=0.02,
        commission_per_lot_side_usd=0.1,
    )

    assert position["entry_cost"] == pytest.approx(0.084)
    assert position["exit_cost"] == pytest.approx(0.024)
    assert position["profit"] == pytest.approx(
        position["gross_profit"] - 0.108
    )
