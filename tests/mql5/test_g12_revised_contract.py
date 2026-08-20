from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

import pytest

from gold_engine_core.rules.revised import RevisedEngineConfig

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TYPES_PATH = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineRevisedTypes.mqh"
INDICATORS_PATH = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineRevisedIndicators.mqh"
CONFIRMATION_PATH = (
    REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineRevisedConfirmation.mqh"
)
CONTEXT_PATH = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineRevisedContext.mqh"


def assignment(source: str, name: str) -> str:
    match = re.search(rf"config\.{re.escape(name)}=([^;]+);", source)
    if match is None:
        raise AssertionError(f"missing MQL5 Revised config field: {name}")
    return match.group(1)


def test_mql5_revised_scalar_defaults_match_python_reference() -> None:
    value = TYPES_PATH.read_text(encoding="utf-8")
    config = RevisedEngineConfig()
    ignored = {"symbol", "psychological_steps", "strong_m5_patterns"}

    for field in fields(config):
        if field.name in ignored:
            continue
        expected = getattr(config, field.name)
        actual = assignment(value, field.name)
        if isinstance(expected, int):
            assert int(actual) == expected
        elif isinstance(expected, float):
            assert float(actual) == pytest.approx(expected, abs=1e-12)
        else:
            raise AssertionError(f"unhandled config field: {field.name}")


def test_revised_contract_preserves_optional_geometry_explicitly() -> None:
    value = TYPES_PATH.read_text(encoding="utf-8")
    for flag in (
        "has_level",
        "has_invalidation",
        "has_entry",
        "has_stop",
        "has_target",
        "has_first_obstacle",
        "has_first_obstacle_r",
    ):
        assert flag in value


def test_mql5_indicators_preserve_python_window_and_smoothing_semantics() -> None:
    value = INDICATORS_PATH.read_text(encoding="utf-8")

    assert "count<period+1" in value
    assert "const int start=count-period" in value
    assert "gain=(gain*(period-1)+up)/period" in value
    assert "loss=(loss*(period-1)+down)/period" in value
    assert "pivot<=bars[index-offset].high" in value
    assert "pivot>=bars[index-offset].low" in value
    assert "MathCeil((value-1.0e-12)/tick)*tick" in value


def test_range_and_m1_confirmation_preserve_reference_thresholds() -> None:
    value = CONFIRMATION_PATH.read_text(encoding="utf-8")

    assert "bars[start].open_time<=trigger" in value
    assert "config.range_max_bars" in value
    assert "config.range_touch_separation_bars" in value
    assert "retreat_since_touch<width*config.range_retreat_fraction" in value
    assert "retreat>=width*0.10" in value
    assert "outside>=config.acceptance_close_count" in value
    assert "latest.close>previous.high" in value
    assert "latest.close<previous.low" in value
    assert "result.rsi7>=50.0" in value
    assert "result.rsi7<=50.0" in value
    assert "stats.excursion>=stats.width*config.range_min_excursion_fraction" in value


def test_momentum_fibonacci_and_hard_invalidation_preserve_reference_rules() -> None:
    value = CONTEXT_PATH.read_text(encoding="utf-8")

    assert "count<config.momentum_bars || atr<=0.0" in value
    assert "stats.displacement_atr>=config.momentum_min_displacement_atr" in value
    assert "body_ratio<0.35" in value
    assert "stats.exhaustion_signals>=config.exhaustion_min_signals" in value
    assert "best_end-best_range*0.618" in value
    assert "best_end-best_range*0.382" in value
    assert "config.fibonacci_retest_separation_bars" in value
    assert "last_touch>=after_count-3" in value
    assert "count-start<config.acceptance_close_count" in value
    assert "outside>=3" in value
    assert "displacement>=atr_m1*config.acceptance_displacement_atr" in value
