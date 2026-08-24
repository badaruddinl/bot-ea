from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineRuntime.mqh"
BROKER = ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineExecutionBroker.mqh"
BROKER_CONTEXT = ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineBrokerContext.mqh"
LIFECYCLE = ROOT / "mt5" / "Include" / "bot-ea" / "GoldEnginePositionLifecycle.mqh"
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
    assert "plan.minimum_executable_rr=minimum_executable_rr;" in value
    assert "RevisedMinimumExecutableRr(m_last_revised_decision)" in value
    assert "m_bear_machine.MinimumExecutableRr" in value


def test_runtime_ignores_manual_magic_and_fails_closed_on_owned_identity_conflict() -> None:
    value = RUNTIME.read_text(encoding="utf-8")
    assert "RecoverOwnedPositions" in value
    assert "DiscoverOwnedPositions" in value
    assert "m_ownership_conflict" in value
    assert "POSITION_OWNERSHIP_CONFLICT" in value
    assert "m_execution_broker.DisableAuthority();" in value
    assert "TRADING_PAUSED" not in value
    assert "POSITION_RECOVERED" in value
    assert "void OnTradeTransaction" in value
    assert "DEAL_MAGIC" not in value
    assert "DEAL_POSITION_ID" in value
    assert "transaction.position" in value
    assert "ReconcileClosingDeal" in value
    assert "POSITION_PARTIALLY_CLOSED" in value
    assert "RecoverOwnedPositions(TimeCurrent(),true)" in value
    assert "RecoverOwnedPositions(TimeCurrent(),false)" in value

    lifecycle = LIFECYCLE.read_text(encoding="utf-8")
    assert "PositionExitBelongsToExpected" in lifecycle
    assert "expected.identifier" in lifecycle
    assert "MANUAL_DESKTOP" in lifecycle
    assert "MANUAL_MOBILE" in lifecycle
    assert "MANUAL_WEB" in lifecycle
    assert "STOP_LOSS" in lifecycle
    assert "TAKE_PROFIT" in lifecycle

    broker = BROKER.read_text(encoding="utf-8")
    assert "identity==POSITION_IDENTITY_OTHER_SYMBOL ||" in broker
    assert "identity==POSITION_IDENTITY_FOREIGN_MAGIC" in broker
    assert "identity==POSITION_IDENTITY_MANUAL_COMMENT" in broker
    assert "ownership_conflict=true;" in broker

    context = BROKER_CONTEXT.read_text(encoding="utf-8")
    assert "PositionGetInteger(POSITION_MAGIC)!=profile.magic" in context


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
    assert '\\"minimum_executable_rr\\":%.8f' in value
    assert '\\"quote_time_msc\\":%I64d' in value
    assert '\\"quote_bid\\":%.8f' in value
    assert '\\"quote_ask\\":%.8f' in value
    assert '\\"requested_entry\\":%.8f' in value
    assert '\\"actual_rr\\":%.8f' in value
    assert '\\"adverse_drift_r\\":%.8f' in value
    assert '\\"preflight_to_submit_us\\":%I64u' in value
    assert '\\"server_time_text\\":\\"%s\\"' in value
    assert '\\"vm_time_text\\":\\"%s\\"' in value
    assert 'EmitTransition("POSITION_OPENED"' in value
    assert "string ClosedPositionPayload" in value
    assert "DEAL_COMMISSION" in value
    assert "DEAL_FEE" in value
    assert "DEAL_ENTRY_OUT" in value
    assert r"\"closed_volume\":%.8f" in value
    assert r"\"remaining_volume\":%.8f" in value
    assert r"\"close_reason\":\"%s\"" in value
    assert r"\"deal_id\":%I64u" in value
    assert "PositionCloseEventReason(close_reason,partial)" in value
    assert 'EmitTransition("POSITION_PARTIALLY_CLOSED"' in value
    assert 'EmitTransition("POSITION_CLOSED"' in value
    assert 'EmitTransition("RECOVERY_COMPLETED",setup_id,signal_id' in value


def test_runtime_submits_market_order_synchronously_and_classifies_rejects() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    broker = BROKER.read_text(encoding="utf-8")

    assert "SubmitSignalPlan(" in runtime
    assert "m_execution_broker.Submit(" in runtime
    assert 'EmitTransition("ENTRY_REJECTED"' in runtime
    assert 'EmitTransition("ORDER_SUBMITTED"' in runtime
    assert 'EmitTransition("POSITION_OPENED"' in runtime
    assert broker.count("ExecutionCollectBrokerContext(") >= 2
    assert "fresh_validation.order.price" in broker
    assert "m_trade.PositionOpen(" in broker
    assert "ORDER_TYPE_BUY_LIMIT" not in broker
    assert "ORDER_TYPE_SELL_LIMIT" not in broker
