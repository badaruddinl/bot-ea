from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay-goldm-revised-management.py"


def _module():
    spec = importlib.util.spec_from_file_location("goldm_revised_management", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_management_requires_persistent_evidence_not_one_signal() -> None:
    module = _module()
    evidence = {
        "micro_break": True,
        "momentum": True,
        "acceptance": False,
        "m5_persistence": False,
    }

    assert module.management_reason(
        policy="CONSERVATIVE",
        peak_r=1.2,
        obstacle_touched=True,
        near_target=False,
        bars_since_peak=3,
        evidence=evidence,
    ) is None


def test_obstacle_aware_near_target_can_exit_on_confirmed_momentum() -> None:
    module = _module()
    evidence = {
        "micro_break": True,
        "momentum": True,
        "acceptance": False,
        "m5_persistence": False,
    }

    assert module.management_reason(
        policy="OBSTACLE_AWARE",
        peak_r=2.0,
        obstacle_touched=True,
        near_target=True,
        bars_since_peak=3,
        evidence=evidence,
    ) == "NEAR_TARGET_MOMENTUM_REVERSAL"


def test_typed_state_separates_fast_fade_from_runner() -> None:
    module = _module()
    evidence = {
        "micro_break": True,
        "momentum": True,
        "acceptance": True,
        "m5_persistence": False,
    }

    assert module.management_reason(
        policy="TYPED_STATE",
        peak_r=0.8,
        obstacle_touched=False,
        near_target=False,
        bars_since_peak=4,
        evidence=evidence,
    ) == "FAST_FADE_INVALIDATION"
