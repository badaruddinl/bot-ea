from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from types import SimpleNamespace
from typing import Any, Protocol
from uuid import uuid4

from .mt5_adapter import MT5Adapter
from .execution_guard import evaluate_execution_guards
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
    snapshot: dict[str, Any] = field(default_factory=dict)


class SnapshotProvider(Protocol):
    def get_snapshot(self) -> RuntimeSnapshot:
        raise NotImplementedError


class DecisionEngine(Protocol):
    def decide(self, snapshot: RuntimeSnapshot) -> AIIntent:
        raise NotImplementedError


class ExecutionRuntime(Protocol):
    def preflight(self, snapshot: RuntimeSnapshot, intent: AIIntent, size_result) -> dict:
        raise NotImplementedError

    def execute(self, snapshot: RuntimeSnapshot, intent: AIIntent, size_result, preflight_result: dict | None = None) -> dict:
        raise NotImplementedError


class MT5SnapshotProvider:
    """Concrete snapshot provider that hydrates RuntimeSnapshot from an MT5 adapter."""

    def __init__(
        self,
        *,
        adapter: MT5Adapter,
        symbol: str,
        timeframe: str,
        risk_policy: RiskPolicy,
        trading_style: TradingStyle,
        stop_distance_points: float,
        capital_allocation: CapitalAllocation | None = None,
        session_state: str = "",
        news_state: str = "",
        context: dict[str, Any] | None = None,
    ) -> None:
        self.adapter = adapter
        self.symbol = symbol
        self.timeframe = timeframe
        self.risk_policy = risk_policy
        self.trading_style = trading_style
        self.stop_distance_points = stop_distance_points
        self.capital_allocation = capital_allocation
        self.session_state = session_state
        self.news_state = news_state
        self.context = context or {}

    def get_snapshot(self) -> RuntimeSnapshot:
        account = self.adapter.load_account_snapshot()
        fingerprint_loader = getattr(self.adapter, "load_account_fingerprint", None)
        fingerprint = fingerprint_loader() if callable(fingerprint_loader) else None
        symbol_snapshot = self.adapter.load_symbol_snapshot(self.symbol)
        tick = self.adapter.load_price_tick(self.symbol)
        enriched_symbol = replace(
            symbol_snapshot,
            bid=tick.bid,
            ask=tick.ask,
            price=tick.ask or tick.bid or symbol_snapshot.price,
        )
        spread_points = 0.0
        if enriched_symbol.point and enriched_symbol.point > 0 and tick.ask and tick.bid:
            spread_points = (tick.ask - tick.bid) / enriched_symbol.point

        context = dict(self.context)
        context["tick_time"] = tick.time
        if fingerprint is not None:
            context["account_fingerprint"] = {
                "login": fingerprint.login,
                "server": fingerprint.server,
                "broker": fingerprint.broker,
                "is_live": fingerprint.is_live,
            }
        return RuntimeSnapshot(
            symbol=self.symbol,
            timeframe=self.timeframe,
            bid=tick.bid,
            ask=tick.ask,
            spread_points=spread_points,
            account=account,
            symbol_snapshot=enriched_symbol,
            risk_policy=self.risk_policy,
            trading_style=self.trading_style,
            stop_distance_points=self.stop_distance_points,
            capital_allocation=self.capital_allocation,
            session_state=self.session_state,
            news_state=self.news_state,
            context=context,
        )


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
        expected_account_fingerprint: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.snapshot_provider = snapshot_provider
        self.decision_engine = decision_engine
        self.execution_runtime = execution_runtime
        self.risk_engine = risk_engine
        self.stop_policy = stop_policy
        self.config = config or PollingConfig()
        self.expected_account_fingerprint = dict(expected_account_fingerprint or {}) or None

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
        snapshot_payload = self._snapshot_payload(snapshot)
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

        actual_fingerprint = snapshot.context.get("account_fingerprint")
        if self._account_fingerprint_changed(actual_fingerprint):
            detail = (
                "account fingerprint changed during runtime; review akun baru sebelum melanjutkan trading"
            )
            self.store.record_stop_event(
                run_id=run_id,
                cycle_id=cycle_id,
                stop_code="ACCOUNT_CHANGED",
                severity="hard",
                detail=detail,
                payload={
                    "expected_account_fingerprint": self.expected_account_fingerprint,
                    "actual_account_fingerprint": actual_fingerprint,
                },
            )
            self.store.update_run_status(run_id, status="HALTED", stop_reason="account_changed")
            return PollingCycleResult(
                cycle_id=cycle_id,
                halted=True,
                detail=detail,
                action=DecisionAction.HALT.value,
                snapshot=snapshot_payload,
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
                return PollingCycleResult(
                    cycle_id=cycle_id,
                    halted=True,
                    detail=intent.reason or "halted",
                    action=intent.action.value,
                    snapshot=snapshot_payload,
                )
            return PollingCycleResult(
                cycle_id=cycle_id,
                halted=False,
                detail=intent.reason or "no trade",
                action=intent.action.value,
                snapshot=snapshot_payload,
            )

        if intent.action in {DecisionAction.ADD, DecisionAction.REDUCE, DecisionAction.CLOSE, DecisionAction.CANCEL_PENDING}:
            size_result = self._lifecycle_size_result(snapshot, intent)
            self.store.record_risk_guard(
                run_id=run_id,
                cycle_id=cycle_id,
                allowed=True,
                mode="lifecycle",
                rejection_reason=None,
                normalized_volume=size_result.normalized_volume,
                risk_cash_budget=0.0,
                payload={"warnings": [], "lifecycle_action": intent.action.value},
            )
        else:
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
                    snapshot=snapshot_payload,
                )

        attempt_id = uuid4().hex
        intended_price = float(intent.entry_price or snapshot.ask if intent.side == "buy" else snapshot.bid)
        self.store.record_execution_event(
            run_id=run_id,
            cycle_id=cycle_id,
            attempt_id=attempt_id,
            event_type="ORDER_ATTEMPT",
            phase="INTENT",
            status="READY",
            symbol=snapshot.symbol,
            side=intent.side,
            volume=size_result.normalized_volume,
            price=intended_price,
            detail=intent.reason or "execution intent created",
            payload={"confidence": intent.confidence, "payload": intent.payload},
        )

        try:
            preflight_result = self.execution_runtime.preflight(snapshot, intent, size_result)
        except Exception as exc:
            preflight_result = {"status": "ERROR", "retcode": "", "detail": f"execution preflight failure: {exc}"}
        preflight_status = str(preflight_result.get("status", "UNKNOWN"))
        preflight_phase = "GUARD" if preflight_status == "GUARD_REJECTED" else "PRECHECK"
        self.store.record_execution_event(
            run_id=run_id,
            cycle_id=cycle_id,
            attempt_id=attempt_id,
            event_type="ORDER_ATTEMPT",
            phase=preflight_phase,
            status=preflight_status,
            symbol=snapshot.symbol,
            side=intent.side,
            volume=size_result.normalized_volume,
            price=intended_price,
            quoted_price=preflight_result.get("request", {}).get("price"),
            retcode=str(preflight_result.get("retcode", "")),
            detail=str(preflight_result.get("detail", "")),
            payload=preflight_result,
        )
        if preflight_status == "GUARD_REJECTED":
            return PollingCycleResult(
                cycle_id=cycle_id,
                halted=False,
                detail=str(preflight_result.get("detail", "execution guard rejected")),
                action="EXECUTION_GUARD_REJECTED",
                snapshot=snapshot_payload,
            )
        if preflight_status != "PRECHECK_OK":
            return PollingCycleResult(
                cycle_id=cycle_id,
                halted=False,
                detail=str(preflight_result.get("detail", "broker precheck rejected")),
                action="PRECHECK_REJECTED",
                snapshot=snapshot_payload,
            )

        try:
            execution_result = self.execution_runtime.execute(snapshot, intent, size_result, preflight_result=preflight_result)
        except Exception as exc:
            execution_result = {"status": "ERROR", "retcode": "", "detail": f"execution runtime failure: {exc}"}
        final_phase = "FILL" if execution_result.get("status") in {"FILLED", "DRY_RUN_OK", "REJECTED", "ERROR"} else "SEND"
        self.store.record_execution_event(
            run_id=run_id,
            cycle_id=cycle_id,
            attempt_id=attempt_id,
            event_type="ORDER_ATTEMPT",
            phase=final_phase,
            status=str(execution_result.get("status", "UNKNOWN")),
            symbol=snapshot.symbol,
            side=intent.side,
            volume=size_result.normalized_volume,
            price=intended_price,
            quoted_price=execution_result.get("quoted_price"),
            executed_price=execution_result.get("realized_price", execution_result.get("price")),
            slippage_points=execution_result.get("slippage_points"),
            fill_latency_ms=execution_result.get("fill_latency_ms"),
            order_ticket=None if execution_result.get("order") is None else str(execution_result.get("order")),
            deal_ticket=None if execution_result.get("deal") is None else str(execution_result.get("deal")),
            retcode=str(execution_result.get("retcode", "")),
            detail=str(execution_result.get("detail", "")),
            payload=execution_result,
        )
        if execution_result.get("status") == "APPROVAL_REQUIRED":
            return PollingCycleResult(
                cycle_id=cycle_id,
                halted=False,
                detail=str(execution_result.get("detail", "operator approval required")),
                action="APPROVAL_REQUIRED",
                snapshot=snapshot_payload,
            )
        if (
            intent.action is not DecisionAction.CANCEL_PENDING
            and execution_result.get("status") == "FILLED"
            and execution_result.get("order") is not None
        ):
            position_status = "OPENED"
            entry_price = execution_result.get("realized_price", execution_result.get("price"))
            exit_price = None
            opened_at = datetime.now(timezone.utc).isoformat()
            closed_at = None
            realized_pnl_cash = None
            if intent.action is DecisionAction.CLOSE:
                position_status = "CLOSED"
                entry_price = None
                exit_price = execution_result.get("realized_price", execution_result.get("price"))
                opened_at = None
                closed_at = datetime.now(timezone.utc).isoformat()
            elif intent.action is DecisionAction.REDUCE:
                position_status = "REDUCED"
                entry_price = None
                opened_at = None
            elif intent.action is DecisionAction.ADD:
                position_status = "ADDED"
            self.store.record_position_event(
                run_id=run_id,
                cycle_id=cycle_id,
                broker_position_id=str(
                    execution_result.get("position_ticket")
                    or execution_result.get("order")
                ),
                symbol=snapshot.symbol,
                side=intent.side,
                volume=execution_result.get("volume", size_result.normalized_volume),
                status=position_status,
                entry_price=entry_price,
                exit_price=exit_price,
                opened_at=opened_at,
                closed_at=closed_at,
                realized_pnl_cash=realized_pnl_cash,
                commission_cash=execution_result.get("commission_cash"),
                swap_cash=execution_result.get("swap_cash"),
                payload={
                    "deal": execution_result.get("deal"),
                    "quoted_price": execution_result.get("quoted_price"),
                    "slippage_points": execution_result.get("slippage_points"),
                    "fill_latency_ms": execution_result.get("fill_latency_ms"),
                    "commission_cash": execution_result.get("commission_cash"),
                    "swap_cash": execution_result.get("swap_cash"),
                },
            )
        return PollingCycleResult(
            cycle_id=cycle_id,
            halted=False,
            detail="cycle executed",
            action=intent.action.value,
            snapshot=snapshot_payload,
        )

    @staticmethod
    def _snapshot_payload(snapshot: RuntimeSnapshot) -> dict[str, Any]:
        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "bid": snapshot.bid,
            "ask": snapshot.ask,
            "spread_points": snapshot.spread_points,
            "tick_time": snapshot.context.get("tick_time"),
            "equity": snapshot.account.equity,
            "free_margin": snapshot.account.free_margin,
            "trade_mode": snapshot.symbol_snapshot.trade_mode,
            "execution_mode": snapshot.symbol_snapshot.execution_mode,
            "filling_mode": snapshot.symbol_snapshot.filling_mode,
            "account_fingerprint": snapshot.context.get("account_fingerprint"),
        }

    def _account_fingerprint_changed(self, actual_fingerprint: Any) -> bool:
        if not self.expected_account_fingerprint or not isinstance(actual_fingerprint, dict):
            return False
        expected = {
            "login": str(self.expected_account_fingerprint.get("login") or ""),
            "server": str(self.expected_account_fingerprint.get("server") or ""),
            "broker": str(self.expected_account_fingerprint.get("broker") or ""),
        }
        actual = {
            "login": str(actual_fingerprint.get("login") or ""),
            "server": str(actual_fingerprint.get("server") or ""),
            "broker": str(actual_fingerprint.get("broker") or ""),
        }
        return actual != expected

    @staticmethod
    def _lifecycle_size_result(snapshot: RuntimeSnapshot, intent: AIIntent):
        volume = float(intent.payload.get("volume") or intent.payload.get("position_volume") or 0.0)
        if intent.action is DecisionAction.CANCEL_PENDING:
            volume = 0.0
        elif intent.action is DecisionAction.ADD and volume <= 0:
            volume = 0.01
        return SimpleNamespace(
            accepted=True,
            mode="lifecycle",
            capital_base_cash=snapshot.account.equity,
            recommended_minimum_allocation_cash=0.0,
            effective_risk_pct=0.0,
            risk_cash_budget=0.0,
            normalized_volume=volume,
            estimated_loss_cash=0.0,
            stop_distance_points=float(intent.stop_distance_points or snapshot.stop_distance_points),
            rejection_reason=None,
            warnings=[],
        )
