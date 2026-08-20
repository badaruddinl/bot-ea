from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from itertools import pairwise
from math import ceil, floor, isfinite
from statistics import fmean
from typing import Any, cast

STRATEGY_ID = "GOLDM_REVISED"
STRATEGY_VERSION = "0.6.0"


def _as_int(value: object) -> int:
    """Preserve legacy int coercion while keeping unstructured data at the boundary."""

    return int(cast(Any, value))


def _as_float(value: object) -> float:
    """Preserve legacy float coercion while keeping unstructured data at the boundary."""

    return float(cast(Any, value))


def _as_dict(value: object) -> dict[str, object]:
    return cast(dict[str, object], value)


class RevisedSide(str, Enum):  # noqa: UP042 - preserve legacy str(Enum) semantics
    BUY = "BUY"
    SELL = "SELL"


class RevisedState(str, Enum):  # noqa: UP042 - preserve legacy str(Enum) semantics
    WAIT = "WAIT"
    WATCH = "WATCH"
    ENTRY_READY = "ENTRY_READY"
    CANCELLED = "CANCELLED"


class RevisedAction(str, Enum):  # noqa: UP042 - preserve legacy str(Enum) semantics
    OBSERVE = "OBSERVE"
    ENTER = "ENTER"
    CANCEL = "CANCEL"


class ConfirmationMode(str, Enum):  # noqa: UP042 - preserve legacy str(Enum) semantics
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
    scalper_min_obstacle_r: float = 0.10
    strict_target_buffer_atr: float = 0.12
    scalper_target_buffer_atr: float = 0.03
    stop_buffer_atr: float = 0.18
    adaptive_stop_buffer_atr: float = 0.10
    adaptive_stop_min_risk_atr: float = 0.35
    strong_m1_body_ratio: float = 0.55
    strong_m1_close_location: float = 0.75
    supply_displacement_atr: float = 0.80
    supply_confirmation_bars: int = 3
    zone_acceptance_closes: int = 2
    h1_supply_breakout_trend_min_atr: float = 0.0
    h1_supply_breakout_trend_max_atr: float = 2.0
    h1_supply_breakout_max_efficiency: float = 0.20
    watch_max_m1_bars: int = 60
    fibonacci_lookback_m5: int = 12
    fibonacci_retest_separation_bars: int = 2
    fibonacci_leave_fraction: float = 0.25
    psychological_steps: tuple[float, ...] = (10.0, 50.0, 100.0)
    swing_span: int = 2
    minimum_m5_votes: int = 2
    strong_m5_patterns: tuple[str, ...] = (
        "BULL_ENGULFING",
        "BEAR_ENGULFING",
        "BULL_MORNING_STAR",
        "BEAR_EVENING_STAR",
        "BULL_REJECTION",
        "BEAR_REJECTION",
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
        if (
            self.first_obstacle_reject_r <= 0
            or self.first_obstacle_strict_r <= self.first_obstacle_reject_r
        ):
            raise ValueError("first-obstacle R thresholds are invalid")
        if not 0 < self.scalper_min_obstacle_r < self.first_obstacle_reject_r:
            raise ValueError("scalper obstacle threshold is invalid")
        if self.scalper_target_buffer_atr < 0:
            raise ValueError("scalper target buffer is invalid")
        if self.price_tick <= 0 or self.spread_floor < 0:
            raise ValueError("price tick/spread floor is invalid")
        if self.adaptive_stop_buffer_atr < 0 or self.adaptive_stop_min_risk_atr <= 0:
            raise ValueError("adaptive stop configuration is invalid")
        if not 0 < self.strong_m1_body_ratio <= 1:
            raise ValueError("strong M1 body ratio is invalid")
        if not 0 < self.strong_m1_close_location <= 1:
            raise ValueError("strong M1 close location is invalid")
        if self.supply_displacement_atr <= 0:
            raise ValueError("supply displacement must be positive")
        if self.supply_confirmation_bars < 2:
            raise ValueError("supply confirmation window is too short")
        if self.zone_acceptance_closes < 2:
            raise ValueError("zone acceptance closes must be at least two")
        if self.h1_supply_breakout_trend_max_atr <= self.h1_supply_breakout_trend_min_atr:
            raise ValueError("H1 supply breakout trend bounds are invalid")
        if not 0 < self.h1_supply_breakout_max_efficiency <= 1:
            raise ValueError("H1 supply breakout efficiency is invalid")
        if self.watch_max_m1_bars < self.range_max_bars:
            raise ValueError("watch window must cover the range window")
        if self.fibonacci_lookback_m5 < 3 or self.fibonacci_retest_separation_bars < 1:
            raise ValueError("fibonacci window configuration is invalid")
        if not 0 < self.fibonacci_leave_fraction < 1:
            raise ValueError("fibonacci leave fraction is invalid")
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
    entry_profile: str
    observation_only: bool
    setup_trigger_time: datetime | None
    time: datetime
    reason: str
    validation_status: str
    retest_count: int
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
        self._zone_cache: dict[
            tuple[bool, int, datetime, datetime, float],
            tuple[dict[str, object], ...],
        ] = {}

    def terminal_decision(
        self,
        snapshot: RevisedSnapshot,
        reason: str,
    ) -> RevisedDecision:
        return self._decision(
            snapshot,
            RevisedState.CANCELLED,
            RevisedAction.CANCEL,
            reason,
            confidence=min(
                snapshot.confidence,
                self.config.promotion_confidence - 0.01,
            ),
            validation_status="HARD_INVALID",
        )

    def evaluate(self, snapshot: RevisedSnapshot) -> RevisedDecision:
        self._validate_snapshot(snapshot)
        if snapshot.m5_trigger_time is None or snapshot.m5_pattern == "NONE":
            return self._decision(
                snapshot,
                RevisedState.WAIT,
                RevisedAction.OBSERVE,
                "M5_SETUP_UNAVAILABLE",
                confidence=min(snapshot.confidence, self.config.promotion_confidence - 0.01),
            )
        side = snapshot.side
        current = snapshot.m1_bars[-1]
        atr_m1 = _atr(snapshot.m1_bars, self.config.atr_period)
        atr_m5 = _atr(snapshot.m5_bars, self.config.atr_period)
        entry = snapshot.entry if snapshot.entry is not None else current.close
        if atr_m1 <= 0 or atr_m5 <= 0:
            return self._decision(
                snapshot, RevisedState.WAIT, RevisedAction.OBSERVE, "ATR_UNAVAILABLE"
            )

        stop, risk_stats = self._entry_stop(snapshot, entry, atr_m1, atr_m5)
        risk_stats = dict(risk_stats)
        risk_stats["nearest_supply_zone"] = self._nearest_supply_zone(
            snapshot,
            entry,
        )
        risk_stats["nearest_demand_zone"] = self._nearest_demand_zone(
            snapshot,
            entry,
        )
        risk_stats["market_regime"] = self._market_regime_stats(snapshot)
        risk = abs(entry - stop)
        fibonacci = self._fibonacci_stats(snapshot, side, atr_m1)
        hard_invalidation = self._hard_invalidation(snapshot, side, atr_m1)
        obstacle, obstacle_kind = self._first_obstacle(snapshot, entry, atr_m1)
        obstacle_r = abs(obstacle - entry) / risk if obstacle is not None and risk > 0 else None
        range_stats = self._range_stats(snapshot, side, atr_m1)
        momentum, exhaustion, _momentum_stats = self._momentum_stats(snapshot, side, atr_m5)
        m1 = self._m1_confirmation(snapshot.m1_bars, side)
        strong_m1_now = self._strong_m1_confirmation(m1)
        strong_m1_latched = self._strong_m1_latched(snapshot, side)
        fibonacci_ok = bool(
            _as_int(fibonacci.get("retests", 0)) >= 1
            and bool(fibonacci.get("current_rejection"))
            and _as_int(m1.get("votes", 0)) == 3
            and bool(m1.get("micro_break"))
        )
        range_ok = self._range_confirmed(range_stats, m1) or fibonacci_ok
        strict_room = obstacle_r is not None and obstacle_r < self.config.first_obstacle_strict_r
        momentum_ok = (
            momentum
            and not exhaustion
            and obstacle_r is not None
            and obstacle_r >= self.config.first_obstacle_strict_r
            and snapshot.m5_votes >= self.config.minimum_m5_votes
        )
        strong_pattern = snapshot.m5_pattern in self.config.strong_m5_patterns
        supply_context = risk_stats.get("nearest_supply_zone") or {}
        inside_h1_supply = bool(
            isinstance(supply_context, dict) and supply_context.get("kind") == "H1_SUPPLY_INSIDE"
        )
        regime_context = _as_dict(risk_stats.get("market_regime") or {})
        h1_trend_atr = _as_float(regime_context.get("h1_trend_atr", 0.0))
        h1_supply_breakout_ok = bool(
            inside_h1_supply
            and bool(regime_context.get("above_h1_sma20"))
            and self.config.h1_supply_breakout_trend_min_atr
            <= h1_trend_atr
            < self.config.h1_supply_breakout_trend_max_atr
            and _as_float(regime_context.get("h1_efficiency", 1.0))
            < self.config.h1_supply_breakout_max_efficiency
        )
        supply_entry_context_ok = bool(not supply_context or h1_supply_breakout_ok)
        strong_first_ok = bool(
            obstacle_r is not None
            and obstacle_r >= self.config.first_obstacle_strict_r
            and strong_pattern
            and snapshot.m5_votes >= self.config.minimum_m5_votes
            and strong_m1_now
            and not bool(range_stats.get("acceptance"))
        )
        latched_retest_ok = bool(
            obstacle_r is not None
            and obstacle_r >= self.config.first_obstacle_strict_r
            and strong_pattern
            and snapshot.m5_votes >= self.config.minimum_m5_votes
            and strong_m1_latched
            and _as_int(fibonacci.get("retests", 0)) >= 1
            and bool(m1.get("directional"))
            and not inside_h1_supply
            and not bool(range_stats.get("acceptance"))
        )
        strict_ok = (
            obstacle_r is not None
            and obstacle_r >= self.config.first_obstacle_reject_r
            and m1["votes"] == 3
            and bool(m1["micro_break"])
            and strong_pattern
            and snapshot.m5_votes >= self.config.minimum_m5_votes
            and range_ok
        )
        scalper_ok = bool(
            side is RevisedSide.BUY
            and obstacle_r is not None
            and self.config.scalper_min_obstacle_r
            <= obstacle_r
            < self.config.first_obstacle_reject_r
            and obstacle_kind is not None
            and not obstacle_kind.startswith("PSYCH_")
            and not supply_context
            and strong_pattern
            and _as_int(m1.get("votes", 0)) == 3
            and bool(m1.get("micro_break"))
            and _as_int(fibonacci.get("retests", 0)) >= 1
            and (bool(fibonacci.get("current_rejection")) or self._range_confirmed(range_stats, m1))
            and not bool(range_stats.get("acceptance"))
        )
        if hard_invalidation:
            return self._decision(
                snapshot,
                RevisedState.CANCELLED,
                RevisedAction.CANCEL,
                "HARD_INVALIDATION_ACCEPTED",
                confidence=min(snapshot.confidence, self.config.promotion_confidence - 0.01),
                validation_status="HARD_INVALID",
                retest_count=_as_int(fibonacci.get("retests", 0)),
                entry=entry,
                stop=stop,
                obstacle=obstacle,
                obstacle_kind=obstacle_kind,
                obstacle_r=obstacle_r,
                range_stats=range_stats,
                m1=m1,
                momentum=momentum,
                exhausted=exhaustion,
                risk_stats=risk_stats,
                fibonacci=fibonacci,
            )
        if obstacle_r is None or obstacle_r < self.config.first_obstacle_reject_r:
            if scalper_ok:
                target = self._target(snapshot, side, entry, obstacle, atr_m5, scalper=True)
                if target is not None and target > entry:
                    return self._decision(
                        snapshot,
                        RevisedState.ENTRY_READY,
                        RevisedAction.ENTER,
                        "SCALPER_FIRST_OBSTACLE_ENTRY",
                        confidence=min(
                            snapshot.confidence, self.config.promotion_confidence - 0.01
                        ),
                        mode=ConfirmationMode.RANGE,
                        observation_only=True,
                        entry_profile="SCALPER",
                        validation_status="VALID",
                        retest_count=_as_int(fibonacci.get("retests", 0)),
                        entry=entry,
                        stop=stop,
                        target=target,
                        obstacle=obstacle,
                        obstacle_kind=obstacle_kind,
                        obstacle_r=obstacle_r,
                        range_stats=range_stats,
                        m1=m1,
                        momentum=momentum,
                        exhausted=exhaustion,
                        risk_stats=risk_stats,
                        fibonacci=fibonacci,
                    )
            return self._decision(
                snapshot,
                RevisedState.WATCH,
                RevisedAction.OBSERVE,
                "SOFT_FAIL_FIRST_OBSTACLE_ROOM",
                confidence=min(snapshot.confidence, self.config.promotion_confidence - 0.01),
                validation_status=(
                    "SOFT_FAIL" if _as_int(fibonacci.get("retests", 0)) > 0 else "WATCH_ONLY"
                ),
                retest_count=_as_int(fibonacci.get("retests", 0)),
                entry=entry,
                stop=stop,
                obstacle=obstacle,
                obstacle_kind=obstacle_kind,
                obstacle_r=obstacle_r,
                range_stats=range_stats,
                m1=m1,
                momentum=momentum,
                exhausted=exhaustion,
                risk_stats=risk_stats,
                fibonacci=fibonacci,
            )
        mode: ConfirmationMode | None
        if exhaustion:
            mode = ConfirmationMode.RANGE
        elif momentum_ok:
            mode = ConfirmationMode.MOMENTUM
        elif strong_first_ok or latched_retest_ok or range_ok:
            mode = ConfirmationMode.RANGE
        else:
            mode = ConfirmationMode.RANGE if strict_room else None
        eligible = bool(
            supply_entry_context_ok
            and (
                momentum_ok
                or strong_first_ok
                or latched_retest_ok
                or (range_ok and (not strict_room or strict_ok))
            )
        )
        if not eligible:
            return self._decision(
                snapshot,
                RevisedState.WATCH,
                RevisedAction.OBSERVE,
                (
                    "SUPPLY_CONTEXT_PENDING"
                    if not supply_entry_context_ok
                    else "M1_RANGE_OR_MOMENTUM_GATE_PENDING"
                ),
                confidence=min(snapshot.confidence, self.config.promotion_confidence - 0.01),
                entry=entry,
                stop=stop,
                obstacle=obstacle,
                obstacle_kind=obstacle_kind,
                obstacle_r=obstacle_r,
                range_stats=range_stats,
                m1=m1,
                momentum=momentum,
                exhausted=exhaustion,
                mode=mode,
                risk_stats=risk_stats,
                fibonacci=fibonacci,
                validation_status=(
                    "SOFT_FAIL" if _as_int(fibonacci.get("retests", 0)) > 0 else "WATCH_ONLY"
                ),
                retest_count=_as_int(fibonacci.get("retests", 0)),
            )
        target = self._target(snapshot, side, entry, obstacle, atr_m5)
        retest_count = _as_int(fibonacci.get("retests", 0))
        local_retest_scalper = bool(
            side is RevisedSide.BUY
            and obstacle_kind == "M5_SWING"
            and obstacle_r is not None
            and obstacle_r < 2.0
            and retest_count >= 2
        )
        confidence = min(100.0, max(0.0, float(snapshot.confidence)))
        confidence = min(confidence, self.config.promotion_confidence + 20.0)
        if strict_room and not strict_ok:
            confidence = min(confidence, self.config.promotion_confidence - 0.01)
        observation_only = side is RevisedSide.SELL or local_retest_scalper
        return self._decision(
            snapshot,
            RevisedState.ENTRY_READY,
            RevisedAction.ENTER,
            "MOMENTUM_ENTRY"
            if mode is ConfirmationMode.MOMENTUM
            else "STRONG_FIRST_CONFIRMATION"
            if strong_first_ok
            else "LATCHED_CONFIRMATION_RETEST"
            if latched_retest_ok
            else "RANGE_REJECTIONS_CONFIRMED",
            confidence=confidence,
            mode=mode,
            observation_only=observation_only,
            entry_profile="SCALPER" if local_retest_scalper else "CORE",
            validation_status="VALID",
            retest_count=retest_count,
            entry=entry,
            stop=stop,
            target=target,
            obstacle=obstacle,
            obstacle_kind=obstacle_kind,
            obstacle_r=obstacle_r,
            range_stats=range_stats,
            m1=m1,
            momentum=momentum,
            exhausted=exhaustion,
            risk_stats=risk_stats,
            fibonacci=fibonacci,
        )

    def _nearest_supply_zone(
        self,
        snapshot: RevisedSnapshot,
        entry: float,
        *,
        blocking_only: bool = False,
    ) -> dict[str, object] | None:
        candidates: list[dict[str, object]] = []
        for bars, timeframe in (
            (snapshot.m5_bars, "M5"),
            (snapshot.h1_bars, "H1"),
        ):
            atr = _atr(bars, self.config.atr_period)
            for zone in self._confirmed_zones(bars, atr, supply=True):
                proximal = _as_float(zone["proximal"])
                distal = _as_float(zone["distal"])
                if entry > distal:
                    continue
                inside = proximal <= entry <= distal
                if blocking_only and inside and timeframe == "H1":
                    continue
                candidates.append(
                    {
                        **zone,
                        "timeframe": timeframe,
                        "kind": (
                            f"{timeframe}_SUPPLY_INSIDE"
                            if inside
                            else f"{timeframe}_SUPPLY_PROXIMAL"
                        ),
                        "obstacle": entry if inside else proximal,
                    }
                )
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: abs(_as_float(item["obstacle"]) - entry),
        )

    def _nearest_demand_zone(
        self,
        snapshot: RevisedSnapshot,
        entry: float,
    ) -> dict[str, object] | None:
        candidates: list[dict[str, object]] = []
        for bars, timeframe in (
            (snapshot.m5_bars, "M5"),
            (snapshot.h1_bars, "H1"),
        ):
            atr = _atr(bars, self.config.atr_period)
            for zone in self._confirmed_zones(bars, atr, supply=False):
                proximal = _as_float(zone["proximal"])
                distal = _as_float(zone["distal"])
                if entry < distal:
                    continue
                inside = distal <= entry <= proximal
                candidates.append(
                    {
                        **zone,
                        "timeframe": timeframe,
                        "kind": (
                            f"{timeframe}_DEMAND_INSIDE"
                            if inside
                            else f"{timeframe}_DEMAND_PROXIMAL"
                        ),
                        "distance": 0.0 if inside else entry - proximal,
                    }
                )
        if not candidates:
            return None
        return min(candidates, key=lambda item: _as_float(item["distance"]))

    def _market_regime_stats(
        self,
        snapshot: RevisedSnapshot,
    ) -> dict[str, object]:
        m5 = snapshot.m5_bars
        h1 = snapshot.h1_bars
        atr_window = self.config.atr_period + 1
        recent_m5_atr = _atr(m5[-atr_window:], self.config.atr_period)
        prior_m5 = m5[-atr_window * 2 : -atr_window]
        prior_m5_atr = _atr(prior_m5, self.config.atr_period)
        h1_atr = _atr(h1, self.config.atr_period)
        trend_bars = h1[-24:]
        if len(trend_bars) >= 2:
            trend_move = trend_bars[-1].close - trend_bars[0].close
            travelled = sum(
                abs(current.close - previous.close) for previous, current in pairwise(trend_bars)
            )
            h1_trend_atr = trend_move / h1_atr if h1_atr > 0 else 0.0
            h1_efficiency = abs(trend_move) / travelled if travelled > 0 else 0.0
        else:
            h1_trend_atr = 0.0
            h1_efficiency = 0.0
        sma_bars = h1[-20:]
        h1_sma = fmean(bar.close for bar in sma_bars) if sma_bars else 0.0
        current_price = snapshot.m1_bars[-1].close
        return {
            "m5_atr": recent_m5_atr,
            "m5_atr_expansion": (recent_m5_atr / prior_m5_atr if prior_m5_atr > 0 else 1.0),
            "h1_atr": h1_atr,
            "h1_trend_atr": h1_trend_atr,
            "h1_efficiency": h1_efficiency,
            "above_h1_sma20": current_price >= h1_sma if h1_sma > 0 else False,
        }

    def _confirmed_zones(
        self,
        bars: Sequence[RevisedBar],
        atr: float,
        *,
        supply: bool,
    ) -> list[dict[str, object]]:
        confirmation = self.config.supply_confirmation_bars
        if len(bars) <= confirmation or atr <= 0:
            return []
        cache_key = (
            supply,
            len(bars),
            bars[0].time,
            bars[-1].time,
            round(atr, 8),
        )
        cached = self._zone_cache.get(cache_key)
        if cached is not None:
            return list(cached)
        zones: list[dict[str, object]] = []
        tolerance = self.config.spread_floor
        for index in range(len(bars) - confirmation):
            origin = bars[index]
            if origin.range <= 0:
                continue
            previous = bars[max(0, index - 2) : index]
            confirming = bars[index + 1 : index + confirmation + 1]
            body_ratio = origin.body / origin.range
            if supply:
                base_ok = origin.close >= origin.open or body_ratio <= 0.55
                swing_origin = not previous or all(origin.high >= bar.high for bar in previous)
                displacement = origin.high - min(bar.low for bar in confirming)
                structure_broken = min(bar.close for bar in confirming) < origin.low
                directional_count = sum(bar.close < bar.open for bar in confirming)
                proximal = min(origin.open, origin.close)
                distal = origin.high
                later = bars[index + confirmation + 1 :]
                accepted = self._zone_accepted(
                    later, boundary=distal + tolerance, above=True
                ) or any(
                    bar.range > 0
                    and bar.close > distal + tolerance
                    and bar.body / bar.range >= 0.55
                    and (bar.close - bar.low) / bar.range >= 0.75
                    for bar in later
                )
            else:
                base_ok = origin.close <= origin.open or body_ratio <= 0.55
                swing_origin = not previous or all(origin.low <= bar.low for bar in previous)
                displacement = max(bar.high for bar in confirming) - origin.low
                structure_broken = max(bar.close for bar in confirming) > origin.high
                directional_count = sum(bar.close > bar.open for bar in confirming)
                proximal = max(origin.open, origin.close)
                distal = origin.low
                later = bars[index + confirmation + 1 :]
                accepted = self._zone_accepted(
                    later, boundary=distal - tolerance, above=False
                ) or any(
                    bar.range > 0
                    and bar.close < distal - tolerance
                    and bar.body / bar.range >= 0.55
                    and (bar.high - bar.close) / bar.range >= 0.75
                    for bar in later
                )
            if (
                base_ok
                and swing_origin
                and structure_broken
                and directional_count >= 2
                and displacement >= atr * self.config.supply_displacement_atr
                and not accepted
            ):
                zones.append(
                    {
                        "proximal": proximal,
                        "distal": distal,
                        "origin_time": origin.time,
                        "displacement_atr": displacement / atr,
                    }
                )
        if len(self._zone_cache) >= 64:
            self._zone_cache.pop(next(iter(self._zone_cache)))
        self._zone_cache[cache_key] = tuple(zones)
        return zones

    def _zone_accepted(
        self,
        bars: Sequence[RevisedBar],
        *,
        boundary: float,
        above: bool,
    ) -> bool:
        consecutive = 0
        for bar in bars:
            accepted = bar.close > boundary if above else bar.close < boundary
            consecutive = consecutive + 1 if accepted else 0
            if consecutive >= self.config.zone_acceptance_closes:
                return True
        return False

    def _first_obstacle(
        self,
        snapshot: RevisedSnapshot,
        entry: float,
        atr_m1: float,
    ) -> tuple[float | None, str | None]:
        candidates: list[tuple[float, str]] = []
        side = snapshot.side
        if side is RevisedSide.BUY:
            supply = self._nearest_supply_zone(
                snapshot,
                entry,
                blocking_only=True,
            )
            if supply is not None:
                candidates.append((_as_float(supply["obstacle"]), str(supply["kind"])))
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
        for bars, label in (
            (snapshot.m5_bars, "M5_SWING"),
            (snapshot.h1_bars, "H1_SWING"),
            (snapshot.d1_bars, "D1_SWING"),
        ):
            pivots = (
                _swing_highs(bars, self.config.swing_span)
                if side is RevisedSide.BUY
                else _swing_lows(bars, self.config.swing_span)
            )
            for price in pivots:
                if (side is RevisedSide.BUY and price > entry) or (
                    side is RevisedSide.SELL and price < entry
                ):
                    candidates.append((price, label))
        # M1 candles formed after the M5 trigger belong to the confirmation
        # range. Treating their internal retest pivots as external obstacles
        # makes the measured room collapse while a WATCH is developing.
        # Only structure already confirmed before the setup may constrain its
        # first-obstacle room; post-trigger levels are handled by range,
        # acceptance, micro-break, and Fibonacci validation instead.
        obstacle_m1_bars = tuple(
            bar
            for bar in snapshot.m1_bars
            if snapshot.m5_trigger_time is None or bar.time < snapshot.m5_trigger_time
        )
        m1_pivots = (
            _swing_highs(obstacle_m1_bars, self.config.swing_span)
            if side is RevisedSide.BUY
            else _swing_lows(obstacle_m1_bars, self.config.swing_span)
        )
        directional_m1 = [
            price
            for price in m1_pivots
            if (side is RevisedSide.BUY and price > entry)
            or (side is RevisedSide.SELL and price < entry)
        ]
        tolerance = max(self.config.spread_floor * 2.0, atr_m1 * 0.20)
        for index, price in enumerate(directional_m1):
            repeated = any(
                abs(price - other) <= tolerance
                for other_index, other in enumerate(directional_m1)
                if other_index != index
            )
            confluent = any(
                abs(price - candidate_price) <= tolerance for candidate_price, _ in candidates
            )
            if repeated or confluent:
                candidates.append((price, "M1_SWING_CLUSTER"))
        if not candidates:
            return None, None
        selected = (
            min(
                candidates,
                key=lambda item: (
                    abs(item[0] - entry),
                    0 if "SUPPLY" in item[1] else 1,
                ),
            )
            if side is RevisedSide.BUY
            else max(candidates, key=lambda item: item[0])
        )
        return selected

    def _range_stats(
        self, snapshot: RevisedSnapshot, side: RevisedSide, atr: float
    ) -> dict[str, object]:
        trigger = snapshot.m5_trigger_time
        bars = [bar for bar in snapshot.m1_bars if trigger is None or bar.time > trigger]
        bars = bars[-self.config.range_max_bars :]
        if not bars:
            return {
                "bars": 0,
                "width": 0.0,
                "touches": 0,
                "rejections": 0,
                "acceptance": 0,
                "excursion": 0.0,
            }
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
            hit = (
                bar.low <= boundary + tolerance
                if side is RevisedSide.BUY
                else bar.high >= boundary - tolerance
            )
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
            bar
            for bar in bars[-self.config.acceptance_window :]
            if (
                bar.close < boundary - tolerance
                if side is RevisedSide.BUY
                else bar.close > boundary + tolerance
            )
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
            return {
                "votes": 0,
                "micro_break": False,
                "body_ratio": 0.0,
                "close_location": 0.0,
                "rsi7": 0.0,
            }
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
            close_location = (
                (latest.high - latest.close) / latest.range if latest.range > 0 else 0.0
            )
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

    def _strong_m1_confirmation(self, m1: dict[str, object]) -> bool:
        return bool(
            _as_int(m1.get("votes", 0)) == 3
            and bool(m1.get("micro_break"))
            and _as_float(m1.get("body_ratio", 0.0)) >= self.config.strong_m1_body_ratio
            and _as_float(m1.get("close_location", 0.0)) >= self.config.strong_m1_close_location
        )

    def _strong_m1_latched(
        self,
        snapshot: RevisedSnapshot,
        side: RevisedSide,
    ) -> bool:
        trigger = snapshot.m5_trigger_time
        bars = tuple(bar for bar in snapshot.m1_bars if trigger is None or bar.time > trigger)[
            -self.config.watch_max_m1_bars :
        ]
        return any(
            self._qualified_range_m1_confirmation(self._m1_confirmation(bars[: index + 1], side))
            for index in range(1, len(bars))
        )

    def _qualified_range_m1_confirmation(
        self,
        m1: dict[str, object],
    ) -> bool:
        return bool(
            _as_int(m1.get("votes", 0)) == 3
            and bool(m1.get("micro_break"))
            and _as_float(m1.get("body_ratio", 0.0)) >= self.config.range_min_body_fraction
            and _as_float(m1.get("close_location", 0.0)) >= self.config.range_min_close_location
        )

    def _range_confirmed(self, stats: dict[str, object], m1: dict[str, object]) -> bool:
        width = _as_float(stats.get("width", 0.0))
        excursion = _as_float(stats.get("excursion", 0.0))
        return bool(
            _as_int(stats.get("touches", 0)) >= self.config.range_min_rejections
            and _as_int(stats.get("rejections", 0)) >= self.config.range_min_rejections
            and width > 0
            and excursion >= width * self.config.range_min_excursion_fraction
            and not bool(stats.get("acceptance"))
            and bool(m1.get("micro_break"))
            and _as_float(m1.get("body_ratio", 0.0)) >= self.config.range_min_body_fraction
            and _as_float(m1.get("close_location", 0.0)) >= self.config.range_min_close_location
            and _as_int(m1.get("votes", 0)) >= 3
        )

    def _momentum_stats(
        self, snapshot: RevisedSnapshot, side: RevisedSide, atr: float
    ) -> tuple[bool, bool, dict[str, object]]:
        bars = snapshot.m5_bars[-self.config.momentum_bars :]
        if len(bars) < self.config.momentum_bars or atr <= 0:
            return False, False, {"displacement_atr": 0.0, "body_ratio": 0.0}
        first, latest = bars[0], bars[-1]
        displacement = (
            (latest.close - first.open) if side is RevisedSide.BUY else (first.open - latest.close)
        )
        body_ratio = latest.body / latest.range if latest.range > 0 else 0.0
        close_location = (
            (
                (latest.close - latest.low) / latest.range
                if side is RevisedSide.BUY
                else (latest.high - latest.close) / latest.range
            )
            if latest.range > 0
            else 0.0
        )
        directional = all(
            (bar.close > bar.open if side is RevisedSide.BUY else bar.close < bar.open)
            for bar in bars[-2:]
        )
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
            if (side is RevisedSide.BUY and latest.high <= prev.high + atr * 0.10) or (
                side is RevisedSide.SELL and latest.low >= prev.low - atr * 0.10
            ):
                exhaustion_signals += 1
            if body_ratio < 0.35:
                exhaustion_signals += 1
        exhausted = exhaustion_signals >= self.config.exhaustion_min_signals
        return (
            momentum,
            exhausted,
            {
                "displacement_atr": displacement / atr,
                "body_ratio": body_ratio,
                "close_location": close_location,
                "exhaustion_signals": exhaustion_signals,
            },
        )

    def _fibonacci_stats(
        self,
        snapshot: RevisedSnapshot,
        side: RevisedSide,
        atr_m1: float,
    ) -> dict[str, object]:
        trigger = snapshot.m5_trigger_time
        closed_before_trigger = [
            bar for bar in snapshot.m5_bars if trigger is None or bar.time < trigger
        ][-self.config.fibonacci_lookback_m5 :]
        if len(closed_before_trigger) < 3:
            return {"available": False, "retests": 0, "current_rejection": False}
        best: tuple[float, float] | None = None
        best_range = 0.0
        if side is RevisedSide.BUY:
            for start_index, start in enumerate(closed_before_trigger[:-1]):
                for end in closed_before_trigger[start_index + 1 :]:
                    distance = end.high - start.low
                    if distance > best_range:
                        best_range = distance
                        best = (start.low, end.high)
        else:
            for start_index, start in enumerate(closed_before_trigger[:-1]):
                for end in closed_before_trigger[start_index + 1 :]:
                    distance = start.high - end.low
                    if distance > best_range:
                        best_range = distance
                        best = (start.high, end.low)
        if best is None or best_range <= 0:
            return {"available": False, "retests": 0, "current_rejection": False}
        anchor_start, anchor_end = best
        if side is RevisedSide.BUY:
            zone_low = anchor_end - best_range * 0.618
            zone_high = anchor_end - best_range * 0.382
        else:
            zone_low = anchor_end + best_range * 0.382
            zone_high = anchor_end + best_range * 0.618
        after_trigger = [bar for bar in snapshot.m1_bars if trigger is None or bar.time > trigger][
            -self.config.watch_max_m1_bars :
        ]
        retests = 0
        last_touch = -10_000
        left_zone = True
        leave_distance = max(
            (zone_high - zone_low) * self.config.fibonacci_leave_fraction,
            atr_m1 * 0.10,
        )
        for index, bar in enumerate(after_trigger):
            overlaps = bar.low <= zone_high and bar.high >= zone_low
            if not overlaps:
                if side is RevisedSide.BUY:
                    left_zone = bar.close >= zone_high + leave_distance
                else:
                    left_zone = bar.close <= zone_low - leave_distance
                continue
            if left_zone and index - last_touch >= self.config.fibonacci_retest_separation_bars:
                retests += 1
                last_touch = index
                left_zone = False
        current = after_trigger[-1] if after_trigger else None
        recent_touch = bool(last_touch >= 0 and last_touch >= len(after_trigger) - 3)
        current_rejection = bool(
            current is not None
            and recent_touch
            and (current.close > zone_high if side is RevisedSide.BUY else current.close < zone_low)
        )
        return {
            "available": True,
            "anchor_start": anchor_start,
            "anchor_end": anchor_end,
            "zone_low": zone_low,
            "zone_high": zone_high,
            "retests": retests,
            "current_rejection": current_rejection,
        }

    def _hard_invalidation(
        self,
        snapshot: RevisedSnapshot,
        side: RevisedSide,
        atr_m1: float,
    ) -> bool:
        if snapshot.invalidation is None or snapshot.m5_trigger_time is None:
            return False
        bars = [bar for bar in snapshot.m1_bars if bar.time > snapshot.m5_trigger_time][
            -self.config.acceptance_window :
        ]
        if len(bars) < self.config.acceptance_close_count:
            return False
        tolerance = max(self.config.spread_floor, atr_m1 * 0.10)
        outside = [
            bar
            for bar in bars
            if (
                bar.close < snapshot.invalidation - tolerance
                if side is RevisedSide.BUY
                else bar.close > snapshot.invalidation + tolerance
            )
        ]
        consecutive = all(
            (
                bar.close < snapshot.invalidation - tolerance
                if side is RevisedSide.BUY
                else bar.close > snapshot.invalidation + tolerance
            )
            for bar in bars[-self.config.acceptance_close_count :]
        )
        displacement = abs(bars[-1].close - bars[0].open)
        return bool(
            consecutive
            or (
                len(outside) >= 3
                and len(bars) >= 4
                and displacement >= atr_m1 * self.config.acceptance_displacement_atr
            )
        )

    def _risk(self, snapshot: RevisedSnapshot, entry: float, atr: float) -> float:
        if snapshot.stop is not None:
            return abs(entry - snapshot.stop)
        return max(atr * self.config.stop_buffer_atr, self.config.spread_floor * 2.0)

    def _entry_stop(
        self,
        snapshot: RevisedSnapshot,
        entry: float,
        atr_m1: float,
        atr_m5: float,
    ) -> tuple[float, dict[str, object]]:
        side = snapshot.side
        fallback_risk = self._risk(snapshot, entry, atr_m5)
        fallback = (
            snapshot.stop
            if snapshot.stop is not None
            else entry - fallback_risk
            if side is RevisedSide.BUY
            else entry + fallback_risk
        )
        source = "M5_INVALIDATION" if snapshot.stop is not None else "ATR_FALLBACK"
        trigger = snapshot.m5_trigger_time
        bars = tuple(bar for bar in snapshot.m1_bars if trigger is None or bar.time > trigger)
        pivots = (
            _swing_lows(bars, self.config.swing_span)
            if side is RevisedSide.BUY
            else _swing_highs(bars, self.config.swing_span)
        )
        directional_pivots = [
            price
            for price in pivots
            if (side is RevisedSide.BUY and price < entry)
            or (side is RevisedSide.SELL and price > entry)
        ]
        buffer = max(
            self.config.spread_floor,
            atr_m1 * self.config.adaptive_stop_buffer_atr,
        )
        minimum_risk = max(
            self.config.spread_floor * 2.0,
            atr_m1 * self.config.adaptive_stop_min_risk_atr,
        )
        structural: float | None = None
        if directional_pivots:
            pivot = max(directional_pivots) if side is RevisedSide.BUY else min(directional_pivots)
            structural = pivot - buffer if side is RevisedSide.BUY else pivot + buffer
            structural = (
                min(structural, entry - minimum_risk)
                if side is RevisedSide.BUY
                else max(structural, entry + minimum_risk)
            )
        selected = float(fallback)
        if structural is not None:
            fallback_distance = abs(entry - selected)
            structural_distance = abs(entry - structural)
            if minimum_risk <= structural_distance < fallback_distance:
                selected = structural
                source = "M1_CONFIRMED_STRUCTURE"
        selected = _normalize(selected, self.config.price_tick)
        return selected, {
            "source": source,
            "original_stop": _normalize(float(fallback), self.config.price_tick),
            "selected_stop": selected,
            "risk": abs(entry - selected),
            "m1_pivot_count": len(directional_pivots),
        }

    def _stop(self, snapshot: RevisedSnapshot, entry: float, risk: float) -> float:
        if snapshot.stop is not None:
            return _normalize(snapshot.stop, self.config.price_tick)
        return _normalize(
            entry - risk if snapshot.side is RevisedSide.BUY else entry + risk,
            self.config.price_tick,
        )

    def _target(
        self,
        snapshot: RevisedSnapshot,
        side: RevisedSide,
        entry: float,
        obstacle: float | None,
        atr: float,
        *,
        scalper: bool = False,
    ) -> float | None:
        if obstacle is None:
            return None
        buffer_atr = (
            self.config.scalper_target_buffer_atr
            if scalper
            else self.config.strict_target_buffer_atr
        )
        buffer = max(self.config.spread_floor, atr * buffer_atr)
        return _normalize(
            obstacle - buffer if side is RevisedSide.BUY else obstacle + buffer,
            self.config.price_tick,
        )

    def _decision(
        self,
        snapshot: RevisedSnapshot,
        state: RevisedState,
        action: RevisedAction,
        reason: str,
        *,
        confidence: float | None = None,
        mode: ConfirmationMode | None = None,
        exhausted: bool = False,
        observation_only: bool | None = None,
        entry_profile: str = "CORE",
        validation_status: str = "WATCH_ONLY",
        retest_count: int = 0,
        entry: float | None = None,
        stop: float | None = None,
        target: float | None = None,
        obstacle: float | None = None,
        obstacle_kind: str | None = None,
        obstacle_r: float | None = None,
        range_stats: dict[str, object] | None = None,
        m1: dict[str, object] | None = None,
        momentum: bool = False,
        risk_stats: dict[str, object] | None = None,
        fibonacci: dict[str, object] | None = None,
    ) -> RevisedDecision:
        range_stats = range_stats or {}
        m1 = m1 or {}
        evidence = {
            "range": range_stats,
            "m1": m1,
            "momentum": momentum,
            "m5_pattern": snapshot.m5_pattern,
            "m5_votes": snapshot.m5_votes,
            "risk": risk_stats or {},
            "fibonacci": fibonacci or {},
        }
        return RevisedDecision(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            symbol=snapshot.symbol,
            side=snapshot.side,
            state=state,
            action=action,
            entry_profile=entry_profile,
            observation_only=(
                snapshot.side is RevisedSide.SELL if observation_only is None else observation_only
            ),
            setup_trigger_time=snapshot.m5_trigger_time,
            time=snapshot.current_time,
            reason=reason,
            validation_status=validation_status,
            retest_count=retest_count,
            confidence=float(snapshot.confidence if confidence is None else confidence),
            mode=mode,
            exhausted=exhausted,
            entry=entry,
            stop=stop,
            target=target,
            first_obstacle=obstacle,
            first_obstacle_kind=obstacle_kind,
            first_obstacle_r=obstacle_r,
            touch_count=_as_int(range_stats.get("touches", 0)),
            rejection_count=_as_int(range_stats.get("rejections", 0)),
            acceptance_count=_as_int(range_stats.get("acceptance", 0)),
            m1_votes=_as_int(m1.get("votes", 0)),
            evidence=evidence,
        )

    @staticmethod
    def _validate_snapshot(snapshot: RevisedSnapshot) -> None:
        if snapshot.symbol.strip() == "":
            raise ValueError("snapshot symbol is required")
        if not snapshot.m1_bars or not snapshot.m5_bars:
            raise ValueError("M1 and M5 closed bars are required")
        for bars in (snapshot.m1_bars, snapshot.m5_bars, snapshot.h1_bars, snapshot.d1_bars):
            if any(current.time <= previous.time for previous, current in pairwise(bars)):
                raise ValueError("snapshot bars must be strictly ordered")
        if snapshot.m1_bars[-1].time > snapshot.current_time:
            raise ValueError("current_time cannot precede the latest closed M1 bar")


def _atr(bars: Sequence[RevisedBar], period: int) -> float:
    if len(bars) < period + 1:
        return 0.0
    values = []
    for previous, current in zip(bars[-(period + 1) : -1], bars[-period:], strict=True):
        values.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return fmean(values)


def _rsi(closes: Sequence[float], period: int = 7) -> float:
    if len(closes) < period + 1:
        return 50.0
    changes = [current - previous for previous, current in pairwise(closes)]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    gain = fmean(gains[:period])
    loss = fmean(losses[:period])
    for up, down in zip(gains[period:], losses[period:], strict=True):
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
