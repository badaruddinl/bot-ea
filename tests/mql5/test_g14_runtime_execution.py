from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineRuntime.mqh"
EXPERTS = [
    ROOT / "mt5" / "Experts" / "bot-ea" / "GoldEngine-GOLDi.mq5",
    ROOT / "mt5" / "Experts" / "bot-ea" / "GoldEngine-GOLDm.mq5",
]


def test_runtime_builds_complete_profile_bound_plans_for_revised_and_bear() -> None:
    value = RUNTIME.read_text(encoding="utf-8")
    assert "void BuildSignalPlan" in value
    assert "plan.profile_fingerprint=m_profile.profile_fingerprint;" in value
    assert "plan.account_login=AccountInfoInteger(ACCOUNT_LOGIN);" in value
    assert "plan.account_server=AccountInfoString(ACCOUNT_SERVER);" in value
    assert "plan.magic=m_profile.magic;" in value
    assert "plan.volume=ResolveProfileLot" in value
    assert "BuildSignalPlan(side" in value
    assert "BuildSignalPlan(ENGINE_SIDE_SELL" in value
    assert "m_last_revised_decision.observation_only" in value


def test_runtime_pauses_without_latching_authority_off_for_external_position() -> None:
    value = RUNTIME.read_text(encoding="utf-8")
    assert "RecoverOwnedPositions" in value
    assert "DiscoverOwnedPositions" in value
    external_block = value[value.index("const bool external_position=") :]
    external_block = external_block[: external_block.index("m_position_state_status=")]
    assert "DisableAuthority" not in external_block
    assert "ENGINE_EVENT_TRADING_PAUSED" in external_block
    assert "EXTERNAL_POSITION_DETECTED" in external_block
    assert "ENGINE_EVENT_TRADING_RESUMED" in external_block
    assert "EXTERNAL_POSITION_CLEARED" in external_block
    assert "if(m_external_position_active)" in value
    assert "POSITION_RECOVERED" in value
    assert "void OnTradeTransaction" in value


def test_profile_entrypoints_keep_authority_default_false_and_forward_transactions() -> None:
    for path in EXPERTS:
        value = path.read_text(encoding="utf-8")
        assert "input bool   InpEnableOrderAuthority=false;" in value
        assert "InpEnableOrderAuthority" in value
        assert "void OnTradeTransaction" in value
        assert "Runtime.OnTradeTransaction" in value


def test_runtime_emits_complete_human_trade_payloads() -> None:
    value = RUNTIME.read_text(encoding="utf-8")
    assert "string SignalPlanPayload" in value
    assert '\\"side\\":\\"%s\\"' in value
    assert '\\"planned_entry\\":%.8f' in value
    assert '\\"stop_loss\\":%.8f' in value
    assert '\\"take_profit\\":%.8f' in value
    assert '\\"rr\\":%.8f' in value
    assert '\\"server_time_text\\":\\"%s\\"' in value
    assert '\\"vm_time_text\\":\\"%s\\"' in value
    assert 'EmitTransition("POSITION_OPENED"' in value
    assert "string ClosedPositionPayload" in value
    assert "DEAL_COMMISSION" in value
    assert "DEAL_FEE" in value
    assert "DEAL_ENTRY_OUT" in value
    assert 'SetEvent(ENGINE_EVENT_POSITION,closed_at,"POSITION_CLOSED"' in value
