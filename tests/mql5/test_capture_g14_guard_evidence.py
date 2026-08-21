from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "capture_g14_guard_evidence.py"
SPEC = importlib.util.spec_from_file_location("capture_g14_guard_evidence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def log(*, passed: bool = True) -> str:
    status = "true" if passed else "false"
    return (
        "AA\tTester\tGOLD.i#,M15 (XMGlobal-MT5 5): generating based on real ticks\n"
        "AA\tCore 1\tGOLD.i#,M15: testing of "
        "Experts\\bot-ea\\GoldEngineExecutionGuardHarness.ex5 from x started\n"
        f"AA\tCore 1\tG14_EXECUTION_GUARD passed={status} goldi=true goldm=true "
        "structural_geometry=true reasons=18 order_authority=DISABLED\n"
        "AA\tCore 1\tfinal balance 100.00 USD\n"
        "AA\tCore 1\tOnTester result 1\n"
        "AA\tCore 1\tconnection closed\n"
    )


def test_capture_writes_bounded_hashed_guard_proof(tmp_path: Path) -> None:
    source = tmp_path / "tester.log"
    source.write_text(log(), encoding="utf-8")
    output = tmp_path / "evidence"
    metadata = MODULE.write_evidence(
        source=source,
        output_directory=output,
        symbol="GOLD.i#",
        timeframe="M15",
        server="XMGlobal-MT5 5",
    )
    raw = (output / "goldi-execution-guard-tester.log").read_bytes()
    checksum = (output / "goldi-execution-guard-tester.sha256").read_text().split()
    stored = json.loads((output / "goldi-execution-guard-tester.json").read_text(encoding="utf-8"))
    assert checksum == [hashlib.sha256(raw).hexdigest(), "goldi-execution-guard-tester.log"]
    assert metadata == stored
    assert metadata["order_authority"] == "DISABLED"


@pytest.mark.parametrize("text", (log(passed=False), "unrelated\n"))
def test_capture_rejects_failed_or_missing_guard_run(text: str) -> None:
    with pytest.raises(MODULE.EvidenceError):
        block = MODULE.capture_block(
            text, symbol="GOLD.i#", timeframe="M15", server="XMGlobal-MT5 5"
        )
        MODULE.validate_block(block, symbol="GOLD.i#", timeframe="M15", server="XMGlobal-MT5 5")
