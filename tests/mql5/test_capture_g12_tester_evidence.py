from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "capture_g12_tester_evidence.py"
SPEC = importlib.util.spec_from_file_location("capture_g12_tester_evidence", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _tester_log(*, passed: bool = True, complete: bool = True) -> str:
    value = "true" if passed else "false"
    tail = (
        "AA\t0\t07:54:16.511\tCore 1\tfinal balance 100.00 USD\n"
        "AA\t0\t07:54:16.511\tCore 1\tOnTester result 1\n"
        "AA\t0\t07:54:16.511\tCore 1\tGOLDm#,M15: 1 ticks, 1 bars generated.\n"
        if complete
        else ""
    )
    return (
        "old unrelated run\n"
        "AA\t0\t07:54:16.511\tCore 1\tGOLDm#,M15: testing of "
        "Experts\\bot-ea\\GoldEngineRevisedParityHarness.ex5 from x started\n"
        "AA\t0\t07:54:16.511\tCore 1\tG12_REVISED_PARITY profile=GOLDm# "
        f"passed={value} range=true sell_range=true no_setup=true obstacle=true momentum=true "
        "setup=true reinforcement_restart=true consume_restart=true expiry_restart=true "
        "opposite_restart=true\n"
        f"{tail}"
        "AA\t0\t07:54:16.545\tCore 1\tconnection closed\n"
    )


def test_capture_writes_bounded_hashed_proof(tmp_path: Path) -> None:
    source = tmp_path / "tester.log"
    source.write_text(_tester_log(), encoding="utf-8")
    output = tmp_path / "evidence"

    metadata = MODULE.write_evidence(
        source=source,
        output_directory=output,
        profile_id="GOLDM",
        symbol="GOLDm#",
        timeframe="M15",
    )

    raw = (output / "goldm-strategy-tester.log").read_bytes()
    checksum = (output / "goldm-strategy-tester.sha256").read_text(encoding="ascii").split()
    stored = json.loads((output / "goldm-strategy-tester.json").read_text(encoding="utf-8"))
    assert checksum == [hashlib.sha256(raw).hexdigest(), "goldm-strategy-tester.log"]
    assert b"old unrelated run" not in raw
    assert stored == metadata
    assert metadata["real_order_authority"] == "DISABLED"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (_tester_log(passed=False), "incomplete"),
        (_tester_log(complete=False), "incomplete"),
        ("unrelated\n", "start marker"),
    ],
)
def test_capture_rejects_incomplete_or_failed_native_run(
    text: str,
    message: str,
) -> None:
    with pytest.raises(MODULE.EvidenceError, match=message):
        block = MODULE.capture_block(text, symbol="GOLDm#", timeframe="M15")
        MODULE.validate_block(block, symbol="GOLDm#", timeframe="M15")
