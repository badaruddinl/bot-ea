from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import ceil, floor, isfinite
from statistics import fmean
from typing import Sequence


STRATEGY_ID = "GOLDM_REVISED"
STRATEGY_VERSION = "0.1.0"


class RevisedSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class RevisedState(str, Enum):
    WAIT = "WAIT"
    WATCH = "WATCH"
    ENTRY_READY = "ENTRY_READY"
    CANCELLED = "CANCELLED"


class RevisedAction(str, Enum):
    OBSERVE = "OBSERVE"
    ENTER = "ENTER"
    CANCEL = "CANCEL"


class ConfirmationMode(str, Enum):
    RANGE = "RANGE"
    MOMENTUM = "MOMENTUM"


@dataclass(frozen=True, slots=True)
class RevisedBar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    spread: float = 0.20

    def __post_init__(self) -> None:
        values = (self.open, self.high, self.low, self.close, self.volume, self.spread)
        if not all(isfinite(value) for value in values):
            raise ValueError("bar values must be finite")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC values must be positive")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("bar high/low do not contain open and close")
        if self.volume < 0 or self.spread < 0:
            raise ValueError("volume and spread cannot be negative")

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)


@dataclass(frozen=True, slots=True)
class RevisedSnapshot:
    symbol: str
    side: RevisedSide
    current_time: datetime
    m1_bars: tuple[RevisedBar, ...]
    m5_bars: tuple[RevisedBar, ...]
    h1_bars: tuple[RevisedBar, ...] = ()
    d1_bars: tuple[RevisedBar, ...] = ()
    m5_trigger_time: datetime | None = None
    m5_pattern: str = "NONE"
    m5_votes: int = 0
    confidence: float = 0.0
    level: float | None = None
    invalidation: float | None = None
    entry: float | None = None
    stop: float | None = None


@dataclass(frozen=True, slots=True)
class RevisedEngineConfig:
    symbol: str = "GOLD.i#"
    price_tick: float = 0.01
    spread_floor: float = 0.20
    atr_period: int = 14
    range_min_bars: int = 4
    range_max_bars: int = 12
    range_touch_separation_bars: int = 2
    range_retreat_fraction: float = 0.25
    range_min_rejections: int = 2
    range_min_excursion_fraction: float = 0.50
    range_min_body_fraction: float = 0.35
    range_min_close_location: float = 0.65
    acceptance_close_count: int = 2
    acceptance_window: int = 4
    acceptance_displacement_atr: float = 0.50
    momentum_bars: int = 3
    momentum_min_displacement_atr: float = 0.80
    momentum_min_body_fraction: float = 0.55
    momentum_close_location: float = 0.75
    momentum_max_opposite_wick_fraction: float = 1.0
    exhaustion_min_signals: int = 2
    first_obstacle_reject_r: float = 1.0
    first_obstacle_strict_r: float = 1.5
    strict_target_buffer_atr: float = 0.08
    stop_buffer_atr: float = 0.18
    psychological_steps: tuple[float, ...] = (10.0, 50.0, 100.0)
    swing_span: int = 2
    minimum_m5_votes: int = 2
    strong_m5_patterns: tuple[str, ...] = (
        "BULL_ENGULFING",
        "BEAR_ENGULFING",
        "BULL_MORNING_STAR",
        "BEAR_EVENING_STAR",
    )
    promotion_confidence: float = 60.0

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.atr_period < 2 or self.range_min_bars < 2:
            raise ValueError("ATR and range windows are too short")
        if self.range_max_bars < self.range_min_bars:
            raise ValueError("range_max_bars must be >= range_min_bars")
        if self.range_touch_separation_bars < 1:
            raise ValueError("range_touch_separation_bars must be positive")
        if not 0 < self.range_retreat_fraction < 1:
            raise ValueError("range_retreat_fraction must be between 0 and 1")
        if self.range_min_rejections < 1:
            raise ValueError("range_min_rejections must be positive")
        if not 0 < self.range_min_excursion_fraction <= 1:
            raise ValueError("range_min_excursion_fraction is invalid")
        if not 0 < self.range_min_body_fraction <= 1:
            raise ValueError("range_min_body_fraction is invalid")
        if not 0.5 < self.range_min_close_location <= 1:
            raise ValueError("range_min_close_location is invalid")
        if self.acceptance_close_count < 2 or self.acceptance_window < self.acceptance_close_count:
            raise ValueError("acceptance window is invalid")
        if self.momentum_bars < 2 or self.momentum_min_displacement_atr <= 0:
            raise ValueError("momentum configuration is invalid")
        if self.exhaustion_min_signals < 1:
            raise ValueError("exhaustion_min_signals must be positive")
        if self.first_obstacle_reject_r <= 0 or self.first_obstacle_strict_r <= self.first_obstacle_reject_r:
            raise ValueError("first-obstacle R thresholds are invalid")
        if self.price_tick <= 0 or self.spread_floor < 0:
            raise ValueError("price tick/spread floor is invalid")
        if not self.psychological_steps or any(step <= 0 for step in self.psychological_steps):
            raise ValueError("psychological steps must be positive")


@dataclass(frozen=True, slots=True)
class RevisedDecision:
    strategy_id: str
    strategy_version: str
    symbol: str
    side: RevisedSide
    state: RevisedState
    action: RevisedAction
    observation_only: bool
    time: datetime
    reason: str
    confidence: float
    mode: ConfirmationMode | None
    exhausted: bool
    entry: float | None
    stop: float | None
    target: float | None
    first_obstacle: float | None
    first_obstacle_kind: str | None
    first_obstacle_r: float | None
    touch_count: int
    rejection_count: int
    acceptance_count: int
    m1_votes: int
    evidence: dict[str, object]


class RevisedEngine:
    """Causal, signal-only BUY/SELL range and momentum engine."""

    def __init__(self, config: RevisedEngineConfig | None = None) -> None:
        self.config = config or RevisedEngineConfig()

    def evaluate(self, snapshot: RevisedSnapshot) -> RevisedDecision:
        self._validate_snapshot(snapshot)
        side = snapshot.side
        current = snapshot.m1_bars[-1]
        atr_m1 = _atr(snapshot.m1_bars, self.config.atr_period)
        atr_m5 = _atr(snapshot.m5_bars, self.config.atr_period)
        entry = snapshot.entry if snapshot.entry is not None else current.close
        if atr_m1 <= 0 or atr_m5 <= 0:
            return self._decision(snapshot, RevisedState.WAIT, RevisedAction.OBSERVE, "ATR_UNAVAILABLE")

        obstacle, obstacle_kind = self._first_obstacle(snapshot, entry)
        risk = self._risk(snapshot, entry, atr_m5)
        obstacle_r = abs(obstacle - entry) / risk if obstacle is not None and risk > 0 else None
        range_stats = self._range_stats(snapshot, side, atr_m1)
        momentum, exhaustion, momentum_stats = self._momentum_stats(snapshot, side, atr_m5)
        m1 = self._m1_confirmation(snapshot.m1_bars, side)
        range_ok = self._range_confirmed(range_stats, m1)
        strict_room = obstacle_r is not None and obstacle_r < self.config.first_obstacle_strict_r
        momentum_ok = (
            momentum
            and not exhaustion
            and obstacle_r is not None
            and obstacle_r >= self.config.first_obstacle_strict_r
            and snapshot.m5_votes >= self.config.minimum_m5_votes
        )
        strong_pattern = snapshot.m5_pattern in self.config.strong_m5_patterns
        strict_ok = (
            obstacle_r is not None
            and obstacle_r >= self.config.first_obstacle_reject_r
            and m1["votes"] == 3
            and bool(m1["micro_break"])
            and strong_pattern
            and snapshot.m5_votes >= self.config.minimum_m5_votes
            and range_ok
        )
        if obstacle_r is None or obstacle_r < self.config.first_obstacle_reject_r:
            return self._decision(
                snapshot,
                RevisedState.CANCELLED,
                RevisedAction.CANCEL,
                "FIRST_OBSTACLE_ROOM_BELOW_1R",
                confidence=min(snapshot.confidence, self.config.promotion_confidence - 0.01),
                entry=entry,
                stop=risk and self._stop(snapshot, entry, risk),
                obstacle=obstacle,
                obstacle_kind=obstacle_kind,
                obstacle_r=obstacle_r,
                range_stats=range_stats,
                m1=m1,
                momentum=momentum,
                exhausted=exhaustion,
            )
        if exhaustion:
            mode = ConfirmationMode.RANGE
        elif momentum_ok:
            mode = ConfirmationMode.MOMENTUM
        elif range_ok:
            mode = ConfirmationMode.RANGE
        else:
            mode = ConfirmationMode.RANGE if strict_room else None
        eligible = momentum_ok or (range_ok and (not strict_room or strict_ok))
        if not eligible:
            return self._decision(
                snapshot,
                RevisedState.WATCH,
                RevisedAction.OBSERVE,
                "M1_RANGE_OR_MOMENTUM_GATE_PENDING",
                confidence=min(snapshot.confidence, self.config.promotion_confidence - 0.01),
                entry=entry,
                stop=self._stop(snapshot, entry, risk),
                obstacle=obstacle,
                obstacle_kind=obstacle_kind,
                obstacle_r=obstacle_r,
                range_stats=range_stats,
                m1=m1,
                momentum=momentum,
                exhausted=exhaustion,
                mode=mode,
            )
        target = self._target(snapshot, side, entry, obstacle, atr_m5)
        confidence = min(100.0, max(0.0, float(snapshot.confidence)))
        confidence = min(confidence, self.config.promotion_confidence + 20.0)
        if strict_room and not strict_ok:
            confidence = min(confidence, self.config.promotion_confidence - 0.01)
        observation_only = side is RevisedSide.SELL
        return self._decision(
            snapshot,
            RevisedState.ENTRY_READY,
            RevisedAction.ENTER,
            "MOMENTUM_ENTRY" if mode is ConfirmationMode.MOMENTUM else "RANGE_REJECTIONS_CONFIRMED",
            confidence=confidence,
            mode=mode,
            observation_only=observation_only,
            entry=entry,
            stop=self._stop(snapshot, entry, risk),
            target=target,
            obstacle=obstacle,
            obstacle_kind=obstacle_kind,
            obstacle_r=obstacle_r,
            range_stats=range_stats,
            m1=m1,
            momentum=momentum,
            exhausted=exhaustion,
        )

    def _first_obstacle(self, snapshot: RevisedSnapshot, entry: float) -> tuple[float | None, str | None]:
        candidates: list[tuple[float, str]] = []
        side = snapshot.side
        for step in self.config.psychological_steps:
            if side is RevisedSide.BUY:
                price = ceil((entry + 1e-12) / step) * step
                if price <= entry:
                    price += step
            else:
                price = floor((entry - 1e-12) / step) * step
                if price >= entry:
                    price -= step
            candidates.append((round(price, 8), f"PSYCH_{step:g}"))
        for bars, label in ((snapshot.m1_bars, "M1_SWING"), (snapshot.m5_bars, "M5_SWING"), (snapshot.h1_bars, "H1_SWING"), (snapshot.d1_bars, "D1_SWING")):
            pivots = _swing_highs(bars, self.config.swing_span) if side is RevisedSide.BUY else _swing_lows(bars, self.config.swing_span)
            for price in pivots:
                if (side is RevisedSide.BUY and price > entry) or (side is RevisedSide.SELL and price < entry):
                    candidates.append((price, label))
        if not candidates:
            return None, None
        selected = min(candidates, key=lambda item: abs(item[0] - entry)) if side is RevisedSide.BUY else max(candidates, key=lambda item: item[0])
        return selected

    def _range_stats(self, snapshot: RevisedSnapshot, side: RevisedSide, atr: float) -> dict[str, object]:
        trigger = snapshot.m5_trigger_time
        bars = [bar for bar in snapshot.m1_bars if trigger is None or bar.time > trigger]
        bars = bars[-self.config.range_max_bars :]
        if not bars:
            return {"bars": 0, "width": 0.0, "touches": 0, "rejections": 0, "acceptance": 0, "excursion": 0.0}
        high = max(bar.high for bar in bars)
        low = min(bar.low for bar in bars)
        width = high - low
        boundary = low if side is RevisedSide.BUY else high
        tolerance = max(self.config.spread_floor * 2.0, atr * 0.10)
        touches = 0
        rejections = 0
        last_touch = -10_000
        retreat_since_touch = 0.0
        excursions: list[float] = []
        for index, bar in enumerate(bars):
            distance_from_boundary = (
                bar.close - boundary if side is RevisedSide.BUY else boundary - bar.close
            )
            if last_touch >= 0:
                retreat_since_touch = max(retreat_since_touch, distance_from_boundary)
            hit = bar.low <= boundary + tolerance if side is RevisedSide.BUY else bar.high >= boundary - tolerance
            if not hit or index - last_touch < self.config.range_touch_separation_bars:
                continue
            retreat = (bar.close - boundary) if side is RevisedSide.BUY else (boundary - bar.close)
            if last_touch >= 0 and retreat_since_touch < width * self.config.range_retreat_fraction:
                continue
            touches += 1
            last_touch = index
            retreat_since_touch = 0.0
            if retreat >= width * 0.10:
                rejections += 1
            excursions.append(retreat)
        outside = [
            bar for bar in bars[-self.config.acceptance_window :]
            if (bar.close < boundary - tolerance if side is RevisedSide.BUY else bar.close > boundary + tolerance)
        ]
        acceptance = len(outside) >= self.config.acceptance_close_count
        return {
            "bars": len(bars),
            "high": high,
            "low": low,
            "width": width,
            "touches": touches,
            "rejections": rejections,
            "acceptance": int(acceptance),
            "excursion": max(excursions, default=0.0),
            "boundary": boundary,
        }

    def _m1_confirmation(self, bars: Sequence[RevisedBar], side: RevisedSide) -> dict[str, object]:
        if len(bars) < 2:
            return {"votes": 0, "micro_break": False, "body_ratio": 0.0, "close_location": 0.0, "rsi7": 0.0}
        latest, previous = bars[-1], bars[-2]
        body_ratio = latest.body / latest.range if latest.range > 0 else 0.0
        if side is RevisedSide.BUY:
            directional = latest.close > latest.open
            micro = latest.close > previous.high
            close_location = (latest.close - latest.low) / latest.range if latest.range > 0 else 0.0
            rsi = _rsi([bar.close for bar in bars])
            rsi_ok = rsi >= 50.0
        else:
            directional = latest.close < latest.open
            micro = latest.close < previous.low
            close_location = (latest.high - latest.close) / latest.range if latest.range > 0 else 0.0
            rsi = _rsi([bar.close for bar in bars])
            rsi_ok = rsi <= 50.0
        return {
            "votes": int(directional) + int(micro) + int(rsi_ok),
            "directional": directional,
            "micro_break": micro,
            "rsi_ok": rsi_ok,
            "rsi7": rsi,
            "body_ratio": body_ratio,
            "close_location": close_location,
        }

    def _range_confirmed(self, stats: dict[str, object], m1: dict[str, object]) -> bool:
        width = float(stats.get("width", 0.0))
        excursion = float(stats.get("excursion", 0.0))
        return bool(
            int(stats.get("touches", 0)) >= self.config.range_min_rejections
            and int(stats.get("rejections", 0)) >= self.config.range_min_rejections
            and width > 0
            and excursion >= width * self.config.range_min_excursion_fraction
            and not bool(stats.get("acceptance"))
            and bool(m1.get("micro_break"))
            and float(m1.get("body_ratio", 0.0)) >= self.config.range_min_body_fraction
            and float(m1.get("close_location", 0.0)) >= self.config.range_min_close_location
            and int(m1.get("votes", 0)) >= 3
        )

    def _momentum_stats(self, snapshot: RevisedSnapshot, side: RevisedSide, atr: float) -> tuple[bool, bool, dict[str, object]]:
        bars = snapshot.m5_bars[-self.config.momentum_bars :]
        if len(bars) < self.config.momentum_bars or atr <= 0:
            return False, False, {"displacement_atr": 0.0, "body_ratio": 0.0}
        first, latest = bars[0], bars[-1]
        displacement = (latest.close - first.open) if side is RevisedSide.BUY else (first.open - latest.close)
        body_ratio = latest.body / latest.range if latest.range > 0 else 0.0
        close_location = ((latest.close - latest.low) / latest.range if side is RevisedSide.BUY else (latest.high - latest.close) / latest.range) if latest.range > 0 else 0.0
        directional = all((bar.close > bar.open if side is RevisedSide.BUY else bar.close < bar.open) for bar in bars[-2:])
        expansion = latest.range >= bars[-2].range
        momentum = bool(
            directional
            and displacement / atr >= self.config.momentum_min_displacement_atr
            and body_ratio >= self.config.momentum_min_body_fraction
            and close_location >= self.config.momentum_close_location
            and expansion
        )
        exhaustion_signals = 0
        if len(snapshot.m5_bars) >= 4:
            prev = snapshot.m5_bars[-2]
            if latest.body < prev.body:
                exhaustion_signals += 1
            if latest.range < prev.range:
                exhaustion_signals += 1
            if (side is RevisedSide.BUY and latest.high <= prev.high + atr * 0.10) or (side is RevisedSide.SELL and latest.low >= prev.low - atr * 0.10):
                exhaustion_signals += 1
            if body_ratio < 0.35:
                exhaustion_signals += 1
        exhausted = exhaustion_signals >= self.config.exhaustion_min_signals
        return momentum, exhausted, {
            "displacement_atr": displacement / atr,
            "body_ratio": body_ratio,
            "close_location": close_location,
            "exhaustion_signals": exhaustion_signals,
        }

    def _risk(self, snapshot: RevisedSnapshot, entry: float, atr: float) -> float:
        if snapshot.stop is not None:
            return abs(entry - snapshot.stop)
        return max(atr * self.config.stop_buffer_atr, self.config.spread_floor * 2.0)

    def _stop(self, snapshot: RevisedSnapshot, entry: float, risk: float) -> float:
        if snapshot.stop is not None:
            return _normalize(snapshot.stop, self.config.price_tick)
        return _normalize(entry - risk if snapshot.side is RevisedSide.BUY else entry + risk, self.config.price_tick)

    def _target(self, snapshot: RevisedSnapshot, side: RevisedSide, entry: float, obstacle: float | None, atr: float) -> float | None:
        if obstacle is None:
            return None
        buffer = max(self.config.spread_floor, atr * self.config.strict_target_buffer_atr)
        return _normalize(obstacle - buffer if side is RevisedSide.BUY else obstacle + buffer, self.config.price_tick)

    def _decision(self, snapshot: RevisedSnapshot, state: RevisedState, action: RevisedAction, reason: str, *, confidence: float | None = None, mode: ConfirmationMode | None = None, exhausted: bool = False, observation_only: bool | None = None, entry: float | None = None, stop: float | None = None, target: float | None = None, obstacle: float | None = None, obstacle_kind: str | None = None, obstacle_r: float | None = None, range_stats: dict[str, object] | None = None, m1: dict[str, object] | None = None, momentum: bool = False) -> RevisedDecision:
        range_stats = range_stats or {}
        m1 = m1 or {}
        evidence = {"range": range_stats, "m1": m1, "momentum": momentum, "m5_pattern": snapshot.m5_pattern, "m5_votes": snapshot.m5_votes}
        return RevisedDecision(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            symbol=snapshot.symbol,
            side=snapshot.side,
            state=state,
            action=action,
            observation_only=(snapshot.side is RevisedSide.SELL if observation_only is None else observation_only),
            time=snapshot.current_time,
            reason=reason,
            confidence=float(snapshot.confidence if confidence is None else confidence),
            mode=mode,
            exhausted=exhausted,
            entry=entry,
            stop=stop,
            target=target,
            first_obstacle=obstacle,
            first_obstacle_kind=obstacle_kind,
            first_obstacle_r=obstacle_r,
            touch_count=int(range_stats.get("touches", 0)),
            rejection_count=int(range_stats.get("rejections", 0)),
            acceptance_count=int(range_stats.get("acceptance", 0)),
            m1_votes=int(m1.get("votes", 0)),
            evidence=evidence,
        )

    @staticmethod
    def _validate_snapshot(snapshot: RevisedSnapshot) -> None:
        if snapshot.symbol.strip() == "":
            raise ValueError("snapshot symbol is required")
        if not snapshot.m1_bars or not snapshot.m5_bars:
            raise ValueError("M1 and M5 closed bars are required")
        for bars in (snapshot.m1_bars, snapshot.m5_bars, snapshot.h1_bars, snapshot.d1_bars):
            if any(current.time <= previous.time for previous, current in zip(bars, bars[1:])):
                raise ValueError("snapshot bars must be strictly ordered")
        if snapshot.m1_bars[-1].time > snapshot.current_time:
            raise ValueError("current_time cannot precede the latest closed M1 bar")


def _atr(bars: Sequence[RevisedBar], period: int) -> float:
    if len(bars) < period + 1:
        return 0.0
    values = []
    for previous, current in zip(bars[-(period + 1) : -1], bars[-period:]):
        values.append(max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close)))
    return fmean(values)


def _rsi(closes: Sequence[float], period: int = 7) -> float:
    if len(closes) < period + 1:
        return 50.0
    changes = [current - previous for previous, current in zip(closes, closes[1:])]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    gain = fmean(gains[:period])
    loss = fmean(losses[:period])
    for up, down in zip(gains[period:], losses[period:]):
        gain = (gain * (period - 1) + up) / period
        loss = (loss * (period - 1) + down) / period
    if loss <= 0:
        return 100.0 if gain > 0 else 50.0
    rs = gain / loss
    return 100.0 - 100.0 / (1.0 + rs)


def _swing_highs(bars: Sequence[RevisedBar], span: int) -> list[float]:
    result: list[float] = []
    for index in range(span, len(bars) - span):
        pivot = bars[index].high
        neighbours = list(bars[index - span : index]) + list(bars[index + 1 : index + span + 1])
        if all(pivot > bar.high for bar in neighbours):
            result.append(pivot)
    return result


def _swing_lows(bars: Sequence[RevisedBar], span: int) -> list[float]:
    result: list[float] = []
    for index in range(span, len(bars) - span):
        pivot = bars[index].low
        neighbours = list(bars[index - span : index]) + list(bars[index + 1 : index + span + 1])
        if all(pivot < bar.low for bar in neighbours):
            result.append(pivot)
    return result


def _normalize(value: float, tick: float) -> float:
    return round(ceil((value - 1e-12) / tick) * tick, 10)
