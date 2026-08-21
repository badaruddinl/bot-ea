from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_position_state_store_is_profile_bound_dual_slot_and_checked() -> None:
    source = (ROOT / "mt5/Include/bot-ea/GoldEnginePositionPersistence.mqh").read_text(
        encoding="utf-8"
    )

    assert "m_profile_id" in source
    assert "m_profile_fingerprint" in source
    assert "SlotPath(0" in source
    assert "SlotPath(1" in source
    assert "PositionStateChecksum" in source
    assert "field_count<11" in source
    assert 'state.signal_id+="|"+fields[index]' in source
    assert "POSITION_STATE_INVALID" in source
    assert "PositionStateMatches" in source
    assert "POSITION_STOP_CHANGED" in source


def test_runtime_recovers_expected_geometry_and_fails_closed_on_changes() -> None:
    source = (ROOT / "mt5/Include/bot-ea/GoldEngineRuntime.mqh").read_text(encoding="utf-8")

    assert "PersistSubmittedPosition" in source
    assert "m_position_store.Save" in source
    assert "m_position_store.Load" in source
    assert "PositionStateMatches" in source
    assert "m_execution_broker.DisableAuthority()" in source
    assert "POSITION_STATE_MISSING" in source
    assert "MULTIPLE_OWNED_POSITIONS" in source
    assert "POSITION_ALREADY_OPEN" in source
    assert "bool ModifyOwnedPosition" in source
    assert "bool CloseOwnedPosition" in source


def test_native_harness_contract_covers_restart_and_manual_intervention() -> None:
    source = (ROOT / "mt5/Experts/bot-ea/GoldEnginePositionPersistenceHarness.mq5").read_text(
        encoding="utf-8"
    )

    assert "fallback_recovered" in source
    assert "manual_detected" in source
    assert "order_authority=DISABLED" in source
    assert "G14_POSITION_PERSISTENCE" in source
