from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INCLUDE_ROOT = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea"
EXPERT_ROOT = REPOSITORY_ROOT / "mt5" / "Experts" / "bot-ea"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("profile_id", "macro", "expert_name"),
    [
        ("GOLDI", "BUILD_PROFILE_GOLDI", "GoldEngine-GOLDi.mq5"),
        ("GOLDM", "BUILD_PROFILE_GOLDM", "GoldEngine-GOLDm.mq5"),
    ],
)
def test_profile_entrypoint_is_thin_strict_and_single_macro(
    profile_id: str,
    macro: str,
    expert_name: str,
) -> None:
    value = source(EXPERT_ROOT / expert_name)
    other = "BUILD_PROFILE_GOLDM" if profile_id == "GOLDI" else "BUILD_PROFILE_GOLDI"

    assert "#property strict" in value
    assert f"#define {macro}" in value
    assert other not in value
    assert '#include "../../Include/bot-ea/GoldEngineRuntime.mqh"' in value
    assert re.search(r"void OnTick\(void\)\s*\{\s*Runtime\.OnTick\(\);\s*\}", value)
    assert "CTrade" not in value
    assert "OrderSend" not in value


def test_embedded_profiles_match_canonical_manifests() -> None:
    profile_source = source(INCLUDE_ROOT / "GoldEngineProfile.mqh")
    for profile_id in ("GOLDI", "GOLDM"):
        manifest_path = REPOSITORY_ROOT / "config" / "engine_profiles" / f"{profile_id}.json"
        checksum_path = manifest_path.with_suffix(".sha256")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        fingerprint = checksum_path.read_text(encoding="ascii").split()[0]

        assert f'config.profile_id="{profile_id}"' in profile_source
        assert f'config.profile_fingerprint="{fingerprint}"' in profile_source
        assert f'config.symbol="{manifest["symbol"]}"' in profile_source
        assert f"config.magic={manifest['magic']}" in profile_source
        assert "config.order_authority_default=false" in profile_source


def test_embedded_balance_tiers_and_resolver_match_profile_contracts() -> None:
    value = source(INCLUDE_ROOT / "GoldEngineProfile.mqh")
    for profile_id in ("GOLDI", "GOLDM"):
        manifest = json.loads(
            (REPOSITORY_ROOT / "config" / "engine_profiles" / f"{profile_id}.json").read_text(
                encoding="utf-8"
            )
        )
        for index, tier in enumerate(manifest["sizing_tiers"]):
            assert (
                f"config.sizing_minimum_balance[{index}]={float(tier['minimum_balance'])};"
            ) in value
            assert f"config.sizing_lot[{index}]={float(tier['lot'])};" in value
        assert f"config.sizing_tier_count={len(manifest['sizing_tiers'])};" in value
        assert f"config.max_total_lot={float(manifest['max_total_lot'])};" in value

    assert "double ResolveProfileLot" in value
    assert "balance<config.sizing_minimum_balance[index]" in value


def test_runtime_declares_all_required_g11_contract_types() -> None:
    value = source(INCLUDE_ROOT / "GoldEngineTypes.mqh")
    for contract in (
        "EngineBar",
        "EngineTick",
        "ProfileConfig",
        "StrategyState",
        "StrategyDecision",
        "SignalPlan",
        "EngineEvent",
        "ManagedPosition",
    ):
        assert f"struct {contract}" in value


def test_scheduler_is_bounded_ordered_and_idempotent_by_forming_bar() -> None:
    value = source(INCLUDE_ROOT / "GoldEngineScheduler.mqh")
    positions = [
        value.index(f"m_timeframes[{index}]={timeframe}")
        for index, timeframe in enumerate(
            ("PERIOD_D1", "PERIOD_H1", "PERIOD_M15", "PERIOD_M5", "PERIOD_M1")
        )
    ]
    assert positions == sorted(positions)
    assert "#define GOLD_ENGINE_TIMEFRAME_COUNT 5" in value
    assert "CopyRates(m_symbol,timeframe,1,1,rates)" in value
    assert "if(current==m_last_forming_open[index])" in value
    assert "m_last_forming_open[index]=current;" in value
    assert "while(" not in value
    assert "CopyRates(m_symbol,timeframe,0" not in value


def test_warmup_is_bounded_non_dispatching_and_fail_closed_on_gap() -> None:
    value = source(INCLUDE_ROOT / "GoldEngineRuntime.mqh")
    warmup_body = value[value.index("bool Warmup(void)") : value.index("void DispatchClosedBar")]

    assert "required_bars>512" in value
    assert "CopyRates(m_profile.symbol,timeframe,1,required_bars,rates)" in value
    assert "DispatchClosedBar" not in warmup_body
    assert "if(gap_detected)" in value
    assert "reason=CLOSED_BAR_GAP" in value
    assert "m_data_healthy=false;" in value


def test_g11_has_no_order_network_database_or_unbounded_tick_path() -> None:
    combined = "\n".join(
        source(path)
        for path in (
            INCLUDE_ROOT / "GoldEngineTypes.mqh",
            INCLUDE_ROOT / "GoldEngineProfile.mqh",
            INCLUDE_ROOT / "GoldEngineScheduler.mqh",
            INCLUDE_ROOT / "GoldEngineRuntime.mqh",
            EXPERT_ROOT / "GoldEngine-GOLDi.mq5",
            EXPERT_ROOT / "GoldEngine-GOLDm.mq5",
        )
    )
    forbidden = (
        "CTrade",
        "OrderSend",
        "OrderCheck",
        "WebRequest",
        "Database",
        "Socket",
        "FileOpen",
        "HistorySelect",
    )
    assert not [name for name in forbidden if name in combined]

    tick_body = combined[
        combined.index("void OnTick(void)", combined.index("class CGoldEngineRuntime")) :
    ]
    assert "while(" not in tick_body
    assert "CopyRates(m_profile.symbol,timeframe,1,required_bars,rates)" not in tick_body
