from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineRuntime.mqh"
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


def test_runtime_recovers_owned_positions_and_disables_on_intervention() -> None:
    value = RUNTIME.read_text(encoding="utf-8")
    assert "RecoverOwnedPositions" in value
    assert "DiscoverOwnedPositions" in value
    assert "m_execution_broker.DisableAuthority();" in value
    assert "MANUAL_INTERVENTION_DETECTED" in value
    assert "FOREIGN_SYMBOL_POSITION_DETECTED" in value
    assert "POSITION_RECOVERED" in value
    assert "void OnTradeTransaction" in value


def test_profile_entrypoints_keep_authority_default_false_and_forward_transactions() -> None:
    for path in EXPERTS:
        value = path.read_text(encoding="utf-8")
        assert "input bool   InpEnableOrderAuthority=false;" in value
        assert "InpEnableOrderAuthority" in value
        assert "void OnTradeTransaction" in value
        assert "Runtime.OnTradeTransaction" in value
