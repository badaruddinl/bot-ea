from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "mt5/Experts/bot-ea/GoldEngineProcessProbeCore.mqh"


def test_process_probe_is_profile_bound_heartbeat_only() -> None:
    source = CORE.read_text(encoding="utf-8")

    assert "ValidateObservedAccountBinding" in source
    assert "ProbeLease.Acquire" in source
    assert 'ProbeProfile.profile_id+".json"' in source
    assert "EventSetTimer(1)" in source
    assert "WriteProbeHeartbeat" in source
    assert 'order_authority\\":\\"DISABLED' in source
    for forbidden in ("PositionOpen", "PositionModify", "PositionClose", "OrderSend", "CTrade"):
        assert forbidden not in source


def test_thin_probes_lock_exact_build_profiles() -> None:
    goldi = (ROOT / "mt5/Experts/bot-ea/GoldEngineProcessProbeGoldi.mq5").read_text(
        encoding="utf-8"
    )
    goldm = (ROOT / "mt5/Experts/bot-ea/GoldEngineProcessProbeGoldm.mq5").read_text(
        encoding="utf-8"
    )

    assert "#define BUILD_PROFILE_GOLDI" in goldi
    assert "#define BUILD_PROFILE_GOLDM" in goldm
