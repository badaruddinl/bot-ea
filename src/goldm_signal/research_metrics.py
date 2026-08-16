from __future__ import annotations

import math
import random
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from statistics import NormalDist
from typing import Iterable, Mapping, Sequence


_EVENT_PATTERN = re.compile(
    r"\b(SNIPER_CONFIG|SNIPER_SIGNAL|SNIPER_OUTCOME|SNIPER_PERFORMANCE)\b"
)
_FIELD_PATTERN = re.compile(r"(?<!\S)([A-Za-z][A-Za-z0-9_]*)=([^\s]+)")
_DIRECTIONS = {"ALL", "BULL_ONLY", "BEAR_ONLY"}
_SIDES = {"BUY", "SELL"}


class ResearchMetricsError(ValueError):
    """Raised when an MT5 research log is incomplete or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class BrokerCostEvidence:
    volume_lots: float
    point: float
    tick_size: float
    tick_value: float
    spread_points: float
    commission_per_lot_round_turn: float
    swap_per_lot_round_turn: float
    slippage_points: float


@dataclass(frozen=True, slots=True)
class SelectionBiasDiagnostic:
    name: str
    status: str
    value: float | None
    samples: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchTrade:
    setup_id: str
    side: str
    result: str
    outcome_r: float
    entry: float
    initial_stop: float
    exit_price: float
    target: float
    projected_r: float
    score: int
    m5_votes: int
    pattern: str
    fibonacci_aligned: bool
    m1_confirmed: bool
    hit_r1: bool
    hit_r2: bool
    hit_r3: bool
    mfe_r: float
    mae_r: float
    duration_minutes: int
    setup_utc_epoch: int
    outcome_utc_epoch: int

    @property
    def initial_risk_price(self) -> float:
        return abs(self.entry - self.initial_stop)


@dataclass(frozen=True, slots=True)
class MetricBucket:
    trades: int
    total_r: float
    mean_r: float | None
    median_r: float | None
    profit_factor: float | None
    win_rate: float | None
    payoff_ratio: float | None
    maximum_drawdown_r: float
    maximum_loss_streak: int
    time_under_water_seconds: int


@dataclass(frozen=True, slots=True)
class ResearchMetrics:
    run_id: str
    direction_profile: str
    strategy_mode: int
    strategy: str
    strategy_version: str
    per_trade_cost_r: float
    pooled: MetricBucket
    by_side: Mapping[str, MetricBucket]
    hit_r1_rate: float | None
    hit_r2_rate: float | None
    hit_r3_rate: float | None
    average_mfe_r: float | None
    average_mae_r: float | None
    average_duration_minutes: float | None
    average_score: float | None
    pattern_counts: Mapping[str, int]
    exit_reasons: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class ParsedResearchRun:
    run_id: str
    direction_profile: str
    strategy_mode: int
    strategy: str
    strategy_version: str
    trades: tuple[ResearchTrade, ...]
    performance_fields: Mapping[str, str]

    def metrics(self, *, per_trade_cost_r: float = 0.0) -> ResearchMetrics:
        return summarize_research_trades(
            self.trades,
            run_id=self.run_id,
            direction_profile=self.direction_profile,
            strategy_mode=self.strategy_mode,
            strategy=self.strategy,
            strategy_version=self.strategy_version,
            per_trade_cost_r=per_trade_cost_r,
        )


def parse_research_log(
    text: str,
    *,
    expected_run_id: str,
    expected_direction_profile: str | None = None,
    expected_strategy_mode: int | None = None,
) -> ParsedResearchRun:
    """Parse and cross-check one append-only, run-correlated MT5 log slice.

    The caller must pass only the bytes appended by one tester invocation.  Any
    lineage event carrying another run ID is rejected instead of silently
    filtered, preventing stale or interleaved terminal output from being scored.
    """

    if (
        not expected_run_id
        or "=" in expected_run_id
        or any(character.isspace() for character in expected_run_id)
    ):
        raise ResearchMetricsError("expected_run_id must be a non-empty structured token")
    if expected_direction_profile is not None:
        expected_direction_profile = expected_direction_profile.upper()
        if expected_direction_profile not in _DIRECTIONS:
            raise ResearchMetricsError("unsupported expected direction profile")

    events: list[tuple[str, dict[str, str]]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        marker = _EVENT_PATTERN.search(line)
        if marker is None:
            continue
        field_pairs = _FIELD_PATTERN.findall(line[marker.start() :])
        field_names = [name for name, _ in field_pairs]
        duplicate_fields = sorted(
            name for name, count in Counter(field_names).items() if count > 1
        )
        if duplicate_fields:
            raise ResearchMetricsError(
                f"line {line_number} {marker.group(1)} has duplicate fields: "
                f"{duplicate_fields!r}"
            )
        fields = dict(field_pairs)
        observed_run_id = fields.get("runId")
        if observed_run_id != expected_run_id:
            raise ResearchMetricsError(
                f"line {line_number} {marker.group(1)} runId mismatch: "
                f"expected {expected_run_id!r}, observed {observed_run_id!r}"
            )
        events.append((marker.group(1), fields))

    if not events:
        raise ResearchMetricsError("no correlated SNIPER events found")
    if events[0][0] != "SNIPER_CONFIG":
        raise ResearchMetricsError("SNIPER_CONFIG must be the first correlated event")
    if events[-1][0] != "SNIPER_PERFORMANCE":
        raise ResearchMetricsError("SNIPER_PERFORMANCE must be the last correlated event")

    lineage = [_lineage_tuple(name, fields) for name, fields in events]
    first_lineage = lineage[0]
    if any(item != first_lineage for item in lineage[1:]):
        raise ResearchMetricsError("strategy/direction lineage changes inside one run")
    strategy, strategy_version, direction_profile, strategy_mode = first_lineage
    if expected_direction_profile is not None and direction_profile != expected_direction_profile:
        raise ResearchMetricsError("direction profile does not match the declared run")
    if expected_strategy_mode is not None and strategy_mode != int(expected_strategy_mode):
        raise ResearchMetricsError("strategy mode does not match the declared run")

    config_events = [fields for name, fields in events if name == "SNIPER_CONFIG"]
    performance_events = [fields for name, fields in events if name == "SNIPER_PERFORMANCE"]
    if len(config_events) != 1:
        raise ResearchMetricsError(
            f"expected exactly one SNIPER_CONFIG event, observed {len(config_events)}"
        )
    if len(performance_events) != 1:
        raise ResearchMetricsError(
            "expected exactly one SNIPER_PERFORMANCE event, "
            f"observed {len(performance_events)}"
        )
    if config_events[0].get("signalOnly", "").lower() != "true":
        raise ResearchMetricsError("SNIPER_CONFIG must declare signalOnly=true")

    signals: dict[str, dict[str, str]] = {}
    outcomes: dict[str, dict[str, str]] = {}
    signal_positions: dict[str, int] = {}
    outcome_positions: dict[str, int] = {}
    for event_position, (event_name, fields) in enumerate(events):
        if event_name not in {"SNIPER_SIGNAL", "SNIPER_OUTCOME"}:
            continue
        setup_id = _required(fields, "id", event_name)
        target = signals if event_name == "SNIPER_SIGNAL" else outcomes
        if setup_id in target:
            raise ResearchMetricsError(f"duplicate {event_name} for setup {setup_id!r}")
        target[setup_id] = fields
        positions = signal_positions if event_name == "SNIPER_SIGNAL" else outcome_positions
        positions[setup_id] = event_position

    missing_outcomes = sorted(set(signals) - set(outcomes))
    orphan_outcomes = sorted(set(outcomes) - set(signals))
    if missing_outcomes:
        raise ResearchMetricsError(f"signals without outcomes: {missing_outcomes!r}")
    if orphan_outcomes:
        raise ResearchMetricsError(f"outcomes without signals: {orphan_outcomes!r}")
    for setup_id in signals:
        if outcome_positions[setup_id] < signal_positions[setup_id]:
            raise ResearchMetricsError(
                f"SNIPER_OUTCOME precedes its SNIPER_SIGNAL for setup {setup_id!r}"
            )

    trades = tuple(
        sorted(
            (_join_trade(setup_id, signals[setup_id], outcomes[setup_id]) for setup_id in signals),
            key=lambda trade: (trade.outcome_utc_epoch, trade.setup_utc_epoch, trade.setup_id),
        )
    )
    _assert_direction_membership(direction_profile, trades)
    _assert_performance_summary(performance_events[0], trades)
    return ParsedResearchRun(
        run_id=expected_run_id,
        direction_profile=direction_profile,
        strategy_mode=strategy_mode,
        strategy=strategy,
        strategy_version=strategy_version,
        trades=trades,
        performance_fields=dict(performance_events[0]),
    )


def summarize_research_trades(
    trades: Sequence[ResearchTrade],
    *,
    run_id: str,
    direction_profile: str,
    strategy_mode: int,
    strategy: str,
    strategy_version: str,
    per_trade_cost_r: float = 0.0,
) -> ResearchMetrics:
    if not math.isfinite(per_trade_cost_r) or per_trade_cost_r < 0.0:
        raise ResearchMetricsError("per_trade_cost_r must be finite and non-negative")
    ordered = tuple(
        sorted(trades, key=lambda trade: (trade.outcome_utc_epoch, trade.setup_utc_epoch, trade.setup_id))
    )
    adjusted = tuple(trade.outcome_r - per_trade_cost_r for trade in ordered)
    by_side = {
        side: _metric_bucket(
            [trade.outcome_r - per_trade_cost_r for trade in ordered if trade.side == side],
            [trade.outcome_utc_epoch for trade in ordered if trade.side == side],
        )
        for side in ("BUY", "SELL")
    }
    count = len(ordered)
    return ResearchMetrics(
        run_id=run_id,
        direction_profile=direction_profile,
        strategy_mode=int(strategy_mode),
        strategy=strategy,
        strategy_version=strategy_version,
        per_trade_cost_r=per_trade_cost_r,
        pooled=_metric_bucket(adjusted, [trade.outcome_utc_epoch for trade in ordered]),
        by_side=by_side,
        hit_r1_rate=_rate(sum(trade.hit_r1 for trade in ordered), count),
        hit_r2_rate=_rate(sum(trade.hit_r2 for trade in ordered), count),
        hit_r3_rate=_rate(sum(trade.hit_r3 for trade in ordered), count),
        average_mfe_r=_mean_or_none(trade.mfe_r for trade in ordered),
        average_mae_r=_mean_or_none(trade.mae_r for trade in ordered),
        average_duration_minutes=_mean_or_none(trade.duration_minutes for trade in ordered),
        average_score=_mean_or_none(trade.score for trade in ordered),
        pattern_counts=dict(sorted(Counter(trade.pattern for trade in ordered).items())),
        exit_reasons=dict(sorted(Counter(trade.result for trade in ordered).items())),
    )


def moving_block_bootstrap_mean_ci(
    outcomes_r: Sequence[float],
    *,
    block_size: int,
    samples: int = 10_000,
    confidence: float = 0.95,
    seed: int = 0,
) -> tuple[float, float]:
    """Deterministic circular moving-block bootstrap CI for serial trade outcomes."""

    values = tuple(float(value) for value in outcomes_r)
    if not values or any(not math.isfinite(value) for value in values):
        raise ResearchMetricsError("bootstrap outcomes must be non-empty and finite")
    if (
        not isinstance(block_size, int)
        or isinstance(block_size, bool)
        or block_size < 1
        or block_size > len(values)
    ):
        raise ResearchMetricsError("block_size must be within [1, number of outcomes]")
    if not isinstance(samples, int) or isinstance(samples, bool) or samples < 100:
        raise ResearchMetricsError("bootstrap samples must be at least 100")
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not math.isfinite(confidence)
        or not 0.5 < confidence < 1.0
    ):
        raise ResearchMetricsError("confidence must be between 0.5 and 1.0")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ResearchMetricsError("bootstrap seed must be an integer")

    generator = random.Random(seed)
    length = len(values)
    means: list[float] = []
    for _ in range(samples):
        sample: list[float] = []
        while len(sample) < length:
            start = generator.randrange(length)
            sample.extend(values[(start + offset) % length] for offset in range(block_size))
        means.append(statistics.fmean(sample[:length]))
    means.sort()
    tail = (1.0 - confidence) / 2.0
    return _quantile(means, tail), _quantile(means, 1.0 - tail)


def broker_cost_r(
    *,
    entry: float,
    initial_stop: float,
    evidence: BrokerCostEvidence,
) -> float:
    """Convert explicit round-turn broker costs to the frozen initial-risk R unit."""

    numeric = {
        "entry": entry,
        "initial_stop": initial_stop,
        "volume_lots": evidence.volume_lots,
        "point": evidence.point,
        "tick_size": evidence.tick_size,
        "tick_value": evidence.tick_value,
        "spread_points": evidence.spread_points,
        "commission_per_lot_round_turn": evidence.commission_per_lot_round_turn,
        "swap_per_lot_round_turn": evidence.swap_per_lot_round_turn,
        "slippage_points": evidence.slippage_points,
    }
    for name, value in numeric.items():
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ResearchMetricsError(f"broker cost evidence {name} must be finite")
    for name in ("volume_lots", "point", "tick_size", "tick_value"):
        if numeric[name] <= 0.0:
            raise ResearchMetricsError(f"broker cost evidence {name} must be positive")
    for name in (
        "spread_points",
        "commission_per_lot_round_turn",
        "swap_per_lot_round_turn",
        "slippage_points",
    ):
        if numeric[name] < 0.0:
            raise ResearchMetricsError(
                f"broker cost evidence {name} must be non-negative"
            )
    risk_distance = abs(float(entry) - float(initial_stop))
    if risk_distance <= 0.0:
        raise ResearchMetricsError("broker cost conversion requires non-zero initial risk")
    risk_cash = (
        risk_distance
        / evidence.tick_size
        * evidence.tick_value
        * evidence.volume_lots
    )
    price_cost_cash = (
        (evidence.spread_points + evidence.slippage_points)
        * evidence.point
        / evidence.tick_size
        * evidence.tick_value
        * evidence.volume_lots
    )
    fixed_cost_cash = (
        evidence.commission_per_lot_round_turn
        + evidence.swap_per_lot_round_turn
    ) * evidence.volume_lots
    result = (price_cost_cash + fixed_cost_cash) / risk_cash
    if not math.isfinite(result) or result < 0.0:
        raise ResearchMetricsError("broker cost conversion produced an invalid R value")
    return result


def probability_of_backtest_overfitting(
    candidate_segment_returns: Mapping[str, Sequence[float]],
) -> SelectionBiasDiagnostic:
    """Deterministic combinatorially symmetric cross-validation PBO estimate."""

    prepared = _aligned_finite_candidates(candidate_segment_returns)
    if isinstance(prepared, str):
        return SelectionBiasDiagnostic("PBO", "BLOCKED", None, 0, prepared)
    names, matrix, observations = prepared
    if len(names) < 2 or observations < 6 or observations % 2:
        return SelectionBiasDiagnostic(
            "PBO",
            "BLOCKED",
            None,
            0,
            "PBO requires at least two candidates and an even six-or-more aligned observations",
        )
    overfit = 0
    samples = 0
    all_indexes = tuple(range(observations))
    for in_sample in combinations(all_indexes, observations // 2):
        in_set = set(in_sample)
        out_sample = tuple(index for index in all_indexes if index not in in_set)
        in_means = [statistics.fmean(row[index] for index in in_sample) for row in matrix]
        winner = max(range(len(names)), key=lambda index: (in_means[index], names[index]))
        out_means = [statistics.fmean(row[index] for index in out_sample) for row in matrix]
        selected = out_means[winner]
        lower = sum(value < selected for value in out_means)
        equal = sum(value == selected for value in out_means)
        percentile = (lower + 0.5 * equal) / len(out_means)
        overfit += percentile <= 0.5
        samples += 1
    return SelectionBiasDiagnostic("PBO", "OK", overfit / samples, samples)


def deflated_sharpe_ratio(
    outcomes: Sequence[float],
    *,
    candidate_trials: int,
) -> SelectionBiasDiagnostic:
    values = tuple(float(value) for value in outcomes)
    if (
        len(values) < 30
        or candidate_trials < 2
        or any(not math.isfinite(value) for value in values)
    ):
        return SelectionBiasDiagnostic(
            "DSR",
            "BLOCKED",
            None,
            len(values),
            "DSR requires at least 30 finite outcomes and two candidate trials",
        )
    mean = statistics.fmean(values)
    standard_deviation = statistics.stdev(values)
    if standard_deviation <= 0.0:
        return SelectionBiasDiagnostic(
            "DSR", "BLOCKED", None, len(values), "DSR variance is zero"
        )
    sharpe = mean / standard_deviation
    centered = tuple(value - mean for value in values)
    second = statistics.fmean(value**2 for value in centered)
    skew = statistics.fmean(value**3 for value in centered) / second**1.5
    kurtosis = statistics.fmean(value**4 for value in centered) / second**2
    normal = NormalDist()
    euler_gamma = 0.5772156649015329
    sharpe_null_standard_error = 1.0 / math.sqrt(len(values) - 1)
    expected_maximum = sharpe_null_standard_error * (
        (1.0 - euler_gamma) * normal.inv_cdf(1.0 - 1.0 / candidate_trials)
        + euler_gamma
        * normal.inv_cdf(1.0 - 1.0 / (candidate_trials * math.e))
    )
    denominator_term = 1.0 - skew * sharpe + (
        (kurtosis - 1.0) / 4.0
    ) * sharpe**2
    if denominator_term <= 0.0:
        return SelectionBiasDiagnostic(
            "DSR",
            "BLOCKED",
            None,
            len(values),
            "DSR sampling denominator is non-positive",
        )
    statistic = (sharpe - expected_maximum) * math.sqrt(len(values) - 1) / math.sqrt(
        denominator_term
    )
    return SelectionBiasDiagnostic("DSR", "OK", normal.cdf(statistic), len(values))


def superior_predictive_ability(
    candidate_differentials: Mapping[str, Sequence[float]],
    *,
    block_size: int,
    samples: int = 2_000,
    seed: int = 0,
) -> SelectionBiasDiagnostic:
    """Deterministic moving-block bootstrap SPA-style max-mean p-value."""

    prepared = _aligned_finite_candidates(candidate_differentials)
    if isinstance(prepared, str):
        return SelectionBiasDiagnostic("SPA", "BLOCKED", None, 0, prepared)
    names, matrix, observations = prepared
    if len(names) < 1 or observations < 30:
        return SelectionBiasDiagnostic(
            "SPA",
            "BLOCKED",
            None,
            observations,
            "SPA requires at least 30 aligned finite differentials",
        )
    if (
        not isinstance(block_size, int)
        or isinstance(block_size, bool)
        or block_size < 1
        or block_size > observations
        or not isinstance(samples, int)
        or isinstance(samples, bool)
        or samples < 500
    ):
        return SelectionBiasDiagnostic(
            "SPA", "BLOCKED", None, observations, "SPA bootstrap settings are invalid"
        )
    means = [statistics.fmean(row) for row in matrix]
    standard_errors = [statistics.stdev(row) / math.sqrt(observations) for row in matrix]
    if any(value <= 0.0 for value in standard_errors):
        return SelectionBiasDiagnostic(
            "SPA", "BLOCKED", None, observations, "SPA candidate variance is zero"
        )
    observed = max(mean / error for mean, error in zip(means, standard_errors, strict=True))
    centered = [
        tuple(value - max(mean, 0.0) for value in row)
        for row, mean in zip(matrix, means, strict=True)
    ]
    generator = random.Random(seed)
    exceedances = 0
    for _ in range(samples):
        indexes: list[int] = []
        while len(indexes) < observations:
            start = generator.randrange(observations)
            indexes.extend(
                (start + offset) % observations for offset in range(block_size)
            )
        indexes = indexes[:observations]
        statistic = max(
            statistics.fmean(row[index] for index in indexes) / error
            for row, error in zip(centered, standard_errors, strict=True)
        )
        exceedances += statistic >= observed
    p_value = (exceedances + 1.0) / (samples + 1.0)
    return SelectionBiasDiagnostic("SPA", "OK", p_value, samples)


def _aligned_finite_candidates(
    candidates: Mapping[str, Sequence[float]],
) -> tuple[tuple[str, ...], tuple[tuple[float, ...], ...], int] | str:
    if not isinstance(candidates, Mapping) or not candidates:
        return "diagnostic candidate matrix is empty"
    names = tuple(sorted(candidates))
    rows: list[tuple[float, ...]] = []
    expected_length: int | None = None
    for name in names:
        if not isinstance(name, str) or not name:
            return "diagnostic candidate names must be non-empty strings"
        try:
            row = tuple(float(value) for value in candidates[name])
        except (TypeError, ValueError):
            return "diagnostic candidate observations must be numeric"
        if not row or any(not math.isfinite(value) for value in row):
            return "diagnostic candidate observations must be non-empty and finite"
        if expected_length is None:
            expected_length = len(row)
        elif len(row) != expected_length:
            return "diagnostic candidate observations must be aligned and equal length"
        rows.append(row)
    return names, tuple(rows), expected_length or 0


def _join_trade(
    setup_id: str, signal: Mapping[str, str], outcome: Mapping[str, str]
) -> ResearchTrade:
    if signal.get("status") != "ENTRY_READY":
        raise ResearchMetricsError(f"signal status is not ENTRY_READY for setup {setup_id!r}")
    if outcome.get("status") != "CLOSED":
        raise ResearchMetricsError(f"outcome status is not CLOSED for setup {setup_id!r}")
    if outcome.get("source") != "MODEL_SIMULATION":
        raise ResearchMetricsError(
            f"outcome source is not MODEL_SIMULATION for setup {setup_id!r}"
        )
    signal_side = _side(_required(signal, "side", "SNIPER_SIGNAL"))
    outcome_side = _side(_required(outcome, "side", "SNIPER_OUTCOME"))
    if signal_side != outcome_side:
        raise ResearchMetricsError(f"side mismatch for setup {setup_id!r}")
    signal_entry = _float(signal, "entry", "SNIPER_SIGNAL")
    outcome_entry = _float(outcome, "entry", "SNIPER_OUTCOME")
    if not math.isclose(signal_entry, outcome_entry, rel_tol=0.0, abs_tol=1e-7):
        raise ResearchMetricsError(f"entry mismatch for setup {setup_id!r}")
    initial_stop = _float(signal, "stop", "SNIPER_SIGNAL")
    if math.isclose(signal_entry, initial_stop, rel_tol=0.0, abs_tol=1e-12):
        raise ResearchMetricsError(f"zero initial risk for setup {setup_id!r}")
    if signal_side == "BUY" and initial_stop >= signal_entry:
        raise ResearchMetricsError(f"BUY initial stop is not below entry for setup {setup_id!r}")
    if signal_side == "SELL" and initial_stop <= signal_entry:
        raise ResearchMetricsError(f"SELL initial stop is not above entry for setup {setup_id!r}")
    setup_epoch = _int(signal, "setupUtcEpoch", "SNIPER_SIGNAL")
    if setup_epoch != _int(outcome, "setupUtcEpoch", "SNIPER_OUTCOME"):
        raise ResearchMetricsError(f"setup time mismatch for setup {setup_id!r}")
    outcome_epoch = _int(outcome, "generatedUtcEpoch", "SNIPER_OUTCOME")
    if outcome_epoch < setup_epoch:
        raise ResearchMetricsError(f"outcome predates setup {setup_id!r}")
    hit_r1 = _bool(outcome, "hit1R", "SNIPER_OUTCOME")
    hit_r2 = _bool(outcome, "hit2R", "SNIPER_OUTCOME")
    hit_r3 = _bool(outcome, "hit3R", "SNIPER_OUTCOME")
    if (hit_r2 and not hit_r1) or (hit_r3 and not hit_r2):
        raise ResearchMetricsError(f"non-monotonic R milestones for setup {setup_id!r}")
    mfe_r = _float(outcome, "mfeR", "SNIPER_OUTCOME")
    mae_r = _float(outcome, "maeR", "SNIPER_OUTCOME")
    if mfe_r < -1e-7 or mae_r > 1e-7:
        raise ResearchMetricsError(f"invalid MFE/MAE signs for setup {setup_id!r}")
    duration_minutes = _int(outcome, "durationMinutes", "SNIPER_OUTCOME")
    if duration_minutes < 0:
        raise ResearchMetricsError(f"negative duration for setup {setup_id!r}")
    return ResearchTrade(
        setup_id=setup_id,
        side=signal_side,
        result=_required(outcome, "result", "SNIPER_OUTCOME"),
        outcome_r=_float(outcome, "outcomeR", "SNIPER_OUTCOME"),
        entry=signal_entry,
        initial_stop=initial_stop,
        exit_price=_float(outcome, "exitPrice", "SNIPER_OUTCOME"),
        target=_float(signal, "target", "SNIPER_SIGNAL"),
        projected_r=_float(signal, "projectedR", "SNIPER_SIGNAL"),
        score=_bounded_int(signal, "score", "SNIPER_SIGNAL", minimum=0, maximum=100),
        m5_votes=_bounded_int(
            signal, "m5Votes", "SNIPER_SIGNAL", minimum=0, maximum=10
        ),
        pattern=_required(signal, "pattern", "SNIPER_SIGNAL"),
        fibonacci_aligned=_bool(signal, "fibonacciAligned", "SNIPER_SIGNAL"),
        m1_confirmed=_bool(signal, "m1Confirmed", "SNIPER_SIGNAL"),
        hit_r1=hit_r1,
        hit_r2=hit_r2,
        hit_r3=hit_r3,
        mfe_r=mfe_r,
        mae_r=mae_r,
        duration_minutes=duration_minutes,
        setup_utc_epoch=setup_epoch,
        outcome_utc_epoch=outcome_epoch,
    )


def _assert_performance_summary(
    performance: Mapping[str, str], trades: Sequence[ResearchTrade]
) -> None:
    count = len(trades)
    if _int(performance, "resolved", "SNIPER_PERFORMANCE") != count:
        raise ResearchMetricsError("SNIPER_PERFORMANCE resolved count does not match outcomes")
    expected_counts = {
        "hit1R": sum(trade.hit_r1 for trade in trades),
        "hit2R": sum(trade.hit_r2 for trade in trades),
        "hit3R": sum(trade.hit_r3 for trade in trades),
    }
    for field, expected in expected_counts.items():
        if _int(performance, field, "SNIPER_PERFORMANCE") != expected:
            raise ResearchMetricsError(f"SNIPER_PERFORMANCE {field} does not match outcomes")

    result_counts = Counter(trade.result for trade in trades)
    aggregate_counts = {
        "stopped": result_counts["STOP"],
        "protectedStops": result_counts["PROTECTED_STOP"],
        "timedOut": result_counts["TIMEOUT"] + result_counts["END_OF_TEST"],
        "m1ManagedExits": (
            result_counts["M1_DEFENSIVE"] + result_counts["M1_MANAGEMENT"]
        ),
    }
    for field, expected in aggregate_counts.items():
        if _int(performance, field, "SNIPER_PERFORMANCE") != expected:
            raise ResearchMetricsError(f"SNIPER_PERFORMANCE {field} does not match outcomes")

    observed_total = _float(performance, "totalR", "SNIPER_PERFORMANCE")
    calculated_total = math.fsum(trade.outcome_r for trade in trades)
    total_tolerance = 0.00006 * max(1, count)
    if not math.isclose(observed_total, calculated_total, rel_tol=0.0, abs_tol=total_tolerance):
        raise ResearchMetricsError("SNIPER_PERFORMANCE totalR does not match outcomes")
    observed_mean = _float(performance, "expectancyR", "SNIPER_PERFORMANCE")
    calculated_mean = calculated_total / count if count else 0.0
    if not math.isclose(observed_mean, calculated_mean, rel_tol=0.0, abs_tol=0.00006):
        raise ResearchMetricsError("SNIPER_PERFORMANCE expectancyR does not match outcomes")

    average_fields = {
        "averageMFE_R": (
            _mean_or_zero(trade.mfe_r for trade in trades),
            0.00006,
        ),
        "averageMAE_R": (
            _mean_or_zero(trade.mae_r for trade in trades),
            0.00006,
        ),
        # SNIPER_SIGNAL emits projectedR with three decimals, while the EA
        # summary retains five-decimal precision from its internal double.
        "averageProjectedR": (
            _mean_or_zero(trade.projected_r for trade in trades),
            0.00051,
        ),
        # Individual setup scores are integers; the summary prints two decimals.
        "averageScore": (
            _mean_or_zero(trade.score for trade in trades),
            0.0051,
        ),
    }
    for field, (expected, tolerance) in average_fields.items():
        observed = _float(performance, field, "SNIPER_PERFORMANCE")
        if not math.isclose(observed, expected, rel_tol=0.0, abs_tol=tolerance):
            raise ResearchMetricsError(f"SNIPER_PERFORMANCE {field} does not match outcomes")

    for field, hits in (
        ("P1", expected_counts["hit1R"]),
        ("P2", expected_counts["hit2R"]),
        ("P3", expected_counts["hit3R"]),
    ):
        expected_percent = hits * 100.0 / count if count else 0.0
        observed_percent = _float(performance, field, "SNIPER_PERFORMANCE")
        if not math.isclose(
            observed_percent, expected_percent, rel_tol=0.0, abs_tol=0.0051
        ):
            raise ResearchMetricsError(f"SNIPER_PERFORMANCE {field} does not match outcomes")


def _assert_direction_membership(
    direction_profile: str, trades: Sequence[ResearchTrade]
) -> None:
    if direction_profile == "BULL_ONLY" and any(trade.side != "BUY" for trade in trades):
        raise ResearchMetricsError("BULL_ONLY run contains a non-BUY trade")
    if direction_profile == "BEAR_ONLY" and any(trade.side != "SELL" for trade in trades):
        raise ResearchMetricsError("BEAR_ONLY run contains a non-SELL trade")


def _metric_bucket(values: Sequence[float], epochs: Sequence[int]) -> MetricBucket:
    count = len(values)
    positives = [value for value in values if value > 0.0]
    negatives = [value for value in values if value < 0.0]
    gross_profit = math.fsum(positives)
    gross_loss = abs(math.fsum(negatives))
    profit_factor = gross_profit / gross_loss if gross_loss > 0.0 else None
    payoff_ratio = (
        statistics.fmean(positives) / abs(statistics.fmean(negatives))
        if positives and negatives
        else None
    )
    maximum_drawdown, underwater = _drawdown(values, epochs)
    return MetricBucket(
        trades=count,
        total_r=math.fsum(values),
        mean_r=statistics.fmean(values) if count else None,
        median_r=statistics.median(values) if count else None,
        profit_factor=profit_factor,
        win_rate=_rate(len(positives), count),
        payoff_ratio=payoff_ratio,
        maximum_drawdown_r=maximum_drawdown,
        maximum_loss_streak=_maximum_loss_streak(values),
        time_under_water_seconds=underwater,
    )


def _drawdown(values: Sequence[float], epochs: Sequence[int]) -> tuple[float, int]:
    if len(values) != len(epochs):
        raise ResearchMetricsError("drawdown values and timestamps must align")
    if not values:
        return 0.0, 0
    equity = 0.0
    peak = 0.0
    peak_epoch = int(epochs[0])
    maximum_drawdown = 0.0
    maximum_underwater = 0
    for value, epoch_value in zip(values, epochs, strict=True):
        epoch = int(epoch_value)
        equity += float(value)
        if equity >= peak:
            maximum_underwater = max(maximum_underwater, max(0, epoch - peak_epoch))
            peak = equity
            peak_epoch = epoch
        else:
            maximum_drawdown = max(maximum_drawdown, peak - equity)
            maximum_underwater = max(maximum_underwater, max(0, epoch - peak_epoch))
    return maximum_drawdown, maximum_underwater


def _maximum_loss_streak(values: Sequence[float]) -> int:
    current = maximum = 0
    for value in values:
        current = current + 1 if value < 0.0 else 0
        maximum = max(maximum, current)
    return maximum


def _lineage_tuple(
    event_name: str, fields: Mapping[str, str]
) -> tuple[str, str, str, int]:
    strategy = _required(fields, "strategy", event_name)
    strategy_version = _required(fields, "strategyVersion", event_name)
    direction = _required(fields, "directionProfile", event_name).upper()
    if direction not in _DIRECTIONS:
        raise ResearchMetricsError(f"invalid directionProfile in {event_name}: {direction!r}")
    return strategy, strategy_version, direction, _int(fields, "strategyMode", event_name)


def _required(fields: Mapping[str, str], name: str, event_name: str) -> str:
    value = fields.get(name)
    if value is None or value == "":
        raise ResearchMetricsError(f"{event_name} is missing {name}")
    return value


def _float(fields: Mapping[str, str], name: str, event_name: str) -> float:
    value = _required(fields, name, event_name)
    try:
        result = float(value)
    except ValueError as exc:
        raise ResearchMetricsError(f"{event_name} has invalid {name}: {value!r}") from exc
    if not math.isfinite(result):
        raise ResearchMetricsError(f"{event_name} has non-finite {name}")
    return result


def _int(fields: Mapping[str, str], name: str, event_name: str) -> int:
    value = _required(fields, name, event_name)
    try:
        return int(value)
    except ValueError as exc:
        raise ResearchMetricsError(f"{event_name} has invalid {name}: {value!r}") from exc


def _bounded_int(
    fields: Mapping[str, str],
    name: str,
    event_name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = _int(fields, name, event_name)
    if value < minimum or value > maximum:
        raise ResearchMetricsError(
            f"{event_name} has out-of-range {name}: {value!r}"
        )
    return value


def _bool(fields: Mapping[str, str], name: str, event_name: str) -> bool:
    value = _required(fields, name, event_name).lower()
    if value not in {"true", "false"}:
        raise ResearchMetricsError(f"{event_name} has invalid {name}: {value!r}")
    return value == "true"


def _side(value: str) -> str:
    side = value.upper()
    if side not in _SIDES:
        raise ResearchMetricsError(f"unsupported trade side: {value!r}")
    return side


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _mean_or_none(values: Iterable[float]) -> float | None:
    materialized = tuple(float(value) for value in values)
    return statistics.fmean(materialized) if materialized else None


def _mean_or_zero(values: Iterable[float]) -> float:
    value = _mean_or_none(values)
    return 0.0 if value is None else value


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    position = probability * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight
