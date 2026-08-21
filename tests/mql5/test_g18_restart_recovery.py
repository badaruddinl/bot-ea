from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "mt5/Experts/bot-ea/GoldEngineRestartRecoveryHarness.mq5"


def test_restart_harness_persists_open_position_then_recovers_exact_ticket() -> None:
    source = HARNESS.read_text(encoding="utf-8")

    assert "HarnessStore.Save(expected)" in source
    assert "positions_before_restart=" in source
    assert "TerminalClose(1801)" in source
    assert "HarnessStore.Load(expected)" in source
    assert "POSITION_STATE_VALID" in source
    assert "PositionStateMatches" in source
    assert "CloseOwnedPosition(position.ticket" in source
    assert "HarnessStore.Clear(expected)" in source
    assert "positions_after=" in source
    assert "order_authority=DEMO_E2E_ONLY" in source


def test_restart_harness_is_demo_account_profile_and_instance_locked() -> None:
    source = HARNESS.read_text(encoding="utf-8")

    assert "ValidateObservedAccountBinding" in source
    assert '108098316,"XMGlobal-MT5 5"' in source
    assert "HarnessLease.Acquire" in source
    assert "ArraySize(positions)>1" in source
