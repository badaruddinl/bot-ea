from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze-goldm-revised-stop-paths.py"


def _module():
    spec = importlib.util.spec_from_file_location("goldm_revised_stop_paths", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_path_archetypes_are_not_single_threshold_bucket() -> None:
    module = _module()

    assert module.classify_path(0.3, 2.0) == "SHALLOW_PROFIT_FADE"
    assert module.classify_path(0.8, 2.0) == "MEDIUM_PROFIT_FADE"
    assert module.classify_path(1.2, 3.0) == "ONE_R_PLUS_ROUND_TRIP"
    assert module.classify_path(2.2, 4.0) == "DEEP_RUNNER_FADE"
    assert module.classify_path(1.8, 2.0) == "NEAR_TARGET_REVERSAL"
