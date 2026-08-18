from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .engine import RevisedBar, RevisedSide


@dataclass(frozen=True, slots=True)
class RevisedM5Setup:
    side: RevisedSide
    trigger_time: datetime
    pattern: str
    votes: int
    confidence: float
    level: float
    invalidation: float


class RevisedSetupDetector:
    """Persists one M5 setup per side while M1 builds confirmation evidence."""

    def __init__(self, *, maximum_m1_bars: int = 12) -> None:
        if maximum_m1_bars < 1:
            raise ValueError("maximum_m1_bars must be positive")
        self.maximum_age = timedelta(minutes=maximum_m1_bars)
        self._active: dict[RevisedSide, RevisedM5Setup] = {}
        self._last_classified_m5: datetime | None = None

    def update(
        self,
        m5_bars: Sequence[RevisedBar],
        *,
        current_m1_time: datetime,
        side: RevisedSide,
    ) -> RevisedM5Setup | None:
        if len(m5_bars) < 2:
            return None
        latest = m5_bars[-1]
        if self._last_classified_m5 != latest.time:
            self._last_classified_m5 = latest.time
            for candidate_side in (RevisedSide.BUY, RevisedSide.SELL):
                candidate = classify_m5_setup(m5_bars, candidate_side)
                if candidate is not None:
                    opposite = (
                        RevisedSide.SELL
                        if candidate_side is RevisedSide.BUY
                        else RevisedSide.BUY
                    )
                    # A newly closed opposite M5 setup invalidates the stale
                    # hypothesis immediately. This prevents a late BUY from
                    # promoting after bearish displacement (and vice versa),
                    # while allowing the reversal to start its own causal M1
                    # confirmation window.
                    self._active.pop(opposite, None)
                    self._active[candidate_side] = candidate
        setup = self._active.get(side)
        if setup is None:
            return None
        if current_m1_time <= setup.trigger_time:
            return None
        if current_m1_time - setup.trigger_time > self.maximum_age:
            self._active.pop(side, None)
            return None
        return setup

    def consume(self, side: RevisedSide, trigger_time: datetime) -> None:
        setup = self._active.get(side)
        if setup is not None and setup.trigger_time == trigger_time:
            self._active.pop(side, None)


def classify_m5_setup(
    bars: Sequence[RevisedBar],
    side: RevisedSide,
) -> RevisedM5Setup | None:
    if len(bars) < 2:
        return None
    latest, previous = bars[-1], bars[-2]
    if side is RevisedSide.BUY:
        directional = latest.close > latest.open
        micro_break = latest.close > previous.high
        engulfing = (
            directional
            and latest.open <= previous.close
            and latest.close >= previous.open
            and latest.body >= previous.body
        )
        level = previous.high
        invalidation = previous.low
        pattern = "BULL_ENGULFING" if engulfing else "BULL_MICRO_BREAK" if directional and micro_break else "NONE"
    else:
        directional = latest.close < latest.open
        micro_break = latest.close < previous.low
        engulfing = (
            directional
            and latest.open >= previous.close
            and latest.close <= previous.open
            and latest.body >= previous.body
        )
        level = previous.low
        invalidation = previous.high
        pattern = "BEAR_ENGULFING" if engulfing else "BEAR_MICRO_BREAK" if directional and micro_break else "NONE"
    if pattern == "NONE":
        return None
    votes = int(directional) + int(micro_break) + int(engulfing)
    return RevisedM5Setup(
        side=side,
        # MqlRates/MetaTrader bars are timestamped at bar open. M1 confirmation
        # starts only after the trigger M5 candle has fully closed.
        trigger_time=latest.time + timedelta(minutes=5),
        pattern=pattern,
        votes=votes,
        confidence=min(100.0, 60.0 + votes * 10.0),
        level=level,
        invalidation=invalidation,
    )
