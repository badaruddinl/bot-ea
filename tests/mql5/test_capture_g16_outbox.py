from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/capture_g16_outbox_evidence.py"
SPEC = importlib.util.spec_from_file_location("capture_g16_outbox_evidence", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def log(*, passed: bool = True) -> str:
    status = "true" if passed else "false"
    return (
        "AA GOLD.i#,M15 (XMGlobal-MT5 5): generating based on real ticks\n"
        "AA GOLD.i#,M15: testing of Experts\\bot-ea\\GoldEngineOutboxHarness.ex5 "
        "from x started\n"
        f"AA G16_OUTBOX passed={status} goldi_append=true goldm_append=true "
        "goldi_audience=goldi_approved goldm_audience=admin_only "
        "order_authority=DISABLED\n"
        "AA final balance 100.00 USD\n"
        "AA OnTester result 1\n"
        "AA connection closed\n"
    )


def test_capture_writes_hash_locked_outbox_proof(tmp_path: Path) -> None:
    source = tmp_path / "tester.log"
    source.write_text(log(), encoding="utf-8")
    output = tmp_path / "evidence"

    metadata = MODULE.write_evidence(source, output, symbol="GOLD.i#", server="XMGlobal-MT5 5")

    assert metadata["order_authority"] == "DISABLED"
    assert (output / "goldi-outbox-tester.log").is_file()
    assert (output / "goldi-outbox-tester.sha256").is_file()


@pytest.mark.parametrize(
    "value",
    (
        log(passed=False),
        log().replace("AA connection closed", "AA deal performed\nAA connection closed"),
    ),
)
def test_capture_rejects_failure_or_mutation(value: str) -> None:
    block = MODULE.capture(value, symbol="GOLD.i#", server="XMGlobal-MT5 5")
    with pytest.raises(MODULE.EvidenceError):
        MODULE.validate(block)
