from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay-goldm-dual-tp.py"


def test_dual_tp_module_loads_and_declares_split_policies() -> None:
    spec = importlib.util.spec_from_file_location("goldm_dual_tp", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert "SPLIT_KEEP_STOP" in module.POLICIES
    assert "SPLIT_BE_AFTER_TP1" in module.POLICIES
    assert "ADAPTIVE_ENGINE" in module.POLICIES
    assert "FULL_TP2_BE_AFTER_TP1" in module.POLICIES
    assert "ENGINE_BE_AFTER_TP1" in module.POLICIES
    assert "ENGINE_PARTIAL_BE" in module.POLICIES
    assert "ENGINE_PARTIAL_KEEP_STOP" in module.POLICIES
    assert "SPLIT_PROFIT_LOCK_AFTER_TP1" in module.POLICIES
    assert "ENGINE_PARTIAL_PROFIT_LOCK" in module.POLICIES


def test_adaptive_allocation_uses_only_broker_executable_fractions() -> None:
    spec = importlib.util.spec_from_file_location("goldm_dual_tp", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fraction = module.adaptive_runner_fraction(
        "BUY",
        {
            "execution_first_obstacle_r": 1.5,
            "confirmation_mode": "MOMENTUM",
            "m5_pattern": "BULL_ENGULFING",
            "market_regime": {"h1_trend_atr": 2.5, "m5_atr_expansion": 1.2},
            "retest_count": 2,
        },
        1.0,
        2.0,
    )
    assert fraction in {0.0, 0.5, 1.0}


def test_engine_bep_distinguishes_range_from_momentum_buy() -> None:
    spec = importlib.util.spec_from_file_location("goldm_dual_tp", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    base = {"execution_first_obstacle_r": 1.1}
    assert module.engine_should_move_be(
        "BUY", {**base, "confirmation_mode": "RANGE"}, 0.8, 2.0
    )
    assert not module.engine_should_move_be(
        "BUY", {**base, "confirmation_mode": "MOMENTUM"}, 0.8, 2.0
    )


def test_engine_partial_be_only_moves_split_runner_to_break_even() -> None:
    spec = importlib.util.spec_from_file_location("goldm_dual_tp", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    evidence = {"confirmation_mode": "RANGE", "execution_first_obstacle_r": 1.2}
    assert module.policy_moves_be_after_tp1(
        "ENGINE_PARTIAL_BE", "BUY", evidence, 0.7, 2.5, 0.5
    )
    assert not module.policy_moves_be_after_tp1(
        "ENGINE_PARTIAL_BE", "BUY", evidence, 0.7, 2.5, 1.0
    )
    assert not module.policy_moves_be_after_tp1(
        "ENGINE_PARTIAL_BE", "BUY", evidence, 0.7, 2.5, 0.0
    )


def test_engine_partial_allocation_is_narrow_and_side_specific() -> None:
    spec = importlib.util.spec_from_file_location("goldm_dual_tp", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    range_evidence = {
        "confirmation_mode": "RANGE",
        "entry": 100.0,
        "stop": 99.5,
        "market_regime": {"m5_atr": 1.0},
    }
    assert module.engine_partial_runner_fraction(
        "BUY", range_evidence, 0.8, 2.0
    ) == 0.5
    assert module.engine_partial_runner_fraction(
        "BUY", {"confirmation_mode": "MOMENTUM"}, 0.8, 2.0
    ) == 1.0
    assert module.engine_partial_runner_fraction(
        "BUY", range_evidence, 1.0, 2.5
    ) == 1.0
    assert module.engine_partial_runner_fraction(
        "SELL", range_evidence, 0.8, 2.0
    ) == 1.0
    assert module.engine_partial_runner_fraction(
        "BUY",
        {**range_evidence, "stop": 98.5},
        0.8,
        2.0,
    ) == 1.0


def test_profit_lock_keeps_part_of_realized_tp1_profit() -> None:
    spec = importlib.util.spec_from_file_location("goldm_dual_tp", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    stop_r = module.profit_lock_runner_stop_r(0.8, 0.5, 0.5)
    basket_floor_r = 0.5 * 0.8 + 0.5 * stop_r

    assert stop_r == pytest.approx(-0.6)
    assert basket_floor_r == pytest.approx(0.1)


def test_profit_lock_never_widens_the_original_stop() -> None:
    spec = importlib.util.spec_from_file_location("goldm_dual_tp", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.profit_lock_runner_stop_r(2.0, 0.5, 0.5) == -1.0


def test_engine_partial_tp1_uses_structural_price_not_tp2_midpoint() -> None:
    spec = importlib.util.spec_from_file_location("goldm_dual_tp", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    opened_at = datetime(2026, 8, 18, 10, 0)
    report = {
        "from_time": opened_at.isoformat(),
        "to_time": (opened_at + timedelta(minutes=4)).isoformat(),
        "outcomes": [
            {
                "opened_at": opened_at.isoformat(),
                "entry": 100.0,
                "stop": 99.0,
                "first_obstacle": 100.8,
                "target": 102.5,
                "execution_first_obstacle_r": 1.2,
                "confirmation_mode": "RANGE",
                "retest_count": 2,
                "market_regime": {"m5_atr": 2.0},
            }
        ],
    }
    bars = [
        SimpleNamespace(
            time=opened_at,
            high=100.8,
            low=99.8,
            close=100.6,
        ),
        SimpleNamespace(
            time=opened_at + timedelta(minutes=1),
            high=100.7,
            low=100.0,
            close=100.1,
        ),
    ]

    replayed = module.replay_policy(
        report,
        bars,
        [bar.time for bar in bars],
        side="BUY",
        tp1_field="first_obstacle",
        tp2_field="target",
        policy="ENGINE_PARTIAL_BE",
    )

    outcome = replayed["outcomes"][0]
    assert outcome["tp1"] == 100.8
    assert outcome["tp1"] != (outcome["entry"] + outcome["tp2"]) / 2
    assert outcome["tp1_fraction"] == 0.5
    assert outcome["runner_fraction"] == 0.5
    assert outcome["partial_close_taken"]
    assert outcome["result"] == "STOP_AFTER_TP1"
    assert outcome["outcome_r"] == pytest.approx(0.4)


def test_profit_lock_applies_on_next_bar_and_preserves_basket_profit() -> None:
    spec = importlib.util.spec_from_file_location("goldm_dual_tp", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    opened_at = datetime(2026, 8, 18, 10, 0)
    report = {
        "from_time": opened_at.isoformat(),
        "to_time": (opened_at + timedelta(minutes=4)).isoformat(),
        "outcomes": [
            {
                "opened_at": opened_at.isoformat(),
                "entry": 100.0,
                "stop": 99.0,
                "structural_tp1": 100.8,
                "target": 102.5,
            }
        ],
    }
    bars = [
        SimpleNamespace(time=opened_at, high=100.8, low=99.8, close=100.6),
        SimpleNamespace(
            time=opened_at + timedelta(minutes=1),
            high=100.7,
            low=99.4,
            close=99.5,
        ),
    ]

    replayed = module.replay_policy(
        report,
        bars,
        [bar.time for bar in bars],
        side="BUY",
        tp1_field="structural_tp1",
        tp2_field="target",
        policy="SPLIT_PROFIT_LOCK_AFTER_TP1",
    )

    outcome = replayed["outcomes"][0]
    assert outcome["partial_close_taken"]
    assert outcome["tp1_taken_at"] == "2026-08-18T10:01:00"
    assert outcome["profit_lock_enabled"]
    assert outcome["runner_stop_after_tp1_r"] == pytest.approx(-0.6)
    assert outcome["locked_basket_profit_r"] == pytest.approx(0.1)
    assert outcome["result"] == "STOP_AFTER_TP1"
    assert outcome["outcome_r"] == pytest.approx(0.1)


def test_profit_lock_is_symmetric_for_sell_runner() -> None:
    spec = importlib.util.spec_from_file_location("goldm_dual_tp", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    opened_at = datetime(2026, 8, 18, 10, 0)
    report = {
        "from_time": opened_at.isoformat(),
        "to_time": (opened_at + timedelta(minutes=4)).isoformat(),
        "outcomes": [
            {
                "opened_at": opened_at.isoformat(),
                "entry": 100.0,
                "stop": 101.0,
                "structural_tp1": 99.2,
                "target": 97.5,
            }
        ],
    }
    bars = [
        SimpleNamespace(time=opened_at, high=100.2, low=99.2, close=99.4),
        SimpleNamespace(
            time=opened_at + timedelta(minutes=1),
            high=100.6,
            low=99.3,
            close=100.5,
        ),
    ]

    replayed = module.replay_policy(
        report,
        bars,
        [bar.time for bar in bars],
        side="SELL",
        tp1_field="structural_tp1",
        tp2_field="target",
        policy="SPLIT_PROFIT_LOCK_AFTER_TP1",
    )

    outcome = replayed["outcomes"][0]
    assert outcome["runner_stop_after_tp1_r"] == pytest.approx(-0.6)
    assert outcome["locked_basket_profit_r"] == pytest.approx(0.1)
    assert outcome["result"] == "STOP_AFTER_TP1"
    assert outcome["outcome_r"] == pytest.approx(0.1)
