from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from .contracts import Bar, Side, SignalPlan, Tick, Timeframe
from .profile import canonical_sha256
from .reference_runtime import ReferenceEnvelope, ReferenceProfileRuntime, ReferenceRuntimeState


class CausalReplayError(ValueError):
    """Raised when replay data would permit lookahead or ambiguous identity."""


_DURATIONS = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.D1: timedelta(days=1),
}


@dataclass(frozen=True, slots=True)
class ReplayBar:
    timeframe: Timeframe
    bar: Bar

    def __post_init__(self) -> None:
        expected = _DURATIONS.get(self.timeframe)
        if expected is None:
            raise CausalReplayError(f"unsupported replay timeframe: {self.timeframe}")
        if self.bar.close_time - self.bar.open_time != expected:
            raise CausalReplayError("bar duration does not match timeframe")


@dataclass(frozen=True, slots=True)
class CausalReplayDataset:
    profile_id: str
    profile_fingerprint: str
    symbol: str
    ticks: tuple[Tick, ...]
    bars: tuple[ReplayBar, ...]
    warmup_until: datetime
    replay_end: datetime

    def __post_init__(self) -> None:
        _aware(self.warmup_until, "dataset.warmup_until")
        _aware(self.replay_end, "dataset.replay_end")
        if not self.profile_id or len(self.profile_fingerprint) != 64 or not self.symbol:
            raise CausalReplayError("dataset profile identity is invalid")
        if self.warmup_until > self.replay_end:
            raise CausalReplayError("warmup_until cannot exceed replay_end")
        tick_times = tuple(item.time for item in self.ticks)
        if tick_times != tuple(sorted(set(tick_times))):
            raise CausalReplayError("ticks must have unique ascending times")
        identities = tuple((item.timeframe, item.bar.open_time) for item in self.bars)
        if len(set(identities)) != len(identities):
            raise CausalReplayError("dataset contains duplicate bars")
        if any(item.bar.close_time > self.replay_end for item in self.bars):
            # Future/possibly-forming bars may be retained in source exports, but
            # they must be explicitly outside the tradable dataset.
            return


@dataclass(frozen=True, slots=True)
class CausalReplayReport:
    profile_id: str
    profile_fingerprint: str
    symbol: str
    from_time: datetime
    to_time: datetime
    tick_count: int
    closed_bar_count: int
    decision_count: int
    warmup_suppressed_decisions: int
    event_hash: str
    events: tuple[ReferenceEnvelope, ...]
    final_state: ReferenceRuntimeState


class ReplayTradeResult(StrEnum):
    TARGET = "TARGET"
    STOP = "STOP"
    OPEN = "OPEN"
    NO_POST_ENTRY_PATH = "NO_POST_ENTRY_PATH"


@dataclass(frozen=True, slots=True)
class ReplayTradeOutcome:
    signal_id: str
    result: ReplayTradeResult
    resolved_at: datetime | None
    resolved_price: Decimal | None
    source: str


class ReferenceRuntimeReplay:
    """Feeds the exact event-driven runtime used by incremental reference live."""

    def __init__(self, runtime: ReferenceProfileRuntime) -> None:
        self.runtime = runtime

    def run(
        self,
        dataset: CausalReplayDataset,
        initial_state: ReferenceRuntimeState,
    ) -> CausalReplayReport:
        profile = self.runtime.profile
        if (
            dataset.profile_id != profile.profile_id
            or dataset.profile_fingerprint != profile.manifest_fingerprint
            or dataset.symbol != profile.symbol
        ):
            raise CausalReplayError("dataset crossed runtime profile contract")
        if initial_state.profile_id != profile.profile_id:
            raise CausalReplayError("initial state crossed runtime profile")
        bar_index = {
            (item.timeframe, item.bar.open_time): item.bar
            for item in dataset.bars
            if item.bar.close_time <= dataset.replay_end
        }
        ticks = tuple(item for item in dataset.ticks if item.time <= dataset.replay_end)
        if not ticks:
            raise CausalReplayError("replay requires at least one closed-path tick")
        state = initial_state
        events: list[ReferenceEnvelope] = []
        closed_bars = 0
        for tick in ticks:
            fast = self.runtime.on_tick(state, tick)
            state = fast.next_state
            events.extend(fast.events)
            for request in fast.bar_requests:
                bar = bar_index.get((request.timeframe, request.open_time))
                if bar is None:
                    raise CausalReplayError(
                        f"closed bar unavailable: {request.timeframe.value} "
                        f"{request.open_time.isoformat()}"
                    )
                if bar.close_time > tick.time:
                    raise CausalReplayError("replay attempted to read a future bar")
                output = self.runtime.on_bar_close(state, request, bar)
                state = output.next_state
                events.extend(output.events)
                closed_bars += 1
        decision_count = sum(item.decision is not None for item in events)
        suppressed = sum(
            item.decision is not None and item.semantic_time < dataset.warmup_until
            for item in events
        )
        event_hash = str(
            canonical_sha256(
                [
                    {
                        "event_id": item.event_id,
                        "kind": item.kind,
                        "lane": item.lane.value,
                        "semantic_time": item.semantic_time.isoformat(),
                        "timeframe": item.timeframe.value if item.timeframe else None,
                    }
                    for item in events
                ]
            )
        )
        return CausalReplayReport(
            profile_id=profile.profile_id,
            profile_fingerprint=profile.manifest_fingerprint,
            symbol=profile.symbol,
            from_time=ticks[0].time,
            to_time=ticks[-1].time,
            tick_count=len(ticks),
            closed_bar_count=closed_bars,
            decision_count=decision_count,
            warmup_suppressed_decisions=suppressed,
            event_hash=event_hash,
            events=tuple(events),
            final_state=state,
        )


def resolve_signal_path(
    plan: SignalPlan,
    *,
    ticks: tuple[Tick, ...] = (),
    bars: tuple[Bar, ...] = (),
) -> ReplayTradeOutcome:
    post_ticks = tuple(item for item in ticks if item.time >= plan.entry_ready_at)
    for item in post_ticks:
        if plan.side is Side.BUY:
            stop_hit = item.bid <= plan.planned_stop
            target_hit = item.bid >= plan.planned_target
            stop_price, target_price = item.bid, item.bid
        else:
            stop_hit = item.ask >= plan.planned_stop
            target_hit = item.ask <= plan.planned_target
            stop_price, target_price = item.ask, item.ask
        if stop_hit:
            return ReplayTradeOutcome(
                plan.signal_id,
                ReplayTradeResult.STOP,
                item.time,
                stop_price,
                "TICK",
            )
        if target_hit:
            return ReplayTradeOutcome(
                plan.signal_id,
                ReplayTradeResult.TARGET,
                item.time,
                target_price,
                "TICK",
            )
    post_bars = tuple(item for item in bars if item.close_time > plan.entry_ready_at)
    for item in post_bars:
        stop_hit = (
            item.low <= plan.planned_stop
            if plan.side is Side.BUY
            else item.high >= plan.planned_stop
        )
        target_hit = (
            item.high >= plan.planned_target
            if plan.side is Side.BUY
            else item.low <= plan.planned_target
        )
        if stop_hit:  # conservative same-bar policy: STOP wins ambiguity
            return ReplayTradeOutcome(
                plan.signal_id,
                ReplayTradeResult.STOP,
                item.close_time,
                plan.planned_stop,
                "BAR_CONSERVATIVE",
            )
        if target_hit:
            return ReplayTradeOutcome(
                plan.signal_id,
                ReplayTradeResult.TARGET,
                item.close_time,
                plan.planned_target,
                "BAR_CONSERVATIVE",
            )
    if post_ticks or post_bars:
        return ReplayTradeOutcome(
            plan.signal_id,
            ReplayTradeResult.OPEN,
            None,
            None,
            "UNRESOLVED",
        )
    return ReplayTradeOutcome(
        plan.signal_id,
        ReplayTradeResult.NO_POST_ENTRY_PATH,
        None,
        None,
        "NONE",
    )


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CausalReplayError(f"{field} must include an explicit UTC offset")
