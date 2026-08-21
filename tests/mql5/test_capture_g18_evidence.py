from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/capture_g18_evidence.py"
SPEC = importlib.util.spec_from_file_location("capture_g18_evidence", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_restart_capture_correlates_same_ticket_across_processes() -> None:
    mql = (
        "G18_RESTART_RECOVERY passed=true phase=RECOVER ticket=77 "
        "state_generation=2 positions_after=0 close_retcode=10009"
    )
    terminal = "\n".join(
        (
            "order #77 buy 0.01 / 0.01 GOLD.i# at x",
            "shutdown with 0",
            "disconnected from XMGlobal-MT5 5",
            "authorized on XMGlobal-MT5 5",
            "terminal synchronized with XM Global Limited: 1 positions, 0 orders",
            "market sell 0.01 GOLD.i#, close #77 buy 0.01",
            "shutdown with 0",
        )
    )

    block, metadata = MODULE.capture_restart(mql, terminal)

    assert metadata["ticket"] == "77"
    assert metadata["positions_seen_after_restart"] == 1
    assert metadata["positions_after_recovery"] == 0
    assert metadata["disconnect_seen"]
    assert metadata["reconnect_authorized"]
    assert "close #77" in block


def test_algo_off_is_expected_fail_closed_result() -> None:
    block, metadata = MODULE.capture_algo_off(
        "G18_RESTART_RECOVERY passed=false phase=OPEN reason=x retcode=10027"
    )

    assert metadata["result"] == "EXPECTED_REJECTION_PASS"
    assert metadata["retcode"] == 10027
    assert "retcode=10027" in block
