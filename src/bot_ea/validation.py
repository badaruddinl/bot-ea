from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json


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
        decided_at=datetime.utcnow(),
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
