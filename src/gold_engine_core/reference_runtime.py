from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from time import monotonic
from typing import Protocol, TypeAlias

from .contracts import (
    Bar,
    EngineEvent,
    ProfileConfig,
    PureStrategyEngine,
    StateField,
    StrategyDecision,
    StrategyState,
    Tick,
    Timeframe,
)


class ReferenceRuntimeError(ValueError):
    """Raised when event-driven reference runtime invariants are violated."""


class ReferenceLane(StrEnum):
    FAST = "FAST"
    BAR = "BAR"
    SLOW = "SLOW"


_BAR_TIMEFRAMES = (
    Timeframe.D1,
    Timeframe.H1,
    Timeframe.M15,
    Timeframe.M5,
    Timeframe.M1,
)
_DURATIONS = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.D1: timedelta(days=1),
}


@dataclass(frozen=True, slots=True)
class GuardResult:
    allowed: bool
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.allowed and self.reasons:
            raise ReferenceRuntimeError("allowed guard result cannot carry rejection reasons")
        if not self.allowed and not self.reasons:
            raise ReferenceRuntimeError("rejected guard result requires a reason")


class TickGuard(Protocol):
    def evaluate(self, profile: ProfileConfig, tick: Tick) -> GuardResult: ...


@dataclass(frozen=True, slots=True)
class RuntimeBucket:
    timeframe: Timeframe
    open_time: datetime

    def __post_init__(self) -> None:
        _aware(self.open_time, "bucket.open_time")


@dataclass(frozen=True, slots=True)
class RuntimeBarCursor:
    timeframe: Timeframe
    open_time: datetime

    def __post_init__(self) -> None:
        _aware(self.open_time, "bar_cursor.open_time")


@dataclass(frozen=True, slots=True)
class BarRequest:
    profile_id: str
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime

    def __post_init__(self) -> None:
        _aware(self.open_time, "bar_request.open_time")
        _aware(self.close_time, "bar_request.close_time")
        if not self.profile_id or self.close_time <= self.open_time:
            raise ReferenceRuntimeError("bar request identity or time is invalid")


EnvelopeValue: TypeAlias = str | int | bool | datetime | None


@dataclass(frozen=True, slots=True)
class ReferenceEnvelope:
    event_id: str
    profile_id: str
    lane: ReferenceLane
    kind: str
    semantic_time: datetime
    timeframe: Timeframe | None = None
    decision: StrategyDecision | None = None
    engine_event: EngineEvent | None = None
    fields: tuple[StateField, ...] = ()

    def __post_init__(self) -> None:
        _aware(self.semantic_time, "envelope.semantic_time")
        if not self.event_id or not self.profile_id or not self.kind:
            raise ReferenceRuntimeError("envelope identity is incomplete")
        populated = int(self.decision is not None) + int(self.engine_event is not None)
        if populated > 1:
            raise ReferenceRuntimeError(
                "envelope cannot contain decision and engine event together"
            )


@dataclass(frozen=True, slots=True)
class ReferenceRuntimeConfig:
    maximum_catchup_bars: int = 8
    maximum_pending_events: int = 2_000

    def __post_init__(self) -> None:
        if self.maximum_catchup_bars < 1:
            raise ReferenceRuntimeError("maximum_catchup_bars must be positive")
        if self.maximum_pending_events < 1:
            raise ReferenceRuntimeError("maximum_pending_events must be positive")


@dataclass(frozen=True, slots=True)
class ReferenceRuntimeState:
    profile_id: str
    sequence: int
    as_of: datetime
    engine_state: StrategyState
    last_tick: Tick | None = None
    buckets: tuple[RuntimeBucket, ...] = ()
    bar_cursors: tuple[RuntimeBarCursor, ...] = ()
    pending: tuple[ReferenceEnvelope, ...] = ()
    halted: bool = False
    halt_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _aware(self.as_of, "runtime_state.as_of")
        if not self.profile_id or self.sequence < 0:
            raise ReferenceRuntimeError("runtime state identity or sequence is invalid")
        if self.engine_state.profile_id != self.profile_id:
            raise ReferenceRuntimeError("engine state crossed runtime profile")
        bucket_frames = tuple(item.timeframe for item in self.buckets)
        cursor_frames = tuple(item.timeframe for item in self.bar_cursors)
        if len(set(bucket_frames)) != len(bucket_frames):
            raise ReferenceRuntimeError("runtime state contains duplicate buckets")
        if len(set(cursor_frames)) != len(cursor_frames):
            raise ReferenceRuntimeError("runtime state contains duplicate bar cursors")
        if self.halted != bool(self.halt_reasons):
            raise ReferenceRuntimeError("halted state and reasons are inconsistent")


@dataclass(frozen=True, slots=True)
class FastLaneOutput:
    next_state: ReferenceRuntimeState
    bar_requests: tuple[BarRequest, ...] = ()
    events: tuple[ReferenceEnvelope, ...] = ()


@dataclass(frozen=True, slots=True)
class BarLaneOutput:
    next_state: ReferenceRuntimeState
    events: tuple[ReferenceEnvelope, ...] = ()


class SlowLaneSink(Protocol):
    def reconcile(self, profile_id: str, as_of: datetime) -> tuple[ReferenceEnvelope, ...]: ...

    def persist(self, profile_id: str, events: tuple[ReferenceEnvelope, ...]) -> None: ...

    def notify(self, profile_id: str, events: tuple[ReferenceEnvelope, ...]) -> None: ...


@dataclass(frozen=True, slots=True)
class SlowLaneOutput:
    next_state: ReferenceRuntimeState
    delivered: tuple[ReferenceEnvelope, ...] = ()
    error: str | None = None


class ReferenceProfileRuntime:
    """Pure critical lanes with all side effects deferred to the slow lane."""

    def __init__(
        self,
        profile: ProfileConfig,
        engine: PureStrategyEngine,
        guard: TickGuard,
        config: ReferenceRuntimeConfig | None = None,
    ) -> None:
        self.profile = profile
        self.engine = engine
        self.guard = guard
        self.config = config or ReferenceRuntimeConfig()
        if engine.profile != profile:
            raise ReferenceRuntimeError("engine and runtime profile configs differ")

    def initial_state(self, engine_state: StrategyState) -> ReferenceRuntimeState:
        if engine_state.profile_id != self.profile.profile_id:
            raise ReferenceRuntimeError("initial engine state belongs to another profile")
        return ReferenceRuntimeState(
            profile_id=self.profile.profile_id,
            sequence=0,
            as_of=engine_state.as_of,
            engine_state=engine_state,
        )

    def on_tick(self, state: ReferenceRuntimeState, tick: Tick) -> FastLaneOutput:
        self._validate_state(state)
        if state.last_tick is not None and tick.time <= state.last_tick.time:
            if tick.time == state.last_tick.time and tick == state.last_tick:
                return FastLaneOutput(state)
            raise ReferenceRuntimeError("tick time must increase strictly")
        guard = self.guard.evaluate(self.profile, tick)
        sequence = state.sequence + 1
        if not guard.allowed:
            event = self._envelope(
                sequence,
                ReferenceLane.FAST,
                "GUARD_REJECTED",
                tick.time,
                fields=tuple(
                    StateField(f"reason_{index}", reason)
                    for index, reason in enumerate(guard.reasons)
                ),
            )
            next_state = replace(
                state,
                sequence=sequence,
                as_of=max(state.as_of, tick.time),
                last_tick=tick,
                halted=True,
                halt_reasons=guard.reasons,
                pending=self._append_pending(state.pending, (event,)),
            )
            return FastLaneOutput(next_state, events=(event,))

        buckets = {item.timeframe: item.open_time for item in state.buckets}
        requests: list[BarRequest] = []
        catchup_failed: list[str] = []
        for timeframe in _BAR_TIMEFRAMES:
            current_bucket = _bucket_open(tick.time, timeframe)
            previous_bucket = buckets.get(timeframe)
            if previous_bucket is None:
                buckets[timeframe] = current_bucket
                continue
            count = 0
            cursor = previous_bucket
            duration = _DURATIONS[timeframe]
            while cursor + duration <= current_bucket:
                if count >= self.config.maximum_catchup_bars:
                    catchup_failed.append(f"{timeframe.value}_CATCHUP_LIMIT")
                    break
                requests.append(
                    BarRequest(
                        self.profile.profile_id,
                        timeframe,
                        cursor,
                        cursor + duration,
                    )
                )
                cursor += duration
                count += 1
            buckets[timeframe] = current_bucket
        halted = bool(catchup_failed)
        events = (
            (
                self._envelope(
                    sequence,
                    ReferenceLane.FAST,
                    "BAR_CATCHUP_REJECTED",
                    tick.time,
                    fields=tuple(
                        StateField(f"reason_{index}", reason)
                        for index, reason in enumerate(catchup_failed)
                    ),
                ),
            )
            if halted
            else ()
        )
        next_state = replace(
            state,
            sequence=sequence,
            as_of=max(state.as_of, tick.time),
            last_tick=tick,
            buckets=tuple(RuntimeBucket(item, buckets[item]) for item in _BAR_TIMEFRAMES),
            halted=halted,
            halt_reasons=tuple(catchup_failed),
            pending=self._append_pending(state.pending, events),
        )
        return FastLaneOutput(
            next_state,
            bar_requests=(() if halted else tuple(requests)),
            events=events,
        )

    def on_bar_close(
        self,
        state: ReferenceRuntimeState,
        request: BarRequest,
        bar: Bar,
    ) -> BarLaneOutput:
        self._validate_state(state)
        if state.halted:
            raise ReferenceRuntimeError("bar lane is halted by fast-lane guard")
        if request.profile_id != self.profile.profile_id:
            raise ReferenceRuntimeError("bar request crossed profile boundary")
        if bar.open_time != request.open_time or bar.close_time != request.close_time:
            raise ReferenceRuntimeError("closed bar does not match its request")
        cursor = next(
            (item for item in state.bar_cursors if item.timeframe is request.timeframe),
            None,
        )
        if cursor is not None:
            if request.open_time == cursor.open_time:
                return BarLaneOutput(state)
            if request.open_time < cursor.open_time:
                raise ReferenceRuntimeError("closed bar arrived before its cursor")
        engine_output = self.engine.on_bar_close(
            state.engine_state,
            request.timeframe,
            bar,
        )
        engine_output.validate_after(state.engine_state)
        sequence = state.sequence + 1
        envelopes = [
            replace(
                self._envelope(
                    sequence,
                    ReferenceLane.BAR,
                    "BAR_CLOSED",
                    request.close_time,
                    timeframe=request.timeframe,
                ),
                event_id=(
                    f"{self.profile.profile_id}:BAR:{request.timeframe.value}:"
                    f"{request.open_time.isoformat()}"
                ),
            )
        ]
        envelopes.extend(
            self._decision_envelope(sequence, request.timeframe, item)
            for item in engine_output.decisions
        )
        envelopes.extend(
            self._engine_event_envelope(sequence, request.timeframe, item)
            for item in engine_output.events
        )
        cursors = (
            *(item for item in state.bar_cursors if item.timeframe is not request.timeframe),
            RuntimeBarCursor(request.timeframe, request.open_time),
        )
        next_state = replace(
            state,
            sequence=sequence,
            as_of=max(state.as_of, request.close_time),
            engine_state=engine_output.next_state,
            bar_cursors=tuple(
                sorted(cursors, key=lambda item: _BAR_TIMEFRAMES.index(item.timeframe))
            ),
            pending=self._append_pending(state.pending, tuple(envelopes)),
        )
        return BarLaneOutput(next_state, tuple(envelopes))

    def run_slow_lane(
        self,
        state: ReferenceRuntimeState,
        sink: SlowLaneSink,
    ) -> SlowLaneOutput:
        self._validate_state(state)
        try:
            reconciled = sink.reconcile(self.profile.profile_id, state.as_of)
            delivery = state.pending + reconciled
            if delivery:
                sink.persist(self.profile.profile_id, delivery)
                sink.notify(self.profile.profile_id, delivery)
        except Exception as exc:  # slow-lane failure must retain the outbox
            return SlowLaneOutput(state, error=f"{type(exc).__name__}:{exc}")
        next_state = replace(
            state,
            sequence=state.sequence + 1,
            pending=(),
        )
        return SlowLaneOutput(next_state, delivered=delivery)

    def _validate_state(self, state: ReferenceRuntimeState) -> None:
        if state.profile_id != self.profile.profile_id:
            raise ReferenceRuntimeError("runtime state crossed profile boundary")

    def _append_pending(
        self,
        existing: tuple[ReferenceEnvelope, ...],
        values: tuple[ReferenceEnvelope, ...],
    ) -> tuple[ReferenceEnvelope, ...]:
        combined = existing + values
        if len(combined) > self.config.maximum_pending_events:
            raise ReferenceRuntimeError("in-memory event outbox capacity exceeded")
        return combined

    def _envelope(
        self,
        sequence: int,
        lane: ReferenceLane,
        kind: str,
        semantic_time: datetime,
        *,
        timeframe: Timeframe | None = None,
        fields: tuple[StateField, ...] = (),
    ) -> ReferenceEnvelope:
        suffix = timeframe.value if timeframe is not None else "NONE"
        return ReferenceEnvelope(
            event_id=f"{self.profile.profile_id}:{lane.value}:{sequence}:{kind}:{suffix}",
            profile_id=self.profile.profile_id,
            lane=lane,
            kind=kind,
            semantic_time=semantic_time,
            timeframe=timeframe,
            fields=fields,
        )

    def _decision_envelope(
        self,
        sequence: int,
        timeframe: Timeframe,
        decision: StrategyDecision,
    ) -> ReferenceEnvelope:
        return replace(
            self._envelope(
                sequence,
                ReferenceLane.BAR,
                "DECISION",
                decision.available_at,
                timeframe=timeframe,
            ),
            event_id=f"{self.profile.profile_id}:DECISION:{decision.decision_id}",
            decision=decision,
        )

    def _engine_event_envelope(
        self,
        sequence: int,
        timeframe: Timeframe,
        event: EngineEvent,
    ) -> ReferenceEnvelope:
        return replace(
            self._envelope(
                sequence,
                ReferenceLane.BAR,
                "ENGINE_EVENT",
                event.available_at,
                timeframe=timeframe,
            ),
            event_id=f"{self.profile.profile_id}:ENGINE:{event.event_id}",
            engine_event=event,
        )


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReferenceRuntimeError(f"{field} must include an explicit UTC offset")


def _bucket_open(value: datetime, timeframe: Timeframe) -> datetime:
    _aware(value, "bucket.time")
    if timeframe is Timeframe.D1:
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    if timeframe is Timeframe.H1:
        return value.replace(minute=0, second=0, microsecond=0)
    minutes = {Timeframe.M15: 15, Timeframe.M5: 5, Timeframe.M1: 1}[timeframe]
    return value.replace(
        minute=value.minute - value.minute % minutes,
        second=0,
        microsecond=0,
    )


IsolatedStepValue: TypeAlias = object


@dataclass(frozen=True, slots=True)
class IsolatedProfileStep:
    profile_id: str
    callback: Callable[[], IsolatedStepValue]

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ReferenceRuntimeError("isolated step profile_id is required")


@dataclass(frozen=True, slots=True)
class IsolatedStepsOutput:
    completed: tuple[tuple[str, IsolatedStepValue], ...]
    failed: tuple[tuple[str, str], ...]
    stalled: tuple[str, ...]


def run_isolated_profile_steps(
    steps: tuple[IsolatedProfileStep, ...],
    *,
    timeout_seconds: float,
) -> IsolatedStepsOutput:
    if timeout_seconds <= 0:
        raise ReferenceRuntimeError("isolation timeout must be positive")
    profile_ids = tuple(item.profile_id for item in steps)
    if len(set(profile_ids)) != len(profile_ids):
        raise ReferenceRuntimeError("isolated profile steps must have unique IDs")
    results: queue.Queue[tuple[str, bool, object]] = queue.Queue()

    def execute(step: IsolatedProfileStep) -> None:
        try:
            results.put((step.profile_id, True, step.callback()))
        except Exception as exc:
            results.put((step.profile_id, False, f"{type(exc).__name__}:{exc}"))

    threads = [
        threading.Thread(target=execute, args=(step,), daemon=True, name=f"gold-{step.profile_id}")
        for step in steps
    ]
    for thread in threads:
        thread.start()
    deadline = monotonic() + timeout_seconds
    completed: list[tuple[str, object]] = []
    failed: list[tuple[str, str]] = []
    received: set[str] = set()
    while len(received) < len(steps):
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        try:
            profile_id, ok, value = results.get(timeout=remaining)
        except queue.Empty:
            break
        received.add(profile_id)
        if ok:
            completed.append((profile_id, value))
        else:
            failed.append((profile_id, str(value)))
    stalled = tuple(sorted(set(profile_ids) - received))
    return IsolatedStepsOutput(
        completed=tuple(sorted(completed, key=lambda item: item[0])),
        failed=tuple(sorted(failed, key=lambda item: item[0])),
        stalled=stalled,
    )
