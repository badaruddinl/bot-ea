from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/verify_g18_evidence.py"
SPEC = importlib.util.spec_from_file_location("verify_g18_evidence", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_current_gate_stays_open_without_windows_reboot_evidence(tmp_path: Path) -> None:
    native = tmp_path / "evidence/G18-failure-restart-e2e/native"
    native.mkdir(parents=True)
    # The verifier must fail on the first missing required source rather than
    # synthesize or downgrade restart evidence.
    with pytest.raises(MODULE.G18VerificationError, match=r"dependency-lab\.json"):
        MODULE.build_report(tmp_path)


def test_reboot_and_dual_terminal_sources_are_unconditionally_required() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'native / "windows-restart.json"' in source
    assert 'native / "dual-terminal-restart.json"' in source
    assert 'get("boot_id_changed") is True' in source
    assert 'get("both_profiles_recovered") is True' in source
    assert 'get("one_profile_restart_isolated") is True' in source
    assert "production_real_orders" in source
