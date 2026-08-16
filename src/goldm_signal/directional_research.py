from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .research_folds import RegisteredFoldPlan, load_registered_fold_plan
from .research_policy import (
    ResearchPurpose,
    StatisticalClassification,
    assert_research_range,
    parse_research_date,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9_]{2,95}\Z")
_SOURCE_TIME = "%d.%m.%Y %H:%M:%S.%f GMT%z"


class DirectionalResearchError(RuntimeError):
    """Raised when directional research input or evidence is not reproducible."""


@dataclass(frozen=True, slots=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class RegisteredBarDataset:
    dataset_id: str
    source_symbol: str
    target_symbol: str
    warmup_start: datetime
    run_start: datetime
    end: datetime
    round_trip_quote: float
    bars: tuple[Bar, ...]
    manifest_path: Path
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class Candidate:
    candidate_id: str
    side: str
    family: str
    pattern: str
    session_start_utc: int
    session_end_utc: int
    structure_lookback: int
    stop_atr: float
    target_r: float
    max_hold_bars: int
    rsi_minimum: float
    rsi_maximum: float
    squeeze_ratio: float


@dataclass(frozen=True, slots=True)
class CandidatePlan:
    plan_id: str
    candidates: tuple[Candidate, ...]
    tweaks: tuple[tuple[float, float, int], ...]
    minimum_trades: Mapping[str, int]
    maximum_drawdown_r: float
    plan_path: Path
    plan_sha256: str


@dataclass(frozen=True, slots=True)
class Features:
    ema_fast: tuple[float, ...]
    ema_slow: tuple[float, ...]
    atr: tuple[float, ...]
    atr_slow: tuple[float, ...]
    rsi: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class Trade:
    signal_time: str
    entry_time: str
    exit_time: str
    side: str
    entry: float
    stop: float
    target: float
    exit_price: float
    exit_reason: str
    gross_r: float
    net_r: float


@dataclass(frozen=True, slots=True)
class Metrics:
    trades: int
    wins: int
    losses: int
    total_r: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    positive_month_ratio: float


def load_registered_bar_dataset(manifest_path: Path) -> RegisteredBarDataset:
    canonical = _canonical_file(manifest_path, "bar dataset manifest")
    payload = _load_json(canonical)
    required = {
        "schema_version",
        "dataset_id",
        "registered_at",
        "purpose",
        "statistical_classification",
        "source_repository",
        "source_commit",
        "archive_path",
        "archive_sha256",
        "source_symbol",
        "target_symbol",
        "format",
        "time_semantics",
        "bar_model_classification",
        "warmup_from_inclusive",
        "run_from_inclusive",
        "to_exclusive",
        "files",
        "cost_model",
        "manifest_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != required or payload.get(
        "schema_version"
    ) != 1:
        raise DirectionalResearchError(
            "bar dataset manifest must use schema_version 1 with exact fields"
        )
    supplied_hash = payload["manifest_sha256"]
    hash_payload = dict(payload)
    hash_payload.pop("manifest_sha256")
    if not isinstance(supplied_hash, str) or not _SHA256.fullmatch(supplied_hash):
        raise DirectionalResearchError("bar dataset manifest SHA-256 is invalid")
    if _canonical_sha256(hash_payload) != supplied_hash:
        raise DirectionalResearchError("bar dataset manifest SHA-256 does not match")
    if payload["purpose"] != ResearchPurpose.DEVELOPMENT.value or payload[
        "statistical_classification"
    ] != StatisticalClassification.DEVELOPMENT_SELECTION.value:
        raise DirectionalResearchError("directional selection requires Development data")
    if payload["format"] != "EPSOFT_XAUUSD_BID_M5_V1" or payload[
        "time_semantics"
    ] != "SOURCE_ROW_EXPLICIT_GMT_OFFSET_TO_UTC_HALF_OPEN":
        raise DirectionalResearchError("unsupported bar dataset format/time semantics")
    if payload["bar_model_classification"] != "EXPLORATORY_BAR_MODEL_NOT_MT5_TICKS":
        raise DirectionalResearchError("bar-model limitation must be explicit")

    warmup_start = parse_research_date(
        payload["warmup_from_inclusive"], field="warmup_from_inclusive"
    )
    run_start = parse_research_date(
        payload["run_from_inclusive"], field="run_from_inclusive"
    )
    end = parse_research_date(payload["to_exclusive"], field="to_exclusive")
    assert_research_range(
        run_start,
        end,
        purpose=ResearchPurpose.DEVELOPMENT,
        statistical_classification=StatisticalClassification.DEVELOPMENT_SELECTION,
        label=f"directional bar dataset/{payload['dataset_id']}",
    )
    if warmup_start >= run_start:
        raise DirectionalResearchError("bar dataset requires pre-run warmup")

    archive_path = _resolve_bound_path(canonical, payload["archive_path"], "archive")
    _assert_digest(archive_path, payload["archive_sha256"], "archive")
    file_specs = payload["files"]
    if not isinstance(file_specs, list) or not file_specs:
        raise DirectionalResearchError("bar dataset files must be non-empty")

    bars: list[Bar] = []
    previous_time: datetime | None = None
    for index, raw in enumerate(file_specs):
        if not isinstance(raw, dict) or set(raw) != {"path", "sha256"}:
            raise DirectionalResearchError(f"bar source file {index} has invalid fields")
        source_path = _resolve_bound_path(canonical, raw["path"], f"bar source {index}")
        _assert_digest(source_path, raw["sha256"], f"bar source {index}")
        for bar in _read_epsoft_bars(source_path):
            if bar.time < warmup_start or bar.time >= end:
                continue
            if previous_time is not None and bar.time <= previous_time:
                raise DirectionalResearchError("bar timestamps are duplicate or unordered")
            previous_time = bar.time
            bars.append(bar)
    if not bars or bars[0].time > warmup_start + timedelta(days=1):
        raise DirectionalResearchError("bar dataset does not cover declared warmup start")
    if bars[-1].time < end - timedelta(minutes=5):
        raise DirectionalResearchError("bar dataset does not cover declared exclusive end")
    if not any(run_start <= bar.time < end for bar in bars):
        raise DirectionalResearchError("bar dataset has no rows in evaluation range")

    cost_model = payload["cost_model"]
    if not isinstance(cost_model, dict) or set(cost_model) != {
        "round_trip_quote",
        "same_bar_collision",
    }:
        raise DirectionalResearchError("cost model fields are invalid")
    round_trip_quote = _finite_positive(
        cost_model["round_trip_quote"], "round_trip_quote"
    )
    if cost_model["same_bar_collision"] != "STOP_FIRST_CONSERVATIVE":
        raise DirectionalResearchError("same-bar collision policy must be conservative")
    dataset_id = payload["dataset_id"]
    if not isinstance(dataset_id, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9._-]{2,95}", dataset_id
    ):
        raise DirectionalResearchError("dataset_id is invalid")
    return RegisteredBarDataset(
        dataset_id=dataset_id,
        source_symbol=str(payload["source_symbol"]),
        target_symbol=str(payload["target_symbol"]),
        warmup_start=warmup_start,
        run_start=run_start,
        end=end,
        round_trip_quote=round_trip_quote,
        bars=tuple(bars),
        manifest_path=canonical,
        manifest_sha256=_sha256_file(canonical),
    )


def load_candidate_plan(path: Path) -> CandidatePlan:
    canonical = _canonical_file(path, "candidate plan")
    payload = _load_json(canonical)
    required = {
        "schema_version",
        "plan_id",
        "registered_at",
        "target_symbol",
        "candidate_budget_per_side",
        "selection_protocol",
        "minimum_trades",
        "maximum_drawdown_r",
        "candidates",
        "tweak_offsets",
        "plan_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != required or payload.get(
        "schema_version"
    ) != 1:
        raise DirectionalResearchError("candidate plan must use schema_version 1")
    supplied = payload["plan_sha256"]
    digest_payload = dict(payload)
    digest_payload.pop("plan_sha256")
    if not isinstance(supplied, str) or not _SHA256.fullmatch(supplied):
        raise DirectionalResearchError("candidate plan SHA-256 is invalid")
    if _canonical_sha256(digest_payload) != supplied:
        raise DirectionalResearchError("candidate plan SHA-256 does not match")
    if payload["target_symbol"] != "GOLD.i#":
        raise DirectionalResearchError("candidate plan target must be GOLD.i#")
    if payload["selection_protocol"] != (
        "TRAIN_RANK_BASE__VALIDATION_1_SELECT_TWEAK__VALIDATION_2_CONFIRM_ONLY"
    ):
        raise DirectionalResearchError("candidate selection protocol is not frozen")
    budget = payload["candidate_budget_per_side"]
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 2:
        raise DirectionalResearchError("candidate budget is invalid")
    candidates = tuple(_candidate_from_json(raw) for raw in payload["candidates"])
    ids = [candidate.candidate_id for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise DirectionalResearchError("candidate IDs must be unique")
    for side in ("BULL", "BEAR"):
        side_candidates = [candidate for candidate in candidates if candidate.side == side]
        if len(side_candidates) != budget:
            raise DirectionalResearchError(f"{side} candidate budget mismatch")
        if len({candidate.family for candidate in side_candidates}) < 3:
            raise DirectionalResearchError(f"{side} needs at least three independent families")
    tweaks_raw = payload["tweak_offsets"]
    if not isinstance(tweaks_raw, list) or not tweaks_raw or len(tweaks_raw) > 9:
        raise DirectionalResearchError("tweak budget must contain 1..9 frozen offsets")
    tweaks: list[tuple[float, float, int]] = []
    for raw in tweaks_raw:
        if not isinstance(raw, dict) or set(raw) != {
            "stop_atr_delta",
            "target_r_delta",
            "max_hold_delta",
        }:
            raise DirectionalResearchError("tweak offset fields are invalid")
        tweaks.append(
            (
                float(raw["stop_atr_delta"]),
                float(raw["target_r_delta"]),
                int(raw["max_hold_delta"]),
            )
        )
    minimum_trades = payload["minimum_trades"]
    if not isinstance(minimum_trades, dict) or set(minimum_trades) != {
        "train",
        "validation_1",
        "validation_2",
    } or any(
        not isinstance(value, int) or isinstance(value, bool) or value < 1
        for value in minimum_trades.values()
    ):
        raise DirectionalResearchError("minimum trade gates are invalid")
    return CandidatePlan(
        plan_id=str(payload["plan_id"]),
        candidates=candidates,
        tweaks=tuple(tweaks),
        minimum_trades=dict(minimum_trades),
        maximum_drawdown_r=_finite_positive(
            payload["maximum_drawdown_r"], "maximum_drawdown_r"
        ),
        plan_path=canonical,
        plan_sha256=_sha256_file(canonical),
    )


def run_directional_research(
    dataset: RegisteredBarDataset,
    folds: RegisteredFoldPlan,
    plan: CandidatePlan,
) -> dict[str, Any]:
    if folds.start != dataset.run_start or folds.end != dataset.end:
        raise DirectionalResearchError("fold plan must exactly match dataset run range")
    if dataset.target_symbol != "GOLD.i#":
        raise DirectionalResearchError("research target symbol must be GOLD.i#")
    features = build_features(dataset.bars)
    fold_by_name = {fold.name: fold for fold in folds.folds}
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "RESEARCH_ONLY_NOT_DEPLOYABLE",
        "target_symbol": dataset.target_symbol,
        "source_symbol": dataset.source_symbol,
        "limitations": [
            "external XAUUSD BID M5 bars; not broker GOLD.i# ask/real ticks",
            "exploratory bar model; MT5 isolated real-tick confirmation is mandatory",
            "validation_2 is confirmation-only and cannot trigger another tweak",
        ],
        "inputs": {
            "dataset_id": dataset.dataset_id,
            "dataset_manifest_path": str(dataset.manifest_path),
            "dataset_manifest_sha256": dataset.manifest_sha256,
            "fold_plan_path": str(folds.source_path),
            "fold_plan_sha256": folds.plan_sha256,
            "candidate_plan_path": str(plan.plan_path),
            "candidate_plan_sha256": plan.plan_sha256,
        },
        "sides": {},
    }
    for side in ("BULL", "BEAR"):
        base_results: list[dict[str, Any]] = []
        for candidate in (item for item in plan.candidates if item.side == side):
            train = _evaluate_fold(dataset, features, candidate, fold_by_name["train"])
            base_results.append(
                {
                    "candidate": asdict(candidate),
                    "train": _metrics_payload(train),
                    "train_score": _ranking_score(train),
                }
            )
        ranked_base = sorted(
            base_results,
            key=lambda item: (float(item["train_score"]), item["candidate"]["candidate_id"]),
            reverse=True,
        )
        base_winner = _candidate_from_json(ranked_base[0]["candidate"])
        tweak_results: list[dict[str, Any]] = []
        for tweak_index, (stop_delta, target_delta, hold_delta) in enumerate(plan.tweaks):
            candidate = replace(
                base_winner,
                candidate_id=f"{base_winner.candidate_id}__T{tweak_index:02d}",
                stop_atr=round(base_winner.stop_atr + stop_delta, 4),
                target_r=round(base_winner.target_r + target_delta, 4),
                max_hold_bars=base_winner.max_hold_bars + hold_delta,
            )
            if candidate.stop_atr <= 0 or candidate.target_r <= 0 or candidate.max_hold_bars < 1:
                raise DirectionalResearchError("frozen tweak produced invalid risk parameters")
            train = _evaluate_fold(dataset, features, candidate, fold_by_name["train"])
            validation_1 = _evaluate_fold(
                dataset, features, candidate, fold_by_name["validation_1"]
            )
            eligible = _eligible_before_confirmation(train, validation_1, plan)
            tweak_results.append(
                {
                    "candidate": asdict(candidate),
                    "train": _metrics_payload(train),
                    "validation_1": _metrics_payload(validation_1),
                    "selection_score": _selection_score(train, validation_1),
                    "eligible_before_confirmation": eligible,
                }
            )
        eligible = [item for item in tweak_results if item["eligible_before_confirmation"]]
        selection_pool = eligible or tweak_results
        selected = max(
            selection_pool,
            key=lambda item: (
                float(item["selection_score"]),
                item["candidate"]["candidate_id"],
            ),
        )
        selected_candidate = _candidate_from_json(selected["candidate"])
        confirmation = _evaluate_fold(
            dataset, features, selected_candidate, fold_by_name["validation_2"]
        )
        confirmation_passed = bool(eligible) and _confirmation_passes(
            confirmation, plan
        )
        report["sides"][side] = {
            "engine_class": "INDEPENDENT_DIRECTIONAL_ALGORITHM",
            "base_ranking": ranked_base,
            "base_winner": base_winner.candidate_id,
            "tweak_results": tweak_results,
            "selected_candidate": selected_candidate.candidate_id,
            "selected_from_eligible_pool": bool(eligible),
            "validation_2_confirmation": _metrics_payload(confirmation),
            "confirmation_passed": confirmation_passed,
            "promotion_status": (
                "BAR_MODEL_CONFIRMED_AWAITING_GOLDI_REAL_TICKS"
                if confirmation_passed
                else "REJECTED_OR_MORE_DEVELOPMENT_REQUIRED"
            ),
        }
    report["report_sha256"] = _canonical_sha256(report)
    return report


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    if not isinstance(path, Path) or not path.is_absolute():
        raise DirectionalResearchError("report path must be absolute")
    if path.exists():
        raise DirectionalResearchError("research report is immutable and already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def build_features(bars: Sequence[Bar]) -> Features:
    closes = [bar.close for bar in bars]
    true_ranges: list[float] = []
    for index, bar in enumerate(bars):
        previous_close = closes[index - 1] if index else bar.close
        true_ranges.append(
            max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close))
        )
    return Features(
        ema_fast=tuple(_ema(closes, 20)),
        ema_slow=tuple(_ema(closes, 50)),
        atr=tuple(_ema(true_ranges, 14)),
        atr_slow=tuple(_ema(true_ranges, 50)),
        rsi=tuple(_rsi(closes, 14)),
    )


def simulate_candidate(
    bars: Sequence[Bar],
    features: Features,
    candidate: Candidate,
    *,
    start: datetime,
    end: datetime,
    round_trip_quote: float,
) -> tuple[Trade, ...]:
    trades: list[Trade] = []
    index = max(candidate.structure_lookback + 2, 52)
    while index + 1 < len(bars):
        signal_bar = bars[index]
        entry_bar = bars[index + 1]
        if signal_bar.time < start or entry_bar.time < start:
            index += 1
            continue
        if entry_bar.time >= end:
            break
        if not _has_signal(bars, features, candidate, index):
            index += 1
            continue
        entry = entry_bar.open
        atr = features.atr[index]
        lookback = bars[index - candidate.structure_lookback : index + 1]
        if candidate.side == "BULL":
            structural_stop = min(bar.low for bar in lookback) - 0.05 * atr
            stop = min(entry - candidate.stop_atr * atr, structural_stop)
            risk = entry - stop
            target = entry + candidate.target_r * risk
        else:
            structural_stop = max(bar.high for bar in lookback) + 0.05 * atr
            stop = max(entry + candidate.stop_atr * atr, structural_stop)
            risk = stop - entry
            target = entry - candidate.target_r * risk
        if not math.isfinite(risk) or risk <= 0:
            index += 1
            continue
        exit_index = min(index + candidate.max_hold_bars, len(bars) - 1)
        exit_price = bars[exit_index].close
        exit_reason = "MAX_HOLD"
        for probe in range(index + 1, exit_index + 1):
            bar = bars[probe]
            if bar.time >= end:
                exit_index = probe - 1
                exit_price = bars[exit_index].close
                exit_reason = "FOLD_END"
                break
            stop_hit = bar.low <= stop if candidate.side == "BULL" else bar.high >= stop
            target_hit = bar.high >= target if candidate.side == "BULL" else bar.low <= target
            if stop_hit:
                exit_index = probe
                exit_price = stop
                exit_reason = "STOP" if not target_hit else "STOP_FIRST_COLLISION"
                break
            if target_hit:
                exit_index = probe
                exit_price = target
                exit_reason = "TARGET"
                break
        gross_r = (
            (exit_price - entry) / risk
            if candidate.side == "BULL"
            else (entry - exit_price) / risk
        )
        net_r = gross_r - round_trip_quote / risk
        trades.append(
            Trade(
                signal_time=signal_bar.time.isoformat(),
                entry_time=entry_bar.time.isoformat(),
                exit_time=bars[exit_index].time.isoformat(),
                side=candidate.side,
                entry=entry,
                stop=stop,
                target=target,
                exit_price=exit_price,
                exit_reason=exit_reason,
                gross_r=gross_r,
                net_r=net_r,
            )
        )
        index = max(index + 1, exit_index + 1)
    return tuple(trades)


def calculate_metrics(trades: Sequence[Trade]) -> Metrics:
    values = [trade.net_r for trade in trades]
    wins = sum(value > 0 for value in values)
    losses = sum(value <= 0 for value in values)
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    monthly: dict[str, float] = {}
    for trade, value in zip(trades, values, strict=True):
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        month = trade.exit_time[:7]
        monthly[month] = monthly.get(month, 0.0) + value
    return Metrics(
        trades=len(values),
        wins=wins,
        losses=losses,
        total_r=sum(values),
        expectancy_r=(sum(values) / len(values) if values else 0.0),
        profit_factor=(gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit else 0.0)),
        max_drawdown_r=max_drawdown,
        positive_month_ratio=(
            sum(value > 0 for value in monthly.values()) / len(monthly) if monthly else 0.0
        ),
    )


def _evaluate_fold(dataset, features, candidate, fold) -> Metrics:
    return calculate_metrics(
        simulate_candidate(
            dataset.bars,
            features,
            candidate,
            start=fold.start,
            end=fold.end,
            round_trip_quote=dataset.round_trip_quote,
        )
    )


def _has_signal(
    bars: Sequence[Bar], features: Features, candidate: Candidate, index: int
) -> bool:
    bar = bars[index]
    previous = bars[index - 1]
    if not _session_allows(candidate, bar.time.hour):
        return False
    rsi = features.rsi[index]
    if not candidate.rsi_minimum <= rsi <= candidate.rsi_maximum:
        return False
    prior = bars[index - candidate.structure_lookback : index]
    prior_high = max(item.high for item in prior)
    prior_low = min(item.low for item in prior)
    bull = candidate.side == "BULL"
    candle_ok = _pattern_matches(candidate.pattern, bull, bar, previous)
    if candidate.family == "TREND_RECLAIM":
        if bull:
            return (
                features.ema_fast[index] > features.ema_slow[index]
                and bar.low <= features.ema_fast[index]
                and bar.close > features.ema_fast[index]
                and candle_ok
            )
        return (
            features.ema_fast[index] < features.ema_slow[index]
            and bar.high >= features.ema_fast[index]
            and bar.close < features.ema_fast[index]
            and candle_ok
        )
    if candidate.family == "LIQUIDITY_SWEEP":
        if bull:
            return bar.low < prior_low and bar.close > prior_low and candle_ok
        return bar.high > prior_high and bar.close < prior_high and candle_ok
    if candidate.family == "SQUEEZE_EXPANSION":
        compressed = features.atr[index - 1] <= (
            candidate.squeeze_ratio * features.atr_slow[index - 1]
        )
        if bull:
            return compressed and bar.close > prior_high and bar.close > features.ema_slow[index]
        return compressed and bar.close < prior_low and bar.close < features.ema_slow[index]
    raise DirectionalResearchError(f"unsupported family {candidate.family}")


def _pattern_matches(pattern: str, bull: bool, bar: Bar, previous: Bar) -> bool:
    body = abs(bar.close - bar.open)
    span = max(bar.high - bar.low, 1e-12)
    if pattern == "BODY":
        return (bar.close > bar.open if bull else bar.close < bar.open) and body >= 0.45 * span
    if pattern == "ENGULF":
        if bull:
            return (
                bar.close > bar.open
                and previous.close < previous.open
                and bar.open <= previous.close
                and bar.close >= previous.open
            )
        return (
            bar.close < bar.open
            and previous.close > previous.open
            and bar.open >= previous.close
            and bar.close <= previous.open
        )
    if pattern == "PIN":
        if bull:
            lower_wick = min(bar.open, bar.close) - bar.low
            return bar.close > bar.open and lower_wick >= max(2.0 * body, 0.45 * span)
        upper_wick = bar.high - max(bar.open, bar.close)
        return bar.close < bar.open and upper_wick >= max(2.0 * body, 0.45 * span)
    if pattern == "NONE":
        return True
    raise DirectionalResearchError(f"unsupported candle pattern {pattern}")


def _candidate_from_json(raw: Any) -> Candidate:
    fields = {
        "candidate_id",
        "side",
        "family",
        "pattern",
        "session_start_utc",
        "session_end_utc",
        "structure_lookback",
        "stop_atr",
        "target_r",
        "max_hold_bars",
        "rsi_minimum",
        "rsi_maximum",
        "squeeze_ratio",
    }
    if not isinstance(raw, dict) or set(raw) != fields:
        raise DirectionalResearchError("candidate fields are invalid")
    candidate = Candidate(
        candidate_id=str(raw["candidate_id"]),
        side=str(raw["side"]),
        family=str(raw["family"]),
        pattern=str(raw["pattern"]),
        session_start_utc=int(raw["session_start_utc"]),
        session_end_utc=int(raw["session_end_utc"]),
        structure_lookback=int(raw["structure_lookback"]),
        stop_atr=float(raw["stop_atr"]),
        target_r=float(raw["target_r"]),
        max_hold_bars=int(raw["max_hold_bars"]),
        rsi_minimum=float(raw["rsi_minimum"]),
        rsi_maximum=float(raw["rsi_maximum"]),
        squeeze_ratio=float(raw["squeeze_ratio"]),
    )
    if not _TOKEN.fullmatch(candidate.candidate_id) or candidate.side not in {
        "BULL",
        "BEAR",
    } or not candidate.candidate_id.startswith(candidate.side + "_"):
        raise DirectionalResearchError("candidate identity/side is invalid")
    if candidate.family not in {
        "TREND_RECLAIM",
        "LIQUIDITY_SWEEP",
        "SQUEEZE_EXPANSION",
    } or candidate.pattern not in {"BODY", "ENGULF", "PIN", "NONE"}:
        raise DirectionalResearchError("candidate family/pattern is invalid")
    if not (
        0 <= candidate.session_start_utc <= 23
        and 0 <= candidate.session_end_utc <= 24
        and 3 <= candidate.structure_lookback <= 96
        and candidate.stop_atr > 0
        and candidate.target_r > 0
        and candidate.max_hold_bars > 0
        and 0 <= candidate.rsi_minimum < candidate.rsi_maximum <= 100
        and 0 < candidate.squeeze_ratio <= 1.5
    ):
        raise DirectionalResearchError("candidate parameter bounds are invalid")
    return candidate


def _eligible_before_confirmation(train: Metrics, validation: Metrics, plan: CandidatePlan) -> bool:
    return (
        train.trades >= plan.minimum_trades["train"]
        and validation.trades >= plan.minimum_trades["validation_1"]
        and train.expectancy_r > 0
        and validation.expectancy_r > 0
        and train.profit_factor > 1
        and validation.profit_factor > 1
        and max(train.max_drawdown_r, validation.max_drawdown_r)
        <= plan.maximum_drawdown_r
    )


def _confirmation_passes(metrics: Metrics, plan: CandidatePlan) -> bool:
    return (
        metrics.trades >= plan.minimum_trades["validation_2"]
        and metrics.expectancy_r > 0
        and metrics.profit_factor > 1
        and metrics.max_drawdown_r <= plan.maximum_drawdown_r
    )


def _ranking_score(metrics: Metrics) -> float:
    return metrics.expectancy_r + 0.10 * math.log(max(metrics.profit_factor, 0.01)) - 0.01 * metrics.max_drawdown_r


def _selection_score(train: Metrics, validation: Metrics) -> float:
    return (
        min(train.expectancy_r, validation.expectancy_r)
        + 0.10 * math.log(max(min(train.profit_factor, validation.profit_factor), 0.01))
        - 0.01 * max(train.max_drawdown_r, validation.max_drawdown_r)
    )


def _metrics_payload(metrics: Metrics) -> dict[str, Any]:
    payload = asdict(metrics)
    for key, value in payload.items():
        if isinstance(value, float) and not math.isfinite(value):
            payload[key] = 999.0
    return payload


def _session_allows(candidate: Candidate, hour: int) -> bool:
    start, end = candidate.session_start_utc, candidate.session_end_utc
    if start == 0 and end == 24:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _read_epsoft_bars(path: Path) -> Iterable[Bar]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["Local time", "Open", "High", "Low", "Close", "Volume"]:
            raise DirectionalResearchError(f"unexpected EPSOFT header: {path}")
        for line_number, raw in enumerate(reader, start=2):
            try:
                local = datetime.strptime(raw["Local time"], _SOURCE_TIME)
                values = tuple(float(raw[name]) for name in ("Open", "High", "Low", "Close"))
            except (KeyError, TypeError, ValueError) as exc:
                raise DirectionalResearchError(
                    f"invalid EPSOFT row {path}:{line_number}"
                ) from exc
            open_price, high, low, close = values
            if any(not math.isfinite(value) or value <= 0 for value in values):
                raise DirectionalResearchError(f"non-positive bar at {path}:{line_number}")
            if high < max(open_price, close) or low > min(open_price, close) or high < low:
                raise DirectionalResearchError(f"invalid OHLC geometry at {path}:{line_number}")
            yield Bar(local.astimezone(timezone.utc), open_price, high, low, close)


def _ema(values: Sequence[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1.0)
    output: list[float] = []
    current = values[0]
    for value in values:
        current = alpha * value + (1.0 - alpha) * current
        output.append(current)
    return output


def _rsi(values: Sequence[float], period: int) -> list[float]:
    output = [50.0] * len(values)
    average_gain = 0.0
    average_loss = 0.0
    for index in range(1, len(values)):
        delta = values[index] - values[index - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        if index <= period:
            average_gain += gain / period
            average_loss += loss / period
        else:
            average_gain = (average_gain * (period - 1) + gain) / period
            average_loss = (average_loss * (period - 1) + loss) / period
        if average_loss == 0:
            output[index] = 100.0 if average_gain > 0 else 50.0
        else:
            relative_strength = average_gain / average_loss
            output[index] = 100.0 - 100.0 / (1.0 + relative_strength)
    return output


def _resolve_bound_path(manifest: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise DirectionalResearchError(f"{label} path is invalid")
    candidate = (manifest.parent / value).resolve(strict=True)
    if not candidate.is_file():
        raise DirectionalResearchError(f"{label} path is not a file")
    return candidate


def _assert_digest(path: Path, expected: Any, label: str) -> None:
    if not isinstance(expected, str) or not _SHA256.fullmatch(expected):
        raise DirectionalResearchError(f"{label} SHA-256 is invalid")
    if _sha256_file(path) != expected:
        raise DirectionalResearchError(f"{label} SHA-256 mismatch")


def _canonical_file(path: Path, label: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or not path.is_file():
        raise DirectionalResearchError(f"{label} must be an absolute existing file")
    canonical = path.resolve(strict=True)
    if canonical != path:
        raise DirectionalResearchError(f"{label} path must be canonical")
    return canonical


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DirectionalResearchError(f"invalid JSON: {path}") from exc


def _finite_positive(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise DirectionalResearchError(f"{label} must be positive")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise DirectionalResearchError(f"{label} must be positive")
    return parsed


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
