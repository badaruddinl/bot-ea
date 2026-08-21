from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "mt5/Include/bot-ea/GoldEngineProfile.mqh"
HARNESS = ROOT / "mt5/Experts/bot-ea/GoldEngineGoldmRefusalHarness.mq5"
ENTRYPOINT = ROOT / "mt5/Experts/bot-ea/GoldEngine-GOLDm.mq5"


def test_observed_binding_contract_refuses_wrong_account_server_and_mode() -> None:
    source = PROFILE.read_text(encoding="utf-8")

    assert "ValidateObservedAccountBinding" in source
    assert 'reason="WRONG_ACCOUNT"' in source
    assert 'reason="WRONG_SERVER"' in source
    assert 'reason="WRONG_TRADE_MODE"' in source
    assert "AccountInfoInteger(ACCOUNT_LOGIN)" in source
    assert "AccountInfoString(ACCOUNT_SERVER)" in source


def test_exact_goldm_harness_covers_refusal_and_disabled_authority() -> None:
    source = HARNESS.read_text(encoding="utf-8")

    assert "#define BUILD_PROFILE_GOLDM" in source
    assert "ACCOUNT_TRADE_MODE_DEMO" in source
    assert "wrong_account" in source
    assert "wrong_server" in source
    assert "demo_refused" in source
    assert "broker.Initialize(profile,false,reason)" in source
    assert "magic==26081912" in source
    assert "order_authority=DISABLED" in source


def test_production_goldm_authority_is_human_input_default_false() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")

    assert "InpEnableOrderAuthority=false;" in source
    assert "InpEnableOrderAuthority" in source
