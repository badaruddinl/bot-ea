from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

import pytest

from gold_engine_core.rules.revised import RevisedEngineConfig

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TYPES_PATH = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineRevisedTypes.mqh"
INDICATORS_PATH = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineRevisedIndicators.mqh"


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
