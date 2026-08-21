from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "mt5/Experts/bot-ea/GoldEngineBrokerFailureContractHarness.mq5"


def test_native_contract_covers_partial_ambiguous_and_hard_rejects() -> None:
    source = HARNESS.read_text(encoding="utf-8")

    assert "TRADE_RETCODE_DONE_PARTIAL" in source
    assert "TRADE_RETCODE_TIMEOUT" in source
    assert "TRADE_RETCODE_CONNECTION" in source
    assert "TRADE_RETCODE_NO_MONEY" in source
    assert "TRADE_RETCODE_INVALID" in source
    assert "blind_retry=false" in source
    assert "order_authority=DISABLED" in source
