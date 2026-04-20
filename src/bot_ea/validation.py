from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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
    warnings: list[str] = field(default_factory=list)


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
            "",
            "## Warnings",
            warning_lines,
        ]
    )
