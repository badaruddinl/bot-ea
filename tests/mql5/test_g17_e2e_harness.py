from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "mt5/Experts/bot-ea/GoldEngineExecutionLifecycleHarnessCore.mqh"


def test_harness_correlates_full_lifecycle_to_one_chain_and_spool() -> None:
    source = CORE.read_text(encoding="utf-8")

    for event_type in (
        "SETUP_CREATED",
        "ENTRY_READY",
        "ORDER_SUBMITTED",
        "POSITION_OPENED",
        "POSITION_MODIFIED",
        "POSITION_CLOSED",
    ):
        assert f'"{event_type}"' in source
    assert 'HarnessChainId+"|SETUP"' in source
    assert 'HarnessChainId+"|SIGNAL"' in source
    assert "opened.order_ticket" in source
    assert "HarnessActiveTicket=ticket" in source
    assert "HarnessEventCount==6" in source
    assert 'Print("G17_E2E passed="' in source
    assert "FileDelete(HarnessOutbox.Path(),FILE_COMMON)" in source


def test_goldm_tester_override_remains_compile_and_tester_locked() -> None:
    guard = (ROOT / "mt5/Include/bot-ea/GoldEngineExecutionGuard.mqh").read_text(encoding="utf-8")

    assert "plan.engineering_tester" in guard
    assert 'profile.profile_id=="GOLDM"' in guard
    assert "MQLInfoInteger(MQL_TESTER)" in guard
