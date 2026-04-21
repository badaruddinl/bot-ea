from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic
from typing import Any, Callable
from uuid import uuid4

from .codex_cli_engine import CodexCLIEngine, CodexContractError, CodexTimeoutError
from .models import CapitalAllocation, RiskPolicy, TradingStyle
from .mt5_adapter import LiveMT5Adapter, TerminalStatusSnapshot
from .mt5_execution_runtime import MT5ExecutionRuntime
from .polling_runtime import AIIntent, DecisionAction, MT5SnapshotProvider, PollingConfig, PollingRuntime
from .risk_engine import RiskEngine
from .runtime_store import RuntimeStore
from .stop_policy import SessionPerformance, StopPolicy


@dataclass(slots=True)
class DesktopRuntimeConfig:
    symbol: str
    timeframe: str
    trading_style: TradingStyle
    stop_distance_points: float
    capital_allocation: CapitalAllocation
    db_path: str
    codex_executable: str = "codex"
    codex_model: str | None = None
    codex_cwd: str | None = None
    codex_timeout_seconds: int = 60
    codex_timeout_cooldown_seconds: int = 30
    poll_interval_seconds: int = 30
    session_state: str = "desktop_runtime"
    news_state: str = "unknown"
    run_id: str | None = None
    ai_workspace_path: str | None = None
    ai_documents_path: str | None = None
    ai_context_path: str | None = None
    resume_prompt_path: str | None = None
    behavior_profile_path: str | None = None
    account_fingerprint: dict[str, Any] | None = None


@dataclass(slots=True)
class DesktopRuntimeEvent:
    kind: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PendingApproval:
    approval_key: str
    run_id: str
    symbol: str
    action: str
    side: str | None
    volume: float
    price: float
    reason: str
    created_at: str
    detail: str
    request: dict[str, Any] = field(default_factory=dict)


class SupervisedExecutionRuntime:
    def __init__(
        self,
        *,
        dry_runtime: MT5ExecutionRuntime,
        live_runtime: MT5ExecutionRuntime,
        event_callback: Callable[[str, str, dict[str, Any]], None],
    ) -> None:
        self.dry_runtime = dry_runtime
        self.live_runtime = live_runtime
        self.event_callback = event_callback
        self.live_requested = False
        self.pending_approval: PendingApproval | None = None
        self._armed_approval_key: str | None = None
        self.run_id: str = ""

    @property
    def live_enabled(self) -> bool:
        return self.live_requested

    def set_live_enabled(self, enabled: bool) -> None:
        self.live_requested = enabled
        if not enabled:
            self._armed_approval_key = None
            self.pending_approval = None

    def approve_pending(self) -> PendingApproval:
        if self.pending_approval is None:
            raise RuntimeError("no pending approval")
        self._armed_approval_key = self.pending_approval.approval_key
        self.event_callback(
            "approval_armed",
            "pending live order approved; next matching cycle may submit",
            asdict(self.pending_approval),
        )
        return self.pending_approval

    def reject_pending(self) -> PendingApproval:
        if self.pending_approval is None:
            raise RuntimeError("no pending approval")
        rejected = self.pending_approval
        self.pending_approval = None
        self._armed_approval_key = None
        self.event_callback(
            "approval_rejected",
            "pending live order rejected by operator",
            asdict(rejected),
        )
        return rejected

    def preflight(self, snapshot, intent, size_result) -> dict:
        return self.live_runtime.preflight(snapshot, intent, size_result)

    def execute(self, snapshot, intent, size_result, preflight_result: dict | None = None) -> dict:
        preflight = preflight_result or self.preflight(snapshot, intent, size_result)
        if preflight.get("status") != "PRECHECK_OK":
            return preflight
        if not self.live_requested:
            return self.dry_runtime.execute(snapshot, intent, size_result, preflight_result=preflight)

        approval_key = self._build_approval_key(intent=intent, request=preflight.get("request", {}), volume=size_result.normalized_volume)
        if self._armed_approval_key == approval_key:
            self._armed_approval_key = None
            self.pending_approval = None
            return self.live_runtime.execute(snapshot, intent, size_result, preflight_result=preflight)

        pending = PendingApproval(
            approval_key=approval_key,
            run_id=self.run_id,
            symbol=str(preflight.get("request", {}).get("symbol") or snapshot.symbol),
            action=str(intent.action.value),
            side=intent.side,
            volume=float(size_result.normalized_volume),
            price=float(preflight.get("request", {}).get("price") or 0.0),
            reason=str(intent.reason or ""),
            created_at=datetime.now(timezone.utc).isoformat(),
            detail="operator approval required before live order",
            request=dict(preflight.get("request", {})),
        )
        self.pending_approval = pending
        payload = asdict(pending)
        self.event_callback("approval_pending", "live order awaiting operator approval", payload)
        return {
            "status": "APPROVAL_REQUIRED",
            "detail": pending.detail,
            "request": pending.request,
            "approval_key": pending.approval_key,
            "quoted_price": pending.price,
            "live_order_submitted": False,
        }

    @staticmethod
    def _build_approval_key(*, intent, request: dict[str, Any], volume: float) -> str:
        symbol = str(request.get("symbol") or "")
        side = str(intent.side or "")
        price = float(request.get("price") or 0.0)
        return "|".join(
            [
                str(intent.action.value),
                symbol,
                side,
                f"{volume:.6f}",
                f"{price:.6f}",
            ]
        )


class TimeoutTolerantDecisionEngine:
    def __init__(
        self,
        *,
        engine: Any,
        event_callback: Callable[[str, str, dict[str, Any]], None],
        cooldown_seconds: int,
    ) -> None:
        self.engine = engine
        self.event_callback = event_callback
        self.cooldown_seconds = max(int(cooldown_seconds), 0)
        self._cooldown_until = 0.0

    def decide(self, snapshot) -> AIIntent:
        remaining = self._cooldown_remaining_seconds()
        if remaining > 0:
            return AIIntent(
                action=DecisionAction.NO_TRADE,
                side=None,
                reason=f"codex timeout cooldown active for {remaining}s",
                stop_distance_points=snapshot.stop_distance_points,
                payload={"timeout_cooldown_seconds_remaining": remaining},
            )
        try:
            return self.engine.decide(snapshot)
        except CodexTimeoutError as exc:
            if self.cooldown_seconds > 0:
                self._cooldown_until = monotonic() + self.cooldown_seconds
            self.event_callback(
                "codex_timeout",
                f"codex decision timed out; using NO_TRADE fallback for {self.cooldown_seconds}s",
                {"error": str(exc), "cooldown_seconds": self.cooldown_seconds},
            )
            return AIIntent(
                action=DecisionAction.NO_TRADE,
                side=None,
                reason=f"codex timeout fallback: {exc}",
                stop_distance_points=snapshot.stop_distance_points,
                payload={"error": str(exc), "cooldown_seconds": self.cooldown_seconds},
            )
        except CodexContractError as exc:
            self.event_callback(
                "codex_contract_invalid",
                "codex returned an invalid response contract; using NO_TRADE fallback",
                {"error": str(exc), "raw_response": getattr(exc, "raw_response", None)},
            )
            return AIIntent(
                action=DecisionAction.NO_TRADE,
                side=None,
                reason=f"codex contract invalid: {exc}",
                stop_distance_points=snapshot.stop_distance_points,
                payload={"error": str(exc), "raw_response": getattr(exc, "raw_response", None)},
            )

    def _cooldown_remaining_seconds(self) -> int:
        remaining = self._cooldown_until - monotonic()
        return int(remaining) if remaining.is_integer() else int(remaining) + (1 if remaining > 0 else 0)


class DesktopRuntimeCoordinator:
    _MAX_MT5_IPC_RECOVERY_ATTEMPTS = 2

    def __init__(
        self,
        *,
        adapter_factory: Callable[[], Any] = LiveMT5Adapter,
        codex_engine_factory: Callable[..., Any] = CodexCLIEngine,
        runtime_store_factory: Callable[[str], RuntimeStore] = RuntimeStore,
        risk_engine_factory: Callable[[], RiskEngine] = RiskEngine,
        stop_policy_factory: Callable[[], StopPolicy] = StopPolicy,
        risk_policy: RiskPolicy | None = None,
    ) -> None:
        self.adapter_factory = adapter_factory
        self.codex_engine_factory = codex_engine_factory
        self.runtime_store_factory = runtime_store_factory
        self.risk_engine_factory = risk_engine_factory
        self.stop_policy_factory = stop_policy_factory
        self.risk_policy = risk_policy or RiskPolicy(
            base_risk_pct=1.0,
            max_total_open_risk_pct=2.0,
            daily_loss_limit_pct=3.0,
        )
        self._events: Queue[DesktopRuntimeEvent] = Queue()
        self._stop_event: Event | None = None
        self._thread: Thread | None = None
        self._execution_runtime: MT5ExecutionRuntime | None = None
        self._supervised_runtime: SupervisedExecutionRuntime | None = None
        self._adapter: Any | None = None
        self._run_id: str | None = None
        self._db_path: str | None = None
        self._desired_live_enabled = False

    @property
    def run_id(self) -> str | None:
        return self._run_id

    @property
    def db_path(self) -> str | None:
        return self._db_path

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def live_enabled(self) -> bool:
        return bool(self._supervised_runtime and self._supervised_runtime.live_enabled)

    @property
    def pending_approval(self) -> PendingApproval | None:
        return None if self._supervised_runtime is None else self._supervised_runtime.pending_approval

    def drain_events(self) -> list[DesktopRuntimeEvent]:
        events: list[DesktopRuntimeEvent] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except Empty:
                return events

    def probe_codex(self, *, executable: str, model: str | None = None, cwd: str | None = None, timeout_seconds: int = 20) -> str:
        engine = self.codex_engine_factory(
            executable=executable,
            model=model,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )
        version = engine.probe()
        self._emit("codex_ready", f"codex ready: {version}", {"version": version})
        return version

    def probe_mt5(
        self,
        *,
        symbol: str,
        timeframe: str,
        trading_style: TradingStyle,
        stop_distance_points: float,
        capital_allocation: CapitalAllocation,
    ) -> dict[str, Any]:
        adapter = self.adapter_factory()
        try:
            terminal = adapter.load_terminal_status()
            provider = self._build_provider(
                adapter=adapter,
                symbol=symbol,
                timeframe=timeframe,
                trading_style=trading_style,
                stop_distance_points=stop_distance_points,
                capital_allocation=capital_allocation,
            )
            snapshot = provider.get_snapshot()
            result = {
                "terminal": asdict(terminal),
                "snapshot": {
                    "symbol": snapshot.symbol,
                    "bid": snapshot.bid,
                    "ask": snapshot.ask,
                    "spread_points": snapshot.spread_points,
                    "equity": snapshot.account.equity,
                    "free_margin": snapshot.account.free_margin,
                    "account_trade_allowed": snapshot.account.trade_allowed,
                    "account_trade_expert": snapshot.account.trade_expert,
                    "symbol_trade_allowed": snapshot.symbol_snapshot.trade_allowed,
                    "stops_level_points": snapshot.symbol_snapshot.stops_level_points,
                    "freeze_level_points": snapshot.symbol_snapshot.freeze_level_points,
                },
                "symbols": adapter.load_available_symbols(),
            }
            self._emit("mt5_ready", "mt5 ready", result)
            return result
        finally:
            self._shutdown_adapter(adapter)

    def probe_mt5_process(self) -> dict[str, Any]:
        adapter = self.adapter_factory()
        try:
            terminal = adapter.load_terminal_status()
            return {
                "running": bool(terminal.connected),
                "detail": "MetaTrader 5 terdeteksi dan bisa diakses.",
                "terminal": asdict(terminal),
            }
        finally:
            self._shutdown_adapter(adapter)

    def probe_mt5_session(self) -> dict[str, Any]:
        adapter = self.adapter_factory()
        try:
            terminal = adapter.load_terminal_status()
            if not terminal.connected:
                raise RuntimeError("Terminal MT5 belum terhubung.")
            detail = "Sesi MT5 aktif dan data terminal bisa dibaca."
            return {
                "connected": bool(terminal.connected),
                "detail": detail,
                "terminal": asdict(terminal),
            }
        finally:
            self._shutdown_adapter(adapter)

    def probe_account_fingerprint(self) -> dict[str, Any]:
        adapter = self.adapter_factory()
        try:
            fingerprint = adapter.load_account_fingerprint()
            if not fingerprint.login or not fingerprint.server:
                raise RuntimeError("Akun MT5 belum login atau fingerprint belum lengkap.")
            result = asdict(fingerprint)
            result["detail"] = (
                f"Akun aktif {fingerprint.login} pada server {fingerprint.server} "
                f"({fingerprint.broker or 'broker tidak diketahui'})."
            )
            return result
        finally:
            self._shutdown_adapter(adapter)

    def probe_symbol_baseline(
        self,
        *,
        symbol: str,
        timeframe: str,
        trading_style: TradingStyle,
        stop_distance_points: float,
        capital_allocation: CapitalAllocation,
    ) -> dict[str, Any]:
        adapter = self.adapter_factory()
        try:
            provider = self._build_provider(
                adapter=adapter,
                symbol=symbol,
                timeframe=timeframe,
                trading_style=trading_style,
                stop_distance_points=stop_distance_points,
                capital_allocation=capital_allocation,
            )
            snapshot = provider.get_snapshot()
            return {
                "symbol": snapshot.symbol,
                "detail": f"Simbol dasar {snapshot.symbol} siap dibaca.",
                "snapshot": {
                    "symbol": snapshot.symbol,
                    "bid": snapshot.bid,
                    "ask": snapshot.ask,
                    "spread_points": snapshot.spread_points,
                    "equity": snapshot.account.equity,
                    "free_margin": snapshot.account.free_margin,
                    "symbol_trade_allowed": snapshot.symbol_snapshot.trade_allowed,
                    "stops_level_points": snapshot.symbol_snapshot.stops_level_points,
                    "freeze_level_points": snapshot.symbol_snapshot.freeze_level_points,
                    "trade_mode": snapshot.symbol_snapshot.trade_mode,
                    "execution_mode": snapshot.symbol_snapshot.execution_mode,
                    "filling_mode": snapshot.symbol_snapshot.filling_mode,
                    "account_fingerprint": snapshot.context.get("account_fingerprint"),
                },
                "symbols": adapter.load_available_symbols(),
            }
        finally:
            self._shutdown_adapter(adapter)

    def start(self, config: DesktopRuntimeConfig) -> str:
        if self.is_running:
            raise RuntimeError("desktop runtime already running")
        config.run_id = config.run_id or f"desktop-{uuid4().hex[:12]}"
        self._run_id = config.run_id
        self._db_path = config.db_path
        self._stop_event = Event()
        self._thread = Thread(target=self._run_loop, args=(config,), daemon=True, name="bot-ea-desktop-runtime")
        self._thread.start()
        return config.run_id

    def stop(self, *, join_timeout: float = 5.0) -> None:
        if self._stop_event is None:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=join_timeout)

    def set_live_enabled(self, enabled: bool) -> None:
        self._desired_live_enabled = enabled
        if self._supervised_runtime is not None:
            self._supervised_runtime.set_live_enabled(enabled)
        self._emit(
            "live_toggle",
            "live orders enabled" if enabled else "live orders disabled",
            {"enabled": enabled, "run_id": self._run_id},
        )

    def approve_pending_live_order(self) -> PendingApproval:
        if self._supervised_runtime is None:
            raise RuntimeError("desktop runtime is not active")
        pending = self._supervised_runtime.approve_pending()
        self._emit("approval_status", "operator approved pending live order", asdict(pending))
        return pending

    def reject_pending_live_order(self) -> PendingApproval:
        if self._supervised_runtime is None:
            raise RuntimeError("desktop runtime is not active")
        pending = self._supervised_runtime.reject_pending()
        self._emit("approval_status", "operator rejected pending live order", asdict(pending))
        return pending

    def _run_loop(self, config: DesktopRuntimeConfig) -> None:
        store: RuntimeStore | None = None
        adapter: Any | None = None
        runtime: PollingRuntime | None = None
        halted = False
        try:
            store = self.runtime_store_factory(config.db_path)
            store.initialize()
            started_at = datetime.now(timezone.utc).isoformat()
            store.start_run(
                run_id=config.run_id or "",
                started_at=started_at,
                status="RUNNING",
                symbol=config.symbol,
                timeframe=config.timeframe,
                trading_style=config.trading_style.value,
                allocation_mode=config.capital_allocation.mode.value,
                allocation_value=config.capital_allocation.value,
                config={
                    "codex_executable": config.codex_executable,
                    "codex_model": config.codex_model,
                    "codex_cwd": config.codex_cwd,
                    "codex_timeout_seconds": config.codex_timeout_seconds,
                    "codex_timeout_cooldown_seconds": config.codex_timeout_cooldown_seconds,
                    "poll_interval_seconds": config.poll_interval_seconds,
                    "stop_distance_points": config.stop_distance_points,
                    "ai_workspace_path": config.ai_workspace_path,
                    "ai_documents_path": config.ai_documents_path,
                    "ai_context_path": config.ai_context_path,
                    "resume_prompt_path": config.resume_prompt_path,
                    "behavior_profile_path": config.behavior_profile_path,
                    "account_fingerprint": config.account_fingerprint,
                },
            )
            adapter, runtime = self._build_runtime(config, store)
            self._emit(
                "runtime_started",
                "desktop runtime started",
                {
                    "run_id": config.run_id,
                    "db_path": config.db_path,
                    "live_enabled": bool(self._supervised_runtime and self._supervised_runtime.live_enabled),
                },
            )

            ipc_recovery_attempts = 0
            while self._stop_event is not None and not self._stop_event.is_set():
                assert runtime is not None
                try:
                    result = runtime.run_cycle(run_id=config.run_id or "", performance=SessionPerformance())
                except Exception as exc:
                    if self._is_transient_mt5_ipc_error(exc) and ipc_recovery_attempts < self._MAX_MT5_IPC_RECOVERY_ATTEMPTS:
                        ipc_recovery_attempts += 1
                        if config.run_id is not None:
                            store.record_log(
                                run_id=config.run_id,
                                cycle_id=None,
                                level="WARNING",
                                message=(
                                    "transient MT5 IPC failure detected; "
                                    f"reconnecting attempt {ipc_recovery_attempts}/{self._MAX_MT5_IPC_RECOVERY_ATTEMPTS}: {exc}"
                                ),
                            )
                        self._emit(
                            "runtime_recovering",
                            (
                                "transient MT5 IPC connection lost; "
                                f"retrying ({ipc_recovery_attempts}/{self._MAX_MT5_IPC_RECOVERY_ATTEMPTS})"
                            ),
                            {"run_id": config.run_id, "error": str(exc), "db_path": config.db_path},
                        )
                        adapter, runtime = self._reconnect_runtime(config, store, adapter)
                        continue
                    raise
                ipc_recovery_attempts = 0
                overview = store.fetch_latest_run_overview()
                health = store.fetch_execution_health_summary(run_id=config.run_id, limit=20)
                supervised_runtime = self._supervised_runtime
                self._emit(
                    "runtime_cycle",
                    f"{result.action}: {result.detail}",
                    {
                        "run_id": config.run_id,
                        "action": result.action,
                        "detail": result.detail,
                        "halted": result.halted,
                        "snapshot": result.snapshot,
                        "overview": overview or {},
                        "health": health,
                        "live_enabled": supervised_runtime.live_enabled,
                    },
                )
                if result.halted:
                    halted = True
                    break
                if self._stop_event.wait(config.poll_interval_seconds):
                    break

            if halted:
                self._emit(
                    "runtime_halted",
                    "desktop runtime halted by stop policy",
                    {"run_id": config.run_id, "db_path": config.db_path},
                )
            elif store is not None:
                store.update_run_status(config.run_id or "", status="STOPPED", stop_reason="operator_stop")
                self._emit(
                    "runtime_stopped",
                    "desktop runtime stopped",
                    {"run_id": config.run_id, "db_path": config.db_path},
                )
        except Exception as exc:
            if store is not None and config.run_id is not None:
                store.record_log(
                    run_id=config.run_id,
                    cycle_id=None,
                    level="ERROR",
                    message=f"desktop runtime failure: {exc}",
                )
                store.update_run_status(config.run_id, status="ERROR", stop_reason="runtime_failure")
            self._emit(
                "runtime_error",
                f"desktop runtime error: {exc}",
                {"run_id": config.run_id, "error": str(exc), "db_path": config.db_path},
            )
        finally:
            self._execution_runtime = None
            self._supervised_runtime = None
            self._adapter = None
            self._shutdown_adapter(adapter)
            self._thread = None
            self._stop_event = None

    def _build_runtime(self, config: DesktopRuntimeConfig, store: RuntimeStore) -> tuple[Any, PollingRuntime]:
        adapter = self.adapter_factory()
        self._adapter = adapter
        live_execution_runtime = MT5ExecutionRuntime(
            adapter=adapter,
            allow_live_orders=True,
        )
        dry_execution_runtime = MT5ExecutionRuntime(
            adapter=adapter,
            allow_live_orders=False,
        )
        supervised_runtime = SupervisedExecutionRuntime(
            dry_runtime=dry_execution_runtime,
            live_runtime=live_execution_runtime,
            event_callback=self._emit,
        )
        supervised_runtime.run_id = config.run_id or ""
        supervised_runtime.set_live_enabled(self._desired_live_enabled)
        self._execution_runtime = live_execution_runtime
        self._supervised_runtime = supervised_runtime
        decision_engine = TimeoutTolerantDecisionEngine(
            engine=self.codex_engine_factory(
                executable=config.codex_executable,
                model=config.codex_model,
                cwd=config.codex_cwd,
                timeout_seconds=config.codex_timeout_seconds,
            ),
            event_callback=self._emit,
            cooldown_seconds=config.codex_timeout_cooldown_seconds,
        )
        runtime = PollingRuntime(
            store=store,
            snapshot_provider=self._build_provider(
                adapter=adapter,
                symbol=config.symbol,
                timeframe=config.timeframe,
                trading_style=config.trading_style,
                stop_distance_points=config.stop_distance_points,
                capital_allocation=config.capital_allocation,
                session_state=config.session_state,
                news_state=config.news_state,
            ),
            decision_engine=decision_engine,
            execution_runtime=supervised_runtime,
            risk_engine=self.risk_engine_factory(),
            stop_policy=self.stop_policy_factory(),
            config=PollingConfig(poll_interval_seconds=config.poll_interval_seconds),
        )
        return adapter, runtime

    def _reconnect_runtime(self, config: DesktopRuntimeConfig, store: RuntimeStore, adapter: Any) -> tuple[Any, PollingRuntime]:
        self._shutdown_adapter(adapter)
        return self._build_runtime(config, store)

    def _build_provider(
        self,
        *,
        adapter: Any,
        symbol: str,
        timeframe: str,
        trading_style: TradingStyle,
        stop_distance_points: float,
        capital_allocation: CapitalAllocation,
        session_state: str = "desktop_runtime",
        news_state: str = "unknown",
    ) -> MT5SnapshotProvider:
        return MT5SnapshotProvider(
            adapter=adapter,
            symbol=symbol,
            timeframe=timeframe,
            risk_policy=self.risk_policy,
            trading_style=trading_style,
            stop_distance_points=stop_distance_points,
            capital_allocation=capital_allocation,
            session_state=session_state,
            news_state=news_state,
            context={"source": "desktop_gui"},
        )

    def _emit(self, kind: str, message: str, payload: dict[str, Any] | None = None) -> None:
        self._events.put(DesktopRuntimeEvent(kind=kind, message=message, payload=payload or {}))

    @staticmethod
    def _is_transient_mt5_ipc_error(exc: Exception) -> bool:
        message = " ".join(str(exc).split()).lower()
        return "no ipc connection" in message and "account_info() failed" in message

    @staticmethod
    def _shutdown_adapter(adapter: Any | None) -> None:
        if adapter is None:
            return
        shutdown = getattr(adapter, "shutdown", None)
        if callable(shutdown):
            shutdown()
