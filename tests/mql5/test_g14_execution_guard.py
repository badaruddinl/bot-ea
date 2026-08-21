from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TYPES = ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineTypes.mqh"
PROFILE = ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineProfile.mqh"
GUARD = ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineExecutionGuard.mqh"
HARNESS = ROOT / "mt5" / "Experts" / "bot-ea" / "GoldEngineExecutionGuardHarness.mq5"


def test_signal_plan_carries_complete_immutable_execution_identity() -> None:
    value = TYPES.read_text(encoding="utf-8")
    for token in (
        "profile_version",
        "profile_fingerprint",
        "account_login",
        "account_server",
        "trade_mode",
        "terminal_identity",
        "magic",
        "valid_until",
        "volume",
        "tick_size",
        "maximum_drift_r",
        "maximum_spread",
        "planned_entry",
        "stop_loss",
        "take_profit",
        "invalidation",
        "risk_price",
    ):
        assert token in value


def test_profile_locks_python_reference_execution_policy() -> None:
    value = PROFILE.read_text(encoding="utf-8")
    assert "config.tick_size=0.01;" in value
    assert "config.maximum_drift_r=0.15;" in value
    assert "config.maximum_spread=0.60;" in value
    assert "config.maximum_spread=0.72;" in value
    assert "config.maximum_signal_age_seconds=60;" in value
    assert "config.order_authority_default=false;" in value


def test_guard_contains_every_reference_reject_and_no_mutation_authority() -> None:
    value = GUARD.read_text(encoding="utf-8")
    for reason in (
        "PROFILE_MISMATCH",
        "POLICY_MISMATCH",
        "SIGNAL_AGE_INVALID",
        "ENTRY_DRIFT_EXCEEDED",
        "SPREAD_EXCEEDED",
        "SETUP_INVALIDATED",
        "ACCOUNT_MISMATCH",
        "SERVER_MODE_MISMATCH",
        "TERMINAL_MISMATCH",
        "SYMBOL_MISMATCH",
        "MAGIC_MISMATCH",
        "POSITION_COUNT_EXCEEDED",
        "TOTAL_VOLUME_EXCEEDED",
        "FREE_MARGIN_INSUFFICIENT",
        "BROKER_CONSTRAINT_REJECTED",
        "DUPLICATE_SIGNAL",
        "EXECUTABLE_GEOMETRY_INVALID",
        "BROKER_CHECK_REJECTED",
    ):
        assert reason in value
    assert "result.order.stop_loss=plan.stop_loss;" in value
    assert "result.order.take_profit=plan.take_profit;" in value
    for forbidden in ("OrderSend", "CTrade", "PositionModify", "PositionClose"):
        assert forbidden not in value


def test_harness_is_dual_profile_and_asserts_all_guard_classes() -> None:
    value = HARNESS.read_text(encoding="utf-8")
    assert 'TestProfile("GOLDI")' in value
    assert 'TestProfile("GOLDM")' in value
    assert "reasons=18" in value
    assert "structural_geometry=true" in value
    assert "order_authority=DISABLED" in value
    assert value.count("AssertRejected(") >= 19
    for forbidden in ("OrderSend", "CTrade", "PositionModify", "PositionClose"):
        assert forbidden not in value
