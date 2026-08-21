from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TYPES = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineBearTypes.mqh"
INDICATORS = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineBearIndicators.mqh"
VALIDATION = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineBearValidation.mqh"
HARNESS = REPOSITORY_ROOT / "mt5" / "Experts" / "bot-ea" / "GoldEngineBearParityHarness.mq5"
INCREMENTAL = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineBearIncremental.mqh"
SETUP = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineBearSetup.mqh"
RUNTIME = REPOSITORY_ROOT / "mt5" / "Include" / "bot-ea" / "GoldEngineRuntime.mqh"


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
    assert "EvaluateBearM15Oracle" in value
    assert "BuildG13BearM15Oracle" in value
    assert "setup.confluence_votes==4" in value
    assert "BearCloseEnough(setup.resistance,4398.52,0.01)" in value
    assert "BearCloseEnough(setup.take_profit,4390.50,0.01)" in value
    assert "EvaluateBearIncrementalSequence" in value
    assert "machine.Sequence()!=68" in value
    assert 'profile_id+":BEAR:53:IDLE:WATCH_H1:M15_SETUP_ACCEPTED"' in value
    assert 'profile_id+":BEAR:66:WATCH_M1:ENTRY_READY:M1_ENTRY_CONFIRMATION_READY"' in value
    assert 'profile_id+":BEAR:2026-01-02T00:00:00+03:00"' in value
    assert "return BearHarnessPassed ? INIT_SUCCEEDED : INIT_FAILED" in value
    assert "OrderSend" not in value


def test_incremental_state_owner_is_bounded_idempotent_and_restart_safe() -> None:
    value = INCREMENTAL.read_text(encoding="utf-8")

    assert "class CBearIncrementalMachine" in value
    assert "BAR_BEFORE_PROCESSED_CURSOR" in value
    assert "if(cursor>0 && bar.open_time==cursor)" in value
    assert "AppendBounded" in value
    assert "return 45" in value
    assert "return 40" in value
    assert "return 128" in value
    assert "Snapshot(CBearIncrementalSnapshot &snapshot) const" in value
    assert "Restore(const CBearIncrementalSnapshot &snapshot)" in value
    assert "snapshot.profile_id!=m_profile_id" in value
    assert "SnapshotCursorValid" in value
    assert "snapshot.phase==BEAR_PHASE_WATCH_M1 && !snapshot.has_arm" in value
    assert "snapshot.phase==BEAR_PHASE_ENTRY_READY && !snapshot.has_signal" in value
    assert "M15_SETUP_ACCEPTED" in value
    assert "H1_BEARISH_CONTEXT_ACCEPTED" in value
    assert "H1_BEARISH_CONTEXT_REJECTED" in value
    assert "M5_REJECTION_ARMED" in value
    assert "M5_WATCH_WINDOW_EXPIRED" in value
    assert "M1_ENTRY_CONFIRMATION_READY" in value
    assert "M1_WATCH_WINDOW_EXPIRED_OR_INVALIDATED" in value
    assert "BearArmOnM5" in value
    assert "BearEntryOnM1" in value
    assert "OrderSend" not in value
    assert "replay" not in value.casefold()


def test_m15_scanner_ports_full_standalone_confluence_and_obstacle_geometry() -> None:
    value = SETUP.read_text(encoding="utf-8")

    for token in (
        "BearAverageTrueRange",
        "BearLinearSlope",
        "BearSwingLevels",
        "BearPsychologicalLevels",
        "BearM15Confluence",
        "fibonacci_retest",
        "rsi_turn_down",
        "stochastic_turn_down",
        "supply_retest",
        "momentum_restart",
        "exhausted",
        "no_resistance_retest",
        "rejection_confirmed_waiting_confluence",
        "target_capped_at_nearest_psychological_support",
        "continuation_through_near_support",
    ):
        assert token in value
    assert "if(n<50)" in value
    assert "latest.spread_points*c.price_tick" in value
    assert "setup.confluence_votes=conf.votes" in value
    assert "OrderSend" not in value
    assert "WebRequest" not in value
    assert "GoldEngineRevised" not in value


def test_live_runtime_wires_only_bounded_incremental_bear_path() -> None:
    value = RUNTIME.read_text(encoding="utf-8")

    assert '#include "GoldEngineBearIncremental.mqh"' in value
    assert "CBearIncrementalMachine m_bear_machine" in value
    assert "CopyLatestBars(m_m15_history,50,scanner_bars)" in value
    assert "BearM15Setup" in value
    assert "m_bear_machine.OnBarClose" in value
    assert "m_bear_machine.SeedClosedHistory" in value
    assert "bar.timeframe==PERIOD_H1 ||" in value
    assert "bar.timeframe==PERIOD_M15 ||" in value
    assert "bar.timeframe==PERIOD_M5" in value
    assert "BearBrokerUtcOffsetMinutes(TimeCurrent())" in value
    assert "HasBearSignal" in value
    assert "LastBearSignal" in value
    assert "bear_replay" not in value.casefold()
    assert "lookback_days" not in value.casefold()
    assert "OrderSend" not in value
