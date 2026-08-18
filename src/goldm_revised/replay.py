from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence

from .engine import STRATEGY_ID, STRATEGY_VERSION, RevisedBar, RevisedDecision, RevisedEngine, RevisedSide, RevisedSnapshot, RevisedState
from .setup import RevisedSetupDetector


@dataclass(slots=True)
class ReplayPosition:
    side: RevisedSide
    trigger_time: datetime
    opened_at: datetime
    entry: float
    stop: float
    target: float
    first_obstacle_r: float
    mfe: float = 0.0
    mae: float = 0.0


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    side: RevisedSide
    trigger_time: datetime
    opened_at: datetime
    closed_at: datetime
    result: str
    outcome_r: float
    entry: float
    stop: float
    target: float
    first_obstacle_r: float
    mfe: float
    mae: float


@dataclass(frozen=True, slots=True)
class ReplayInspection:
    requested_time: datetime
    side: RevisedSide
    setup_trigger_time: datetime
    decision_time: datetime
    m5_pattern: str
    state: RevisedState
    reason: str
    entry_profile: str
    validation_status: str
    retest_count: int
    entry: float | None
    stop: float | None
    target: float | None
    first_obstacle: float | None
    first_obstacle_kind: str | None
    first_obstacle_r: float | None
    touch_count: int
    rejection_count: int
    m1_votes: int
    exhausted: bool
    risk_source: str | None


@dataclass(frozen=True, slots=True)
class ReplayReport:
    strategy_id: str
    strategy_version: str
    from_time: datetime
    to_time: datetime
    signals: int
    buy_signals: int
    core_buy_signals: int
    sell_signals: int
    scalper_signals: int
    resolved: int
    total_r: float
    expectancy_r: float
    maximum_drawdown_r: float
    target_count: int
    stop_count: int
    ambiguous_count: int
    end_of_test_count: int
    first_obstacle_violations: int
    fallback_promotions: int
    duplicate_trigger_promotions: int
    outcomes: tuple[ReplayOutcome, ...]
    inspections: tuple[ReplayInspection, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class RevisedReplay:
    def __init__(self, engine: RevisedEngine | None = None) -> None:
        self.engine = engine or RevisedEngine()

    def run(
        self,
        *,
        m1_bars: Sequence[RevisedBar],
        m5_bars: Sequence[RevisedBar],
        h1_bars: Sequence[RevisedBar],
        d1_bars: Sequence[RevisedBar],
        from_time: datetime,
        to_time: datetime,
        inspect_times: Sequence[datetime] = (),
        inspect_tolerance_minutes: int = 5,
    ) -> ReplayReport:
        for bars in (m1_bars, m5_bars, h1_bars, d1_bars):
            _validate_order(bars)
        detector = RevisedSetupDetector(maximum_m1_bars=self.engine.config.watch_max_m1_bars)
        active: dict[RevisedSide, ReplayPosition] = {}
        consumed_triggers: set[tuple[RevisedSide, datetime]] = set()
        duplicate_promotions = 0
        violation_count = 0
        signal_decisions: list[RevisedDecision] = []
        outcomes: list[ReplayOutcome] = []
        inspections: list[ReplayInspection] = []

        for index, current in enumerate(m1_bars):
            close_time = current.time + timedelta(minutes=1)
            if close_time < from_time:
                continue
            if close_time >= to_time:
                break
            self._update_positions(active, outcomes, current)
            m1_history = tuple(m1_bars[: index + 1])
            m5_history = tuple(bar for bar in m5_bars if bar.time + timedelta(minutes=5) <= close_time)
            h1_history = tuple(bar for bar in h1_bars if bar.time + timedelta(hours=1) <= close_time)
            d1_history = tuple(bar for bar in d1_bars if bar.time + timedelta(days=1) <= close_time)
            if len(m1_history) < self.engine.config.atr_period + 1 or len(m5_history) < self.engine.config.atr_period + 1:
                continue
            for side in (RevisedSide.BUY, RevisedSide.SELL):
                setup = detector.update(m5_history, current_m1_time=current.time, side=side)
                if setup is None:
                    continue
                snapshot = RevisedSnapshot(
                    symbol=self.engine.config.symbol,
                    side=side,
                    current_time=current.time,
                    m1_bars=m1_history[-160:],
                    m5_bars=m5_history[-120:],
                    h1_bars=h1_history[-120:],
                    d1_bars=d1_history[-120:],
                    m5_trigger_time=setup.trigger_time,
                    m5_pattern=setup.pattern,
                    m5_votes=setup.votes,
                    confidence=setup.confidence,
                    level=setup.level,
                    invalidation=setup.invalidation,
                    entry=current.close,
                    stop=setup.invalidation,
                )
                decision = self.engine.evaluate(snapshot)
                for requested_time in inspect_times:
                    if abs(setup.trigger_time - requested_time) <= timedelta(
                        minutes=inspect_tolerance_minutes
                    ):
                        risk_evidence = decision.evidence.get("risk", {})
                        inspections.append(
                            ReplayInspection(
                                requested_time=requested_time,
                                side=side,
                                setup_trigger_time=setup.trigger_time,
                                decision_time=decision.time,
                                m5_pattern=setup.pattern,
                                state=decision.state,
                                reason=decision.reason,
                                entry_profile=decision.entry_profile,
                                validation_status=decision.validation_status,
                                retest_count=decision.retest_count,
                                entry=decision.entry,
                                stop=decision.stop,
                                target=decision.target,
                                first_obstacle=decision.first_obstacle,
                                first_obstacle_kind=decision.first_obstacle_kind,
                                first_obstacle_r=decision.first_obstacle_r,
                                touch_count=decision.touch_count,
                                rejection_count=decision.rejection_count,
                                m1_votes=decision.m1_votes,
                                exhausted=decision.exhausted,
                                risk_source=(
                                    str(risk_evidence.get("source"))
                                    if isinstance(risk_evidence, dict)
                                    and risk_evidence.get("source") is not None
                                    else None
                                ),
                            )
                        )
                if decision.state is RevisedState.CANCELLED:
                    detector.consume(side, setup.trigger_time)
                    continue
                if decision.state is not RevisedState.ENTRY_READY:
                    continue
                key = (side, setup.trigger_time)
                if key in consumed_triggers:
                    duplicate_promotions += 1
                    detector.consume(side, setup.trigger_time)
                    continue
                if side in active:
                    continue
                if decision.entry is None or decision.stop is None or decision.target is None or decision.first_obstacle_r is None:
                    continue
                consumed_triggers.add(key)
                detector.consume(side, setup.trigger_time)
                signal_decisions.append(decision)
                if decision.first_obstacle_r < self.engine.config.first_obstacle_reject_r:
                    violation_count += 1
                active[side] = ReplayPosition(
                    side=side,
                    trigger_time=setup.trigger_time,
                    opened_at=close_time,
                    entry=decision.entry,
                    stop=decision.stop,
                    target=decision.target,
                    first_obstacle_r=decision.first_obstacle_r,
                )

        if m1_bars:
            final_bar = max((bar for bar in m1_bars if bar.time < to_time), key=lambda bar: bar.time, default=m1_bars[-1])
            for side, position in list(active.items()):
                risk = abs(position.entry - position.stop)
                if side is RevisedSide.BUY:
                    outcome_r = (final_bar.close - position.entry) / risk
                else:
                    outcome_r = (position.entry - final_bar.close) / risk
                outcomes.append(
                    ReplayOutcome(
                        side=side,
                        trigger_time=position.trigger_time,
                        opened_at=position.opened_at,
                        closed_at=to_time,
                        result="END_OF_TEST",
                        outcome_r=max(-1.0, min(3.0, outcome_r)),
                        entry=position.entry,
                        stop=position.stop,
                        target=position.target,
                        first_obstacle_r=position.first_obstacle_r,
                        mfe=position.mfe,
                        mae=position.mae,
                    )
                )
            active.clear()

        total_r = sum(outcome.outcome_r for outcome in outcomes)
        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for outcome in sorted(outcomes, key=lambda item: item.closed_at):
            equity += outcome.outcome_r
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
        return ReplayReport(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            from_time=from_time,
            to_time=to_time,
            signals=len(signal_decisions),
            buy_signals=sum(decision.side is RevisedSide.BUY for decision in signal_decisions),
            core_buy_signals=sum(
                decision.side is RevisedSide.BUY and not decision.observation_only
                for decision in signal_decisions
            ),
            sell_signals=sum(decision.side is RevisedSide.SELL for decision in signal_decisions),
            scalper_signals=sum(
                decision.entry_profile == "SCALPER" for decision in signal_decisions
            ),
            resolved=len(outcomes),
            total_r=total_r,
            expectancy_r=total_r / len(outcomes) if outcomes else 0.0,
            maximum_drawdown_r=max_drawdown,
            target_count=sum(outcome.result == "TARGET" for outcome in outcomes),
            stop_count=sum(outcome.result == "STOP" for outcome in outcomes),
            ambiguous_count=sum(outcome.result == "AMBIGUOUS_SAME_BAR" for outcome in outcomes),
            end_of_test_count=sum(outcome.result == "END_OF_TEST" for outcome in outcomes),
            first_obstacle_violations=violation_count,
            fallback_promotions=0,
            duplicate_trigger_promotions=duplicate_promotions,
            outcomes=tuple(outcomes),
            inspections=tuple(inspections),
        )

    @staticmethod
    def _update_positions(
        active: dict[RevisedSide, ReplayPosition],
        outcomes: list[ReplayOutcome],
        bar: RevisedBar,
    ) -> None:
        for side, position in list(active.items()):
            if bar.time + timedelta(minutes=1) <= position.opened_at:
                continue
            risk = abs(position.entry - position.stop)
            if side is RevisedSide.BUY:
                mfe = (bar.high - position.entry) / risk
                mae = (bar.low - position.entry) / risk
                stop_hit = bar.low <= position.stop
                target_hit = bar.high >= position.target
            else:
                mfe = (position.entry - bar.low) / risk
                mae = (position.entry - bar.high) / risk
                stop_hit = bar.high >= position.stop
                target_hit = bar.low <= position.target
            position.mfe = max(position.mfe, mfe)
            position.mae = min(position.mae, mae)
            if not stop_hit and not target_hit:
                continue
            if stop_hit and target_hit:
                result = "AMBIGUOUS_SAME_BAR"
                outcome_r = -1.0
            elif target_hit:
                result = "TARGET"
                outcome_r = abs(position.target - position.entry) / risk
            else:
                result = "STOP"
                outcome_r = -1.0
            outcomes.append(
                ReplayOutcome(
                    side=side,
                    trigger_time=position.trigger_time,
                    opened_at=position.opened_at,
                    closed_at=bar.time + timedelta(minutes=1),
                    result=result,
                    outcome_r=outcome_r,
                    entry=position.entry,
                    stop=position.stop,
                    target=position.target,
                    first_obstacle_r=position.first_obstacle_r,
                    mfe=position.mfe,
                    mae=position.mae,
                )
            )
            active.pop(side, None)


class RevisedMt5HistoryLoader:
    def __init__(self, *, mt5_module: ModuleType | None = None) -> None:
        self._mt5 = mt5_module
        self._connected = False

    def connect(self) -> None:
        mt5 = self._module()
        if not self._connected:
            if not mt5.initialize():
                raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
            self._connected = True

    def close(self) -> None:
        if self._connected:
            self._module().shutdown()
            self._connected = False

    def load(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        server_timezone: timezone,
        warmup_days: int = 180,
    ) -> dict[str, list[RevisedBar]]:
        self.connect()
        mt5 = self._module()
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"MT5 symbol selection failed: {mt5.last_error()}")
        info = mt5.symbol_info(symbol)
        point = float(info.point) if info is not None else 0.01
        return {
            "m1": self._rates(symbol, mt5.TIMEFRAME_M1, start - timedelta(days=2), end, server_timezone, point),
            "m5": self._rates(symbol, mt5.TIMEFRAME_M5, start - timedelta(days=10), end, server_timezone, point),
            "h1": self._rates(symbol, mt5.TIMEFRAME_H1, start - timedelta(days=60), end, server_timezone, point),
            "d1": self._rates(symbol, mt5.TIMEFRAME_D1, start - timedelta(days=warmup_days), end, server_timezone, point),
        }

    def _rates(self, symbol: str, timeframe: int, start: datetime, end: datetime, server_timezone: timezone, point: float) -> list[RevisedBar]:
        raw = self._module().copy_rates_range(symbol, timeframe, start.astimezone(timezone.utc), end.astimezone(timezone.utc))
        if raw is None:
            raise RuntimeError(f"MT5 CopyRates range failed: {self._module().last_error()}")
        return [
            RevisedBar(
                time=datetime.fromtimestamp(int(rate["time"]), tz=timezone.utc).astimezone(server_timezone),
                open=float(rate["open"]),
                high=float(rate["high"]),
                low=float(rate["low"]),
                close=float(rate["close"]),
                volume=float(rate["tick_volume"]),
                spread=max(float(rate["spread"]) * point, 0.0),
            )
            for rate in raw
        ]

    def _module(self) -> ModuleType:
        if self._mt5 is None:
            self._mt5 = import_module("MetaTrader5")
        return self._mt5


def _validate_order(bars: Sequence[RevisedBar]) -> None:
    if any(current.time <= previous.time for previous, current in zip(bars, bars[1:])):
        raise ValueError("replay bars must be strictly ordered")
