from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_g12_compile.py"


def test_g12_compile_verifier_is_profile_complete_and_harness_fail_closed() -> None:
    value = SCRIPT.read_text(encoding="utf-8")

    assert "verify_g11_compile_artifacts" in value
    assert '"gate": "G12"' in value
    assert '"status": "COMPILE_PASS"' in value
    assert '"production_real_orders": "DISABLED"' in value
    assert "GoldEngineRevisedParityHarness.mq5" in value
    assert 'forbidden = ("OrderSend", "CTrade", "trade.mqh", "WebRequest")' in value
    assert '"Result: 0 errors, 0 warnings"' in value
    assert "binary.stat().st_size < 1024" in value
