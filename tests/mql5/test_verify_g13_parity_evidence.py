from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_g13_parity_evidence.py"


def test_g13_parity_verifier_requires_dual_native_and_oracle_evidence() -> None:
    value = SCRIPT.read_text(encoding="utf-8")
    assert 'profile_id="GOLDI"' in value
    assert 'profile_id="GOLDM"' in value
    assert 'symbol="GOLD.i#"' in value
    assert 'symbol="GOLDm#"' in value
    assert 'server="XMGlobal-MT5 5"' in value
    assert 'server="XMGlobal-MT5 14"' in value
    assert "m15_scanner_oracle.json" in value
    assert "len(vector_payload) != 10" in value
    assert "validate_block" in value
    assert '"production_real_orders": "DISABLED"' in value
    assert '"status": "PASS"' in value
