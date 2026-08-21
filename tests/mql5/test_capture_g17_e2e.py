from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/capture_g17_e2e_evidence.py"
SPEC = importlib.util.spec_from_file_location("capture_g17_e2e_evidence", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_live_goldi_capture_requires_correlated_demo_round_trip() -> None:
    lifecycle = (
        "G14_EXECUTION_LIFECYCLE passed=true initialized=true opened=true discovered=true "
        "modified=true restarted=true closed=true positions_before=0 positions_after=0 "
        "open_retcode=10009 modify_retcode=10009 close_retcode=10009"
    )
    marker = (
        "G17_E2E passed=true profile=GOLDI chain_id=G17|GOLDI|100 "
        "setup_id=x signal_id=y order_id=77 position_id=77 events=6"
    )
    terminal = "\n".join(
        (
            "authorized on XMGlobal-MT5 5",
            "trading has been enabled, demo account",
            "order #77 buy 0.1 / 0.1 GOLD.i#",
            "modify #77 buy 0.1 GOLD.i#",
            "market sell 0.1 GOLD.i#, close #77",
        )
    )

    block, metadata = MODULE.capture_live_goldi(lifecycle + "\n" + marker, terminal)

    assert metadata["chain_id"] == "G17|GOLDI|100"
    assert metadata["account_mode"] == "DEMO"
    assert metadata["positions_after"] == 0
    assert "order #77 buy" in block


def test_goldm_tester_capture_requires_complete_boundary() -> None:
    text = "\n".join(
        (
            "GOLDm#,M15: testing of Experts\\bot-ea\\GoldEngineExecutionLifecycleGoldmHarness.ex5 from x started",
            "G14_EXECUTION_LIFECYCLE passed=true positions_before=0 positions_after=0 "
            "open_retcode=10009 modify_retcode=10009 close_retcode=10009 magic=26081912",
            "G17_E2E passed=true profile=GOLDM chain_id=G17|GOLDM|100 events=6",
            "OnTester result 1",
            "connection closed",
        )
    )

    block, metadata = MODULE.capture_tester_goldm(text)

    assert metadata["chain_id"] == "G17|GOLDM|100"
    assert metadata["order_authority"] == "TESTER_ONLY"
    assert "OnTester result 1" in block
