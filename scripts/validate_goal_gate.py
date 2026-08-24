from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

PYTHON_GATES: dict[str, tuple[str, ...]] = {
    "validate-unit": ("-m", "not slow", "--ignore=runtime_data"),
    "validate-profile-contracts": (
        "tests/gold_engine_core/test_profile_manifest.py",
        "tests/gold_engine_core/test_profile_sizing_tiers.py",
        "tests/gold_engine_core/test_demo_validation.py",
        "tests/gold_engine_core/test_runtime_validation.py",
    ),
    "validate-causality": ("tests/gold_engine_core/test_causal_replay.py",),
    "validate-replay": (
        "tests/gold_engine_core/test_current_behavior_corpus.py",
        "tests/gold_engine_core/test_causal_replay.py",
    ),
    "validate-incremental": (
        "tests/gold_engine_core/test_bear_incremental.py",
        "tests/gold_engine_core/test_revised_restart.py",
        "tests/gold_engine_core/test_reference_runtime.py",
    ),
    "validate-execution-guards": (
        "tests/gold_engine_core/test_execution.py",
        "tests/mql5/test_g14_execution_guard.py",
        "tests/mql5/test_g14_runtime_execution.py",
    ),
    "validate-python-parity": (
        "tests/gold_engine_core/test_revised_parity_vectors.py",
        "tests/gold_engine_core/test_bear_parity_vectors.py",
        "tests/mql5/test_g15_full_parity.py",
    ),
    "validate-mql5-parity-goldi": (
        "tests/mql5/test_g12_revised_contract.py",
        "tests/mql5/test_g15_full_parity.py",
    ),
    "validate-mql5-parity-goldm": (
        "tests/mql5/test_g13_bear_contract.py",
        "tests/mql5/test_g15_full_parity.py",
    ),
    "validate-cross-profile": (
        "tests/gold_engine_core/test_profile_manifest.py",
        "tests/gold_event_bridge/test_g17_verifier.py",
        "tests/test_verify_g20_unattended_evidence.py",
    ),
    "validate-event-contract": (
        "tests/gold_event_bridge",
        "tests/mql5/test_g16_outbox.py",
    ),
    "validate-e2e": (
        "tests/gold_event_bridge/test_g17_verifier.py",
        "tests/gold_event_bridge/test_g18_verifier.py",
        "tests/test_verify_g20_unattended_evidence.py",
    ),
}

ALL_GATES = (*PYTHON_GATES, "validate-mql5-build", "validate-release")


def command_for(gate: str, repository_root: Path) -> list[str]:
    if gate in PYTHON_GATES:
        return [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *PYTHON_GATES[gate],
            f"--basetemp={repository_root / 'runtime_data' / ('ci-' + gate)}",
        ]
    if gate == "validate-mql5-build":
        metaeditor = os.environ.get(
            "METAEDITOR_PATH", r"C:\Program Files\MetaTrader 5\MetaEditor64.exe"
        )
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repository_root / "scripts/validate-g21-mql5-build.ps1"),
            "-MetaEditorPath",
            metaeditor,
        ]
    if gate == "validate-release":
        return [
            sys.executable,
            str(repository_root / "scripts/verify_g21_release.py"),
            "--release-root",
            str(repository_root / "release"),
            "--output",
            str(repository_root / "runtime_data/ci-validate-release.json"),
        ]
    raise ValueError(f"unknown validation gate: {gate}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one named BOT-EA goal validation gate")
    parser.add_argument("gate", choices=ALL_GATES)
    args = parser.parse_args()
    (REPOSITORY_ROOT / "runtime_data").mkdir(parents=True, exist_ok=True)
    command = command_for(args.gate, REPOSITORY_ROOT)
    completed = subprocess.run(command, cwd=REPOSITORY_ROOT, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
