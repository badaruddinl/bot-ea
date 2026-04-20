from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
from typing import Any


@dataclass(slots=True)
class TradeRecord:
    symbol: str
    strategy_family: str
    side: str
    entry_time: datetime
    exit_time: datetime
    pnl_cash: float
    risk_cash: float
    entry_spread_points: float = 0.0
    quoted_entry_price: float | None = None
    realized_entry_price: float | None = None
    commission_cash: float = 0.0
    swap_cash: float = 0.0
    slippage_points: float = 0.0
    fill_latency_ms: float = 0.0
    reject_code: str | None = None
    exit_reason: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def holding_minutes(self) -> float:
        return max((self.exit_time - self.entry_time).total_seconds() / 60.0, 0.0)

    @property
    def r_multiple(self) -> float:
        if self.risk_cash <= 0:
            return 0.0
        return self.pnl_cash / self.risk_cash


@dataclass(slots=True)
class ValidationSummary:
    total_trades: int
    win_rate: float
    profit_factor: float
    expectancy_r: float
    total_pnl_cash: float
    max_drawdown_cash: float
    max_drawdown_pct: float
    average_holding_minutes: float
    average_entry_spread_points: float
    average_r_multiple: float
    average_slippage_points: float = 0.0
    average_fill_latency_ms: float = 0.0
    total_commission_cash: float = 0.0
    total_swap_cash: float = 0.0
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionQualitySummary:
    total_trade_records: int
    rejected_orders: int
    total_order_attempts: int
    reject_rate: float
    average_entry_spread_points: float
    average_slippage_points: float
    average_fill_latency_ms: float
    spread_drift_points: float
    total_commission_cash: float
    total_swap_cash: float
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeValidationReport:
    trade_records: list[TradeRecord]
    validation_summary: ValidationSummary
    execution_quality: ExecutionQualitySummary
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PromotionGateThresholds:
    min_oos_trade_count: int = 30
    min_oos_expectancy_r: float = 0.0
    min_oos_profit_factor: float = 1.05
    max_oos_drawdown_pct: float = 15.0
    max_average_entry_spread_points: float = 25.0
    max_average_slippage_points: float = 5.0
    max_reject_rate: float = 0.10
    require_expectancy_beat: bool = True
    require_pnl_beat: bool = False
    max_drawdown_delta_pct: float | None = None
    min_window_pass_ratio: float = 0.67
    require_holdout_pass: bool = False


@dataclass(slots=True)
class OOSWindowResult:
    label: str
    window_start: datetime | None
    window_end: datetime | None
    summary: ValidationSummary
    execution_quality: ExecutionQualitySummary
    passed: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PromotionCheckResult:
    name: str
    passed: bool
    detail: str
    metric_value: float | str | None = None
    threshold_value: float | str | None = None


@dataclass(slots=True)
class PromotionCandidate:
    label: str
    out_of_sample_summary: ValidationSummary
    execution_quality: ExecutionQualitySummary
    oos_windows: list[OOSWindowResult] = field(default_factory=list)
    holdout_summary: ValidationSummary | None = None
    parameter_profile: str | None = None
    dataset_label: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PromotionDecision:
    approved: bool
    champion_label: str
    challenger_label: str
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: list[PromotionCheckResult] = field(default_factory=list)


@dataclass(slots=True)
class PromotionAuditRecord:
    decided_at: datetime
    champion: PromotionCandidate
    challenger: PromotionCandidate
    thresholds: PromotionGateThresholds
    checks: list[PromotionCheckResult]
    decision: PromotionDecision
    notes: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)


_FILLED_EXECUTION_STATUSES = {"FILLED", "DRY_RUN_OK"}
_REJECTED_EXECUTION_STATUSES = {"REJECTED", "ERROR", "PRECHECK_REJECTED", "GUARD_REJECTED"}
_TERMINAL_EXECUTION_PHASES = {"FILL", "GUARD"}
_TERMINAL_EXECUTION_STATUSES = _FILLED_EXECUTION_STATUSES | _REJECTED_EXECUTION_STATUSES
_CLOSED_POSITION_STATUSES = {"CLOSED", "CLOSE", "CLOSED_OUT", "EXITED", "SETTLED"}


def build_trade_records_from_runtime(
    position_events: Sequence[Mapping[str, Any]],
    execution_events: Sequence[Mapping[str, Any]] | None = None,
    *,
    default_strategy_family: str = "runtime_ledger",
) -> list[TradeRecord]:
    trades, _, _, _ = _bridge_runtime_records(
        position_events,
        execution_events or [],
        default_strategy_family=default_strategy_family,
    )
    return trades


def build_runtime_validation_report(
    position_events: Sequence[Mapping[str, Any]],
    execution_events: Sequence[Mapping[str, Any]] | None = None,
    *,
    starting_equity: float,
    default_strategy_family: str = "runtime_ledger",
) -> RuntimeValidationReport:
    trades, bridge_warnings, rejected_orders, total_order_attempts = _bridge_runtime_records(
        position_events,
        execution_events or [],
        default_strategy_family=default_strategy_family,
    )
    validation_summary = summarize_trades(trades, starting_equity=starting_equity)
    execution_quality = summarize_execution_quality(
        trades,
        rejected_orders=rejected_orders,
        total_order_attempts=total_order_attempts,
    )
    if bridge_warnings:
        validation_summary.warnings = list(dict.fromkeys(validation_summary.warnings + bridge_warnings))
        execution_quality.warnings = list(dict.fromkeys(execution_quality.warnings + bridge_warnings))
    return RuntimeValidationReport(
        trade_records=trades,
        validation_summary=validation_summary,
        execution_quality=execution_quality,
        warnings=bridge_warnings,
    )


def summarize_trades(trades: list[TradeRecord], *, starting_equity: float) -> ValidationSummary:
    if not trades:
        return ValidationSummary(
            total_trades=0,
            win_rate=0.0,
            profit_factor=0.0,
            expectancy_r=0.0,
            total_pnl_cash=0.0,
            max_drawdown_cash=0.0,
            max_drawdown_pct=0.0,
            average_holding_minutes=0.0,
            average_entry_spread_points=0.0,
            average_r_multiple=0.0,
            average_slippage_points=0.0,
            average_fill_latency_ms=0.0,
            total_commission_cash=0.0,
            total_swap_cash=0.0,
            warnings=["no trades supplied"],
        )

    total_trades = len(trades)
    wins = [trade for trade in trades if trade.pnl_cash > 0]
    losses = [trade for trade in trades if trade.pnl_cash < 0]
    gross_profit = sum(trade.pnl_cash for trade in wins)
    gross_loss = abs(sum(trade.pnl_cash for trade in losses))
    total_pnl_cash = sum(trade.pnl_cash for trade in trades)
    average_holding_minutes = sum(trade.holding_minutes for trade in trades) / total_trades
    average_entry_spread_points = sum(trade.entry_spread_points for trade in trades) / total_trades
    average_r_multiple = sum(trade.r_multiple for trade in trades) / total_trades
    average_slippage_points = sum(trade.slippage_points for trade in trades) / total_trades
    average_fill_latency_ms = sum(trade.fill_latency_ms for trade in trades) / total_trades
    total_commission_cash = sum(trade.commission_cash for trade in trades)
    total_swap_cash = sum(trade.swap_cash for trade in trades)
    expectancy_r = average_r_multiple

    equity = starting_equity
    peak = starting_equity
    max_drawdown_cash = 0.0
    for trade in trades:
        equity += trade.pnl_cash
        peak = max(peak, equity)
        max_drawdown_cash = max(max_drawdown_cash, peak - equity)
    max_drawdown_pct = (max_drawdown_cash / peak) * 100.0 if peak > 0 else 0.0

    warnings: list[str] = []
    if average_entry_spread_points <= 0:
        warnings.append("spread cost data missing or zero")
    if average_fill_latency_ms <= 0:
        warnings.append("fill latency data missing or zero")
    if total_trades < 30:
        warnings.append("sample size still small for serious validation")
    if gross_loss == 0:
        warnings.append("profit factor inflated because there are no losing trades")

    return ValidationSummary(
        total_trades=total_trades,
        win_rate=len(wins) / total_trades,
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
        expectancy_r=expectancy_r,
        total_pnl_cash=total_pnl_cash,
        max_drawdown_cash=max_drawdown_cash,
        max_drawdown_pct=max_drawdown_pct,
        average_holding_minutes=average_holding_minutes,
        average_entry_spread_points=average_entry_spread_points,
        average_r_multiple=average_r_multiple,
        average_slippage_points=average_slippage_points,
        average_fill_latency_ms=average_fill_latency_ms,
        total_commission_cash=total_commission_cash,
        total_swap_cash=total_swap_cash,
        warnings=warnings,
    )


def summarize_execution_quality(
    trades: list[TradeRecord],
    *,
    rejected_orders: int = 0,
    total_order_attempts: int | None = None,
) -> ExecutionQualitySummary:
    if not trades:
        attempts = total_order_attempts or rejected_orders
        reject_rate = (rejected_orders / attempts) if attempts > 0 else 0.0
        return ExecutionQualitySummary(
            total_trade_records=0,
            rejected_orders=rejected_orders,
            total_order_attempts=attempts,
            reject_rate=reject_rate,
            average_entry_spread_points=0.0,
            average_slippage_points=0.0,
            average_fill_latency_ms=0.0,
            spread_drift_points=0.0,
            total_commission_cash=0.0,
            total_swap_cash=0.0,
            warnings=["no trades supplied"],
        )

    total_trade_records = len(trades)
    attempts = total_order_attempts if total_order_attempts is not None else total_trade_records + rejected_orders
    average_entry_spread_points = sum(trade.entry_spread_points for trade in trades) / total_trade_records
    average_slippage_points = sum(trade.slippage_points for trade in trades) / total_trade_records
    average_fill_latency_ms = sum(trade.fill_latency_ms for trade in trades) / total_trade_records
    total_commission_cash = sum(trade.commission_cash for trade in trades)
    total_swap_cash = sum(trade.swap_cash for trade in trades)
    reject_rate = (rejected_orders / attempts) if attempts > 0 else 0.0
    spread_drift_points = average_slippage_points - average_entry_spread_points

    warnings: list[str] = []
    if average_entry_spread_points <= 0:
        warnings.append("quoted spread data missing or zero")
    if average_fill_latency_ms <= 0:
        warnings.append("fill latency data missing or zero")
    if reject_rate > 0.10:
        warnings.append("reject rate elevated")

    return ExecutionQualitySummary(
        total_trade_records=total_trade_records,
        rejected_orders=rejected_orders,
        total_order_attempts=attempts,
        reject_rate=reject_rate,
        average_entry_spread_points=average_entry_spread_points,
        average_slippage_points=average_slippage_points,
        average_fill_latency_ms=average_fill_latency_ms,
        spread_drift_points=spread_drift_points,
        total_commission_cash=total_commission_cash,
        total_swap_cash=total_swap_cash,
        warnings=warnings,
    )


def evaluate_cost_realism(trades: list[TradeRecord], *, spread_threshold_points: float) -> list[str]:
    warnings: list[str] = []
    if not trades:
        return ["no trades to evaluate for cost realism"]
    average_spread = sum(trade.entry_spread_points for trade in trades) / len(trades)
    if average_spread > spread_threshold_points:
        warnings.append("average entry spread exceeds configured realism threshold")
    if any(trade.risk_cash <= 0 for trade in trades):
        warnings.append("one or more trades have invalid risk_cash")
    return warnings


def export_summary_markdown(summary: ValidationSummary) -> str:
    warning_lines = "\n".join(f"- {warning}" for warning in summary.warnings) if summary.warnings else "- none"
    return "\n".join(
        [
            "# Validation Summary",
            "",
            f"- total trades: {summary.total_trades}",
            f"- win rate: {summary.win_rate:.2%}",
            f"- profit factor: {summary.profit_factor:.3f}",
            f"- expectancy (R): {summary.expectancy_r:.3f}",
            f"- total pnl cash: {summary.total_pnl_cash:.2f}",
            f"- max drawdown cash: {summary.max_drawdown_cash:.2f}",
            f"- max drawdown pct: {summary.max_drawdown_pct:.2f}%",
            f"- average holding minutes: {summary.average_holding_minutes:.2f}",
            f"- average entry spread points: {summary.average_entry_spread_points:.2f}",
            f"- average slippage points: {summary.average_slippage_points:.2f}",
            f"- average fill latency ms: {summary.average_fill_latency_ms:.2f}",
            f"- total commission cash: {summary.total_commission_cash:.2f}",
            f"- total swap cash: {summary.total_swap_cash:.2f}",
            "",
            "## Warnings",
            warning_lines,
        ]
    )


def evaluate_promotion_gate(
    champion: PromotionCandidate,
    challenger: PromotionCandidate,
    *,
    thresholds: PromotionGateThresholds | None = None,
) -> PromotionDecision:
    thresholds = thresholds or PromotionGateThresholds()
    checks: list[PromotionCheckResult] = []
    checks.extend(_evaluate_absolute_promotion(challenger, thresholds=thresholds))
    checks.extend(evaluate_oos_windows(challenger, thresholds=thresholds))
    checks.extend(evaluate_relative_promotion(champion, challenger, thresholds=thresholds))

    reasons = [check.detail for check in checks if not check.passed]
    warnings = list(dict.fromkeys(challenger.out_of_sample_summary.warnings + challenger.execution_quality.warnings + challenger.notes))
    return PromotionDecision(
        approved=not reasons,
        champion_label=champion.label,
        challenger_label=challenger.label,
        reasons=reasons,
        warnings=warnings,
        checks=checks,
    )


def evaluate_oos_windows(
    candidate: PromotionCandidate,
    *,
    thresholds: PromotionGateThresholds,
) -> list[PromotionCheckResult]:
    if not candidate.oos_windows:
        return []
    passed_windows = sum(1 for window in candidate.oos_windows if window.passed)
    pass_ratio = passed_windows / len(candidate.oos_windows)
    return [
        PromotionCheckResult(
            name="oos_window_pass_ratio",
            passed=pass_ratio >= thresholds.min_window_pass_ratio,
            detail=(
                f"challenger OOS window pass ratio {pass_ratio:.2f} meets minimum {thresholds.min_window_pass_ratio:.2f}"
                if pass_ratio >= thresholds.min_window_pass_ratio
                else f"challenger OOS window pass ratio {pass_ratio:.2f} below minimum {thresholds.min_window_pass_ratio:.2f}"
            ),
            metric_value=round(pass_ratio, 4),
            threshold_value=thresholds.min_window_pass_ratio,
        )
    ]


def evaluate_relative_promotion(
    champion: PromotionCandidate,
    challenger: PromotionCandidate,
    *,
    thresholds: PromotionGateThresholds,
) -> list[PromotionCheckResult]:
    checks: list[PromotionCheckResult] = []
    champion_oos = champion.out_of_sample_summary
    challenger_oos = challenger.out_of_sample_summary

    if thresholds.require_expectancy_beat:
        checks.append(
            PromotionCheckResult(
                name="expectancy_beat",
                passed=challenger_oos.expectancy_r > champion_oos.expectancy_r,
                detail=(
                    "challenger expectancy exceeds champion"
                    if challenger_oos.expectancy_r > champion_oos.expectancy_r
                    else "challenger expectancy does not exceed champion"
                ),
                metric_value=challenger_oos.expectancy_r,
                threshold_value=champion_oos.expectancy_r,
            )
        )
    if thresholds.require_pnl_beat:
        checks.append(
            PromotionCheckResult(
                name="pnl_beat",
                passed=challenger_oos.total_pnl_cash > champion_oos.total_pnl_cash,
                detail=(
                    "challenger pnl exceeds champion"
                    if challenger_oos.total_pnl_cash > champion_oos.total_pnl_cash
                    else "challenger pnl does not exceed champion"
                ),
                metric_value=challenger_oos.total_pnl_cash,
                threshold_value=champion_oos.total_pnl_cash,
            )
        )
    if thresholds.max_drawdown_delta_pct is not None:
        drawdown_delta = challenger_oos.max_drawdown_pct - champion_oos.max_drawdown_pct
        checks.append(
            PromotionCheckResult(
                name="drawdown_delta",
                passed=drawdown_delta <= thresholds.max_drawdown_delta_pct,
                detail=(
                    f"challenger drawdown delta {drawdown_delta:.2f}% within maximum"
                    if drawdown_delta <= thresholds.max_drawdown_delta_pct
                    else f"challenger drawdown delta {drawdown_delta:.2f}% above maximum"
                ),
                metric_value=round(drawdown_delta, 4),
                threshold_value=thresholds.max_drawdown_delta_pct,
            )
        )
    if thresholds.require_holdout_pass:
        holdout = challenger.holdout_summary
        holdout_pass = holdout is not None and holdout.expectancy_r >= thresholds.min_oos_expectancy_r and holdout.profit_factor >= thresholds.min_oos_profit_factor
        checks.append(
            PromotionCheckResult(
                name="holdout_pass",
                passed=holdout_pass,
                detail="challenger holdout passes" if holdout_pass else "challenger holdout missing or below threshold",
                metric_value=None if holdout is None else holdout.expectancy_r,
                threshold_value=thresholds.min_oos_expectancy_r,
            )
        )
    return checks


def build_promotion_audit_record(
    champion: PromotionCandidate,
    challenger: PromotionCandidate,
    decision: PromotionDecision,
    *,
    thresholds: PromotionGateThresholds,
    notes: list[str] | None = None,
    artifact_refs: list[str] | None = None,
) -> PromotionAuditRecord:
    return PromotionAuditRecord(
        decided_at=datetime.now(UTC),
        champion=champion,
        challenger=challenger,
        thresholds=thresholds,
        checks=decision.checks,
        decision=decision,
        notes=notes or [],
        artifact_refs=artifact_refs or [],
    )


def export_promotion_audit_markdown(audit: PromotionAuditRecord) -> str:
    check_lines = "\n".join(
        f"- [{'PASS' if check.passed else 'FAIL'}] {check.name}: {check.detail}"
        for check in audit.checks
    ) or "- none"
    reason_lines = "\n".join(f"- {reason}" for reason in audit.decision.reasons) or "- none"
    warning_lines = "\n".join(f"- {warning}" for warning in audit.decision.warnings) or "- none"
    threshold_lines = "\n".join(
        f"- {name}: {value}"
        for name, value in asdict(audit.thresholds).items()
    ) or "- none"
    artifact_lines = "\n".join(f"- {artifact}" for artifact in audit.artifact_refs) or "- none"
    note_lines = "\n".join(f"- {note}" for note in audit.notes) or "- none"
    return "\n".join(
        [
            "# Promotion Audit",
            "",
            f"- decided at: {audit.decided_at.isoformat()}",
            f"- champion: {audit.champion.label}",
            f"- champion parameter profile: {audit.champion.parameter_profile or 'n/a'}",
            f"- champion dataset label: {audit.champion.dataset_label or 'n/a'}",
            f"- challenger: {audit.challenger.label}",
            f"- challenger parameter profile: {audit.challenger.parameter_profile or 'n/a'}",
            f"- challenger dataset label: {audit.challenger.dataset_label or 'n/a'}",
            f"- approved: {audit.decision.approved}",
            "",
            "## Thresholds Used",
            threshold_lines,
            "",
            "## Checks",
            check_lines,
            "",
            "## Reasons",
            reason_lines,
            "",
            "## Warnings",
            warning_lines,
            "",
            "## Artifact Refs",
            artifact_lines,
            "",
            "## Notes",
            note_lines,
        ]
    )


def export_promotion_audit_json(audit: PromotionAuditRecord) -> str:
    return json.dumps(asdict(audit), default=str, sort_keys=True, indent=2)


def _bridge_runtime_records(
    position_events: Sequence[Mapping[str, Any]],
    execution_events: Sequence[Mapping[str, Any]],
    *,
    default_strategy_family: str,
) -> tuple[list[TradeRecord], list[str], int, int]:
    execution_bridge = _build_execution_bridge(execution_events)
    position_aggregates = _aggregate_position_events(position_events)

    trade_records: list[TradeRecord] = []
    missing_fill_matches = 0
    skipped_open_positions = 0
    used_fill_tokens: set[tuple[int, int]] = set()

    for aggregate in position_aggregates:
        if not _position_has_exit(aggregate):
            skipped_open_positions += 1
            continue

        fill_meta = _match_fill_event(aggregate, execution_bridge["lookups"], used_fill_tokens)
        fill_row = fill_meta["row"] if fill_meta is not None else {}
        fill_payload = fill_meta["payload"] if fill_meta is not None else {}

        notes = list(aggregate["notes"])
        if fill_meta is None:
            missing_fill_matches += 1
            notes.append("fill telemetry missing; runtime ledger used as fallback")

        entry_time, exit_time = _finalize_trade_times(
            aggregate["opened_at"],
            aggregate["closed_at"],
            fallback=_coerce_datetime(_first_present(fill_row.get("polled_at"), fill_payload.get("time"))),
        )
        trade_records.append(
            TradeRecord(
                symbol=str(aggregate["symbol"] or "unknown"),
                strategy_family=str(aggregate["strategy_family"] or default_strategy_family),
                side=str(aggregate["side"] or "unknown"),
                entry_time=entry_time,
                exit_time=exit_time,
                pnl_cash=_coerce_float(aggregate["pnl_cash"]),
                risk_cash=_coerce_float(aggregate["risk_cash"]),
                entry_spread_points=_coerce_float(
                    _first_present(
                        aggregate["entry_spread_points"],
                        fill_row.get("entry_spread_points"),
                        fill_payload.get("entry_spread_points"),
                        fill_payload.get("quoted_spread_points"),
                        fill_payload.get("spread_points"),
                    )
                ),
                quoted_entry_price=_coerce_optional_float(
                    _first_present(
                        aggregate["quoted_entry_price"],
                        fill_row.get("quoted_price"),
                        fill_payload.get("quoted_price"),
                        fill_row.get("price"),
                    )
                ),
                realized_entry_price=_coerce_optional_float(
                    _first_present(
                        aggregate["realized_entry_price"],
                        fill_row.get("executed_price"),
                        fill_payload.get("realized_price"),
                        fill_row.get("price"),
                        aggregate["entry_price"],
                    )
                ),
                commission_cash=_coerce_float(aggregate["commission_cash"]),
                swap_cash=_coerce_float(aggregate["swap_cash"]),
                slippage_points=_coerce_float(
                    _first_present(
                        aggregate["slippage_points"],
                        fill_row.get("slippage_points"),
                        fill_payload.get("slippage_points"),
                    )
                ),
                fill_latency_ms=_coerce_float(
                    _first_present(
                        aggregate["fill_latency_ms"],
                        fill_row.get("fill_latency_ms"),
                        fill_payload.get("fill_latency_ms"),
                    )
                ),
                reject_code=_normalize_optional_string(
                    _first_present(
                        aggregate["reject_code"],
                        fill_row.get("retcode"),
                        fill_payload.get("retcode"),
                    )
                ),
                exit_reason=str(aggregate["exit_reason"] or ""),
                notes=notes,
            )
        )

    bridge_warnings: list[str] = []
    if skipped_open_positions:
        bridge_warnings.append(_format_count_warning(skipped_open_positions, "open position event skipped because it has no exit ledger", "open position events skipped because they have no exit ledger"))
    if missing_fill_matches:
        bridge_warnings.append(_format_count_warning(missing_fill_matches, "closed trade missing fill telemetry linkage", "closed trades missing fill telemetry linkage"))

    unmatched_fill_attempts = sum(
        1
        for fill_meta in execution_bridge["fill_candidates"]
        if fill_meta["token"] not in used_fill_tokens
    )
    if unmatched_fill_attempts:
        bridge_warnings.append(_format_count_warning(unmatched_fill_attempts, "filled execution attempt was not matched to a ledger position", "filled execution attempts were not matched to ledger positions"))

    trade_records.sort(key=lambda trade: (trade.exit_time, trade.entry_time, trade.symbol, trade.side))
    return (
        trade_records,
        bridge_warnings,
        execution_bridge["rejected_orders"],
        execution_bridge["total_order_attempts"],
    )


def _aggregate_position_events(position_events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = {}
    for index, event in enumerate(position_events):
        payload = _coerce_payload(event)
        key = _position_key(event, payload, index)
        aggregate = aggregates.setdefault(
            key,
            {
                "symbol": _first_present(event.get("symbol"), payload.get("symbol")),
                "strategy_family": _first_present(
                    payload.get("strategy_family"),
                    payload.get("strategy"),
                    payload.get("model_family"),
                ),
                "side": _normalize_side(_first_present(event.get("side"), payload.get("side"))),
                "entry_price": None,
                "quoted_entry_price": None,
                "realized_entry_price": None,
                "entry_spread_points": None,
                "slippage_points": None,
                "fill_latency_ms": None,
                "opened_at": None,
                "closed_at": None,
                "pnl_cash": None,
                "risk_cash": None,
                "commission_cash": 0.0,
                "swap_cash": 0.0,
                "exit_reason": None,
                "reject_code": None,
                "notes": [],
                "position_id": _first_present(event.get("broker_position_id"), payload.get("broker_position_id")),
                "deal_ticket": _first_present(payload.get("deal"), payload.get("deal_ticket")),
                "attempt_id": _first_present(event.get("attempt_id"), payload.get("attempt_id")),
                "statuses": set(),
            },
        )

        aggregate["symbol"] = _first_present(aggregate["symbol"], event.get("symbol"), payload.get("symbol"))
        aggregate["strategy_family"] = _first_present(
            aggregate["strategy_family"],
            payload.get("strategy_family"),
            payload.get("strategy"),
            payload.get("model_family"),
        )
        aggregate["side"] = _normalize_side(_first_present(aggregate["side"], event.get("side"), payload.get("side")))
        aggregate["position_id"] = _first_present(aggregate["position_id"], event.get("broker_position_id"), payload.get("broker_position_id"))
        aggregate["deal_ticket"] = _first_present(aggregate["deal_ticket"], payload.get("deal"), payload.get("deal_ticket"))
        aggregate["attempt_id"] = _first_present(aggregate["attempt_id"], event.get("attempt_id"), payload.get("attempt_id"))

        status = _normalize_status(event.get("status"))
        if status:
            aggregate["statuses"].add(status)

        entry_price = _coerce_optional_float(_first_present(event.get("entry_price"), payload.get("entry_price")))
        if aggregate["entry_price"] is None and entry_price is not None:
            aggregate["entry_price"] = entry_price
        aggregate["quoted_entry_price"] = _first_present(
            aggregate["quoted_entry_price"],
            payload.get("quoted_price"),
            payload.get("quoted_entry_price"),
        )
        aggregate["realized_entry_price"] = _first_present(
            aggregate["realized_entry_price"],
            payload.get("realized_price"),
            payload.get("executed_price"),
            entry_price,
        )
        aggregate["entry_spread_points"] = _first_present(
            aggregate["entry_spread_points"],
            event.get("entry_spread_points"),
            payload.get("entry_spread_points"),
            payload.get("quoted_spread_points"),
            payload.get("spread_points"),
        )
        aggregate["slippage_points"] = _first_present(
            aggregate["slippage_points"],
            event.get("slippage_points"),
            payload.get("slippage_points"),
        )
        aggregate["fill_latency_ms"] = _first_present(
            aggregate["fill_latency_ms"],
            event.get("fill_latency_ms"),
            payload.get("fill_latency_ms"),
        )

        opened_at = _coerce_datetime(_first_present(event.get("opened_at"), payload.get("opened_at"), event.get("polled_at")))
        if opened_at is not None and (aggregate["opened_at"] is None or opened_at < aggregate["opened_at"]):
            aggregate["opened_at"] = opened_at

        closed_at = _coerce_datetime(_first_present(event.get("closed_at"), payload.get("closed_at")))
        if closed_at is None and (
            status in _CLOSED_POSITION_STATUSES
            or event.get("realized_pnl_cash") is not None
            or event.get("exit_price") is not None
        ):
            closed_at = _coerce_datetime(_first_present(event.get("polled_at"), payload.get("polled_at")))
        if closed_at is not None and (aggregate["closed_at"] is None or closed_at > aggregate["closed_at"]):
            aggregate["closed_at"] = closed_at

        pnl_cash = _coerce_optional_float(_first_present(event.get("realized_pnl_cash"), payload.get("realized_pnl_cash")))
        if pnl_cash is not None:
            aggregate["pnl_cash"] = pnl_cash
        aggregate["risk_cash"] = _first_present(
            aggregate["risk_cash"],
            event.get("risk_cash"),
            payload.get("risk_cash"),
            payload.get("risk_cash_budget"),
        )

        commission_cash = _coerce_optional_float(_first_present(event.get("commission_cash"), payload.get("commission_cash")))
        if commission_cash is not None:
            aggregate["commission_cash"] += commission_cash
        swap_cash = _coerce_optional_float(_first_present(event.get("swap_cash"), payload.get("swap_cash")))
        if swap_cash is not None:
            aggregate["swap_cash"] += swap_cash

        aggregate["exit_reason"] = _first_present(
            aggregate["exit_reason"],
            event.get("exit_reason"),
            payload.get("exit_reason"),
            payload.get("close_reason"),
        )
        aggregate["reject_code"] = _first_present(
            aggregate["reject_code"],
            event.get("retcode"),
            payload.get("retcode"),
            payload.get("reject_code"),
        )
        payload_warnings = payload.get("warnings", [])
        if isinstance(payload_warnings, str):
            payload_warnings = [payload_warnings]
        for warning in payload_warnings:
            if isinstance(warning, str):
                aggregate["notes"].append(warning)

    return list(aggregates.values())


def _build_execution_bridge(execution_events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    terminal_by_attempt: dict[str, dict[str, Any]] = {}
    for index, event in enumerate(execution_events):
        payload = _coerce_payload(event)
        if not _is_terminal_execution_event(event, payload):
            continue
        token = _execution_token(event, index)
        attempt_key = _normalize_optional_string(_first_present(event.get("attempt_id"), payload.get("attempt_id"))) or f"legacy-{token[0]}-{token[1]}"
        current = terminal_by_attempt.get(attempt_key)
        candidate = {"row": event, "payload": payload, "token": token}
        if current is None or token > current["token"]:
            terminal_by_attempt[attempt_key] = candidate

    fill_candidates: list[dict[str, Any]] = []
    lookups: dict[str, dict[Any, list[dict[str, Any]]]] = {
        "attempt": {},
        "order": {},
        "deal": {},
        "symbol_side": {},
    }
    rejected_orders = 0
    for candidate in terminal_by_attempt.values():
        row = candidate["row"]
        payload = candidate["payload"]
        status = _normalize_status(_first_present(row.get("status"), payload.get("status")))
        if status in _REJECTED_EXECUTION_STATUSES:
            rejected_orders += 1
        if status not in _FILLED_EXECUTION_STATUSES:
            continue

        fill_candidates.append(candidate)
        _append_lookup(lookups["attempt"], _normalize_optional_string(_first_present(row.get("attempt_id"), payload.get("attempt_id"))), candidate)
        _append_lookup(lookups["order"], _normalize_optional_string(_first_present(row.get("order_ticket"), payload.get("order"), payload.get("order_ticket"))), candidate)
        _append_lookup(lookups["deal"], _normalize_optional_string(_first_present(row.get("deal_ticket"), payload.get("deal"), payload.get("deal_ticket"))), candidate)
        symbol = _normalize_optional_string(_first_present(row.get("symbol"), payload.get("symbol")))
        side = _normalize_side(_first_present(row.get("side"), payload.get("side")))
        if symbol and side:
            lookups["symbol_side"].setdefault((symbol.upper(), side), []).append(candidate)

    return {
        "fill_candidates": fill_candidates,
        "lookups": lookups,
        "rejected_orders": rejected_orders,
        "total_order_attempts": len(terminal_by_attempt),
    }


def _match_fill_event(
    aggregate: Mapping[str, Any],
    lookups: Mapping[str, dict[Any, list[dict[str, Any]]]],
    used_fill_tokens: set[tuple[int, int]],
) -> dict[str, Any] | None:
    direct_candidates = (
        ("order", _normalize_optional_string(aggregate.get("position_id"))),
        ("deal", _normalize_optional_string(aggregate.get("deal_ticket"))),
        ("attempt", _normalize_optional_string(aggregate.get("attempt_id"))),
    )
    target_time = aggregate.get("opened_at")
    for lookup_name, lookup_key in direct_candidates:
        if not lookup_key:
            continue
        candidate = _take_fill_candidate(lookups.get(lookup_name, {}).get(lookup_key, []), used_fill_tokens, target_time=target_time)
        if candidate is not None:
            return candidate

    symbol = _normalize_optional_string(aggregate.get("symbol"))
    side = _normalize_side(aggregate.get("side"))
    if not symbol or not side:
        return None
    return _take_fill_candidate(
        lookups.get("symbol_side", {}).get((symbol.upper(), side), []),
        used_fill_tokens,
        target_time=target_time,
    )


def _take_fill_candidate(
    candidates: Sequence[dict[str, Any]],
    used_fill_tokens: set[tuple[int, int]],
    *,
    target_time: datetime | None,
) -> dict[str, Any] | None:
    available = [candidate for candidate in candidates if candidate["token"] not in used_fill_tokens]
    if not available:
        return None
    if target_time is None:
        chosen = max(available, key=lambda candidate: candidate["token"])
    else:
        chosen = min(
            available,
            key=lambda candidate: (
                _time_distance_seconds(_coerce_datetime(_first_present(candidate["row"].get("polled_at"), candidate["payload"].get("time"))), target_time),
                -candidate["token"][0],
                -candidate["token"][1],
            ),
        )
    used_fill_tokens.add(chosen["token"])
    return chosen


def _position_has_exit(aggregate: Mapping[str, Any]) -> bool:
    if aggregate.get("closed_at") is not None:
        return True
    if aggregate.get("pnl_cash") is not None:
        return True
    return bool(aggregate.get("statuses", set()) & _CLOSED_POSITION_STATUSES)


def _position_key(event: Mapping[str, Any], payload: Mapping[str, Any], index: int) -> str:
    broker_position_id = _normalize_optional_string(_first_present(event.get("broker_position_id"), payload.get("broker_position_id")))
    if broker_position_id:
        return f"broker:{broker_position_id}"
    deal_ticket = _normalize_optional_string(_first_present(payload.get("deal"), payload.get("deal_ticket")))
    if deal_ticket:
        return f"deal:{deal_ticket}"
    symbol = _normalize_optional_string(_first_present(event.get("symbol"), payload.get("symbol"))) or "unknown"
    side = _normalize_side(_first_present(event.get("side"), payload.get("side"))) or "unknown"
    opened_at = _normalize_optional_string(_first_present(event.get("opened_at"), payload.get("opened_at"), event.get("polled_at"))) or f"row-{index}"
    return f"synthetic:{symbol}:{side}:{opened_at}"


def _is_terminal_execution_event(event: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
    phase = _normalize_status(_first_present(event.get("phase"), payload.get("phase")))
    status = _normalize_status(_first_present(event.get("status"), payload.get("status")))
    if phase in _TERMINAL_EXECUTION_PHASES:
        return True
    if status == "PRECHECK_REJECTED":
        return True
    return not phase and status in _TERMINAL_EXECUTION_STATUSES


def _execution_token(event: Mapping[str, Any], index: int) -> tuple[int, int]:
    execution_id = _coerce_optional_float(event.get("execution_id"))
    return (int(execution_id) if execution_id is not None else index, index)


def _append_lookup(lookup: dict[Any, list[dict[str, Any]]], key: Any, candidate: dict[str, Any]) -> None:
    if key in (None, ""):
        return
    lookup.setdefault(key, []).append(candidate)


def _coerce_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row.get("payload_json")
    if payload is None:
        payload = row.get("payload")
    if payload is None:
        return {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    if isinstance(payload, Mapping):
        return dict(payload)
    return {}


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any, *, default: float = 0.0) -> float:
    coerced = _coerce_optional_float(value)
    return default if coerced is None else coerced


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _normalize_status(value: Any) -> str:
    return _normalize_optional_string(value, upper=True) or ""


def _normalize_side(value: Any) -> str:
    normalized = _normalize_optional_string(value)
    return "" if normalized is None else normalized.lower()


def _normalize_optional_string(value: Any, *, upper: bool = False) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized.upper() if upper else normalized


def _finalize_trade_times(
    entry_time: datetime | None,
    exit_time: datetime | None,
    *,
    fallback: datetime | None,
) -> tuple[datetime, datetime]:
    entry = entry_time or fallback
    exit_ = exit_time or fallback
    if entry is None and exit_ is None:
        entry = datetime(1970, 1, 1)
        exit_ = entry
    elif entry is None:
        entry = exit_
    elif exit_ is None:
        exit_ = entry
    assert entry is not None and exit_ is not None
    if entry.tzinfo is None and exit_.tzinfo is not None:
        entry = entry.replace(tzinfo=exit_.tzinfo)
    elif exit_.tzinfo is None and entry.tzinfo is not None:
        exit_ = exit_.replace(tzinfo=entry.tzinfo)
    return entry, exit_


def _time_distance_seconds(candidate: datetime | None, target: datetime) -> float:
    if candidate is None:
        return float("inf")
    candidate_time = candidate
    target_time = target
    if candidate_time.tzinfo is None and target_time.tzinfo is not None:
        candidate_time = candidate_time.replace(tzinfo=target_time.tzinfo)
    elif target_time.tzinfo is None and candidate_time.tzinfo is not None:
        target_time = target_time.replace(tzinfo=candidate_time.tzinfo)
    return abs((candidate_time - target_time).total_seconds())


def _format_count_warning(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _evaluate_absolute_promotion(
    challenger: PromotionCandidate,
    *,
    thresholds: PromotionGateThresholds,
) -> list[PromotionCheckResult]:
    oos = challenger.out_of_sample_summary
    quality = challenger.execution_quality
    return [
        PromotionCheckResult(
            name="oos_trade_count",
            passed=oos.total_trades >= thresholds.min_oos_trade_count,
            detail=(
                "challenger out-of-sample trade count meets minimum"
                if oos.total_trades >= thresholds.min_oos_trade_count
                else "challenger out-of-sample trade count below minimum"
            ),
            metric_value=oos.total_trades,
            threshold_value=thresholds.min_oos_trade_count,
        ),
        PromotionCheckResult(
            name="oos_expectancy",
            passed=oos.expectancy_r >= thresholds.min_oos_expectancy_r,
            detail=(
                "challenger out-of-sample expectancy meets minimum"
                if oos.expectancy_r >= thresholds.min_oos_expectancy_r
                else "challenger out-of-sample expectancy below minimum"
            ),
            metric_value=oos.expectancy_r,
            threshold_value=thresholds.min_oos_expectancy_r,
        ),
        PromotionCheckResult(
            name="oos_profit_factor",
            passed=oos.profit_factor >= thresholds.min_oos_profit_factor,
            detail=(
                "challenger out-of-sample profit factor meets minimum"
                if oos.profit_factor >= thresholds.min_oos_profit_factor
                else "challenger out-of-sample profit factor below minimum"
            ),
            metric_value=oos.profit_factor,
            threshold_value=thresholds.min_oos_profit_factor,
        ),
        PromotionCheckResult(
            name="oos_drawdown",
            passed=oos.max_drawdown_pct <= thresholds.max_oos_drawdown_pct,
            detail=(
                "challenger out-of-sample drawdown within maximum"
                if oos.max_drawdown_pct <= thresholds.max_oos_drawdown_pct
                else "challenger out-of-sample drawdown above maximum"
            ),
            metric_value=oos.max_drawdown_pct,
            threshold_value=thresholds.max_oos_drawdown_pct,
        ),
        PromotionCheckResult(
            name="average_entry_spread",
            passed=quality.average_entry_spread_points <= thresholds.max_average_entry_spread_points,
            detail=(
                "challenger quoted spread within maximum"
                if quality.average_entry_spread_points <= thresholds.max_average_entry_spread_points
                else "challenger quoted spread above maximum"
            ),
            metric_value=quality.average_entry_spread_points,
            threshold_value=thresholds.max_average_entry_spread_points,
        ),
        PromotionCheckResult(
            name="average_slippage",
            passed=quality.average_slippage_points <= thresholds.max_average_slippage_points,
            detail=(
                "challenger slippage within maximum"
                if quality.average_slippage_points <= thresholds.max_average_slippage_points
                else "challenger slippage above maximum"
            ),
            metric_value=quality.average_slippage_points,
            threshold_value=thresholds.max_average_slippage_points,
        ),
        PromotionCheckResult(
            name="reject_rate",
            passed=quality.reject_rate <= thresholds.max_reject_rate,
            detail=(
                "challenger reject rate within maximum"
                if quality.reject_rate <= thresholds.max_reject_rate
                else "challenger reject rate above maximum"
            ),
            metric_value=quality.reject_rate,
            threshold_value=thresholds.max_reject_rate,
        ),
    ]
