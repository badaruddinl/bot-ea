from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/deploy-g20-entry-gates.ps1"


def test_entry_gate_deploy_is_explicit_profile_locked_and_rollback_safe() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "AcknowledgeGatedRealAuthority" in source
    assert "Deployment requires exactly GOLDI and GOLDM" in source
    assert "Trade-mode binding mismatch" in source
    assert "Symbol binding mismatch" in source
    assert "validate-g21-mql5-build.ps1" in source
    assert "rollback-entry-gate-" in source
    assert "ea_binary_path" in source
    assert "Split-Path -Parent $mql5Directory" in source
    assert "production_real_orders = 'GATED'" in source
    assert "goldi_entry_gate=OFF" in source
    assert "goldm_entry_gate=OFF" in source
    assert "Stop-Process -Name" not in source
