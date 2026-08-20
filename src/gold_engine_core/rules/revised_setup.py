from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from .revised import RevisedBar, RevisedSide


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
        self._terminated: dict[RevisedSide, tuple[RevisedM5Setup, str]] = {}
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
                        RevisedSide.SELL if candidate_side is RevisedSide.BUY else RevisedSide.BUY
                    )
                    # A weak opposite micro-break is part of normal range
                    # discovery and must not destroy a live WATCH. Only a
                    # strong reversal pattern terminates the opposite side.
                    opposite_active = self._active.get(opposite)
                    if _is_strong(candidate):
                        terminated = self._active.pop(opposite, None)
                        if terminated is not None:
                            self._terminated[opposite] = (
                                terminated,
                                "OPPOSITE_M5_SETUP_ACCEPTED",
                            )
                    elif opposite_active is not None:
                        # This is evidence for the opposite WATCH's retest,
                        # not enough displacement to open a parallel thesis.
                        continue
                    existing = self._active.get(candidate_side)
                    self._active[candidate_side] = (
                        candidate if existing is None else _merge_setup(existing, candidate)
                    )
        setup = self._active.get(side)
        if setup is None:
            return None
        if current_m1_time <= setup.trigger_time:
            return None
        if current_m1_time - setup.trigger_time > self.maximum_age:
            self._active.pop(side, None)
            self._terminated[side] = (setup, "WATCH_WINDOW_EXPIRED")
            return None
        return setup

    def pop_termination(
        self,
        side: RevisedSide,
    ) -> tuple[RevisedM5Setup, str] | None:
        return self._terminated.pop(side, None)

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
    third = bars[-3] if len(bars) >= 3 else None
    body = max(latest.body, 1e-12)
    lower_wick = min(latest.open, latest.close) - latest.low
    upper_wick = latest.high - max(latest.open, latest.close)
    close_from_low = (latest.close - latest.low) / latest.range if latest.range > 0 else 0.0
    close_from_high = (latest.high - latest.close) / latest.range if latest.range > 0 else 0.0
    if side is RevisedSide.BUY:
        directional = latest.close > latest.open
        micro_break = latest.close > previous.high
        engulfing = (
            directional
            and latest.open <= previous.close
            and latest.close >= previous.open
            and latest.body >= previous.body
        )
        rejection = bool(
            directional
            and latest.low <= previous.low
            and lower_wick >= body
            and close_from_low >= 0.65
        )
        star = bool(
            third is not None
            and third.close < third.open
            and previous.body <= third.body * 0.60
            and directional
            and latest.close >= (third.open + third.close) / 2.0
        )
        level = previous.high
        invalidation = previous.low
        pattern = (
            "BULL_MORNING_STAR"
            if star
            else "BULL_ENGULFING"
            if engulfing
            else "BULL_REJECTION"
            if rejection
            else "BULL_MICRO_BREAK"
            if directional and micro_break
            else "NONE"
        )
    else:
        directional = latest.close < latest.open
        micro_break = latest.close < previous.low
        engulfing = (
            directional
            and latest.open >= previous.close
            and latest.close <= previous.open
            and latest.body >= previous.body
        )
        rejection = bool(
            directional
            and latest.high >= previous.high
            and upper_wick >= body
            and close_from_high >= 0.65
        )
        star = bool(
            third is not None
            and third.close > third.open
            and previous.body <= third.body * 0.60
            and directional
            and latest.close <= (third.open + third.close) / 2.0
        )
        level = previous.low
        invalidation = previous.high
        pattern = (
            "BEAR_EVENING_STAR"
            if star
            else "BEAR_ENGULFING"
            if engulfing
            else "BEAR_REJECTION"
            if rejection
            else "BEAR_MICRO_BREAK"
            if directional and micro_break
            else "NONE"
        )
    if pattern == "NONE":
        return None
    votes = int(directional) + int(micro_break) + int(engulfing or rejection or star)
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


def _is_strong(setup: RevisedM5Setup) -> bool:
    return setup.votes >= 3 and setup.pattern not in {
        "BULL_MICRO_BREAK",
        "BEAR_MICRO_BREAK",
    }


def _merge_setup(
    existing: RevisedM5Setup,
    candidate: RevisedM5Setup,
) -> RevisedM5Setup:
    """Reinforce one WATCH without resetting its causal trigger clock."""
    existing_strong = _is_strong(existing)
    candidate_strong = _is_strong(candidate)
    use_candidate_structure = candidate_strong or not existing_strong
    return RevisedM5Setup(
        side=existing.side,
        trigger_time=existing.trigger_time,
        pattern=(candidate.pattern if use_candidate_structure else existing.pattern),
        votes=max(existing.votes, candidate.votes),
        confidence=max(existing.confidence, candidate.confidence),
        level=(candidate.level if use_candidate_structure else existing.level),
        invalidation=(candidate.invalidation if use_candidate_structure else existing.invalidation),
    )
