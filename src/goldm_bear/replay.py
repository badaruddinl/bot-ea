from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .engine import (
    BearBar,
    BearDecision,
    BearEngine,
    BearExitAction,
    ShortPosition,
)


@dataclass(frozen=True, slots=True)
class BearReplayOutcome:
    signal_time: datetime
    opened_at: datetime
    closed_at: datetime
    result: str
    entry: float
    stop: float
    target: float
    planned_reward_risk: float
    outcome_r: float
    mfe_r: float
    mae_r: float
    score: int
    reason: str
    exit_reason: str
    regime_slope_atr: float | None
    regime_drop_atr: float | None
    chase_distance_atr: float | None
    resistance_kind: str | None


@dataclass(frozen=True, slots=True)
class BearReplayReport:
    from_time: datetime
    to_time: datetime
    candidate_signals: int
    executed_signals: int
    skipped_overlapping_signals: int
    target_count: int
    stop_count: int
    ambiguous_count: int
    invalidated_count: int
    end_of_test_count: int
    total_r: float
    expectancy_r: float
    maximum_drawdown_r: float
    outcomes: tuple[BearReplayOutcome, ...]

    def as_dict(self):
        return asdict(self)


class BearReplay:
    """Causal single-position replay for the standalone SELL engine."""

    def __init__(self, engine: BearEngine | None = None) -> None:
        self.engine = engine or BearEngine()

    def run(
        self,
        bars: Sequence[BearBar],
        *,
        from_time: datetime,
        to_time: datetime,
    ) -> BearReplayReport:
        selected = [bar for bar in bars if bar.time < to_time]
        signals = [
            signal
            for signal in self.engine.scan(selected)
            if from_time <= signal.time < to_time
        ]
        outcomes: list[BearReplayOutcome] = []
        skipped_overlap = 0
        unavailable_until = from_time
        for signal in signals:
            opened_at = signal.time + timedelta(minutes=15)
            if opened_at < unavailable_until:
                skipped_overlap += 1
                continue
            outcome = self._resolve(signal, selected, opened_at, to_time)
            outcomes.append(outcome)
            unavailable_until = outcome.closed_at
        equity = 0.0
        peak = 0.0
        maximum_drawdown = 0.0
        for outcome in sorted(outcomes, key=lambda item: item.closed_at):
            equity += outcome.outcome_r
            peak = max(peak, equity)
            maximum_drawdown = max(maximum_drawdown, peak - equity)
        return BearReplayReport(
            from_time=from_time,
            to_time=to_time,
            candidate_signals=len(signals),
            executed_signals=len(outcomes),
            skipped_overlapping_signals=skipped_overlap,
            target_count=sum(item.result == "TARGET" for item in outcomes),
            stop_count=sum(item.result == "STOP" for item in outcomes),
            ambiguous_count=sum(
                item.result == "AMBIGUOUS_SAME_BAR" for item in outcomes
            ),
            invalidated_count=sum(item.result == "INVALIDATED" for item in outcomes),
            end_of_test_count=sum(item.result == "END_OF_TEST" for item in outcomes),
            total_r=sum(item.outcome_r for item in outcomes),
            expectancy_r=(
                sum(item.outcome_r for item in outcomes) / len(outcomes)
                if outcomes
                else 0.0
            ),
            maximum_drawdown_r=maximum_drawdown,
            outcomes=tuple(outcomes),
        )

    def _resolve(
        self,
        signal: BearDecision,
        bars: Sequence[BearBar],
        opened_at: datetime,
        to_time: datetime,
    ) -> BearReplayOutcome:
        if signal.entry is None or signal.stop is None or signal.take_profit is None:
            raise ValueError("SELL signal is missing its price plan")
        entry = float(signal.entry)
        stop = float(signal.stop)
        target = float(signal.take_profit)
        risk = stop - entry
        if not target < entry < stop or risk <= 0:
            raise ValueError("SELL signal price plan is invalid")
        result = "END_OF_TEST"
        closed_at = to_time
        outcome_r = 0.0
        exit_reason = "end_of_test"
        mfe_r = 0.0
        mae_r = 0.0
        last_close = entry
        position = ShortPosition(
            entry=entry,
            stop=stop,
            take_profit=target,
            structural_resistance=float(signal.resistance or stop),
        )
        for index, bar in enumerate(bars):
            if bar.time < opened_at or bar.time >= to_time:
                continue
            last_close = bar.close
            mfe_r = max(mfe_r, (entry - bar.low) / risk)
            mae_r = min(mae_r, (entry - bar.high) / risk)
            stop_hit = bar.high >= stop
            target_hit = bar.low <= target
            if stop_hit and target_hit:
                closed_at = bar.time + timedelta(minutes=15)
                result = "AMBIGUOUS_SAME_BAR"
                exit_reason = "same_bar_stop_and_target"
                outcome_r = -1.0
            elif stop_hit:
                closed_at = bar.time + timedelta(minutes=15)
                result = "STOP"
                exit_reason = "stop_touched"
                outcome_r = -1.0
            elif target_hit:
                closed_at = bar.time + timedelta(minutes=15)
                result = "TARGET"
                exit_reason = "take_profit_touched"
                outcome_r = (entry - target) / risk
            else:
                exit_window = bars[
                    max(0, index - self.engine.config.atr_period - 1) : index + 1
                ]
                exit_decision = self.engine.evaluate_exit(position, exit_window)
                if exit_decision.action is not BearExitAction.INVALIDATED:
                    continue
                closed_at = bar.time + timedelta(minutes=15)
                result = "INVALIDATED"
                exit_reason = exit_decision.reason
                outcome_r = (entry - bar.close) / risk
            break
        if result == "END_OF_TEST":
            outcome_r = (entry - last_close) / risk
        return BearReplayOutcome(
            signal_time=signal.time,
            opened_at=opened_at,
            closed_at=closed_at,
            result=result,
            entry=entry,
            stop=stop,
            target=target,
            planned_reward_risk=(entry - target) / risk,
            outcome_r=outcome_r,
            mfe_r=mfe_r,
            mae_r=mae_r,
            score=signal.score,
            reason=signal.reason,
            exit_reason=exit_reason,
            regime_slope_atr=signal.regime_slope_atr,
            regime_drop_atr=signal.regime_drop_atr,
            chase_distance_atr=signal.chase_distance_atr,
            resistance_kind=signal.resistance_kind,
        )
