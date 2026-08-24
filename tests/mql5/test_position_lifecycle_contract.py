from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "mt5/Include/bot-ea/GoldEnginePositionLifecycle.mqh"
HARNESS = ROOT / "mt5/Experts/bot-ea/GoldEnginePositionLifecycleHarness.mq5"
PERSISTENCE = ROOT / "mt5/Include/bot-ea/GoldEnginePositionPersistence.mqh"


def test_close_identity_uses_owned_position_not_closing_deal_magic() -> None:
    lifecycle = LIFECYCLE.read_text(encoding="utf-8")

    assert "PositionExitBelongsToExpected" in lifecycle
    assert "transaction_position==expected.ticket" in lifecycle
    assert "deal_position_identifier==expected.identifier" in lifecycle
    assert "DEAL_MAGIC" not in lifecycle


def test_close_reasons_are_explicit_and_side_symmetric() -> None:
    lifecycle = LIFECYCLE.read_text(encoding="utf-8")

    for value in (
        "MANUAL_DESKTOP",
        "MANUAL_MOBILE",
        "MANUAL_WEB",
        "STOP_LOSS",
        "TAKE_PROFIT",
        "EA",
        "STOP_OUT",
        "BROKER_OTHER",
        "POSITION_PARTIALLY_CLOSED_",
        "POSITION_CLOSED_",
    ):
        assert value in lifecycle


def test_position_state_v3_keeps_v1_v2_compatibility_and_trade_context() -> None:
    persistence = PERSISTENCE.read_text(encoding="utf-8")

    assert '"3|%s|%s|' in persistence
    assert 'const bool legacy=fields[0]=="1";' in persistence
    assert 'const bool version_two=fields[0]=="2";' in persistence
    assert 'const bool version_three=fields[0]=="3";' in persistence
    assert "state.identifier" in persistence
    assert "state.strategy_mode" in persistence
    assert "state.trade_reason" in persistence
    assert "actual.identifier!=expected.identifier" in persistence


def test_native_harness_covers_manual_zero_magic_and_unrelated_manual_ignore() -> None:
    harness = HARNESS.read_text(encoding="utf-8")

    assert "manual_close_magic=0" in harness
    assert "manual_by_ticket" in harness
    assert "manual_by_identifier" in harness
    assert "unrelated_manual_ignored" in harness
    assert "order_authority=DISABLED" in harness
