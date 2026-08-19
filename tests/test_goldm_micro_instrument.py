from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from goldm_revised.instrument_profile import GoldInstrumentProfile
from goldm_revised.engine import RevisedEngineConfig


CONFIG = Path(__file__).resolve().parents[1] / "config" / "goldm-micro-baseline-v1.json"
REPLAY_CONFIG = Path(__file__).resolve().parents[1] / "config" / "goldm-micro-replay.json"
SIZING_CONFIGS = (
    "goldm-micro-sizing-moderate.json",
    "goldm-micro-sizing-aggressive.json",
    "goldm-micro-sizing-hybrid.json",
)
PRIMARY_CONFIG = Path(__file__).resolve().parents[1] / "config" / "goldm-micro-primary.json"


def _profile() -> GoldInstrumentProfile:
    return GoldInstrumentProfile.from_mapping(
        json.loads(CONFIG.read_text(encoding="utf-8"))
    )


def test_goldm_micro_profile_has_executable_partial_and_smaller_exposure() -> None:
    profile = _profile()

    assert profile.exposure_ounces(0.1) == pytest.approx(0.1)
    assert profile.exposure_ounces(0.2) == pytest.approx(0.2)
    assert profile.is_executable_lot(0.1)
    assert profile.is_executable_lot(0.11)
    assert not profile.is_executable_lot(0.05)
    assert profile.partial_lot * 2 == profile.high_lot


def test_goldm_micro_profile_maps_gold_i_exposure_without_confusing_lots() -> None:
    profile = _profile()

    assert profile.lot_for_exposure(1.0) == pytest.approx(1.0)
    assert profile.lot_for_exposure(2.0) == pytest.approx(2.0)
    assert profile.high_lot == 0.2
    assert profile.high_lot != profile.lot_for_exposure(2.0)


def test_goldm_micro_profile_validates_mt5_contract_fail_closed() -> None:
    profile = _profile()
    valid = SimpleNamespace(
        name="GOLDm#",
        trade_contract_size=1.0,
        volume_min=0.1,
        volume_step=0.01,
        volume_max=100.0,
        point=0.01,
        trade_tick_size=0.01,
    )
    wrong_contract = SimpleNamespace(**{**vars(valid), "trade_contract_size": 100.0})

    assert profile.validate_mt5_symbol_info(valid) == ()
    assert "trade_contract_size" in profile.validate_mt5_symbol_info(wrong_contract)[0]


def test_goldm_micro_replay_config_targets_native_symbol_and_spread() -> None:
    payload = json.loads(REPLAY_CONFIG.read_text(encoding="utf-8"))
    values = dict(payload["engine"])
    values["psychological_steps"] = tuple(values["psychological_steps"])
    values["strong_m5_patterns"] = tuple(values["strong_m5_patterns"])

    config = RevisedEngineConfig(**values)

    assert config.symbol == "GOLDm#"
    assert config.price_tick == 0.01
    assert config.spread_floor == 0.24


def test_goldm_sizing_profiles_use_executable_sorted_tiers() -> None:
    profile = _profile()
    config_dir = CONFIG.parent

    for name in SIZING_CONFIGS:
        payload = json.loads((config_dir / name).read_text(encoding="utf-8"))
        tiers = payload["balance_tiers"]
        balances = [float(item["minimum_balance"]) for item in tiers]
        lots = [float(item["lot"]) for item in tiers]

        assert balances == sorted(balances)
        assert balances[0] == 0.0
        assert all(profile.is_executable_lot(lot) for lot in lots)


def test_goldm_primary_selects_aggressive_without_enabling_orders() -> None:
    payload = json.loads(PRIMARY_CONFIG.read_text(encoding="utf-8"))
    root = PRIMARY_CONFIG.parents[1]

    assert payload["status"] == "PRIMARY_RESEARCH_FULL_SUITE_STRESS_RESTRICTED"
    assert payload["primary_sizing_profile"].endswith(
        "goldm-micro-sizing-aggressive.json"
    )
    assert (root / payload["primary_sizing_profile"]).is_file()
    assert not payload["runtime_enabled"]
    assert not payload["orders_enabled"]
    assert payload["full_suite_completed"]
    assert not payload["deployment_gate_passed"]
