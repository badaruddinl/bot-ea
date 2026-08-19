from __future__ import annotations

import importlib.util
from pathlib import Path


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
