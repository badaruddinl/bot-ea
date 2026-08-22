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


def log(*, passed: bool = True, proof: str = "guard") -> str:
    status = "true" if passed else "false"
    if proof in {"lifecycle_goldi", "lifecycle_goldm"}:
        is_goldm = proof == "lifecycle_goldm"
        expert = (
            "GoldEngineExecutionLifecycleGoldmHarness.ex5"
            if is_goldm
            else "GoldEngineExecutionLifecycleHarness.ex5"
        )
        magic = "26081912" if is_goldm else "26081911"
        marker = (
            f"G14_EXECUTION_LIFECYCLE passed={status} initialized=true opened=true "
            "discovered=true modified=true restarted=true closed=true "
            "positions_before=0 positions_after=0 open_retcode=10009 "
            "reject_mask=0 submit_reason=ORDER_SENT modify_retcode=10009 "
            f"close_retcode=10009 magic={magic} order_authority=TESTER_ONLY "
            "reason=POSITION_CLOSED"
        )
    elif proof == "position":
        expert = "GoldEnginePositionPersistenceHarness.ex5"
        marker = (
            f"G14_POSITION_PERSISTENCE passed={status} missing=true saved=true "
            "loaded=true geometry=true manual=true restart_fallback=true cleared=true "
            "reason=POSITION_STOP_CHANGED order_authority=DISABLED"
        )
    elif proof == "lifecycle":
        expert = "GoldEngineExecutionLifecycleHarness.ex5"
        marker = (
            f"G14_EXECUTION_LIFECYCLE passed={status} initialized=true opened=true "
            "discovered=true modified=true restarted=true closed=true "
            "positions_before=0 positions_after=0 open_retcode=10009 "
            "modify_retcode=10009 close_retcode=10009 magic=26081911 "
            "order_authority=TESTER_ONLY reason=POSITION_CLOSED"
        )
    elif proof == "disabled":
        expert = "GoldEngineExecutionDisabledHarness.ex5"
        marker = (
            f"G14_EXECUTION_DISABLED passed={status} initialized=true submitted=false "
            "validation=true positions_before=0 positions_after=0 retcode=0 "
            "order_authority=DISABLED reason=ORDER_AUTHORITY_DISABLED"
        )
    elif proof == "broker":
        expert = "GoldEngineBrokerContextHarness.ex5"
        marker = (
            f"G14_BROKER_CONTEXT passed={status} collected=true validated=true "
            "order_check=true retcode=0 filling=ORDER_FILLING_IOC margin=8.75 "
            "positions=0 order_authority=DISABLED reason=OK"
        )
    else:
        expert = "GoldEngineExecutionGuardHarness.ex5"
        marker = (
            f"G14_EXECUTION_GUARD passed={status} goldi=true goldm=true "
            "structural_geometry=true reasons=18 order_authority=DISABLED"
        )
    return (
        "AA\tTester\tGOLD.i#,M15 (XMGlobal-MT5 5): generating based on real ticks\n"
        "AA\tCore 1\tGOLD.i#,M15: testing of "
        f"Experts\\bot-ea\\{expert} from x started\n"
        f"AA\tCore 1\t{marker}\n"
        f"AA\tCore 1\tfinal balance {'99.62' if proof == 'lifecycle' else '100.00'} USD\n"
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
    assert metadata["proof"] == "guard"


def test_capture_supports_actual_broker_context_proof(tmp_path: Path) -> None:
    source = tmp_path / "tester.log"
    source.write_text(log(proof="broker"), encoding="utf-8")
    output = tmp_path / "evidence"
    metadata = MODULE.write_evidence(
        source=source,
        output_directory=output,
        symbol="GOLD.i#",
        timeframe="M15",
        server="XMGlobal-MT5 5",
        proof="broker",
    )
    assert metadata["proof"] == "broker"
    assert (output / "goldi-broker-context-tester.log").is_file()


def test_capture_supports_disabled_authority_proof(tmp_path: Path) -> None:
    source = tmp_path / "tester.log"
    source.write_text(log(proof="disabled"), encoding="utf-8")
    output = tmp_path / "evidence"
    metadata = MODULE.write_evidence(
        source=source,
        output_directory=output,
        symbol="GOLD.i#",
        timeframe="M15",
        server="XMGlobal-MT5 5",
        proof="disabled",
    )
    assert metadata["proof"] == "disabled"
    assert (output / "goldi-execution-disabled-tester.log").is_file()


def test_capture_supports_tester_only_lifecycle_mutations(tmp_path: Path) -> None:
    source = tmp_path / "tester.log"
    source.write_text(log(proof="lifecycle") + "AA\tCore 1\tdeal performed\n", encoding="utf-8")
    output = tmp_path / "evidence"
    metadata = MODULE.write_evidence(
        source=source,
        output_directory=output,
        symbol="GOLD.i#",
        timeframe="M15",
        server="XMGlobal-MT5 5",
        proof="lifecycle",
    )
    assert metadata["proof"] == "lifecycle"
    assert metadata["order_authority"] == "TESTER_ONLY"
    assert metadata["profile_matrix"] == ["GOLDI"]


def test_capture_supports_position_restart_proof(tmp_path: Path) -> None:
    source = tmp_path / "tester.log"
    source.write_text(log(proof="position"), encoding="utf-8")
    output = tmp_path / "evidence"
    metadata = MODULE.write_evidence(
        source=source,
        output_directory=output,
        symbol="GOLD.i#",
        timeframe="M15",
        server="XMGlobal-MT5 5",
        proof="position",
    )
    assert metadata["proof"] == "position"
    assert metadata["order_authority"] == "DISABLED"
    assert metadata["profile_matrix"] == ["GOLDI", "GOLDM"]


def test_capture_supports_goldm_tester_only_lifecycle(tmp_path: Path) -> None:
    source = tmp_path / "tester.log"
    source.write_text(
        log(proof="lifecycle_goldm")
        .replace("GOLD.i#", "GOLDm#")
        .replace("XMGlobal-MT5 5", "XMGlobal-MT5 14"),
        encoding="utf-8",
    )
    output = tmp_path / "evidence"
    metadata = MODULE.write_evidence(
        source=source,
        output_directory=output,
        symbol="GOLDm#",
        timeframe="M15",
        server="XMGlobal-MT5 14",
        proof="lifecycle_goldm",
    )
    assert metadata["profile_matrix"] == ["GOLDM"]
    assert metadata["order_authority"] == "TESTER_ONLY"


def test_capture_supports_goldi_g15_lifecycle(tmp_path: Path) -> None:
    source = tmp_path / "tester.log"
    source.write_text(log(proof="lifecycle_goldi"), encoding="utf-8")
    output = tmp_path / "evidence"
    metadata = MODULE.write_evidence(
        source=source,
        output_directory=output,
        symbol="GOLD.i#",
        timeframe="M15",
        server="XMGlobal-MT5 5",
        proof="lifecycle_goldi",
    )
    assert metadata["profile_matrix"] == ["GOLDI"]


@pytest.mark.parametrize("text", (log(passed=False), "unrelated\n"))
def test_capture_rejects_failed_or_missing_guard_run(text: str) -> None:
    with pytest.raises(MODULE.EvidenceError):
        block = MODULE.capture_block(
            text, symbol="GOLD.i#", timeframe="M15", server="XMGlobal-MT5 5"
        )
        MODULE.validate_block(block, symbol="GOLD.i#", timeframe="M15", server="XMGlobal-MT5 5")
