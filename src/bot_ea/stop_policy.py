from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class StopReason(str, Enum):
    NONE = "none"
    PROFIT_TARGET = "profit_target"
    LOSS_LIMIT = "loss_limit"
    DRAWDOWN_LIMIT = "drawdown_limit"
    CONSECUTIVE_LOSSES = "consecutive_losses"
    MAX_TRADES = "max_trades"
    SESSION_TIMEOUT = "session_timeout"
    ALLOCATION_EXHAUSTED = "allocation_exhausted"


@dataclass(slots=True)
class StopPolicy:
    profit_target_cash: float | None = None
    loss_limit_cash: float | None = None
    max_drawdown_cash: float | None = None
    max_consecutive_losses: int | None = None
    max_trades: int | None = None
    max_runtime_minutes: float | None = None
    min_remaining_allocation_cash: float | None = None


@dataclass(slots=True)
class SessionPerformance:
    realized_pnl_cash: float = 0.0
    peak_pnl_cash: float = 0.0
    consecutive_losses: int = 0
    trades_count: int = 0
    elapsed_minutes: float = 0.0
    remaining_allocation_cash: float | None = None

    @property
    def drawdown_cash(self) -> float:
        return max(self.peak_pnl_cash - self.realized_pnl_cash, 0.0)


@dataclass(slots=True)
class StopDecision:
    should_halt: bool
    reason: StopReason
    detail: str
    hard_stop: bool = True
    metadata: dict[str, float | str] = field(default_factory=dict)


def evaluate_stop_policy(policy: StopPolicy, performance: SessionPerformance) -> StopDecision:
    if policy.profit_target_cash is not None and performance.realized_pnl_cash >= policy.profit_target_cash:
        return StopDecision(
            should_halt=True,
            reason=StopReason.PROFIT_TARGET,
            detail="profit target reached",
            metadata={"profit_target_cash": policy.profit_target_cash},
        )

    if policy.loss_limit_cash is not None and performance.realized_pnl_cash <= -abs(policy.loss_limit_cash):
        return StopDecision(
            should_halt=True,
            reason=StopReason.LOSS_LIMIT,
            detail="loss limit reached",
            metadata={"loss_limit_cash": policy.loss_limit_cash},
        )

    if policy.max_drawdown_cash is not None and performance.drawdown_cash >= policy.max_drawdown_cash:
        return StopDecision(
            should_halt=True,
            reason=StopReason.DRAWDOWN_LIMIT,
            detail="drawdown limit reached",
            metadata={"max_drawdown_cash": policy.max_drawdown_cash},
        )

    if policy.max_consecutive_losses is not None and performance.consecutive_losses >= policy.max_consecutive_losses:
        return StopDecision(
            should_halt=True,
            reason=StopReason.CONSECUTIVE_LOSSES,
            detail="consecutive loss cap reached",
            metadata={"max_consecutive_losses": policy.max_consecutive_losses},
        )

    if policy.max_trades is not None and performance.trades_count >= policy.max_trades:
        return StopDecision(
            should_halt=True,
            reason=StopReason.MAX_TRADES,
            detail="max trades reached",
            metadata={"max_trades": policy.max_trades},
        )

    if policy.max_runtime_minutes is not None and performance.elapsed_minutes >= policy.max_runtime_minutes:
        return StopDecision(
            should_halt=True,
            reason=StopReason.SESSION_TIMEOUT,
            detail="runtime session timeout reached",
            metadata={"max_runtime_minutes": policy.max_runtime_minutes},
        )

    if (
        policy.min_remaining_allocation_cash is not None
        and performance.remaining_allocation_cash is not None
        and performance.remaining_allocation_cash <= policy.min_remaining_allocation_cash
    ):
        return StopDecision(
            should_halt=True,
            reason=StopReason.ALLOCATION_EXHAUSTED,
            detail="remaining allocation too small to continue safely",
            metadata={"min_remaining_allocation_cash": policy.min_remaining_allocation_cash},
        )

    return StopDecision(should_halt=False, reason=StopReason.NONE, detail="stop policy not triggered", hard_stop=False)
