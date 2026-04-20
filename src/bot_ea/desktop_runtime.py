from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from typing import Any, Callable
from uuid import uuid4

from .codex_cli_engine import CodexCLIEngine
from .models import CapitalAllocation, RiskPolicy, TradingStyle
from .mt5_adapter import LiveMT5Adapter, TerminalStatusSnapshot
from .mt5_execution_runtime import MT5ExecutionRuntime
from .polling_runtime import MT5SnapshotProvider, PollingConfig, PollingRuntime
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
    codex_timeout_seconds: int = 20
    poll_interval_seconds: int = 30
    session_state: str = "desktop_runtime"
    news_state: str = "unknown"
    run_id: str | None = None


@dataclass(slots=True)
class DesktopRuntimeEvent:
    kind: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)


class DesktopRuntimeCoordinator:
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
        return bool(self._execution_runtime and self._execution_runtime.allow_live_orders)

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
                },
            }
            self._emit("mt5_ready", "mt5 ready", result)
            return result
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
        if self._execution_runtime is not None:
            self._execution_runtime.allow_live_orders = enabled
        self._emit(
            "live_toggle",
            "live orders enabled" if enabled else "live orders disabled",
            {"enabled": enabled, "run_id": self._run_id},
        )

    def _run_loop(self, config: DesktopRuntimeConfig) -> None:
        store: RuntimeStore | None = None
        adapter: Any | None = None
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
                    "poll_interval_seconds": config.poll_interval_seconds,
                    "stop_distance_points": config.stop_distance_points,
                },
            )
            adapter = self.adapter_factory()
            self._adapter = adapter
            execution_runtime = MT5ExecutionRuntime(
                adapter=adapter,
                allow_live_orders=self._desired_live_enabled,
            )
            self._execution_runtime = execution_runtime
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
                decision_engine=self.codex_engine_factory(
                    executable=config.codex_executable,
                    model=config.codex_model,
                    cwd=config.codex_cwd,
                    timeout_seconds=config.codex_timeout_seconds,
                ),
                execution_runtime=execution_runtime,
                risk_engine=self.risk_engine_factory(),
                stop_policy=self.stop_policy_factory(),
                config=PollingConfig(poll_interval_seconds=config.poll_interval_seconds),
            )
            self._emit(
                "runtime_started",
                "desktop runtime started",
                {
                    "run_id": config.run_id,
                    "db_path": config.db_path,
                    "live_enabled": execution_runtime.allow_live_orders,
                },
            )

            while self._stop_event is not None and not self._stop_event.is_set():
                result = runtime.run_cycle(run_id=config.run_id or "", performance=SessionPerformance())
                overview = store.fetch_latest_run_overview()
                health = store.fetch_execution_health_summary(limit=20)
                self._emit(
                    "runtime_cycle",
                    f"{result.action}: {result.detail}",
                    {
                        "run_id": config.run_id,
                        "action": result.action,
                        "detail": result.detail,
                        "halted": result.halted,
                        "overview": overview or {},
                        "health": health,
                        "live_enabled": execution_runtime.allow_live_orders,
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
            self._adapter = None
            self._shutdown_adapter(adapter)
            self._thread = None
            self._stop_event = None

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
    def _shutdown_adapter(adapter: Any | None) -> None:
        if adapter is None:
            return
        shutdown = getattr(adapter, "shutdown", None)
        if callable(shutdown):
            shutdown()
