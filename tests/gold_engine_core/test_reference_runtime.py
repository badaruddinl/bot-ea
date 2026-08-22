from __future__ import annotations

import ast
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from gold_engine_core import (
    Bar,
    BarRequest,
    DecisionAction,
    EngineEvent,
    EngineEventType,
    EngineOutput,
    GuardResult,
    IsolatedProfileStep,
    ProfileConfig,
    ReferenceProfileRuntime,
    ReferenceRuntimeConfig,
    ReferenceRuntimeError,
    Side,
    StrategyConfig,
    StrategyDecision,
    StrategyKind,
    StrategyPhase,
    StrategyState,
    Tick,
    Timeframe,
    WarmupRequirement,
    load_named_profile,
    run_isolated_profile_steps,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=3))
START = datetime(2026, 8, 18, 12, 59, tzinfo=TZ)
D = Decimal


def profile(profile_id: str = "GOLDI") -> ProfileConfig:
    return ProfileConfig.from_manifest(
        load_named_profile(REPOSITORY_ROOT, profile_id), tick_size=D("0.01")
    )


def strategy_state(profile_id: str = "GOLDI") -> StrategyState:
    return StrategyState(
        profile_id=profile_id,
        strategy_id="PROBE",
        strategy_version="1.0.0",
        phase=StrategyPhase.IDLE,
        as_of=START,
        sequence=0,
        warmup_complete=True,
    )


@dataclass(frozen=True, slots=True)
class ProbeEngine:
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
        decision = StrategyDecision(
            decision_id=f"decision:{suffix}",
            available_at=bar.close_time,
            action=DecisionAction.WATCH,
            reason="PROBE_BAR",
            side=Side.BUY,
        )
        event = EngineEvent(
            event_id=f"event:{suffix}",
            event_type=EngineEventType.STATE_TRANSITION,
            payload_version=1,
            available_at=bar.close_time,
            profile_id=self.profile.profile_id,
            strategy_id=self.config.strategy_id,
            reason="PROBE_BAR",
        )
        return EngineOutput(next_state, (decision,), (event,))

    def on_tick(self, state, tick):
        raise NotImplementedError

    def on_position_event(self, state, event):
        raise NotImplementedError


class AllowGuard:
    def evaluate(self, profile: ProfileConfig, tick: Tick) -> GuardResult:
        del profile, tick
        return GuardResult(True)


class RejectGuard:
    def evaluate(self, profile: ProfileConfig, tick: Tick) -> GuardResult:
        del profile, tick
        return GuardResult(False, ("SPREAD_LIMIT",))


def runtime(
    profile_id: str = "GOLDI",
    *,
    guard=None,
    config: ReferenceRuntimeConfig | None = None,
) -> ReferenceProfileRuntime:
    value = profile(profile_id)
    engine = ProbeEngine(
        value,
        StrategyConfig(
            "PROBE",
            "1.0.0",
            StrategyKind.REVISED,
            (WarmupRequirement(Timeframe.M1, 1),),
            10,
        ),
    )
    return ReferenceProfileRuntime(value, engine, guard or AllowGuard(), config)


def tick(time: datetime) -> Tick:
    return Tick(time, D("4400.00"), D("4400.20"), volume=1.0)


def bar_for(request) -> Bar:
    return Bar(
        request.open_time,
        request.close_time,
        D("4400.00"),
        D("4401.00"),
        D("4399.00"),
        D("4400.50"),
        100,
        D("0.20"),
    )


def feed_reference(runtime_value: ReferenceProfileRuntime):
    state = runtime_value.initial_state(strategy_state(runtime_value.profile.profile_id))
    seeded = runtime_value.on_tick(state, tick(START + timedelta(seconds=30)))
    crossed = runtime_value.on_tick(
        seeded.next_state, tick(START + timedelta(minutes=1, seconds=1))
    )
    state = crossed.next_state
    events = list(crossed.events)
    for request in crossed.bar_requests:
        output = runtime_value.on_bar_close(state, request, bar_for(request))
        state = output.next_state
        events.extend(output.events)
    return state, crossed.bar_requests, tuple(events)


def test_fast_lane_detects_closed_bars_and_bar_lane_sequence_is_deterministic() -> None:
    value = runtime()
    state, requests, events = feed_reference(value)

    assert [item.timeframe for item in requests] == [
        Timeframe.H1,
        Timeframe.M15,
        Timeframe.M5,
        Timeframe.M1,
    ]
    assert state.engine_state.sequence == 4
    assert len(state.pending) == 12
    assert [item.event_id for item in events] == [
        item.event_id for item in feed_reference(runtime())[2]
    ]
    assert len({item.event_id for item in state.pending}) == len(state.pending)
    assert all(item.profile_id == "GOLDI" for item in state.pending)


def test_fast_lane_guard_and_catchup_fail_closed_without_decision_dispatch() -> None:
    guarded = runtime(guard=RejectGuard())
    state = guarded.initial_state(strategy_state())
    rejected = guarded.on_tick(state, tick(START + timedelta(seconds=30)))
    assert rejected.next_state.halted is True
    assert rejected.bar_requests == ()
    assert rejected.events[0].kind == "GUARD_REJECTED"

    bounded = runtime(config=ReferenceRuntimeConfig(maximum_catchup_bars=2))
    first = bounded.on_tick(
        bounded.initial_state(strategy_state()), tick(START + timedelta(seconds=30))
    )
    gap = bounded.on_tick(first.next_state, tick(START + timedelta(hours=2, minutes=1)))
    assert gap.next_state.halted is True
    assert gap.bar_requests == ()
    assert any("CATCHUP_LIMIT" in reason for reason in gap.next_state.halt_reasons)


class CaptureSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []
        self.persisted = ()

    def reconcile(self, profile_id: str, as_of: datetime):
        self.calls.append(f"reconcile:{profile_id}")
        if self.fail:
            raise RuntimeError("slow sink unavailable")
        return ()

    def persist(self, profile_id: str, events) -> None:
        self.calls.append(f"persist:{profile_id}")
        self.persisted = events

    def notify(self, profile_id: str, events) -> None:
        self.calls.append(f"notify:{profile_id}")


def test_db_telegram_like_sinks_run_only_in_slow_lane_and_failure_retains_outbox() -> None:
    value = runtime()
    state, _, _ = feed_reference(value)
    sink = CaptureSink()
    assert sink.calls == []

    delivered = value.run_slow_lane(state, sink)
    assert delivered.error is None
    assert delivered.delivered == state.pending
    assert delivered.next_state.pending == ()
    assert sink.calls == ["reconcile:GOLDI", "persist:GOLDI", "notify:GOLDI"]

    failed = value.run_slow_lane(state, CaptureSink(fail=True))
    assert failed.error == "RuntimeError:slow sink unavailable"
    assert failed.next_state == state
    assert failed.next_state.pending == state.pending


def test_duplicate_bar_and_cross_profile_state_are_rejected_or_idempotent() -> None:
    value = runtime()
    state, requests, _ = feed_reference(value)
    request = requests[-1]
    duplicate = value.on_bar_close(state, request, bar_for(request))
    assert duplicate.next_state == state

    goldm = runtime("GOLDM")
    with pytest.raises(ReferenceRuntimeError, match="crossed profile"):
        goldm.on_tick(state, tick(state.as_of + timedelta(seconds=1)))


def test_one_profile_stall_does_not_stall_other_profile() -> None:
    release = threading.Event()

    def stalled():
        release.wait(1.0)
        return "late"

    output = run_isolated_profile_steps(
        (
            IsolatedProfileStep("GOLDI", lambda: "goldi-ok"),
            IsolatedProfileStep("GOLDM", stalled),
        ),
        timeout_seconds=0.05,
    )
    release.set()

    assert output.completed == (("GOLDI", "goldi-ok"),)
    assert output.failed == ()
    assert output.stalled == ("GOLDM",)


def test_goldi_and_goldm_runtime_state_and_event_namespaces_never_mix() -> None:
    goldi_state, _, _ = feed_reference(runtime("GOLDI"))
    goldm_state, _, _ = feed_reference(runtime("GOLDM"))

    assert goldi_state.profile_id == "GOLDI"
    assert goldm_state.profile_id == "GOLDM"
    assert goldi_state is not goldm_state
    assert all(item.event_id.startswith("GOLDI:") for item in goldi_state.pending)
    assert all(item.event_id.startswith("GOLDM:") for item in goldm_state.pending)
    assert {item.event_id for item in goldi_state.pending}.isdisjoint(
        {item.event_id for item in goldm_state.pending}
    )


def test_isolated_failure_is_scoped_and_duplicate_profiles_are_rejected() -> None:
    def broken():
        raise ValueError("profile fault")

    output = run_isolated_profile_steps(
        (IsolatedProfileStep("GOLDI", broken),), timeout_seconds=0.1
    )
    assert output.failed == (("GOLDI", "ValueError:profile fault"),)
    with pytest.raises(ReferenceRuntimeError, match="unique"):
        run_isolated_profile_steps(
            (
                IsolatedProfileStep("GOLDI", lambda: None),
                IsolatedProfileStep("GOLDI", lambda: None),
            ),
            timeout_seconds=0.1,
        )


def test_reference_runtime_source_has_no_critical_path_external_dependency() -> None:
    path = REPOSITORY_ROOT / "src" / "gold_engine_core" / "reference_runtime.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported.isdisjoint({"MetaTrader5", "requests", "sqlite3", "telegram", "gold_portfolio"})
    assert "order_send" not in source
    assert "sleep(" not in source


def test_runtime_contract_boundaries_fail_closed() -> None:
    with pytest.raises(ReferenceRuntimeError):
        GuardResult(True, ("reason",))
    with pytest.raises(ReferenceRuntimeError):
        GuardResult(False)
    with pytest.raises(ReferenceRuntimeError):
        ReferenceRuntimeConfig(maximum_catchup_bars=0)
    with pytest.raises(ReferenceRuntimeError):
        ReferenceRuntimeConfig(maximum_pending_events=0)
    with pytest.raises(ReferenceRuntimeError):
        BarRequest("", Timeframe.M1, START, START + timedelta(minutes=1))
    with pytest.raises(ValueError, match="explicit UTC offset"):
        tick(datetime(2026, 8, 18, 12, 0))
    with pytest.raises(ReferenceRuntimeError):
        IsolatedProfileStep("", lambda: None)
    with pytest.raises(ReferenceRuntimeError, match="timeout"):
        run_isolated_profile_steps((), timeout_seconds=0)


def test_runtime_state_bar_and_outbox_boundaries_fail_closed() -> None:
    value = runtime()
    state, requests, _ = feed_reference(value)
    with pytest.raises(ReferenceRuntimeError, match="identity or sequence"):
        replace(state, sequence=-1)
    with pytest.raises(ReferenceRuntimeError, match="engine state crossed"):
        replace(state, profile_id="GOLDM")
    with pytest.raises(ReferenceRuntimeError, match="duplicate buckets"):
        replace(state, buckets=(state.buckets[0], state.buckets[0]))
    cursor = state.bar_cursors[0]
    with pytest.raises(ReferenceRuntimeError, match="duplicate bar cursors"):
        replace(state, bar_cursors=(cursor, cursor))
    with pytest.raises(ReferenceRuntimeError, match="inconsistent"):
        replace(state, halted=True, halt_reasons=())

    request = requests[-1]
    with pytest.raises(ReferenceRuntimeError, match="crossed profile"):
        value.on_bar_close(
            state,
            replace(request, profile_id="GOLDM"),
            bar_for(request),
        )
    with pytest.raises(ReferenceRuntimeError, match="does not match"):
        value.on_bar_close(
            state,
            request,
            replace(bar_for(request), close_time=request.close_time + timedelta(minutes=1)),
        )
    earlier = replace(
        request,
        open_time=request.open_time - timedelta(minutes=1),
        close_time=request.close_time - timedelta(minutes=1),
    )
    with pytest.raises(ReferenceRuntimeError, match="before its cursor"):
        value.on_bar_close(state, earlier, bar_for(earlier))
    with pytest.raises(ReferenceRuntimeError, match="halted"):
        value.on_bar_close(
            replace(state, halted=True, halt_reasons=("HALT",)),
            request,
            bar_for(request),
        )

    tiny = runtime(config=ReferenceRuntimeConfig(maximum_pending_events=1))
    seeded = tiny.on_tick(tiny.initial_state(strategy_state()), tick(START + timedelta(seconds=30)))
    crossed = tiny.on_tick(seeded.next_state, tick(START + timedelta(minutes=1, seconds=1)))
    with pytest.raises(ReferenceRuntimeError, match="outbox capacity"):
        tiny.on_bar_close(
            crossed.next_state,
            crossed.bar_requests[-1],
            bar_for(crossed.bar_requests[-1]),
        )


def test_duplicate_tick_and_envelope_exclusivity() -> None:
    value = runtime()
    initial = value.initial_state(strategy_state())
    first_tick = tick(START + timedelta(seconds=30))
    first = value.on_tick(initial, first_tick)
    assert value.on_tick(first.next_state, first_tick).next_state == first.next_state
    with pytest.raises(ReferenceRuntimeError, match="increase strictly"):
        value.on_tick(
            first.next_state,
            Tick(first_tick.time, D("4399"), D("4400"), volume=1.0),
        )

    state, _, _ = feed_reference(runtime())
    decision_envelope = next(item for item in state.pending if item.decision is not None)
    engine_envelope = next(item for item in state.pending if item.engine_event is not None)
    with pytest.raises(ReferenceRuntimeError, match="decision and engine event"):
        replace(decision_envelope, engine_event=engine_envelope.engine_event)


def test_runtime_rejects_engine_profile_mismatch_at_construction() -> None:
    goldi = profile("GOLDI")
    goldm = profile("GOLDM")
    engine = ProbeEngine(
        goldm,
        StrategyConfig(
            "PROBE",
            "1.0.0",
            StrategyKind.REVISED,
            (WarmupRequirement(Timeframe.M1, 1),),
            10,
        ),
    )
    with pytest.raises(ReferenceRuntimeError, match="profile configs differ"):
        ReferenceProfileRuntime(goldi, engine, AllowGuard())
    with pytest.raises(ReferenceRuntimeError, match="another profile"):
        runtime("GOLDI").initial_state(strategy_state("GOLDM"))
