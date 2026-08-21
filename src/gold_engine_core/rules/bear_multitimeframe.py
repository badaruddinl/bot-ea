from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from statistics import fmean
from typing import cast

from .bear import (
    BearBar,
    BearDecision,
    BearEngine,
    _as_float,
    _as_int,
    _average_true_range,
    _simple_rsi,
    _stochastic_stats,
)
from .bear_candidate import confluence_v1_config


def _as_datetime(value: object) -> datetime:
    return cast(datetime, value)


@dataclass(frozen=True, slots=True)
class BearV4Config:
    h1_sma_period: int = 20
    m5_watch_bars: int = 12
    m5_touch_separation_bars: int = 2
    m5_retreat_atr: float = 0.25
    m5_min_touches: int = 1
    m5_min_rejections: int = 1
    m5_acceptance_closes: int = 2
    m1_entry_bars: int = 20
    m1_min_touches: int = 2
    m1_body_fraction: float = 0.35
    m1_close_location: float = 0.35
    stop_buffer_atr_m5: float = 0.10
    minimum_reward_risk: float = 0.70
    minimum_psychological_reward_risk: float = 0.35
    minimum_continuation_reward_risk: float = 0.50
    price_tick: float = 0.01
    fixed_target_r: float | None = None
    cap_fixed_target_at_structural_support: bool = False
    stop_multiplier: float = 1.0
    target_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.fixed_target_r is not None and self.fixed_target_r <= 0:
            raise ValueError("fixed target R must be positive")
        if self.stop_multiplier <= 0 or self.target_multiplier <= 0:
            raise ValueError("stop and target multipliers must be positive")

    spread_floor: float = 0.20


@dataclass(frozen=True, slots=True)
class BearV4Outcome:
    setup_time: datetime
    armed_at: datetime
    opened_at: datetime
    closed_at: datetime
    result: str
    entry: float
    stop: float
    structural_stop: float
    target: float
    structural_target: float
    target_crosses_structural_support: bool
    outcome_r: float
    planned_reward_risk: float
    mfe_r: float
    mae_r: float
    m5_touches: int
    m5_rejections: int
    m1_touches: int
    setup_reason: str


@dataclass(frozen=True, slots=True)
class BearV4Report:
    from_time: datetime
    to_time: datetime
    m15_setups: int
    h1_rejected: int
    m5_armed: int
    m5_cancelled: int
    m1_expired_or_cancelled: int
    executed_signals: int
    skipped_overlapping_signals: int
    target_count: int
    stop_count: int
    ambiguous_count: int
    end_of_test_count: int
    targets_crossing_structural_support: int
    total_r: float
    expectancy_r: float
    maximum_drawdown_r: float
    outcomes: tuple[BearV4Outcome, ...]

    def as_dict(self) -> dict[str, object]:
        return cast(dict[str, object], asdict(self))


class BearMultiTimeframeReplay:
    """H1 context, M15 setup, M5 validation, and M1 SELL timing."""

    def __init__(
        self,
        config: BearV4Config | None = None,
        *,
        symbol: str = "GOLD.i#",
    ) -> None:
        self.config = config or BearV4Config()
        self.setup_engine = BearEngine(confluence_v1_config(symbol=symbol))

    def run(
        self,
        *,
        m1_bars: Sequence[BearBar],
        m5_bars: Sequence[BearBar],
        m15_bars: Sequence[BearBar],
        h1_bars: Sequence[BearBar],
        from_time: datetime,
        to_time: datetime,
    ) -> BearV4Report:
        setup_signals = [
            signal
            for signal in self.setup_engine.scan(m15_bars)
            if from_time <= signal.time < to_time
        ]
        outcomes: list[BearV4Outcome] = []
        h1_rejected = 0
        m5_armed = 0
        m5_cancelled = 0
        m1_cancelled = 0
        overlap = 0
        unavailable_until = from_time
        m1_times = [bar.time for bar in m1_bars]
        m5_times = [bar.time for bar in m5_bars]
        h1_close_times = [bar.time + timedelta(hours=1) for bar in h1_bars]
        m1_end_index = bisect.bisect_left(m1_times, to_time)
        for setup in setup_signals:
            setup_available = setup.time + timedelta(minutes=15)
            if setup_available < unavailable_until:
                overlap += 1
                continue
            h1_index = bisect.bisect_right(h1_close_times, setup_available)
            h1_history = h1_bars[max(0, h1_index - self.config.h1_sma_period - 2) : h1_index]
            if not self._h1_bearish(h1_history):
                h1_rejected += 1
                continue
            m5_index = bisect.bisect_left(m5_times, setup_available)
            validation_start = max(0, m5_index - 3)
            m5_result = self._arm_on_m5(
                setup,
                m5_bars[max(0, validation_start - 20) : validation_start],
                m5_bars[validation_start : validation_start + self.config.m5_watch_bars],
                setup_available,
            )
            if m5_result["state"] != "ARMED":
                m5_cancelled += 1
                continue
            m5_armed += 1
            armed_at = _as_datetime(m5_result["armed_at"])
            m1_index = bisect.bisect_left(m1_times, armed_at)
            entry_plan = self._entry_on_m1(
                setup,
                m5_result,
                m1_bars[max(0, m1_index - 20) : m1_index],
                m1_bars[m1_index : m1_index + self.config.m1_entry_bars],
            )
            if entry_plan is None:
                m1_cancelled += 1
                continue
            opened_index = bisect.bisect_left(m1_times, _as_datetime(entry_plan["opened_at"]))
            outcome = self._resolve_m1(
                setup,
                m1_bars[opened_index:m1_end_index],
                entry_plan,
                to_time,
            )
            outcomes.append(outcome)
            unavailable_until = outcome.closed_at
        equity = 0.0
        peak = 0.0
        maximum_drawdown = 0.0
        for outcome in sorted(outcomes, key=lambda item: item.closed_at):
            equity += outcome.outcome_r
            peak = max(peak, equity)
            maximum_drawdown = max(maximum_drawdown, peak - equity)
        return BearV4Report(
            from_time=from_time,
            to_time=to_time,
            m15_setups=len(setup_signals),
            h1_rejected=h1_rejected,
            m5_armed=m5_armed,
            m5_cancelled=m5_cancelled,
            m1_expired_or_cancelled=m1_cancelled,
            executed_signals=len(outcomes),
            skipped_overlapping_signals=overlap,
            target_count=sum(item.result == "TARGET" for item in outcomes),
            stop_count=sum(item.result == "STOP" for item in outcomes),
            ambiguous_count=sum(item.result == "AMBIGUOUS_SAME_BAR" for item in outcomes),
            end_of_test_count=sum(item.result == "END_OF_TEST" for item in outcomes),
            targets_crossing_structural_support=sum(
                item.target_crosses_structural_support for item in outcomes
            ),
            total_r=sum(item.outcome_r for item in outcomes),
            expectancy_r=(
                sum(item.outcome_r for item in outcomes) / len(outcomes) if outcomes else 0.0
            ),
            maximum_drawdown_r=maximum_drawdown,
            outcomes=tuple(outcomes),
        )

    def _h1_bearish(self, bars: Sequence[BearBar]) -> bool:
        if len(bars) < self.config.h1_sma_period + 1:
            return False
        closes = [bar.close for bar in bars]
        current = fmean(closes[-self.config.h1_sma_period :])
        previous = fmean(closes[-self.config.h1_sma_period - 1 : -1])
        return closes[-1] < current and current < previous

    def _arm_on_m5(
        self,
        setup: BearDecision,
        history: Sequence[BearBar],
        candidates: Sequence[BearBar],
        available_at: datetime,
    ) -> dict[str, object]:
        if setup.resistance is None:
            return {"state": "CANCELLED"}
        # The closed M15 setup is itself the first confirmed resistance touch
        # and rejection. M5 validates the subsequent bearish restart.
        touches = 1
        rejections = 1
        last_touch = -10_000
        retreated = True
        resistance = float(setup.resistance)
        for index, bar in enumerate(candidates):
            context = tuple(history) + tuple(candidates[: index + 1])
            if len(context) < 15:
                continue
            atr = _average_true_range(context, 14)
            tolerance = max(self.config.spread_floor, atr * 0.20)
            acceptance = index + 1 >= self.config.m5_acceptance_closes and all(
                item.close > resistance + tolerance
                for item in candidates[index + 1 - self.config.m5_acceptance_closes : index + 1]
            )
            if acceptance:
                return {"state": "CANCELLED", "reason": "M5_ACCEPTANCE"}
            touched = bar.high >= resistance - tolerance
            if not touched:
                if bar.close <= resistance - atr * self.config.m5_retreat_atr:
                    retreated = True
            else:
                if retreated and index - last_touch >= self.config.m5_touch_separation_bars:
                    touches += 1
                    if bar.close < resistance and (
                        bar.close < bar.open or bar.upper_wick >= bar.body
                    ):
                        rejections += 1
                    last_touch = index
                    retreated = False
            previous = context[-2] if len(context) >= 2 else None
            close_location = (bar.close - bar.low) / bar.full_range if bar.full_range > 0 else 1.0
            momentum = bool(
                previous is not None
                and bar.close < bar.open
                and close_location <= 0.35
                and (bar.close < previous.low or bar.body >= atr * 0.45)
            )
            strong_failure = bool(
                momentum and bar.body >= atr * 0.55 and bar.high >= resistance - tolerance
            )
            repeated = bool(
                touches >= self.config.m5_min_touches
                and rejections >= self.config.m5_min_rejections
                and momentum
            )
            if strong_failure or repeated:
                return {
                    "state": "ARMED",
                    "armed_at": max(
                        available_at,
                        bar.time + timedelta(minutes=5),
                    ),
                    "atr": atr,
                    "touches": touches,
                    "rejections": rejections,
                    "recent_high": max(item.high for item in candidates[: index + 1]),
                }
        return {"state": "EXPIRED", "touches": touches, "rejections": rejections}

    def _entry_on_m1(
        self,
        setup: BearDecision,
        m5_result: dict[str, object],
        history: Sequence[BearBar],
        candidates: Sequence[BearBar],
    ) -> dict[str, object] | None:
        if setup.entry is None or setup.resistance is None or setup.take_profit is None:
            return None
        armed_at = _as_datetime(m5_result["armed_at"])
        resistance = float(setup.resistance)
        zone_low = min(float(setup.entry), resistance)
        atr_m5 = _as_float(m5_result["atr"])
        tolerance = max(self.config.spread_floor, atr_m5 * 0.10)
        touches = 0
        retreated = True
        for index, bar in enumerate(candidates):
            context = tuple(history) + tuple(candidates[: index + 1])
            if index >= 1 and all(
                item.close > resistance + tolerance
                for item in candidates[max(0, index - 1) : index + 1]
            ):
                return None
            touched = bar.high >= zone_low - tolerance
            if not touched:
                if bar.close <= zone_low - tolerance:
                    retreated = True
                continue
            if retreated:
                touches += 1
                retreated = False
            previous = context[-2] if len(context) >= 2 else None
            if previous is None:
                continue
            body_fraction = bar.body / bar.full_range if bar.full_range > 0 else 0.0
            close_location = (bar.close - bar.low) / bar.full_range if bar.full_range > 0 else 1.0
            micro_break = bar.close < previous.low and bar.close < bar.open
            strong = body_fraction >= 0.55 and close_location <= 0.25
            ordinary = bool(
                touches >= self.config.m1_min_touches
                and body_fraction >= self.config.m1_body_fraction
                and close_location <= self.config.m1_close_location
            )
            rsi_now = _simple_rsi([item.close for item in context], 7)
            rsi_previous = _simple_rsi([item.close for item in context[:-1]], 7)
            stochastic = _stochastic_stats(context, 14, 3)
            oscillator_turn = bool(
                rsi_now < rsi_previous
                or (
                    stochastic["k"] < stochastic["previous_k"] and stochastic["k"] < stochastic["d"]
                )
            )
            if not (micro_break and oscillator_turn and (strong or ordinary)):
                continue
            entry = previous.low - self.config.price_tick
            structural_stop = max(
                resistance,
                _as_float(m5_result["recent_high"]),
                max(item.high for item in candidates[: index + 1]),
            ) + max(self.config.spread_floor * 2.0, atr_m5 * self.config.stop_buffer_atr_m5)
            structural_target = float(setup.take_profit)
            stop = entry + (structural_stop - entry) * self.config.stop_multiplier
            multiplied_structural_target = (
                entry - (entry - structural_target) * self.config.target_multiplier
            )
            fixed_target = (
                entry - self.config.fixed_target_r * (stop - entry)
                if self.config.fixed_target_r is not None
                else multiplied_structural_target
            )
            target = (
                max(fixed_target, structural_target)
                if self.config.fixed_target_r is not None
                and self.config.cap_fixed_target_at_structural_support
                else fixed_target
            )
            if not target < entry < stop:
                return None
            reward_risk = (entry - target) / (stop - entry)
            required_reward_risk = (
                0.0
                if self.config.fixed_target_r is not None
                else (
                    self.config.minimum_psychological_reward_risk
                    if "target_capped_at_nearest_psychological_support" in setup.reason
                    else self.config.minimum_continuation_reward_risk
                    if "continuation_through_near_support" in setup.reason
                    else self.config.minimum_reward_risk
                )
            )
            if reward_risk < required_reward_risk:
                return None
            return {
                "armed_at": armed_at,
                "opened_at": bar.time + timedelta(minutes=1),
                "entry": entry,
                "stop": stop,
                "target": target,
                "structural_target": structural_target,
                "structural_stop": structural_stop,
                "m5_touches": _as_int(m5_result["touches"]),
                "m5_rejections": _as_int(m5_result["rejections"]),
                "m1_touches": touches,
            }
        return None

    @staticmethod
    def _resolve_m1(
        setup: BearDecision,
        bars: Sequence[BearBar],
        plan: dict[str, object],
        to_time: datetime,
    ) -> BearV4Outcome:
        entry = _as_float(plan["entry"])
        stop = _as_float(plan["stop"])
        structural_stop = _as_float(plan["structural_stop"])
        target = _as_float(plan["target"])
        structural_target = _as_float(plan["structural_target"])
        risk = stop - entry
        result = "END_OF_TEST"
        closed_at = to_time
        outcome_r = 0.0
        mfe_r = 0.0
        mae_r = 0.0
        last_close = entry
        for bar in bars:
            if bar.time < _as_datetime(plan["opened_at"]) or bar.time >= to_time:
                continue
            last_close = bar.close
            mfe_r = max(mfe_r, (entry - bar.low) / risk)
            mae_r = min(mae_r, (entry - bar.high) / risk)
            stop_hit = bar.high >= stop
            target_hit = bar.low <= target
            if not stop_hit and not target_hit:
                continue
            closed_at = bar.time + timedelta(minutes=1)
            if stop_hit and target_hit:
                result = "AMBIGUOUS_SAME_BAR"
                outcome_r = -1.0
            elif stop_hit:
                result = "STOP"
                outcome_r = -1.0
            else:
                result = "TARGET"
                outcome_r = (entry - target) / risk
            break
        if result == "END_OF_TEST":
            outcome_r = (entry - last_close) / risk
        return BearV4Outcome(
            setup_time=setup.time,
            armed_at=_as_datetime(plan["armed_at"]),
            opened_at=_as_datetime(plan["opened_at"]),
            closed_at=closed_at,
            result=result,
            entry=entry,
            stop=stop,
            structural_stop=structural_stop,
            target=target,
            structural_target=structural_target,
            target_crosses_structural_support=target < structural_target,
            outcome_r=outcome_r,
            planned_reward_risk=(entry - target) / risk,
            mfe_r=mfe_r,
            mae_r=mae_r,
            m5_touches=_as_int(plan["m5_touches"]),
            m5_rejections=_as_int(plan["m5_rejections"]),
            m1_touches=_as_int(plan["m1_touches"]),
            setup_reason=setup.reason,
        )
