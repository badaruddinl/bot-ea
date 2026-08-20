from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import cast

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


@dataclass(frozen=True, slots=True)
class RevisedTermination:
    setup: RevisedM5Setup
    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("termination reason is required")


@dataclass(frozen=True, slots=True)
class RevisedConsumedSetup:
    side: RevisedSide
    trigger_time: datetime

    def __post_init__(self) -> None:
        _require_aware(self.trigger_time, "consumed.trigger_time")


@dataclass(frozen=True, slots=True)
class RevisedDetectorState:
    maximum_m1_bars: int
    active: tuple[RevisedM5Setup, ...] = ()
    terminated: tuple[RevisedTermination, ...] = ()
    consumed: tuple[RevisedConsumedSetup, ...] = ()
    last_classified_m5: datetime | None = None

    def __post_init__(self) -> None:
        if self.maximum_m1_bars < 1:
            raise ValueError("maximum_m1_bars must be positive")
        if self.last_classified_m5 is not None:
            _require_aware(self.last_classified_m5, "last_classified_m5")
        for setup in self.active:
            _validate_setup(setup)
        for termination in self.terminated:
            _validate_setup(termination.setup)
        active_sides = tuple(item.side for item in self.active)
        terminated_sides = tuple(item.setup.side for item in self.terminated)
        consumed_sides = tuple(item.side for item in self.consumed)
        if len(set(active_sides)) != len(active_sides):
            raise ValueError("active detector state contains duplicate sides")
        if len(set(terminated_sides)) != len(terminated_sides):
            raise ValueError("terminated detector state contains duplicate sides")
        if len(set(consumed_sides)) != len(consumed_sides):
            raise ValueError("consumed detector state contains duplicate sides")

    def to_payload(self) -> dict[str, object]:
        return {
            "maximum_m1_bars": self.maximum_m1_bars,
            "active": [_setup_payload(item) for item in self.active],
            "terminated": [
                {"setup": _setup_payload(item.setup), "reason": item.reason}
                for item in self.terminated
            ],
            "consumed": [
                {"side": item.side.value, "trigger_time": item.trigger_time.isoformat()}
                for item in self.consumed
            ],
            "last_classified_m5": (
                self.last_classified_m5.isoformat() if self.last_classified_m5 is not None else None
            ),
        }

    @classmethod
    def from_payload(cls, payload: object) -> RevisedDetectorState:
        data = _mapping(payload, "detector_state")
        expected = {
            "active",
            "consumed",
            "last_classified_m5",
            "maximum_m1_bars",
            "terminated",
        }
        if set(data) != expected:
            raise ValueError(f"detector_state keys must be {sorted(expected)}")
        maximum = data["maximum_m1_bars"]
        if isinstance(maximum, bool) or not isinstance(maximum, int):
            raise ValueError("maximum_m1_bars must be an integer")
        active_values = _list(data["active"], "active")
        terminated_values = _list(data["terminated"], "terminated")
        consumed_values = _list(data["consumed"], "consumed")
        last_value = data["last_classified_m5"]
        return cls(
            maximum_m1_bars=maximum,
            active=tuple(_setup_from_payload(item) for item in active_values),
            terminated=tuple(
                RevisedTermination(
                    setup=_setup_from_payload(_mapping(item, "termination")["setup"]),
                    reason=_string(_mapping(item, "termination")["reason"], "reason"),
                )
                for item in terminated_values
            ),
            consumed=tuple(
                RevisedConsumedSetup(
                    side=RevisedSide(_string(_mapping(item, "consumed")["side"], "consumed.side")),
                    trigger_time=_timestamp(
                        _mapping(item, "consumed")["trigger_time"],
                        "consumed.trigger_time",
                    ),
                )
                for item in consumed_values
            ),
            last_classified_m5=(
                None if last_value is None else _timestamp(last_value, "last_classified_m5")
            ),
        )


class RevisedSetupDetector:
    """Persists one M5 setup per side while M1 builds confirmation evidence."""

    def __init__(self, *, maximum_m1_bars: int = 12) -> None:
        if maximum_m1_bars < 1:
            raise ValueError("maximum_m1_bars must be positive")
        self.maximum_age = timedelta(minutes=maximum_m1_bars)
        self._active: dict[RevisedSide, RevisedM5Setup] = {}
        self._terminated: dict[RevisedSide, tuple[RevisedM5Setup, str]] = {}
        self._consumed: dict[RevisedSide, datetime] = {}
        self._last_classified_m5: datetime | None = None

    @classmethod
    def from_state(cls, state: RevisedDetectorState) -> RevisedSetupDetector:
        detector = cls(maximum_m1_bars=state.maximum_m1_bars)
        detector._active = {item.side: item for item in state.active}
        detector._terminated = {
            item.setup.side: (item.setup, item.reason) for item in state.terminated
        }
        detector._consumed = {item.side: item.trigger_time for item in state.consumed}
        detector._last_classified_m5 = state.last_classified_m5
        return detector

    def snapshot(self) -> RevisedDetectorState:
        return RevisedDetectorState(
            maximum_m1_bars=int(self.maximum_age.total_seconds() // 60),
            active=tuple(
                self._active[side] for side in sorted(self._active, key=lambda x: x.value)
            ),
            terminated=tuple(
                RevisedTermination(*self._terminated[side])
                for side in sorted(self._terminated, key=lambda x: x.value)
            ),
            consumed=tuple(
                RevisedConsumedSetup(side, self._consumed[side])
                for side in sorted(self._consumed, key=lambda x: x.value)
            ),
            last_classified_m5=self._last_classified_m5,
        )

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
        if self._last_classified_m5 is None or latest.time > self._last_classified_m5:
            self._last_classified_m5 = latest.time
            for candidate_side in (RevisedSide.BUY, RevisedSide.SELL):
                candidate = classify_m5_setup(m5_bars, candidate_side)
                if candidate is not None:
                    consumed_at = self._consumed.get(candidate_side)
                    if consumed_at is not None and candidate.trigger_time <= consumed_at:
                        continue
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
        consumed_at = self._consumed.get(side)
        if consumed_at is None or trigger_time > consumed_at:
            self._consumed[side] = trigger_time
        setup = self._active.get(side)
        if setup is not None and setup.trigger_time == trigger_time:
            self._active.pop(side, None)


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include an explicit UTC offset")


def _validate_setup(setup: RevisedM5Setup) -> None:
    _require_aware(setup.trigger_time, "setup.trigger_time")
    if not setup.pattern or setup.votes < 0:
        raise ValueError("setup pattern or votes are invalid")


def _setup_payload(setup: RevisedM5Setup) -> dict[str, object]:
    return {
        "side": setup.side.value,
        "trigger_time": setup.trigger_time.isoformat(),
        "pattern": setup.pattern,
        "votes": setup.votes,
        "confidence": setup.confidence,
        "level": setup.level,
        "invalidation": setup.invalidation,
    }


def _setup_from_payload(payload: object) -> RevisedM5Setup:
    data = _mapping(payload, "setup")
    expected = {
        "confidence",
        "invalidation",
        "level",
        "pattern",
        "side",
        "trigger_time",
        "votes",
    }
    if set(data) != expected:
        raise ValueError(f"setup keys must be {sorted(expected)}")
    votes = data["votes"]
    if isinstance(votes, bool) or not isinstance(votes, int):
        raise ValueError("setup.votes must be an integer")
    return RevisedM5Setup(
        side=RevisedSide(_string(data["side"], "setup.side")),
        trigger_time=_timestamp(data["trigger_time"], "setup.trigger_time"),
        pattern=_string(data["pattern"], "setup.pattern"),
        votes=votes,
        confidence=_float(data["confidence"], "setup.confidence"),
        level=_float(data["level"], "setup.level"),
        invalidation=_float(data["invalidation"], "setup.invalidation"),
    )


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _timestamp(value: object, field: str) -> datetime:
    text = _string(value, field)
    try:
        result = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    _require_aware(result, field)
    return result


def _float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


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
