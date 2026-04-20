from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from .models import AccountSnapshot, CapitalAllocation, PositionSizeRequest, RiskPolicy, SymbolSnapshot, TradingStyle
from .risk_engine import RiskEngine
from .runtime_store import RuntimeStore
from .stop_policy import SessionPerformance, StopPolicy, StopReason, evaluate_stop_policy


class DecisionAction(str, Enum):
    NO_TRADE = "NO_TRADE"
    OPEN = "OPEN"
    ADD = "ADD"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"
    CANCEL_PENDING = "CANCEL_PENDING"
    HALT = "HALT"


@dataclass(slots=True)
class RuntimeSnapshot:
    symbol: str
    timeframe: str
    bid: float
    ask: float
    spread_points: float
    account: AccountSnapshot
    symbol_snapshot: SymbolSnapshot
    risk_policy: RiskPolicy
    trading_style: TradingStyle
    stop_distance_points: float
    capital_allocation: CapitalAllocation | None = None
    session_state: str = ""
    news_state: str = ""
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AIIntent:
    action: DecisionAction
    side: str | None = None
    confidence: float | None = None
    reason: str | None = None
    stop_distance_points: float | None = None
    entry_price: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PollingConfig:
    poll_interval_seconds: int = 30
    ai_timeout_seconds: int = 10
    fallback_mode: str = "NO_TRADE"
    stale_price_threshold_points: float = 0.0


@dataclass(slots=True)
class PollingCycleResult:
    cycle_id: int
    halted: bool
    detail: str
    action: str


class SnapshotProvider(Protocol):
    def get_snapshot(self) -> RuntimeSnapshot:
        raise NotImplementedError


class DecisionEngine(Protocol):
    def decide(self, snapshot: RuntimeSnapshot) -> AIIntent:
        raise NotImplementedError


class ExecutionRuntime(Protocol):
    def execute(self, intent: AIIntent, size_result) -> dict:
        raise NotImplementedError


class PollingRuntime:
    def __init__(
        self,
        *,
        store: RuntimeStore,
        snapshot_provider: SnapshotProvider,
        decision_engine: DecisionEngine,
        execution_runtime: ExecutionRuntime,
        risk_engine: RiskEngine,
        stop_policy: StopPolicy,
        config: PollingConfig | None = None,
    ) -> None:
        self.store = store
        self.snapshot_provider = snapshot_provider
        self.decision_engine = decision_engine
        self.execution_runtime = execution_runtime
        self.risk_engine = risk_engine
        self.stop_policy = stop_policy
        self.config = config or PollingConfig()

    def run_cycle(self, *, run_id: str, performance: SessionPerformance) -> PollingCycleResult:
        cycle_time = datetime.now(timezone.utc).isoformat()
        cycle_id = self.store.start_cycle(run_id=run_id, polled_at=cycle_time, status="STARTED")

        stop_decision = evaluate_stop_policy(self.stop_policy, performance)
        if stop_decision.should_halt:
            self.store.record_stop_event(
                run_id=run_id,
                cycle_id=cycle_id,
                stop_code=stop_decision.reason.value,
                severity="hard",
                detail=stop_decision.detail,
                payload=stop_decision.metadata,
            )
            self.store.update_run_status(run_id, status="HALTED", stop_reason=stop_decision.reason.value)
            return PollingCycleResult(cycle_id=cycle_id, halted=True, detail=stop_decision.detail, action=DecisionAction.HALT.value)

        snapshot = self.snapshot_provider.get_snapshot()
        self.store.record_market_snapshot(
            run_id=run_id,
            cycle_id=cycle_id,
            symbol=snapshot.symbol,
            timeframe=snapshot.timeframe,
            bid=snapshot.bid,
            ask=snapshot.ask,
            spread_points=snapshot.spread_points,
            equity=snapshot.account.equity,
            free_margin=snapshot.account.free_margin,
            session_state=snapshot.session_state,
            news_state=snapshot.news_state,
            payload=snapshot.context,
        )

        try:
            intent = self.decision_engine.decide(snapshot)
        except Exception as exc:  # pragma: no cover - covered by behavior test
            intent = AIIntent(
                action=DecisionAction.NO_TRADE if self.config.fallback_mode == "NO_TRADE" else DecisionAction.HALT,
                reason=f"decision engine failure: {exc}",
            )

        self.store.record_ai_decision(
            run_id=run_id,
            cycle_id=cycle_id,
            action=intent.action.value,
            side=intent.side,
            confidence=intent.confidence,
            reason=intent.reason,
            payload=intent.payload,
        )

        if intent.action in {DecisionAction.NO_TRADE, DecisionAction.HALT}:
            if intent.action is DecisionAction.HALT:
                self.store.record_stop_event(
                    run_id=run_id,
                    cycle_id=cycle_id,
                    stop_code=StopReason.SESSION_TIMEOUT.value,
                    severity="soft",
                    detail=intent.reason or "AI requested halt",
                )
                self.store.update_run_status(run_id, status="HALTED", stop_reason=StopReason.SESSION_TIMEOUT.value)
                return PollingCycleResult(cycle_id=cycle_id, halted=True, detail=intent.reason or "halted", action=intent.action.value)
            return PollingCycleResult(cycle_id=cycle_id, halted=False, detail=intent.reason or "no trade", action=intent.action.value)

        position_request = PositionSizeRequest(
            account=snapshot.account,
            symbol=snapshot.symbol_snapshot,
            policy=snapshot.risk_policy,
            stop_distance_points=intent.stop_distance_points or snapshot.stop_distance_points,
            trading_style=snapshot.trading_style,
            capital_allocation=snapshot.capital_allocation,
        )
        size_result = self.risk_engine.compute_position_size(position_request)
        self.store.record_risk_guard(
            run_id=run_id,
            cycle_id=cycle_id,
            allowed=size_result.accepted,
            mode=size_result.mode.value,
            rejection_reason=size_result.rejection_reason,
            normalized_volume=size_result.normalized_volume,
            risk_cash_budget=size_result.risk_cash_budget,
            payload={
                "capital_base_cash": size_result.capital_base_cash,
                "recommended_minimum_allocation_cash": size_result.recommended_minimum_allocation_cash,
                "warnings": size_result.warnings,
            },
        )

        if not size_result.accepted:
            return PollingCycleResult(
                cycle_id=cycle_id,
                halted=False,
                detail=size_result.rejection_reason or "risk guard rejected",
                action="RISK_REJECTED",
            )

        execution_result = self.execution_runtime.execute(intent, size_result)
        self.store.record_execution_event(
            run_id=run_id,
            cycle_id=cycle_id,
            event_type="ORDER_INTENT",
            status=str(execution_result.get("status", "UNKNOWN")),
            symbol=snapshot.symbol,
            side=intent.side,
            volume=size_result.normalized_volume,
            price=float(intent.entry_price or snapshot.ask if intent.side == "buy" else snapshot.bid),
            retcode=str(execution_result.get("retcode", "")),
            detail=str(execution_result.get("detail", "")),
            payload=execution_result,
        )
        return PollingCycleResult(cycle_id=cycle_id, halted=False, detail="cycle executed", action=intent.action.value)
