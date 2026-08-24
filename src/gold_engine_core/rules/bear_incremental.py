from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import cast

from ..contracts import ProfileConfig, Timeframe
from .bear import BearAction, BearBar, BearDecision, _as_float, _as_int
from .bear_multitimeframe import BearMultiTimeframeReplay


class BearIncrementalError(ValueError):
    """Raised when incremental Bear state or input is inconsistent."""


def _as_datetime(value: object) -> datetime:
    return cast(datetime, value)


class BearIncrementalPhase(StrEnum):
    IDLE = "IDLE"
    WATCH_H1 = "WATCH_H1"
    WATCH_M5 = "WATCH_M5"
    WATCH_M1 = "WATCH_M1"
    ENTRY_READY = "ENTRY_READY"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class BearEvidence:
    name: str
    value: str | int | float | bool | datetime | None

    def __post_init__(self) -> None:
        if not self.name:
            raise BearIncrementalError("evidence name is required")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise BearIncrementalError("evidence float must be finite")
        if isinstance(self.value, datetime):
            _require_aware(self.value, f"evidence.{self.name}")


@dataclass(frozen=True, slots=True)
class BearProcessedBar:
    timeframe: Timeframe
    open_time: datetime

    def __post_init__(self) -> None:
        _require_aware(self.open_time, "processed_bar.open_time")


@dataclass(frozen=True, slots=True)
class BearArmState:
    armed_at: datetime
    atr: float
    touches: int
    rejections: int
    recent_high: float

    def __post_init__(self) -> None:
        _require_aware(self.armed_at, "arm.armed_at")
        if self.atr <= 0 or not math.isfinite(self.atr):
            raise BearIncrementalError("arm ATR must be finite and positive")
        if self.touches < 0 or self.rejections < 0:
            raise BearIncrementalError("arm evidence counts cannot be negative")

    @classmethod
    def from_rule_payload(cls, payload: dict[str, object]) -> BearArmState:
        return cls(
            armed_at=_as_datetime(payload["armed_at"]),
            atr=_as_float(payload["atr"]),
            touches=_as_int(payload["touches"]),
            rejections=_as_int(payload["rejections"]),
            recent_high=_as_float(payload["recent_high"]),
        )

    def to_rule_payload(self) -> dict[str, object]:
        return {
            "state": "ARMED",
            "armed_at": self.armed_at,
            "atr": self.atr,
            "touches": self.touches,
            "rejections": self.rejections,
            "recent_high": self.recent_high,
        }


@dataclass(frozen=True, slots=True)
class BearIncrementalSignal:
    profile_id: str
    setup_id: str
    signal_id: str
    symbol: str
    setup_time: datetime
    armed_at: datetime
    opened_at: datetime
    entry: float
    stop: float
    target: float
    structural_stop: float
    structural_target: float
    m5_touches: int
    m5_rejections: int
    m1_touches: int
    reason: str

    def __post_init__(self) -> None:
        for name, value in (
            ("setup_time", self.setup_time),
            ("armed_at", self.armed_at),
            ("opened_at", self.opened_at),
        ):
            _require_aware(value, f"signal.{name}")
        if not self.setup_time <= self.armed_at <= self.opened_at:
            raise BearIncrementalError("signal timestamps are not causal")
        if not self.target < self.entry < self.stop:
            raise BearIncrementalError("SELL signal geometry is invalid")
        if not self.setup_id.startswith(f"{self.profile_id}:"):
            raise BearIncrementalError("signal setup_id is not profile-namespaced")

    @classmethod
    def from_rule_payload(
        cls,
        *,
        profile_id: str,
        symbol: str,
        setup_id: str,
        setup: BearDecision,
        payload: dict[str, object],
    ) -> BearIncrementalSignal:
        opened_at = _as_datetime(payload["opened_at"])
        entry = _as_float(payload["entry"])
        return cls(
            profile_id=profile_id,
            setup_id=setup_id,
            signal_id=f"{profile_id}:BEAR:{opened_at.isoformat()}:{entry:.8f}",
            symbol=symbol,
            setup_time=setup.time,
            armed_at=_as_datetime(payload["armed_at"]),
            opened_at=opened_at,
            entry=entry,
            stop=_as_float(payload["stop"]),
            target=_as_float(payload["target"]),
            structural_stop=_as_float(payload["structural_stop"]),
            structural_target=_as_float(payload["structural_target"]),
            m5_touches=_as_int(payload["m5_touches"]),
            m5_rejections=_as_int(payload["m5_rejections"]),
            m1_touches=_as_int(payload["m1_touches"]),
            reason=setup.reason,
        )


@dataclass(frozen=True, slots=True)
class BearIncrementalEvent:
    event_id: str
    available_at: datetime
    profile_id: str
    setup_id: str | None
    from_phase: BearIncrementalPhase
    to_phase: BearIncrementalPhase
    reason: str

    def __post_init__(self) -> None:
        _require_aware(self.available_at, "event.available_at")
        if not self.event_id or not self.profile_id or not self.reason:
            raise BearIncrementalError("event identity and reason are required")


@dataclass(frozen=True, slots=True)
class BearIncrementalState:
    profile_id: str
    phase: BearIncrementalPhase
    sequence: int
    as_of: datetime
    setup_id: str | None = None
    setup_time: datetime | None = None
    level: float | None = None
    entry_zone: tuple[float, float] | None = None
    invalidation: float | None = None
    touches: int = 0
    rejections: int = 0
    acceptance: bool = False
    last_processed_bars: tuple[BearProcessedBar, ...] = ()
    evidence: tuple[BearEvidence, ...] = ()
    setup: BearDecision | None = None
    arm: BearArmState | None = None
    signal: BearIncrementalSignal | None = None
    last_setup_time: datetime | None = None
    m1_bars: tuple[BearBar, ...] = ()
    m5_bars: tuple[BearBar, ...] = ()
    m15_bars: tuple[BearBar, ...] = ()
    h1_bars: tuple[BearBar, ...] = ()

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "state.as_of")
        if not self.profile_id or self.sequence < 0:
            raise BearIncrementalError("state identity or sequence is invalid")
        if self.setup_time is not None:
            _require_aware(self.setup_time, "state.setup_time")
        if self.last_setup_time is not None:
            _require_aware(self.last_setup_time, "state.last_setup_time")
        if self.touches < 0 or self.rejections < 0:
            raise BearIncrementalError("state evidence counts cannot be negative")
        if self.phase is not BearIncrementalPhase.IDLE and self.setup_id is None:
            raise BearIncrementalError("active Bear phase requires setup_id")


@dataclass(frozen=True, slots=True)
class BearIncrementalOutput:
    next_state: BearIncrementalState
    events: tuple[BearIncrementalEvent, ...] = ()
    signal: BearIncrementalSignal | None = None


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BearIncrementalError(f"{field} must include an explicit UTC offset")


_DURATIONS = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
}
_PRIORITY = {Timeframe.H1: 0, Timeframe.M5: 1, Timeframe.M1: 2, Timeframe.M15: 3}


class BearIncrementalMachine:
    """Bounded, state-explicit Bear evaluator for bar-by-bar live use."""

    def __init__(self, profile: ProfileConfig, replay: BearMultiTimeframeReplay) -> None:
        self.profile = profile
        self.replay = replay
        if abs(float(profile.tick_size) - replay.config.price_tick) > 1e-12:
            raise BearIncrementalError("profile tick_size differs from Bear rule config")
        if replay.config.spread_floor < 0:
            raise BearIncrementalError("Bear spread floor cannot be negative")
        self._limits = {
            Timeframe.M1: 20 + replay.config.m1_entry_bars + 5,
            Timeframe.M5: 20 + replay.config.m5_watch_bars + 8,
            Timeframe.M15: replay.setup_engine.minimum_bars + 8,
            Timeframe.H1: replay.config.h1_sma_period + 3,
        }

    @property
    def maximum_warmup_span(self) -> timedelta:
        return max(
            timedelta(minutes=self._limits[Timeframe.M1]),
            timedelta(minutes=5 * self._limits[Timeframe.M5]),
            timedelta(minutes=15 * self._limits[Timeframe.M15]),
            timedelta(hours=self._limits[Timeframe.H1]),
        )

    def initial_state(self, as_of: datetime) -> BearIncrementalState:
        _require_aware(as_of, "initial_state.as_of")
        return BearIncrementalState(
            profile_id=self.profile.profile_id,
            phase=BearIncrementalPhase.IDLE,
            sequence=0,
            as_of=as_of,
        )

    def on_bar_close(
        self,
        state: BearIncrementalState,
        timeframe: Timeframe,
        bar: BearBar,
    ) -> BearIncrementalOutput:
        if state.profile_id != self.profile.profile_id:
            raise BearIncrementalError("state belongs to another profile")
        if timeframe not in _DURATIONS:
            raise BearIncrementalError(f"unsupported Bear timeframe: {timeframe}")
        _require_aware(bar.time, "bar.time")
        previous_open = self._last_processed(state, timeframe)
        if previous_open is not None:
            if bar.time == previous_open:
                return BearIncrementalOutput(state)
            if bar.time < previous_open:
                raise BearIncrementalError("bar arrived before the processed cursor")

        current = self._reset_terminal(state)
        available_at = bar.time + _DURATIONS[timeframe]
        current = self._append_bar(current, timeframe, bar, available_at)
        current, events, signal = self._advance(current)
        return BearIncrementalOutput(current, events, signal)

    def feed_closed_batches(
        self,
        state: BearIncrementalState,
        *,
        m1_bars: tuple[BearBar, ...],
        m5_bars: tuple[BearBar, ...],
        m15_bars: tuple[BearBar, ...],
        h1_bars: tuple[BearBar, ...],
        available_at: datetime,
        emit_after: datetime,
    ) -> BearIncrementalOutput:
        _require_aware(available_at, "feed.available_at")
        _require_aware(emit_after, "feed.emit_after")
        items = [
            (bar.time + _DURATIONS[timeframe], _PRIORITY[timeframe], timeframe, bar)
            for timeframe, bars in (
                (Timeframe.M1, m1_bars),
                (Timeframe.M5, m5_bars),
                (Timeframe.M15, m15_bars),
                (Timeframe.H1, h1_bars),
            )
            for bar in bars
            if bar.time + _DURATIONS[timeframe] <= available_at
        ]
        current = state
        events: list[BearIncrementalEvent] = []
        latest_signal: BearIncrementalSignal | None = None
        for _, _, timeframe, bar in sorted(items, key=lambda item: (item[0], item[1])):
            previous_open = self._last_processed(current, timeframe)
            if previous_open is not None and bar.time <= previous_open:
                continue
            output = self.on_bar_close(current, timeframe, bar)
            current = output.next_state
            events.extend(output.events)
            if output.signal is None:
                continue
            if output.signal.opened_at >= emit_after:
                latest_signal = output.signal
            else:
                current = self._reset_terminal(current)
        return BearIncrementalOutput(current, tuple(events), latest_signal)

    def _advance(
        self, state: BearIncrementalState
    ) -> tuple[
        BearIncrementalState,
        tuple[BearIncrementalEvent, ...],
        BearIncrementalSignal | None,
    ]:
        current = state
        events: list[BearIncrementalEvent] = []
        signal: BearIncrementalSignal | None = None
        if current.phase is BearIncrementalPhase.IDLE:
            setup = self._next_setup(current)
            if setup is None:
                return current, (), None
            setup_available = setup.time + timedelta(minutes=15)
            setup_id = f"{self.profile.profile_id}:BEAR:{setup.time.isoformat()}"
            current, event = self._transition(
                replace(
                    current,
                    setup_id=setup_id,
                    setup_time=setup.time,
                    level=setup.resistance,
                    entry_zone=(
                        min(_as_float(setup.entry), _as_float(setup.resistance)),
                        max(_as_float(setup.entry), _as_float(setup.resistance)),
                    ),
                    invalidation=setup.stop,
                    setup=setup,
                    last_setup_time=setup.time,
                    evidence=(BearEvidence("setup_available", setup_available),),
                ),
                BearIncrementalPhase.WATCH_H1,
                "M15_SETUP_ACCEPTED",
            )
            events.append(event)

        if current.phase is BearIncrementalPhase.WATCH_H1:
            setup_available = self._setup_available(current)
            h1_history = tuple(
                bar for bar in current.h1_bars if bar.time + timedelta(hours=1) <= setup_available
            )[-(self.replay.config.h1_sma_period + 2) :]
            if not self.replay._h1_bearish(h1_history):
                current, event = self._transition(
                    replace(current, evidence=(BearEvidence("h1_bars", len(h1_history)),)),
                    BearIncrementalPhase.CANCELLED,
                    "H1_BEARISH_CONTEXT_REJECTED",
                )
                events.append(event)
                return current, tuple(events), None
            current, event = self._transition(
                replace(current, evidence=(BearEvidence("h1_bars", len(h1_history)),)),
                BearIncrementalPhase.WATCH_M5,
                "H1_BEARISH_CONTEXT_ACCEPTED",
            )
            events.append(event)

        if current.phase is BearIncrementalPhase.WATCH_M5:
            setup = self._require_setup(current)
            setup_available = self._setup_available(current)
            m5_times = [bar.time for bar in current.m5_bars]
            m5_index = bisect.bisect_left(m5_times, setup_available)
            validation_start = max(0, m5_index - 3)
            candidates = current.m5_bars[
                validation_start : validation_start + self.replay.config.m5_watch_bars
            ]
            result = self.replay._arm_on_m5(
                setup,
                current.m5_bars[max(0, validation_start - 20) : validation_start],
                candidates,
                setup_available,
            )
            state_value = str(result.get("state") or "EXPIRED")
            touches = _as_int(result.get("touches") or 0)
            rejections = _as_int(result.get("rejections") or 0)
            current = replace(
                current,
                touches=touches,
                rejections=rejections,
                acceptance=state_value == "CANCELLED" and result.get("reason") == "M5_ACCEPTANCE",
                evidence=(BearEvidence("observed_m5_bars", len(candidates)),),
            )
            if state_value == "CANCELLED":
                current, event = self._transition(
                    current,
                    BearIncrementalPhase.CANCELLED,
                    str(result.get("reason") or "M5_VALIDATION_CANCELLED"),
                )
                events.append(event)
                return current, tuple(events), None
            if state_value == "ARMED":
                arm = BearArmState.from_rule_payload(result)
                current, event = self._transition(
                    replace(current, arm=arm),
                    BearIncrementalPhase.WATCH_M1,
                    "M5_REJECTION_ARMED",
                )
                events.append(event)
            elif len(candidates) >= self.replay.config.m5_watch_bars:
                current, event = self._transition(
                    current,
                    BearIncrementalPhase.CANCELLED,
                    "M5_WATCH_WINDOW_EXPIRED",
                )
                events.append(event)
                return current, tuple(events), None
            else:
                return current, tuple(events), None

        if current.phase is BearIncrementalPhase.WATCH_M1:
            setup = self._require_setup(current)
            arm = self._require_arm(current)
            m1_times = [bar.time for bar in current.m1_bars]
            m1_index = bisect.bisect_left(m1_times, arm.armed_at)
            candidates = current.m1_bars[m1_index : m1_index + self.replay.config.m1_entry_bars]
            plan = self.replay._entry_on_m1(
                setup,
                arm.to_rule_payload(),
                current.m1_bars[max(0, m1_index - 20) : m1_index],
                candidates,
            )
            if plan is not None:
                signal = BearIncrementalSignal.from_rule_payload(
                    profile_id=self.profile.profile_id,
                    symbol=self.profile.symbol,
                    setup_id=current.setup_id or "",
                    setup=setup,
                    payload=plan,
                )
                current, event = self._transition(
                    replace(
                        current,
                        signal=signal,
                        touches=signal.m5_touches,
                        rejections=signal.m5_rejections,
                        evidence=(
                            BearEvidence("m1_touches", signal.m1_touches),
                            BearEvidence("entry", signal.entry),
                            BearEvidence("stop", signal.stop),
                            BearEvidence("target", signal.target),
                        ),
                    ),
                    BearIncrementalPhase.ENTRY_READY,
                    "M1_ENTRY_CONFIRMATION_READY",
                )
                events.append(event)
                return current, tuple(events), signal
            if len(candidates) >= self.replay.config.m1_entry_bars:
                current, event = self._transition(
                    replace(
                        current,
                        evidence=(BearEvidence("observed_m1_bars", len(candidates)),),
                    ),
                    BearIncrementalPhase.CANCELLED,
                    "M1_WATCH_WINDOW_EXPIRED_OR_INVALIDATED",
                )
                events.append(event)
            return current, tuple(events), None

        return current, tuple(events), signal

    def _next_setup(self, state: BearIncrementalState) -> BearDecision | None:
        if len(state.m15_bars) < self.replay.setup_engine.minimum_bars:
            return None
        candidates = [
            setup
            for setup in self.replay.setup_engine.scan(state.m15_bars)
            if setup.action is BearAction.SELL
            and (state.last_setup_time is None or setup.time > state.last_setup_time)
            and setup.time + timedelta(minutes=15) <= state.as_of
        ]
        if not candidates:
            return None
        setup = min(candidates, key=lambda item: item.time)
        if setup.symbol != self.profile.symbol:
            raise BearIncrementalError("Bear setup symbol crossed profile boundary")
        return setup

    def _append_bar(
        self,
        state: BearIncrementalState,
        timeframe: Timeframe,
        bar: BearBar,
        available_at: datetime,
    ) -> BearIncrementalState:
        cursors = (
            *(item for item in state.last_processed_bars if item.timeframe is not timeframe),
            BearProcessedBar(timeframe, bar.time),
        )
        values = {
            Timeframe.M1: state.m1_bars,
            Timeframe.M5: state.m5_bars,
            Timeframe.M15: state.m15_bars,
            Timeframe.H1: state.h1_bars,
        }
        updated = (values[timeframe] + (bar,))[-self._limits[timeframe] :]
        common = replace(
            state,
            sequence=state.sequence + 1,
            as_of=max(state.as_of, available_at),
            last_processed_bars=tuple(sorted(cursors, key=lambda item: _PRIORITY[item.timeframe])),
        )
        if timeframe is Timeframe.M1:
            return replace(common, m1_bars=updated)
        if timeframe is Timeframe.M5:
            return replace(common, m5_bars=updated)
        if timeframe is Timeframe.M15:
            return replace(common, m15_bars=updated)
        return replace(common, h1_bars=updated)

    def _transition(
        self,
        state: BearIncrementalState,
        phase: BearIncrementalPhase,
        reason: str,
    ) -> tuple[BearIncrementalState, BearIncrementalEvent]:
        previous = state.phase
        next_state = replace(state, phase=phase)
        event = BearIncrementalEvent(
            event_id=(
                f"{self.profile.profile_id}:BEAR:{state.sequence}:"
                f"{previous.value}:{phase.value}:{reason}"
            ),
            available_at=state.as_of,
            profile_id=self.profile.profile_id,
            setup_id=state.setup_id,
            from_phase=previous,
            to_phase=phase,
            reason=reason,
        )
        return next_state, event

    @staticmethod
    def _last_processed(state: BearIncrementalState, timeframe: Timeframe) -> datetime | None:
        return next(
            (item.open_time for item in state.last_processed_bars if item.timeframe is timeframe),
            None,
        )

    @staticmethod
    def _reset_terminal(state: BearIncrementalState) -> BearIncrementalState:
        if state.phase not in {
            BearIncrementalPhase.ENTRY_READY,
            BearIncrementalPhase.CANCELLED,
        }:
            return state
        return replace(
            state,
            phase=BearIncrementalPhase.IDLE,
            setup_id=None,
            setup_time=None,
            level=None,
            entry_zone=None,
            invalidation=None,
            touches=0,
            rejections=0,
            acceptance=False,
            evidence=(),
            setup=None,
            arm=None,
            signal=None,
        )

    @staticmethod
    def _require_setup(state: BearIncrementalState) -> BearDecision:
        if state.setup is None:
            raise BearIncrementalError("active state is missing Bear setup")
        return state.setup

    @staticmethod
    def _require_arm(state: BearIncrementalState) -> BearArmState:
        if state.arm is None:
            raise BearIncrementalError("WATCH_M1 state is missing M5 arm evidence")
        return state.arm

    @staticmethod
    def _setup_available(state: BearIncrementalState) -> datetime:
        if state.setup_time is None:
            raise BearIncrementalError("active state is missing setup_time")
        return state.setup_time + timedelta(minutes=15)
