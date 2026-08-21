from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_g12_parity_evidence.py"


def test_g12_parity_verifier_requires_dual_native_full_state_evidence() -> None:
    value = SCRIPT.read_text(encoding="utf-8")

    assert 'profile_id="GOLDI"' in value
    assert 'profile_id="GOLDM"' in value
    assert 'symbol="GOLD.i#"' in value
    assert 'symbol="GOLDm#"' in value
    assert '"vectors.json": 10' in value
    assert '"setup_vectors.json": 12' in value
    assert "validate_block" in value
    assert '"production_real_orders": "DISABLED"' in value
    assert '"status": "PASS"' in value
    assert "verify_sidecar(log_path)" in value
