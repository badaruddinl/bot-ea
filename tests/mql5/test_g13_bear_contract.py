from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TYPES = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineBearTypes.mqh"
INDICATORS = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineBearIndicators.mqh"
VALIDATION = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineBearValidation.mqh"
HARNESS = REPOSITORY_ROOT / "mt5" / "Experts" / "bot-ea" / "GoldEngineBearParityHarness.mq5"


def test_bear_types_lock_incremental_phases_and_v4_profile_contract() -> None:
    value = TYPES.read_text(encoding="utf-8")

    for phase in (
        "BEAR_PHASE_IDLE",
        "BEAR_PHASE_WATCH_H1",
        "BEAR_PHASE_WATCH_M5",
        "BEAR_PHASE_WATCH_M1",
        "BEAR_PHASE_ENTRY_READY",
        "BEAR_PHASE_CANCELLED",
    ):
        assert phase in value
    assert "config.fixed_target_r=2.0" in value
    assert "config.price_tick=0.01" in value
    assert "config.spread_floor=spread_floor" in value
    assert "OrderSend" not in value


def test_bear_indicators_are_standalone_closed_bar_algorithms() -> None:
    value = INDICATORS.read_text(encoding="utf-8")

    assert "BearAverageTrueRange" in value
    assert "BearSimpleRsi" in value
    assert "BearStochastic" in value
    assert "count<period+smoothing" in value
    assert "iATR" not in value
    assert "CopyBuffer" not in value
    assert "GoldEngineRevised" not in value


def test_h1_m5_m1_validation_preserves_incremental_reference_rules() -> None:
    value = VALIDATION.read_text(encoding="utf-8")

    assert "BearH1Bearish" in value
    assert "bars[count-1].close<current && current<previous" in value
    assert 'result.reason="M5_ACCEPTANCE"' in value
    assert "current.open_time+PeriodSeconds(PERIOD_M5)" in value
    assert "result.touches>=config.m5_min_touches" in value
    assert "BearEntryOnM1" in value
    assert "current.close<previous.low" in value
    assert "stochastic.k<stochastic.previous_k" in value
    assert "plan.entry=previous.low-config.price_tick" in value
    assert "plan.entry-config.fixed_target_r*(plan.stop-plan.entry)" in value
    assert "OrderSend" not in value
    assert "WebRequest" not in value
    assert "replay" not in value.casefold()


def test_native_bear_harness_locks_profile_specific_python_geometry() -> None:
    value = HARNESS.read_text(encoding="utf-8")

    assert 'const bool goldm=_Symbol=="GOLDm#"' in value
    assert "arm.armed_at!=D'2026.01.02 00:25:00'" in value
    assert "arm.touches!=2" in value
    assert "arm.rejections!=2" in value
    assert "BearCloseEnough(arm.atr,1.1071428571428572" in value
    assert "const double expected_stop=(goldm ? 100.68 : 100.60)" in value
    assert "const double expected_target=(goldm ? 93.21 : 93.37)" in value
    assert "BearCloseEnough(plan.entry,98.19,0.01)" in value
    assert "return BearHarnessPassed ? INIT_SUCCEEDED : INIT_FAILED" in value
    assert "OrderSend" not in value
