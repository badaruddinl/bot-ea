from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineBrokerContext.mqh"
HARNESS = ROOT / "mt5" / "Experts" / "bot-ea" / "GoldEngineBrokerContextHarness.mq5"


def test_broker_context_is_read_only_complete_and_profile_owned() -> None:
    value = CONTEXT.read_text(encoding="utf-8")
    for token in (
        "SymbolInfoTick",
        "ACCOUNT_LOGIN",
        "ACCOUNT_SERVER",
        "ACCOUNT_TRADE_MODE",
        "ACCOUNT_MARGIN_FREE",
        "SYMBOL_TRADE_TICK_SIZE",
        "SYMBOL_VOLUME_MIN",
        "SYMBOL_VOLUME_MAX",
        "SYMBOL_VOLUME_STEP",
        "SYMBOL_TRADE_STOPS_LEVEL",
        "SYMBOL_TRADE_FREEZE_LEVEL",
        "SYMBOL_ORDER_MARKET",
        "SYMBOL_ORDER_SL",
        "SYMBOL_ORDER_TP",
        "OrderCalcMargin",
        "OrderCheck",
        "PositionsTotal",
        "POSITION_SYMBOL",
        "POSITION_MAGIC",
        "POSITION_COMMENT",
    ):
        assert token in value
    for forbidden in ("OrderSend(", ".Buy(", ".Sell(", "PositionModify", "PositionClose"):
        assert forbidden not in value


def test_request_preserves_plan_geometry_identity_and_filling_policy() -> None:
    value = CONTEXT.read_text(encoding="utf-8")
    assert "request.action=TRADE_ACTION_DEAL;" in value
    assert "request.magic=(ulong)plan.magic;" in value
    assert "request.symbol=plan.symbol;" in value
    assert "request.volume=plan.volume;" in value
    assert "request.sl=plan.stop_loss;" in value
    assert "request.tp=plan.take_profit;" in value
    assert "request.comment=ExecutionSignalComment" in value
    assert "ORDER_FILLING_FOK" in value
    assert "ORDER_FILLING_IOC" in value
    assert "ORDER_FILLING_RETURN" in value


def test_harness_runs_actual_broker_preflight_without_mutation() -> None:
    value = HARNESS.read_text(encoding="utf-8")
    assert "ExecutionCollectBrokerContext" in value
    assert "ValidateExecution" in value
    assert "preflight.request.sl==plan.stop_loss" in value
    assert "preflight.request.tp==plan.take_profit" in value
    assert "order_authority=DISABLED" in value
    for forbidden in ("OrderSend(", "CTrade", "PositionModify", "PositionClose"):
        assert forbidden not in value
