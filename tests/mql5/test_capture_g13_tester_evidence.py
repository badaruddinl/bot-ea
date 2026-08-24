from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "capture_g13_tester_evidence.py"
SPEC = importlib.util.spec_from_file_location("capture_g13_tester_evidence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _log(*, passed: bool = True) -> str:
    value = "true" if passed else "false"
    return (
        "AA\tTester\tGOLDm#,M15 (XMGlobal-MT5 14): testing of "
        "Experts\\bot-ea\\GoldEngineBearParityHarness.ex5 from x\n"
        "AA\tCore 1\tGOLDm#,M15: testing of "
        "Experts\\bot-ea\\GoldEngineBearParityHarness.ex5 from x started\n"
        f"AA\tCore 1\tG13_BEAR_PARITY profile=GOLDm# passed={value} "
        "h1_m5_m1=true incremental=true m15=true h1_reject=true "
        "m5_acceptance=true restart_expiry=true persistence=true\n"
        "AA\tCore 1\tfinal balance 100.00 USD\n"
        "AA\tCore 1\tOnTester result 1\n"
        "AA\tCore 1\tGOLDm#,M15: 1 ticks, 1 bars generated.\n"
        "AA\tCore 1\tconnection closed\n"
    )


def test_capture_writes_bounded_hashed_g13_proof(tmp_path: Path) -> None:
    source = tmp_path / "tester.log"
    source.write_text(_log(), encoding="utf-8")
    output = tmp_path / "evidence"

    metadata = MODULE.write_evidence(
        source=source,
        output_directory=output,
        profile_id="GOLDM",
        symbol="GOLDm#",
        timeframe="M15",
        server="XMGlobal-MT5 14",
    )

    raw = (output / "goldm-bear-strategy-tester.log").read_bytes()
    checksum = (output / "goldm-bear-strategy-tester.sha256").read_text(encoding="ascii").split()
    stored = json.loads((output / "goldm-bear-strategy-tester.json").read_text(encoding="utf-8"))
    assert checksum == [hashlib.sha256(raw).hexdigest(), "goldm-bear-strategy-tester.log"]
    assert stored == metadata
    assert metadata["real_order_authority"] == "DISABLED"


@pytest.mark.parametrize("text", (_log(passed=False), "unrelated\n"))
def test_capture_rejects_failed_or_missing_g13_run(text: str) -> None:
    with pytest.raises(MODULE.EvidenceError):
        block = MODULE.capture_block(
            text,
            symbol="GOLDm#",
            timeframe="M15",
            server="XMGlobal-MT5 14",
        )
        MODULE.validate_block(
            block,
            symbol="GOLDm#",
            timeframe="M15",
            server="XMGlobal-MT5 14",
        )
