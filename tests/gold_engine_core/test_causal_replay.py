from __future__ import annotations

import runpy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from gold_engine_core import (
    Bar,
    CausalReplayDataset,
    CausalReplayError,
    DecisionAction,
    EngineEvent,
    EngineEventType,
    EngineOutput,
    GuardResult,
    ProfileConfig,
    ReferenceProfileRuntime,
    ReferenceRuntimeReplay,
    ReplayBar,
    ReplayTradeResult,
    Side,
    SignalPlan,
    StrategyConfig,
    StrategyDecision,
    StrategyKind,
    StrategyPhase,
    StrategyState,
    Tick,
    Timeframe,
    WarmupRequirement,
    load_execution_policy,
    load_named_profile,
    resolve_signal_path,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=3))
START = datetime(2026, 8, 21, 12, 59, tzinfo=TZ)
D = Decimal


def profile(profile_id: str) -> ProfileConfig:
    return ProfileConfig.from_manifest(
        load_named_profile(REPOSITORY_ROOT, profile_id), tick_size=D("0.01")
    )


@dataclass(frozen=True, slots=True)
class ReplayProbeEngine:
    profile: ProfileConfig
    config: StrategyConfig

    def on_warmup(self, history):
        raise NotImplementedError

    def on_bar_close(self, state: StrategyState, timeframe: Timeframe, bar: Bar) -> EngineOutput:
        next_state = replace(
            state,
            sequence=state.sequence + 1,
            as_of=max(state.as_of, bar.close_time),
        )
        suffix = f"{timeframe.value}:{bar.open_time.isoformat()}"
        return EngineOutput(
            next_state,
            decisions=(
                StrategyDecision(
                    f"decision:{suffix}",
                    bar.close_time,
                    DecisionAction.WATCH,
                    "CAUSAL_PROBE",
                    side=Side.BUY,
                ),
            ),
            events=(
                EngineEvent(
                    f"event:{suffix}",
                    EngineEventType.STATE_TRANSITION,
                    1,
                    bar.close_time,
                    self.profile.profile_id,
                    "CAUSAL_PROBE",
                    "BAR_AVAILABLE",
                ),
            ),
        )

    def on_tick(self, state, tick):
        raise NotImplementedError

    def on_position_event(self, state, event):
        raise NotImplementedError


class AllowGuard:
    def evaluate(self, profile: ProfileConfig, tick: Tick) -> GuardResult:
        del profile, tick
        return GuardResult(True)


def runtime(profile_id: str) -> tuple[ReferenceProfileRuntime, StrategyState]:
    value = profile(profile_id)
    engine = ReplayProbeEngine(
        value,
        StrategyConfig(
            "CAUSAL_PROBE",
            "1.0.0",
            StrategyKind.REVISED,
            (WarmupRequirement(Timeframe.M1, 1),),
            10,
        ),
    )
    state = StrategyState(
        profile_id,
        "CAUSAL_PROBE",
        "1.0.0",
        StrategyPhase.IDLE,
        START,
        0,
        True,
    )
    return ReferenceProfileRuntime(value, engine, AllowGuard()), state


def make_bar(timeframe: Timeframe, open_time: datetime) -> ReplayBar:
    duration = {
        Timeframe.M1: timedelta(minutes=1),
        Timeframe.M5: timedelta(minutes=5),
        Timeframe.M15: timedelta(minutes=15),
        Timeframe.H1: timedelta(hours=1),
        Timeframe.D1: timedelta(days=1),
    }[timeframe]
    return ReplayBar(
        timeframe,
        Bar(
            open_time,
            open_time + duration,
            D("4400"),
            D("4401"),
            D("4399"),
            D("4400.5"),
            100,
            D("0.2"),
        ),
    )


def dataset(profile_id: str, *, missing: Timeframe | None = None) -> CausalReplayDataset:
    value = profile(profile_id)
    close = START.replace(minute=0) + timedelta(hours=1)
    bars = tuple(
        item
        for item in (
            make_bar(Timeframe.H1, close - timedelta(hours=1)),
            make_bar(Timeframe.M15, close - timedelta(minutes=15)),
            make_bar(Timeframe.M5, close - timedelta(minutes=5)),
            make_bar(Timeframe.M1, close - timedelta(minutes=1)),
            # This source bar is still forming at replay_end and must never be read.
            make_bar(Timeframe.M1, close),
        )
        if item.timeframe is not missing
    )
    return CausalReplayDataset(
        profile_id,
        value.manifest_fingerprint,
        value.symbol,
        ticks=(
            Tick(START + timedelta(seconds=30), D("4400"), D("4400.2")),
            Tick(close + timedelta(seconds=1), D("4400"), D("4400.2")),
            Tick(close + timedelta(minutes=1, seconds=1), D("4400"), D("4400.2")),
        ),
        bars=bars,
        warmup_until=close + timedelta(seconds=2),
        replay_end=close + timedelta(seconds=30),
    )


@pytest.mark.parametrize("profile_id", ["GOLDI", "GOLDM"])
def test_tick_driven_replay_is_deterministic_causal_and_nontradable_during_warmup(
    profile_id: str,
) -> None:
    runtime_value, engine_state = runtime(profile_id)
    replay = ReferenceRuntimeReplay(runtime_value)
    source = dataset(profile_id)
    first = replay.run(source, runtime_value.initial_state(engine_state))
    second_runtime, second_state = runtime(profile_id)
    second = ReferenceRuntimeReplay(second_runtime).run(
        source, second_runtime.initial_state(second_state)
    )

    assert first.event_hash == second.event_hash
    assert [item.event_id for item in first.events] == [item.event_id for item in second.events]
    assert first.tick_count == 2  # tick after replay_end is excluded
    assert first.closed_bar_count == 4
    assert first.decision_count == 4
    assert first.warmup_suppressed_decisions == 4
    assert first.final_state.engine_state.sequence == 4
    assert all(item.semantic_time <= source.replay_end for item in first.events)


def test_goldi_goldm_reports_are_separate_and_profile_bound() -> None:
    reports = []
    for profile_id in ("GOLDI", "GOLDM"):
        runtime_value, engine_state = runtime(profile_id)
        reports.append(
            ReferenceRuntimeReplay(runtime_value).run(
                dataset(profile_id), runtime_value.initial_state(engine_state)
            )
        )

    assert reports[0].profile_id == "GOLDI"
    assert reports[1].profile_id == "GOLDM"
    assert reports[0].event_hash != reports[1].event_hash
    assert {item.profile_id for item in reports[0].events} == {"GOLDI"}
    assert {item.profile_id for item in reports[1].events} == {"GOLDM"}


def test_missing_closed_bar_wrong_profile_and_naive_timezone_fail_closed() -> None:
    runtime_value, engine_state = runtime("GOLDI")
    replay = ReferenceRuntimeReplay(runtime_value)
    with pytest.raises(CausalReplayError, match="closed bar unavailable"):
        replay.run(
            dataset("GOLDI", missing=Timeframe.M5),
            runtime_value.initial_state(engine_state),
        )
    with pytest.raises(CausalReplayError, match="crossed runtime profile"):
        replay.run(dataset("GOLDM"), runtime_value.initial_state(engine_state))
    with pytest.raises(CausalReplayError, match="explicit UTC offset"):
        replace(dataset("GOLDI"), replay_end=datetime(2026, 8, 21, 13, 0))


def signal(side: Side = Side.BUY) -> SignalPlan:
    value = profile("GOLDI")
    policy = load_execution_policy(REPOSITORY_ROOT / "config" / "execution_profiles" / "GOLDI.json")
    stop, target = (D("4390"), D("4420")) if side is Side.BUY else (D("4410"), D("4380"))
    return SignalPlan(
        "GOLDI",
        value.profile_version,
        value.manifest_fingerprint,
        "PROBE",
        "1.0.0",
        "revised",
        "CAUSAL_SIGNAL",
        "GOLDI:setup:1",
        "GOLDI:signal:1",
        side,
        value.symbol,
        START - timedelta(minutes=1),
        START,
        START + timedelta(minutes=1),
        D("4400"),
        stop,
        target,
        D("10"),
        stop,
        policy.maximum_spread,
        D("1.0"),
        D("0.01"),
        D("0.01"),
        123456,
        "GOLDI-DEMO",
        "demo",
        value.terminal_identity,
        value.magic,
    )


def outcome_bar(*, low: str, high: str) -> Bar:
    return Bar(
        START,
        START + timedelta(minutes=1),
        D("4400"),
        D(high),
        D(low),
        D("4400"),
        100,
        D("0.2"),
    )


def test_tick_path_uses_bid_ask_and_bar_ambiguity_is_conservative_stop_first() -> None:
    buy = signal(Side.BUY)
    target = resolve_signal_path(
        buy,
        ticks=(Tick(START + timedelta(seconds=1), D("4420"), D("4420.2")),),
    )
    assert target.result is ReplayTradeResult.TARGET
    assert target.source == "TICK"

    sell = signal(Side.SELL)
    sell_stop = resolve_signal_path(
        sell,
        ticks=(Tick(START + timedelta(seconds=1), D("4409.8"), D("4410")),),
    )
    assert sell_stop.result is ReplayTradeResult.STOP

    ambiguous = resolve_signal_path(
        buy,
        bars=(outcome_bar(low="4389", high="4421"),),
    )
    assert ambiguous.result is ReplayTradeResult.STOP
    assert ambiguous.source == "BAR_CONSERVATIVE"


def test_no_future_path_is_not_invented() -> None:
    assert resolve_signal_path(signal()).result is ReplayTradeResult.NO_POST_ENTRY_PATH
    unresolved = resolve_signal_path(
        signal(),
        ticks=(Tick(START + timedelta(seconds=1), D("4400"), D("4400.2")),),
    )
    assert unresolved.result is ReplayTradeResult.OPEN


def test_profile_reports_rebuild_byte_identically(tmp_path: Path) -> None:
    builder = runpy.run_path(str(REPOSITORY_ROOT / "scripts" / "build_causal_replay_evidence.py"))[
        "build_reports"
    ]
    hashes = builder(REPOSITORY_ROOT, tmp_path)
    expected_root = REPOSITORY_ROOT / "evidence" / "G09-causal-tick-replay"

    assert hashes == {
        "GOLDI": "5292a8b21047812db8d7d4ba2f0ff7dd0417ff0c61ba3ab06f5e423cb82426f6",
        "GOLDM": "0218dbb0c0ba48920cca34cd688c6f12056b0697792ea0f76ab1078542c9c617",
    }
    for profile_id in ("GOLDI", "GOLDM"):
        assert (tmp_path / f"{profile_id}-report.json").read_bytes() == (
            expected_root / f"{profile_id}-report.json"
        ).read_bytes()
