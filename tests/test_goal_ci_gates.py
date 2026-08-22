from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _load_runner() -> ModuleType:
    path = ROOT / "scripts/validate_goal_gate.py"
    spec = importlib.util.spec_from_file_location("validate_goal_gate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_named_gate_runner_covers_required_commands() -> None:
    module = _load_runner()
    expected = {
        "validate-unit",
        "validate-profile-contracts",
        "validate-causality",
        "validate-replay",
        "validate-incremental",
        "validate-execution-guards",
        "validate-python-parity",
        "validate-mql5-build",
        "validate-mql5-parity-goldi",
        "validate-mql5-parity-goldm",
        "validate-cross-profile",
        "validate-event-contract",
        "validate-e2e",
        "validate-release",
    }
    assert set(module.ALL_GATES) == expected
    for gate in expected:
        assert module.command_for(gate, ROOT)


def test_release_workflow_depends_on_python_and_actual_mql5_gates() -> None:
    workflow = (ROOT / ".github/workflows/dual-profile-release.yml").read_text(encoding="utf-8")
    for gate in _load_runner().PYTHON_GATES:
        assert f"- {gate}" in workflow
    assert "needs: [python-gates, validate-mql5-build]" in workflow
    assert "runs-on: [self-hosted, Windows, X64, goldm-mt5]" in workflow


def test_mql5_build_script_compiles_both_profiles_and_requires_clean_logs() -> None:
    source = (ROOT / "scripts/validate-g21-mql5-build.ps1").read_text(encoding="utf-8")
    assert "GoldEngine-GOLDi.mq5" in source
    assert "GoldEngine-GOLDm.mq5" in source
    assert "0 errors, 0 warnings" in source
    assert "production_real_orders=DISABLED" in source
