from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import ceil, floor, isfinite
from statistics import fmean
from typing import Iterable, Sequence


class BearAction(str, Enum):
    WAIT = "WAIT"
    WATCH = "WATCH"
    SELL = "SELL"


class BearExitAction(str, Enum):
    HOLD = "HOLD"
    TAKE_PROFIT = "TAKE_PROFIT"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True, slots=True)
class BearBar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: float = 0.0
    spread: float = 0.0

    def __post_init__(self) -> None:
        values = (self.open, self.high, self.low, self.close, self.tick_volume, self.spread)
        if not all(isfinite(value) for value in values):
            raise ValueError("bar values must be finite")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC values must be positive")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("bar high/low do not contain open and close")
        if self.tick_volume < 0 or self.spread < 0:
            raise ValueError("tick volume and spread cannot be negative")

    @property
    def full_range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)


@dataclass(frozen=True, slots=True)
class BearEngineConfig:
    symbol: str = "GOLD.i#"
    atr_period: int = 14
    regime_lookback: int = 32
    level_lookback: int = 24
    swing_span: int = 2
    minimum_regime_drop_atr: float = 1.25
    maximum_slope_atr_per_bar: float = 0.025
    resistance_tolerance_atr: float = 0.28
    maximum_breakout_overshoot_atr: float = 0.85
    maximum_chase_atr: float = 1.25
    minimum_body_atr: float = 0.12
    minimum_upper_wick_fraction: float = 0.22
    minimum_room_atr: float = 0.60
    minimum_reward_risk: float = 0.70
    minimum_continuation_reward_risk: float = 0.55
    stop_buffer_atr: float = 0.18
    target_buffer_atr: float = 0.08
    invalidation_buffer_atr: float = 0.16
    price_tick: float = 0.01
    spread_floor: float = 0.20
    psychological_steps: tuple[float, ...] = (10.0, 50.0, 100.0)
    session_open_minute: int = 62
    session_close_minute: int = 23 * 60 + 58
    session_guard_minutes: int = 15

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.atr_period < 2:
            raise ValueError("atr_period must be at least 2")
        if self.regime_lookback < self.atr_period:
            raise ValueError("regime_lookback cannot be shorter than atr_period")
        if self.level_lookback < 2 * self.swing_span + 1:
            raise ValueError("level_lookback is too short for the swing span")
        if self.swing_span < 1:
            raise ValueError("swing_span must be positive")
        positive_fields = (
            self.minimum_regime_drop_atr,
            self.resistance_tolerance_atr,
            self.maximum_breakout_overshoot_atr,
            self.maximum_chase_atr,
            self.minimum_body_atr,
            self.minimum_upper_wick_fraction,
            self.minimum_room_atr,
            self.minimum_reward_risk,
            self.minimum_continuation_reward_risk,
            self.stop_buffer_atr,
            self.target_buffer_atr,
            self.invalidation_buffer_atr,
            self.price_tick,
            self.spread_floor,
        )
        if any(value <= 0 for value in positive_fields):
            raise ValueError("distance and ratio settings must be positive")
        if not self.psychological_steps or any(step <= 0 for step in self.psychological_steps):
            raise ValueError("psychological steps must be positive")
        if not 0 <= self.session_open_minute < self.session_close_minute < 24 * 60:
            raise ValueError("session minutes are invalid")
        if self.session_guard_minutes < 0:
            raise ValueError("session_guard_minutes cannot be negative")


@dataclass(frozen=True, slots=True)
class BearDecision:
    action: BearAction
    time: datetime
    symbol: str
    reason: str
    score: int
    atr: float | None = None
    resistance: float | None = None
    support: float | None = None
    entry: float | None = None
    stop: float | None = None
    take_profit: float | None = None
    take_profit_2: float | None = None
    reward_risk: float | None = None
    regime_slope_atr: float | None = None


@dataclass(frozen=True, slots=True)
class ShortPosition:
    entry: float
    stop: float
    take_profit: float
    structural_resistance: float

    def __post_init__(self) -> None:
        if not self.take_profit < self.entry < self.stop:
            raise ValueError("short position prices must satisfy TP < entry < stop")


@dataclass(frozen=True, slots=True)
class BearExitDecision:
    action: BearExitAction
    reason: str


@dataclass(frozen=True, slots=True)
class _Level:
    price: float
    kind: str


class BearEngine:
    """Closed-bar SELL engine independent from the production strategy.

    The engine models the chart sequence as bearish displacement, a pullback
    into a lower resistance, and a rejection.  It emits WATCH before rejection
    and SELL only after a closed-bar trigger.  Targets stop in front of the
    nearest structural support or psychological round number.
    """

    def __init__(self, config: BearEngineConfig | None = None) -> None:
        self.config = config or BearEngineConfig()

    @property
    def minimum_bars(self) -> int:
        return max(self.config.regime_lookback, self.config.level_lookback) + 2

    def evaluate(self, bars: Sequence[BearBar]) -> BearDecision:
        if not bars:
            raise ValueError("at least one closed bar is required")
        latest = bars[-1]
        if len(bars) < self.minimum_bars:
            return self._wait(latest, "insufficient_history")
        self._validate_order(bars)
        if not self._inside_session(latest.time):
            return self._wait(latest, "outside_trade_session")

        atr = _average_true_range(bars, self.config.atr_period)
        if atr <= 0:
            return self._wait(latest, "zero_volatility", atr=atr)

        regime = bars[-self.config.regime_lookback :]
        slope = _linear_slope([bar.close for bar in regime]) / atr
        regime_high = max(bar.high for bar in regime[:-1])
        regime_drop = (regime_high - latest.close) / atr
        if (
            slope > self.config.maximum_slope_atr_per_bar
            or regime_drop < self.config.minimum_regime_drop_atr
        ):
            return self._wait(
                latest,
                "bear_regime_not_confirmed",
                atr=atr,
                regime_slope_atr=slope,
            )

        history = bars[-(self.config.level_lookback + 1) : -1]
        recent_retest = bars[-4:]
        resistance_levels = self._resistance_levels(
            history,
            recent_retest,
            latest,
            atr,
        )
        if not resistance_levels:
            return self._wait(
                latest,
                "no_resistance_retest",
                atr=atr,
                regime_slope_atr=slope,
            )
        resistance = min(resistance_levels, key=lambda level: abs(level.price - latest.high))
        chase_distance = resistance.price - latest.close
        if chase_distance < -self.config.resistance_tolerance_atr * atr:
            return self._wait(
                latest,
                "resistance_broken_upward",
                atr=atr,
                resistance=resistance.price,
                regime_slope_atr=slope,
            )
        if chase_distance > self.config.maximum_chase_atr * atr:
            return self._wait(
                latest,
                "sell_move_already_extended",
                atr=atr,
                resistance=resistance.price,
                regime_slope_atr=slope,
            )

        rejection = self._is_rejection(latest, bars[-2], resistance.price, atr)
        if not rejection:
            return BearDecision(
                action=BearAction.WATCH,
                time=latest.time,
                symbol=self.config.symbol,
                reason=f"pullback_at_{resistance.kind}_resistance_waiting_rejection",
                score=self._score(slope=slope, regime_drop=regime_drop, rejection=False),
                atr=atr,
                resistance=resistance.price,
                regime_slope_atr=slope,
            )

        entry = latest.close
        stop = _ceil_to_tick(
            max(max(bar.high for bar in recent_retest), resistance.price)
            + max(
                atr * self.config.stop_buffer_atr,
                max(latest.spread, self.config.spread_floor) * 2.0,
            ),
            self.config.price_tick,
        )
        support_levels = self._support_levels(history, entry)
        if not support_levels:
            return self._wait(
                latest,
                "no_support_or_psychological_target",
                atr=atr,
                resistance=resistance.price,
                regime_slope_atr=slope,
            )
        targets = self._targets(entry, atr, support_levels)
        if not targets:
            return self._wait(
                latest,
                "insufficient_room_before_support",
                atr=atr,
                resistance=resistance.price,
                regime_slope_atr=slope,
            )
        take_profit = targets[0]
        risk = stop - entry
        reward = entry - take_profit
        reward_risk = reward / risk if risk > 0 else 0.0
        strong_failure = (
            latest.close < bars[-2].low
            and latest.close < latest.open
            and latest.body >= 0.65 * atr
        )
        continuation_target = False
        if (
            (
                reward < self.config.minimum_room_atr * atr
                or reward_risk < self.config.minimum_reward_risk
            )
            and strong_failure
            and len(targets) > 1
        ):
            continuation_reward = entry - targets[1]
            continuation_reward_risk = continuation_reward / risk if risk > 0 else 0.0
            if (
                continuation_reward >= self.config.minimum_room_atr * atr
                and continuation_reward_risk
                >= self.config.minimum_continuation_reward_risk
            ):
                take_profit = targets[1]
                reward = continuation_reward
                reward_risk = continuation_reward_risk
                continuation_target = True
        if reward < self.config.minimum_room_atr * atr:
            return BearDecision(
                action=BearAction.WATCH,
                time=latest.time,
                symbol=self.config.symbol,
                reason="rejection_confirmed_but_nearest_barrier_too_close",
                score=self._score(slope=slope, regime_drop=regime_drop, rejection=True),
                atr=atr,
                resistance=resistance.price,
                support=support_levels[0].price,
                entry=entry,
                stop=stop,
                take_profit=take_profit,
                reward_risk=reward_risk,
                regime_slope_atr=slope,
            )
        required_reward_risk = (
            self.config.minimum_continuation_reward_risk
            if continuation_target
            else self.config.minimum_reward_risk
        )
        if reward_risk < required_reward_risk:
            return BearDecision(
                action=BearAction.WATCH,
                time=latest.time,
                symbol=self.config.symbol,
                reason="rejection_confirmed_but_reward_risk_too_small",
                score=self._score(slope=slope, regime_drop=regime_drop, rejection=True),
                atr=atr,
                resistance=resistance.price,
                support=support_levels[0].price,
                entry=entry,
                stop=stop,
                take_profit=take_profit,
                reward_risk=reward_risk,
                regime_slope_atr=slope,
            )

        return BearDecision(
            action=BearAction.SELL,
            time=latest.time,
            symbol=self.config.symbol,
            reason=(
                f"bear_pullback_rejected_at_{resistance.kind}_resistance"
                + ("_continuation_through_near_support" if continuation_target else "")
            ),
            score=self._score(slope=slope, regime_drop=regime_drop, rejection=True),
            atr=atr,
            resistance=resistance.price,
            support=support_levels[0].price,
            entry=entry,
            stop=stop,
            take_profit=take_profit,
            take_profit_2=(
                targets[1]
                if not continuation_target and len(targets) > 1
                else None
            ),
            reward_risk=reward_risk,
            regime_slope_atr=slope,
        )

    def scan(self, bars: Sequence[BearBar]) -> list[BearDecision]:
        decisions: list[BearDecision] = []
        for end in range(self.minimum_bars, len(bars) + 1):
            decision = self.evaluate(bars[:end])
            if decision.action is BearAction.SELL:
                decisions.append(decision)
        return decisions

    def evaluate_exit(
        self,
        position: ShortPosition,
        bars: Sequence[BearBar],
    ) -> BearExitDecision:
        if not bars:
            raise ValueError("at least one closed bar is required")
        latest = bars[-1]
        if latest.low <= position.take_profit:
            return BearExitDecision(BearExitAction.TAKE_PROFIT, "take_profit_touched")
        atr = _average_true_range(bars, min(self.config.atr_period, len(bars) - 1))
        invalidation = position.structural_resistance + atr * self.config.invalidation_buffer_atr
        recent = bars[-2:] if len(bars) >= 2 else bars
        closes_above = all(bar.close > invalidation for bar in recent)
        strong_break = (
            latest.close > invalidation
            and latest.close > latest.open
            and latest.body >= 0.5 * atr
        )
        if latest.high >= position.stop or closes_above or strong_break:
            return BearExitDecision(
                BearExitAction.INVALIDATED,
                "resistance_closed_above_or_stop_touched",
            )
        return BearExitDecision(
            BearExitAction.HOLD,
            "bear_structure_intact_ignore_ordinary_pullback",
        )

    def _resistance_levels(
        self,
        history: Sequence[BearBar],
        recent_retest: Sequence[BearBar],
        latest: BearBar,
        atr: float,
    ) -> list[_Level]:
        tolerance = self.config.resistance_tolerance_atr * atr
        maximum_overshoot = self.config.maximum_breakout_overshoot_atr * atr
        levels = [
            _Level(price, "swing")
            for price in _swing_highs(history, self.config.swing_span)
        ]
        levels.extend(self._psychological_levels(latest.low - tolerance, latest.high + tolerance))
        deduped = _deduplicate_levels(levels, tolerance=max(0.01, atr * 0.04))
        return [
            level
            for level in deduped
            if any(
                level.price - tolerance <= bar.high <= level.price + maximum_overshoot
                for bar in recent_retest
            )
            and latest.close <= level.price + tolerance
        ]

    def _support_levels(self, history: Sequence[BearBar], entry: float) -> list[_Level]:
        lows = [
            _Level(price, "swing")
            for price in _swing_lows(history, self.config.swing_span)
            if price < entry
        ]
        lower_bound = min(bar.low for bar in history)
        lows.extend(
            level
            for level in self._psychological_levels(lower_bound, entry)
            if level.price < entry
        )
        return sorted(
            _deduplicate_levels(lows, tolerance=0.02),
            key=lambda level: level.price,
            reverse=True,
        )

    def _psychological_levels(self, lower: float, upper: float) -> list[_Level]:
        levels: dict[float, float] = {}
        for step in sorted(self.config.psychological_steps):
            first = floor(lower / step) * step
            price = first
            while price <= upper + step:
                if lower <= price <= upper:
                    levels[round(price, 8)] = max(step, levels.get(round(price, 8), 0.0))
                price += step
        return [_Level(price, f"psych_{step:g}") for price, step in levels.items()]

    def _targets(
        self,
        entry: float,
        atr: float,
        levels: Sequence[_Level],
    ) -> list[float]:
        buffer = atr * self.config.target_buffer_atr
        targets: list[float] = []
        for level in levels:
            target = _ceil_to_tick(level.price + buffer, self.config.price_tick)
            if target < entry and all(abs(target - item) > 0.02 for item in targets):
                targets.append(target)
            if len(targets) == 2:
                break
        return targets

    def _is_rejection(
        self,
        latest: BearBar,
        previous: BearBar,
        resistance: float,
        atr: float,
    ) -> bool:
        if latest.close > resistance + self.config.resistance_tolerance_atr * atr:
            return False
        bearish_body = (
            latest.close < latest.open
            and latest.body >= self.config.minimum_body_atr * atr
            and latest.close < previous.close
            and latest.close < previous.low
        )
        wick_fraction = latest.upper_wick / latest.full_range if latest.full_range > 0 else 0.0
        wick_rejection = (
            wick_fraction >= self.config.minimum_upper_wick_fraction
            and latest.close <= latest.low + 0.55 * latest.full_range
            and latest.close < previous.close
            and latest.close < previous.low
        )
        return bearish_body or wick_rejection

    def _inside_session(self, timestamp: datetime) -> bool:
        minute = timestamp.hour * 60 + timestamp.minute
        return (
            self.config.session_open_minute + self.config.session_guard_minutes
            <= minute
            <= self.config.session_close_minute - self.config.session_guard_minutes
        )

    def _score(self, *, slope: float, regime_drop: float, rejection: bool) -> int:
        slope_strength = min(25.0, abs(min(0.0, slope)) * 500.0)
        drop_strength = min(30.0, regime_drop * 7.5)
        rejection_strength = 30.0 if rejection else 12.0
        return int(round(min(100.0, 15.0 + slope_strength + drop_strength + rejection_strength)))

    def _wait(
        self,
        latest: BearBar,
        reason: str,
        *,
        atr: float | None = None,
        resistance: float | None = None,
        regime_slope_atr: float | None = None,
    ) -> BearDecision:
        return BearDecision(
            action=BearAction.WAIT,
            time=latest.time,
            symbol=self.config.symbol,
            reason=reason,
            score=0,
            atr=atr,
            resistance=resistance,
            regime_slope_atr=regime_slope_atr,
        )

    @staticmethod
    def _validate_order(bars: Sequence[BearBar]) -> None:
        if any(current.time <= previous.time for previous, current in zip(bars, bars[1:])):
            raise ValueError("bars must be strictly ordered by ascending time")


def _average_true_range(bars: Sequence[BearBar], period: int) -> float:
    if period < 1 or len(bars) < period + 1:
        raise ValueError("not enough bars to calculate ATR")
    true_ranges: list[float] = []
    for previous, current in zip(bars[-(period + 1) : -1], bars[-period:]):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return fmean(true_ranges)


def _linear_slope(values: Sequence[float]) -> float:
    count = len(values)
    x_mean = (count - 1) / 2.0
    y_mean = fmean(values)
    numerator = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values))
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    return numerator / denominator if denominator else 0.0


def _swing_highs(bars: Sequence[BearBar], span: int) -> list[float]:
    values: list[float] = []
    for index in range(span, len(bars) - span):
        pivot = bars[index].high
        neighbours = bars[index - span : index] + bars[index + 1 : index + span + 1]
        if all(pivot > bar.high for bar in neighbours):
            values.append(pivot)
    return values


def _swing_lows(bars: Sequence[BearBar], span: int) -> list[float]:
    values: list[float] = []
    for index in range(span, len(bars) - span):
        pivot = bars[index].low
        neighbours = bars[index - span : index] + bars[index + 1 : index + span + 1]
        if all(pivot < bar.low for bar in neighbours):
            values.append(pivot)
    return values


def _deduplicate_levels(levels: Iterable[_Level], *, tolerance: float) -> list[_Level]:
    ordered = sorted(levels, key=lambda level: (level.price, level.kind))
    result: list[_Level] = []
    for level in ordered:
        if result and abs(level.price - result[-1].price) <= tolerance:
            if level.kind.startswith("psych_") and result[-1].kind == "swing":
                result[-1] = _Level(result[-1].price, "swing_psych_confluence")
            continue
        result.append(level)
    return result


def _ceil_to_tick(value: float, tick: float) -> float:
    return round(ceil((value - 1e-12) / tick) * tick, 10)
