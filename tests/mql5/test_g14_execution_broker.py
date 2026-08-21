from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BROKER = ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineExecutionBroker.mqh"
HARNESS = ROOT / "mt5" / "Experts" / "bot-ea" / "GoldEngineExecutionDisabledHarness.mq5"


def test_broker_uses_ctrade_only_after_preflight_and_authority_gate() -> None:
    value = BROKER.read_text(encoding="utf-8")
    assert "#include <Trade/Trade.mqh>" in value
    assert "ExecutionCollectBrokerContext" in value
    assert "ValidateExecution" in value
    assert value.index("if(!m_authority_enabled)") < value.index("m_trade.PositionOpen(")
    assert "m_trade.SetExpertMagicNumber" in value
    assert "m_trade.SetDeviationInPoints" in value
    assert "m_trade.SetAsyncMode(false)" in value
    assert "m_trade.SetTypeFillingBySymbol" in value
    assert "m_trade.ResultRetcode()" in value
    assert "m_trade.ResultOrder()" in value
    assert "m_trade.ResultDeal()" in value


def test_success_retcode_contract_is_explicit_and_fail_closed() -> None:
    value = BROKER.read_text(encoding="utf-8")
    assert "TRADE_RETCODE_DONE" in value
    assert "TRADE_RETCODE_PLACED" in value
    assert "TRADE_RETCODE_DONE_PARTIAL" in value
    assert "EXECUTION_SUBMIT_FAILED" in value
    assert "ORDER_SEND_FAILED:" in value
    assert "profile.order_authority_default" in value


def test_disabled_harness_proves_no_position_mutation() -> None:
    value = HARNESS.read_text(encoding="utf-8")
    assert "broker.Initialize(profile,false,reason)" in value
    assert "!broker.AuthorityEnabled()" in value
    assert "receipt.state==EXECUTION_SUBMIT_DISABLED" in value
    assert "before==after" in value
    assert "!receipt.sent" in value
    assert "order_authority=DISABLED" in value
