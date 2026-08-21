from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BROKER = ROOT / "mt5/Include/bot-ea/GoldEngineExecutionBroker.mqh"
HARNESS = ROOT / "mt5/Experts/bot-ea/GoldEngineOwnershipFailureHarness.mq5"


def test_discovery_uses_pure_identity_classifier() -> None:
    source = BROKER.read_text(encoding="utf-8")

    assert "ClassifyPositionIdentity" in source
    assert "POSITION_IDENTITY_OTHER_SYMBOL" in source
    assert "POSITION_IDENTITY_FOREIGN_MAGIC" in source
    assert "POSITION_IDENTITY_MANUAL_COMMENT" in source
    assert "POSITION_IDENTITY_OWNED" in source
    assert "positions[count].owned=identity==POSITION_IDENTITY_OWNED" in source


def test_native_harness_proves_magic_collision_and_cross_profile_refusal() -> None:
    source = HARNESS.read_text(encoding="utf-8")

    assert "other_symbol" in source
    assert "foreign_magic" in source
    assert "magic_collision" in source
    assert "manual-or-foreign-ea" in source
    assert "cross_profile_management=false" in source
    assert "order_authority=DISABLED" in source
