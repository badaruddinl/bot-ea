from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, TypeAlias, runtime_checkable

from .profile import ProfileManifest, TradeMode


class ContractError(ValueError):
    """Raised when a portable engine contract violates an invariant."""


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    H1 = "H1"
    D1 = "D1"
    W1 = "W1"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class StrategyKind(StrEnum):
    REVISED = "REVISED"
    BEAR = "BEAR"


class StrategyPhase(StrEnum):
    COLD = "COLD"
    IDLE = "IDLE"
    WATCH = "WATCH"
    ENTRY_READY = "ENTRY_READY"
    POSITION_OPEN = "POSITION_OPEN"
    CANCELLED = "CANCELLED"


class DecisionAction(StrEnum):
    WAIT = "WAIT"
    WATCH = "WATCH"
    ENTRY_READY = "ENTRY_READY"
    CANCEL = "CANCEL"
    HOLD = "HOLD"
    MODIFY = "MODIFY"
    CLOSE = "CLOSE"


class EngineEventType(StrEnum):
    WARMUP_COMPLETED = "WARMUP_COMPLETED"
    STATE_TRANSITION = "STATE_TRANSITION"
    SETUP_CREATED = "SETUP_CREATED"
    SETUP_CANCELLED = "SETUP_CANCELLED"
    SIGNAL_READY = "SIGNAL_READY"
    POSITION_UPDATED = "POSITION_UPDATED"
    POSITION_CLOSED = "POSITION_CLOSED"


class PositionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


StateValue: TypeAlias = str | int | bool | Decimal | datetime | None


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field} must include an explicit UTC offset")


def _positive_decimal(value: Decimal, field: str, *, allow_zero: bool = False) -> None:
    if not value.is_finite():
        raise ContractError(f"{field} must be finite")
    valid = value >= 0 if allow_zero else value > 0
    if not valid:
        relation = ">= 0" if allow_zero else "> 0"
        raise ContractError(f"{field} must be {relation}")


def _finite_float(value: float, field: str, *, allow_zero: bool = True) -> None:
    if not math.isfinite(value):
        raise ContractError(f"{field} must be finite")
    valid = value >= 0 if allow_zero else value > 0
    if not valid:
        relation = ">= 0" if allow_zero else "> 0"
        raise ContractError(f"{field} must be {relation}")


@dataclass(frozen=True, slots=True)
class Bar:
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    tick_volume: int
    spread: Decimal

    def __post_init__(self) -> None:
        _aware(self.open_time, "bar.open_time")
        _aware(self.close_time, "bar.close_time")
        if self.close_time <= self.open_time:
            raise ContractError("bar.close_time must be after open_time")
        for name, value in (
            ("open", self.open),
            ("high", self.high),
            ("low", self.low),
            ("close", self.close),
        ):
            _positive_decimal(value, f"bar.{name}")
        _positive_decimal(self.spread, "bar.spread", allow_zero=True)
        if self.tick_volume < 0:
            raise ContractError("bar.tick_volume must be >= 0")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ContractError("bar OHLC envelope is invalid")
        if self.high < self.low:
            raise ContractError("bar.high must be >= low")


@dataclass(frozen=True, slots=True)
class Tick:
    time: datetime
    bid: Decimal
    ask: Decimal
    last: Decimal | None = None
    volume: float = 0.0

    def __post_init__(self) -> None:
        _aware(self.time, "tick.time")
        _positive_decimal(self.bid, "tick.bid")
        _positive_decimal(self.ask, "tick.ask")
        if self.ask < self.bid:
            raise ContractError("tick.ask must be >= bid")
        if self.last is not None:
            _positive_decimal(self.last, "tick.last")
        _finite_float(self.volume, "tick.volume")

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


@dataclass(frozen=True, slots=True)
class BarSeries:
    timeframe: Timeframe
    bars: tuple[Bar, ...]

    def __post_init__(self) -> None:
        if not self.bars:
            raise ContractError("bar series cannot be empty")
        close_times = tuple(bar.close_time for bar in self.bars)
        if close_times != tuple(sorted(set(close_times))):
            raise ContractError("bar series must have unique ascending close times")


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    profile_id: str
    symbol: str
    available_at: datetime
    series: tuple[BarSeries, ...]
    tick: Tick | None = None

    def __post_init__(self) -> None:
        _aware(self.available_at, "snapshot.available_at")
        if not self.profile_id or not self.symbol:
            raise ContractError("snapshot profile_id and symbol are required")
        timeframes = tuple(item.timeframe for item in self.series)
        if len(set(timeframes)) != len(timeframes):
            raise ContractError("snapshot cannot contain duplicate timeframes")
        if any(bar.close_time > self.available_at for item in self.series for bar in item.bars):
            raise ContractError("snapshot contains a bar unavailable at available_at")
        if self.tick is not None and self.tick.time > self.available_at:
            raise ContractError("snapshot contains a future tick")

    def bars(self, timeframe: Timeframe) -> tuple[Bar, ...]:
        for item in self.series:
            if item.timeframe is timeframe:
                return item.bars
        return ()


@dataclass(frozen=True, slots=True)
class WarmupRequirement:
    timeframe: Timeframe
    bars: int

    def __post_init__(self) -> None:
        if self.bars <= 0:
            raise ContractError("warmup bars must be positive")


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    strategy_id: str
    strategy_version: str
    kind: StrategyKind
    warmup: tuple[WarmupRequirement, ...]
    maximum_history_bars: int

    def __post_init__(self) -> None:
        if not self.strategy_id or not self.strategy_version:
            raise ContractError("strategy identity and version are required")
        if not self.warmup:
            raise ContractError("strategy requires bounded warmup")
        timeframes = tuple(item.timeframe for item in self.warmup)
        if len(set(timeframes)) != len(timeframes):
            raise ContractError("warmup timeframes must be unique")
        maximum_required = max(item.bars for item in self.warmup)
        if self.maximum_history_bars < maximum_required:
            raise ContractError("maximum_history_bars is below a warmup requirement")
        if self.maximum_history_bars > 100_000:
            raise ContractError("maximum_history_bars must remain bounded")


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    profile_id: str
    profile_version: str
    manifest_fingerprint: str
    symbol: str
    expected_trade_mode: TradeMode
    engineering_trade_mode: TradeMode
    terminal_identity: str
    magic: int
    max_positions: int
    max_total_lot: Decimal
    deviation_points: int
    tick_size: Decimal
    telegram_audience: str

    def __post_init__(self) -> None:
        for field, value in (
            ("profile_id", self.profile_id),
            ("profile_version", self.profile_version),
            ("manifest_fingerprint", self.manifest_fingerprint),
            ("symbol", self.symbol),
            ("terminal_identity", self.terminal_identity),
            ("telegram_audience", self.telegram_audience),
        ):
            if not value:
                raise ContractError(f"profile.{field} is required")
        if self.magic <= 0 or self.max_positions <= 0 or self.deviation_points < 0:
            raise ContractError("profile integer limits are invalid")
        _positive_decimal(self.max_total_lot, "profile.max_total_lot")
        _positive_decimal(self.tick_size, "profile.tick_size")

    @classmethod
    def from_manifest(cls, manifest: ProfileManifest, *, tick_size: Decimal) -> ProfileConfig:
        return cls(
            profile_id=manifest.profile_id,
            profile_version=manifest.profile_version,
            manifest_fingerprint=manifest.fingerprint,
            symbol=manifest.symbol,
            expected_trade_mode=manifest.expected_trade_mode,
            engineering_trade_mode=manifest.engineering_trade_mode,
            terminal_identity=manifest.terminal.identity,
            magic=manifest.magic,
            max_positions=manifest.max_positions,
            max_total_lot=manifest.max_total_lot,
            deviation_points=manifest.deviation_points,
            tick_size=tick_size,
            telegram_audience=manifest.telegram_audience,
        )

    def validate_market(self, *, profile_id: str, symbol: str) -> None:
        if profile_id != self.profile_id or symbol != self.symbol:
            raise ContractError("market input does not belong to the explicit profile")


@dataclass(frozen=True, slots=True)
class StateField:
    name: str
    value: StateValue

    def __post_init__(self) -> None:
        if not self.name:
            raise ContractError("state field name is required")
        if isinstance(self.value, datetime):
            _aware(self.value, f"state field {self.name}")
        if isinstance(self.value, Decimal) and not self.value.is_finite():
            raise ContractError(f"state field {self.name} must be finite")


@dataclass(frozen=True, slots=True)
class SetupState:
    setup_id: str
    side: Side
    source_timeframe: Timeframe
    stage: str
    created_at: datetime
    valid_until: datetime
    invalidation: Decimal | None = None

    def __post_init__(self) -> None:
        _aware(self.created_at, "setup.created_at")
        _aware(self.valid_until, "setup.valid_until")
        if not self.setup_id or not self.stage:
            raise ContractError("setup identity and stage are required")
        if self.valid_until <= self.created_at:
            raise ContractError("setup.valid_until must be after created_at")
        if self.invalidation is not None:
            _positive_decimal(self.invalidation, "setup.invalidation")


@dataclass(frozen=True, slots=True)
class StrategyState:
    profile_id: str
    strategy_id: str
    strategy_version: str
    phase: StrategyPhase
    as_of: datetime
    sequence: int
    warmup_complete: bool
    setup: SetupState | None = None
    fields: tuple[StateField, ...] = ()

    def __post_init__(self) -> None:
        _aware(self.as_of, "state.as_of")
        if not self.profile_id or not self.strategy_id or not self.strategy_version:
            raise ContractError("state identity is incomplete")
        if self.sequence < 0:
            raise ContractError("state.sequence must be >= 0")
        names = tuple(item.name for item in self.fields)
        if len(set(names)) != len(names):
            raise ContractError("state fields must have unique names")
        if self.setup is not None and self.setup.created_at > self.as_of:
            raise ContractError("state contains a future setup")


@dataclass(frozen=True, slots=True)
class SignalPlan:
    profile_id: str
    profile_version: str
    strategy_id: str
    strategy_version: str
    setup_id: str
    signal_id: str
    side: Side
    symbol: str
    setup_created_at: datetime
    entry_ready_at: datetime
    valid_until: datetime
    planned_entry: Decimal
    stop: Decimal
    target: Decimal
    planned_risk: Decimal
    invalidation: Decimal
    maximum_spread: Decimal
    maximum_drift_r: Decimal
    tick_size: Decimal
    account_login: int
    account_server: str
    trade_mode: TradeMode
    terminal_identity: str
    magic: int

    def __post_init__(self) -> None:
        for name, timestamp in (
            ("setup_created_at", self.setup_created_at),
            ("entry_ready_at", self.entry_ready_at),
            ("valid_until", self.valid_until),
        ):
            _aware(timestamp, f"signal.{name}")
        if not all(
            (
                self.profile_id,
                self.profile_version,
                self.strategy_id,
                self.strategy_version,
                self.setup_id,
                self.signal_id,
                self.symbol,
                self.account_server,
                self.terminal_identity,
            )
        ):
            raise ContractError("signal identity and ownership fields are required")
        if not self.setup_created_at <= self.entry_ready_at < self.valid_until:
            raise ContractError("signal timestamps are not causal")
        for name, amount in (
            ("planned_entry", self.planned_entry),
            ("stop", self.stop),
            ("target", self.target),
            ("planned_risk", self.planned_risk),
            ("invalidation", self.invalidation),
            ("tick_size", self.tick_size),
        ):
            _positive_decimal(amount, f"signal.{name}")
        _positive_decimal(self.maximum_spread, "signal.maximum_spread", allow_zero=True)
        _positive_decimal(self.maximum_drift_r, "signal.maximum_drift_r", allow_zero=True)
        if self.planned_risk != abs(self.planned_entry - self.stop):
            raise ContractError("signal.planned_risk must equal entry-stop distance")
        if self.side is Side.BUY and not self.stop < self.planned_entry < self.target:
            raise ContractError("BUY signal geometry is invalid")
        if self.side is Side.SELL and not self.target < self.planned_entry < self.stop:
            raise ContractError("SELL signal geometry is invalid")
        if any(
            value % self.tick_size != 0
            for value in (self.planned_entry, self.stop, self.target, self.invalidation)
        ):
            raise ContractError("signal geometry must align to tick_size")
        if self.account_login <= 0 or self.magic <= 0:
            raise ContractError("signal account ownership is invalid")


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    decision_id: str
    available_at: datetime
    action: DecisionAction
    reason: str
    setup_id: str | None = None
    side: Side | None = None
    signal_plan: SignalPlan | None = None

    def __post_init__(self) -> None:
        _aware(self.available_at, "decision.available_at")
        if not self.decision_id or not self.reason:
            raise ContractError("decision identity and reason are required")
        if self.action is DecisionAction.ENTRY_READY and self.signal_plan is None:
            raise ContractError("ENTRY_READY decision requires a SignalPlan")
        if self.signal_plan is not None and self.signal_plan.entry_ready_at > self.available_at:
            raise ContractError("decision contains a future SignalPlan")


@dataclass(frozen=True, slots=True)
class PositionState:
    position_id: str
    profile_id: str
    strategy_id: str
    signal_id: str
    symbol: str
    magic: int
    side: Side
    volume: Decimal
    open_time: datetime
    open_price: Decimal
    stop: Decimal
    target: Decimal
    status: PositionStatus
    last_event_at: datetime

    def __post_init__(self) -> None:
        _aware(self.open_time, "position.open_time")
        _aware(self.last_event_at, "position.last_event_at")
        if not all(
            (self.position_id, self.profile_id, self.strategy_id, self.signal_id, self.symbol)
        ):
            raise ContractError("position identity is incomplete")
        if self.magic <= 0 or self.last_event_at < self.open_time:
            raise ContractError("position ownership or event time is invalid")
        for name, value in (
            ("volume", self.volume),
            ("open_price", self.open_price),
            ("stop", self.stop),
            ("target", self.target),
        ):
            _positive_decimal(value, f"position.{name}")


@dataclass(frozen=True, slots=True)
class EngineEvent:
    event_id: str
    event_type: EngineEventType
    payload_version: int
    available_at: datetime
    profile_id: str
    strategy_id: str
    reason: str
    setup_id: str | None = None
    signal_id: str | None = None
    position_id: str | None = None
    fields: tuple[StateField, ...] = ()

    def __post_init__(self) -> None:
        _aware(self.available_at, "event.available_at")
        if not self.event_id or not self.profile_id or not self.strategy_id or not self.reason:
            raise ContractError("event identity and reason are required")
        if self.payload_version <= 0:
            raise ContractError("event.payload_version must be positive")
        names = tuple(item.name for item in self.fields)
        if len(set(names)) != len(names):
            raise ContractError("event fields must have unique names")


@dataclass(frozen=True, slots=True)
class EngineOutput:
    next_state: StrategyState
    decisions: tuple[StrategyDecision, ...] = ()
    events: tuple[EngineEvent, ...] = ()

    def validate_after(self, previous: StrategyState | None) -> None:
        if previous is not None:
            if self.next_state.profile_id != previous.profile_id:
                raise ContractError("engine output changed profile_id")
            if self.next_state.strategy_id != previous.strategy_id:
                raise ContractError("engine output changed strategy_id")
            if self.next_state.strategy_version != previous.strategy_version:
                raise ContractError("engine output changed strategy_version")
            if self.next_state.sequence != previous.sequence + 1:
                raise ContractError("engine output sequence must increment exactly once")
            if self.next_state.as_of < previous.as_of:
                raise ContractError("engine output moved state time backwards")
        if any(item.available_at > self.next_state.as_of for item in self.decisions):
            raise ContractError("engine output contains a future decision")
        if any(item.available_at > self.next_state.as_of for item in self.events):
            raise ContractError("engine output contains a future event")
        for decision in self.decisions:
            plan = decision.signal_plan
            if plan is None:
                continue
            if plan.profile_id != self.next_state.profile_id:
                raise ContractError("engine decision crossed profile ownership")
            if plan.strategy_id != self.next_state.strategy_id:
                raise ContractError("engine decision crossed strategy ownership")
        if any(
            event.profile_id != self.next_state.profile_id
            or event.strategy_id != self.next_state.strategy_id
            for event in self.events
        ):
            raise ContractError("engine event crossed state ownership")


@runtime_checkable
class PureStrategyEngine(Protocol):
    profile: ProfileConfig
    config: StrategyConfig

    def on_warmup(self, history: MarketSnapshot) -> EngineOutput: ...

    def on_bar_close(
        self, state: StrategyState, timeframe: Timeframe, bar: Bar
    ) -> EngineOutput: ...

    def on_tick(self, state: StrategyState, tick: Tick) -> EngineOutput: ...

    def on_position_event(self, state: StrategyState, event: EngineEvent) -> EngineOutput: ...
