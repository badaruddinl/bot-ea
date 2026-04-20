from __future__ import annotations

import asyncio
import contextlib
import json
import queue
import threading
import uuid
from pathlib import Path
from typing import Any

import websockets
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .desktop_runtime import DesktopRuntimeConfig, DesktopRuntimeCoordinator
from .models import CapitalAllocation, CapitalAllocationMode, RiskPolicy, TradingStyle
from .mt5_adapter import LiveMT5Adapter
from .risk_engine import RiskEngine
from .websocket_service import BotEaWebSocketService


class QtBotEaWebSocketService(BotEaWebSocketService):
    def _runtime_config(self, params: dict[str, Any]) -> DesktopRuntimeConfig:
        poll_interval = int(float(params.get("poll_interval_seconds") or 30))
        return DesktopRuntimeConfig(
            symbol=str(params["symbol"]),
            timeframe=str(params["timeframe"]),
            trading_style=TradingStyle(str(params["trading_style"])),
            stop_distance_points=float(params["stop_distance_points"]),
            capital_allocation=CapitalAllocation(
                mode=CapitalAllocationMode(str(params["capital_mode"])),
                value=float(params["capital_value"]),
            ),
            db_path=str(Path(str(params["db_path"])).expanduser()),
            codex_executable=str(params.get("codex_command") or "codex"),
            codex_model=params.get("model"),
            codex_cwd=params.get("codex_cwd"),
            codex_timeout_seconds=int(params.get("codex_timeout_seconds") or 60),
            poll_interval_seconds=poll_interval,
            session_state=str(params.get("session_state") or "desktop_runtime"),
            news_state=str(params.get("news_state") or "unknown"),
            run_id=str(params["run_id"]) if params.get("run_id") else None,
        )


class QtBotEaLocalServiceRunner:
    def __init__(self, service: BotEaWebSocketService) -> None:
        self._service = service
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = threading.Event()
        self._stop_requested = threading.Event()
        self._start_error: Exception | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, timeout: float = 5.0) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._started.clear()
        self._stop_requested.clear()
        self._start_error = None
        self._thread = threading.Thread(target=self._run, name="bot-ea-qt-service", daemon=True)
        self._thread.start()
        if not self._started.wait(timeout):
            raise RuntimeError("websocket service start timed out")
        if self._start_error is not None:
            raise self._start_error

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_requested.set()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None
        self._loop = None

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)

        async def serve() -> None:
            await self._service.start()
            self._started.set()
            try:
                while not self._stop_requested.is_set():
                    await asyncio.sleep(0.1)
            finally:
                await self._service.stop()

        try:
            loop.run_until_complete(serve())
        except Exception as exc:  # pragma: no cover - startup failures are surfaced to caller
            self._start_error = exc
            self._started.set()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            with contextlib.suppress(Exception):
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()


class QtBotEaWebSocketClient:
    def __init__(self, url: str) -> None:
        self._url = url
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._pending: dict[str, asyncio.Future] = {}
        self._connect_lock = threading.Lock()
        self._websocket = None
        self._reader_task: asyncio.Task | None = None
        self._service_ready_future: asyncio.Future | None = None
        self._connected = False
        self._service_info: dict[str, Any] | None = None

    def connect(self, url: str | None = None, timeout: float = 5.0) -> dict[str, Any]:
        if url is not None:
            self._url = url
        self._ensure_thread()
        with self._connect_lock:
            future = asyncio.run_coroutine_threadsafe(self._connect_async(timeout), self._loop)
            return future.result(timeout + 1)

    def request(self, name: str, params: dict[str, Any], timeout: float = 15.0) -> Any:
        self.connect(timeout=min(timeout, 5.0))
        future = asyncio.run_coroutine_threadsafe(self._request_async(name, params, timeout), self._loop)
        return future.result(timeout + 1)

    def drain_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        while True:
            try:
                events.append(self._event_queue.get_nowait())
            except queue.Empty:
                return events

    def close(self) -> None:
        if self._loop is None:
            return
        future = asyncio.run_coroutine_threadsafe(self._disconnect_async(), self._loop)
        with contextlib.suppress(Exception):
            future.result(5)
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop = None
        self._thread = None
        self._ready.clear()
        self._connected = False
        self._service_info = None

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run_loop, name="bot-ea-qt-ws-client", daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            raise RuntimeError("websocket client loop failed to start")

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            with contextlib.suppress(Exception):
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    async def _connect_async(self, timeout: float) -> dict[str, Any]:
        if self._websocket is not None and self._connected:
            return self._service_info or {}
        await self._disconnect_async()
        self._service_ready_future = self._loop.create_future()
        self._websocket = await websockets.connect(self._url)
        self._reader_task = asyncio.create_task(self._reader_loop())
        info = await asyncio.wait_for(self._service_ready_future, timeout=timeout)
        self._connected = True
        self._service_info = dict(info)
        return self._service_info

    async def _disconnect_async(self) -> None:
        websocket = self._websocket
        self._websocket = None
        self._connected = False
        self._service_info = None
        self._service_ready_future = None
        reader_task = self._reader_task
        self._reader_task = None
        if websocket is not None:
            with contextlib.suppress(Exception):
                await websocket.close()
        if reader_task is not None:
            reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader_task
        self._fail_pending(RuntimeError("websocket service disconnected"))

    async def _reader_loop(self) -> None:
        websocket = self._websocket
        if websocket is None:
            return
        try:
            async for raw_message in websocket:
                message = json.loads(raw_message)
                if message.get("type") == "response":
                    response_id = str(message.get("id") or "")
                    future = self._pending.pop(response_id, None)
                    if future is not None and not future.done():
                        future.set_result(message)
                    continue
                if message.get("type") != "event":
                    continue
                if message.get("name") == "service_ready":
                    future = self._service_ready_future
                    if future is not None and not future.done():
                        future.set_result(message.get("payload") or {})
                    continue
                self._event_queue.put(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_pending(exc)
        finally:
            self._connected = False
            self._websocket = None

    async def _request_async(self, name: str, params: dict[str, Any], timeout: float) -> Any:
        websocket = self._websocket
        if websocket is None:
            raise RuntimeError("websocket service is not connected")
        request_id = uuid.uuid4().hex
        future = self._loop.create_future()
        self._pending[request_id] = future
        await websocket.send(json.dumps({"type": "command", "id": request_id, "name": name, "params": params}, default=str))
        try:
            response = await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error") or f"{name} failed"))
        return response.get("result")

    def _fail_pending(self, exc: Exception) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()


class QtBotEaWebSocketBackend:
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        adapter: LiveMT5Adapter | None = None,
        runtime_coordinator: DesktopRuntimeCoordinator | None = None,
        risk_engine: RiskEngine | None = None,
        risk_policy: RiskPolicy | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.risk_policy = risk_policy or RiskPolicy(
            base_risk_pct=1.0,
            max_total_open_risk_pct=2.0,
            daily_loss_limit_pct=3.0,
        )
        adapter_factory = (lambda: adapter) if adapter is not None else LiveMT5Adapter
        coordinator = runtime_coordinator or DesktopRuntimeCoordinator(
            adapter_factory=adapter_factory,
            risk_policy=self.risk_policy,
        )
        service = QtBotEaWebSocketService(
            host=host,
            port=port,
            adapter_factory=adapter_factory,
            runtime_coordinator=coordinator,
            risk_engine=risk_engine,
            risk_policy=self.risk_policy,
        )
        self._local_runner = QtBotEaLocalServiceRunner(service)
        self._client = QtBotEaWebSocketClient(self._url(host, port))

    def start_managed_service(self) -> dict[str, Any]:
        self._local_runner.start()
        return {"host": self.host, "port": self.port}

    def stop_managed_service(self) -> None:
        self._client.close()
        self._local_runner.stop()

    def is_managed_service_running(self) -> bool:
        return self._local_runner.is_running

    def managed_service_url(self) -> str:
        return self._url(self.host, self.port)

    def managed_service_label(self) -> str:
        return "App-managed"

    def connect(self, url: str) -> dict[str, Any]:
        return self._client.connect(url)

    def request(self, name: str, params: dict[str, Any], timeout: float = 15.0) -> Any:
        return self._client.request(name, params, timeout=timeout)

    def drain_events(self) -> list[dict[str, Any]]:
        return self._client.drain_events()

    def close(self) -> None:
        self.stop_managed_service()

    @staticmethod
    def _url(host: str, port: int) -> str:
        return f"ws://{host}:{port}"


class BotEaQtWindow(QMainWindow):
    TIMEFRAME_OPTIONS = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
    STYLE_OPTIONS = tuple(style.value for style in TradingStyle)
    ALLOCATION_MODE_OPTIONS = tuple(mode.value for mode in CapitalAllocationMode)
    MANUAL_SIDE_OPTIONS = ("buy", "sell")
    LOT_MODE_OPTIONS = ("auto_max", "manual")
    CODEX_MODEL_PRESETS = (
        "",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.3-codex",
        "gpt-5.3-codex-spark",
        "gpt-5.2-codex",
        "gpt-5.1-codex-mini",
    )

    def __init__(
        self,
        *,
        adapter: LiveMT5Adapter | None = None,
        runtime_coordinator: DesktopRuntimeCoordinator | None = None,
        risk_engine: RiskEngine | None = None,
        risk_policy: RiskPolicy | None = None,
        backend: Any | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("bot-ea Qt Desktop Runtime")
        self.resize(1500, 920)

        self.adapter = adapter
        self.risk_engine = risk_engine or RiskEngine()
        self.risk_policy = risk_policy or RiskPolicy(
            base_risk_pct=1.0,
            max_total_open_risk_pct=2.0,
            daily_loss_limit_pct=3.0,
        )
        self.runtime_coordinator = runtime_coordinator
        self.backend = backend or QtBotEaWebSocketBackend(
            adapter=adapter,
            runtime_coordinator=runtime_coordinator,
            risk_engine=self.risk_engine,
            risk_policy=self.risk_policy,
        )

        self.snapshot: dict[str, Any] | None = None
        self.size_result: dict[str, Any] | None = None
        self.manual_order_snapshot: dict[str, Any] | None = None
        self._field_guard = False
        self._service_connected = False
        self._managed_service_owned = False
        self._runtime_running = False
        self._live_enabled = False
        self._pending_approval: dict[str, Any] | None = None
        self._preview_debounce_ms = 150
        self._preview_refresh_inflight = False

        self._build_ui()
        self._wire_events()

        self.event_timer = QTimer(self)
        self.event_timer.timeout.connect(self._pump_runtime_events)
        self.event_timer.start(250)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self._refresh_preview_state)
        self.preview_poll_timer = QTimer(self)
        self.preview_poll_timer.timeout.connect(self._refresh_preview_tick)
        self.preview_poll_timer.start(1000)
        QTimer.singleShot(0, lambda: self.connect_service(show_errors=False))

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        runbook_action = QAction("Runbook", self)
        runbook_action.triggered.connect(
            lambda: self._append_log([f"Runbook: {Path.cwd() / 'docs' / 'desktop-runtime-runbook.md'}"])
        )
        toolbar.addAction(runbook_action)

        splitter = QSplitter(Qt.Horizontal, self)
        root.addWidget(splitter)

        left_panel = QWidget(self)
        left_layout = QVBoxLayout(left_panel)
        splitter.addWidget(left_panel)

        right_panel = QWidget(self)
        right_layout = QVBoxLayout(right_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([480, 980])

        self.service_group = QGroupBox("Backend Service", self)
        service_form = QFormLayout(self.service_group)
        self.service_host_input = QLineEdit("127.0.0.1", self)
        self.service_port_input = QLineEdit("8765", self)
        service_form.addRow("Host", self.service_host_input)
        service_form.addRow("Port", self.service_port_input)
        left_layout.addWidget(self.service_group)

        self.trade_group = QGroupBox("Trade Setup", self)
        trade_form = QFormLayout(self.trade_group)
        self.symbol_combo = QComboBox(self)
        self.symbol_combo.setEditable(True)
        self.symbol_combo.addItem("EURUSD")
        self.timeframe_combo = QComboBox(self)
        self.timeframe_combo.addItems(self.TIMEFRAME_OPTIONS)
        self.timeframe_combo.setCurrentText("M15")
        self.style_combo = QComboBox(self)
        self.style_combo.addItems(self.STYLE_OPTIONS)
        self.style_combo.setCurrentText("intraday")
        self.stop_input = QLineEdit("200", self)
        self.stop_label = QLabel("Stop Loss Distance (points)", self)
        self.capital_mode_combo = QComboBox(self)
        self.capital_mode_combo.addItems(self.ALLOCATION_MODE_OPTIONS)
        self.capital_mode_combo.setCurrentText("fixed_cash")
        self.capital_input = QLineEdit("250", self)
        self.lot_mode_combo = QComboBox(self)
        self.lot_mode_combo.addItems(self.LOT_MODE_OPTIONS)
        self.manual_lot_input = QLineEdit("0.01", self)
        self.side_combo = QComboBox(self)
        self.side_combo.addItems(self.MANUAL_SIDE_OPTIONS)
        self.db_input = QLineEdit(str(Path.cwd() / "bot_ea_runtime.db"), self)

        trade_form.addRow("Symbol (from MT5)", self.symbol_combo)
        trade_form.addRow("Timeframe", self.timeframe_combo)
        trade_form.addRow("Strategy Style", self.style_combo)
        trade_form.addRow(self.stop_label, self.stop_input)
        trade_form.addRow("Capital Mode", self.capital_mode_combo)
        trade_form.addRow("Capital To Use (USD)", self.capital_input)
        trade_form.addRow("Lot Mode", self.lot_mode_combo)
        trade_form.addRow("Manual Lot Request", self.manual_lot_input)
        trade_form.addRow("Manual Side Only", self.side_combo)
        trade_form.addRow("Log File (Runtime DB)", self.db_input)
        left_layout.addWidget(self.trade_group)

        self.codex_group = QGroupBox("Codex", self)
        codex_form = QFormLayout(self.codex_group)
        self.codex_command_input = QLineEdit("codex", self)
        self.model_combo = QComboBox(self)
        self.model_combo.setEditable(True)
        self.model_combo.addItems(self.CODEX_MODEL_PRESETS)
        self.model_combo.setCurrentText("gpt-5.4-mini")
        self.codex_cwd_input = QLineEdit(str(Path.cwd()), self)
        self.poll_interval_input = QLineEdit("30", self)
        codex_form.addRow("Codex Command", self.codex_command_input)
        codex_form.addRow("AI Model", self.model_combo)
        codex_form.addRow("Codex Work Folder", self.codex_cwd_input)
        codex_form.addRow("Check Market Every (s)", self.poll_interval_input)
        left_layout.addWidget(self.codex_group)

        self.action_group = QGroupBox("Actions", self)
        action_layout = QGridLayout(self.action_group)
        self.connect_service_button = QPushButton("Start / Connect Service", self)
        self.check_mt5_button = QPushButton("Check MT5", self)
        self.load_codex_button = QPushButton("Load Codex", self)
        self.refresh_button = QPushButton("Refresh", self)
        self.preflight_button = QPushButton("Preflight", self)
        self.execute_button = QPushButton("Execute Manual Order", self)
        self.play_button = QPushButton("Play Runtime", self)
        self.stop_button = QPushButton("Stop Runtime", self)
        self.live_button = QPushButton("Enable Live", self)
        self.approve_button = QPushButton("Approve Pending", self)
        self.reject_button = QPushButton("Reject Pending", self)
        self.load_telemetry_button = QPushButton("Load Telemetry", self)
        for idx, button in enumerate(
            [
                self.connect_service_button,
                self.check_mt5_button,
                self.load_codex_button,
                self.refresh_button,
                self.preflight_button,
                self.execute_button,
                self.play_button,
                self.stop_button,
                self.live_button,
                self.approve_button,
                self.reject_button,
                self.load_telemetry_button,
            ]
        ):
            action_layout.addWidget(button, idx // 2, idx % 2)
        left_layout.addWidget(self.action_group)
        left_layout.addStretch(1)

        self.status_group = QGroupBox("Readiness", self)
        status_grid = QGridLayout(self.status_group)
        self.service_status = QLabel("Service disconnected", self)
        self.mt5_status = QLabel("MT5 unchecked", self)
        self.codex_status = QLabel("codex-cli unchecked", self)
        self.runtime_status = QLabel("Runtime stopped", self)
        self.run_id_status = QLabel("-", self)
        self.approval_status = QLabel("No pending live approval", self)
        status_grid.addWidget(QLabel("Service"), 0, 0)
        status_grid.addWidget(self.service_status, 0, 1)
        status_grid.addWidget(QLabel("MT5"), 1, 0)
        status_grid.addWidget(self.mt5_status, 1, 1)
        status_grid.addWidget(QLabel("Codex"), 2, 0)
        status_grid.addWidget(self.codex_status, 2, 1)
        status_grid.addWidget(QLabel("Runtime"), 3, 0)
        status_grid.addWidget(self.runtime_status, 3, 1)
        status_grid.addWidget(QLabel("Run ID"), 4, 0)
        status_grid.addWidget(self.run_id_status, 4, 1)
        status_grid.addWidget(QLabel("Approval"), 5, 0)
        status_grid.addWidget(self.approval_status, 5, 1)
        right_layout.addWidget(self.status_group)

        summary_row = QHBoxLayout()
        self.market_card = self._make_text_card("Market Snapshot")
        self.manual_card = self._make_text_card("Manual Lot Snapshot")
        self.risk_card = self._make_text_card("Risk / Sizing Snapshot")
        summary_row.addWidget(self.market_card["frame"])
        summary_row.addWidget(self.manual_card["frame"])
        summary_row.addWidget(self.risk_card["frame"])
        right_layout.addLayout(summary_row)

        self.tabs = QTabWidget(self)
        self.runtime_text = QPlainTextEdit(self)
        self.runtime_text.setReadOnly(True)
        self.validation_text = QPlainTextEdit(self)
        self.validation_text.setReadOnly(True)
        self.events_text = QPlainTextEdit(self)
        self.events_text.setReadOnly(True)
        self.tabs.addTab(self.runtime_text, "Runtime")
        self.tabs.addTab(self.validation_text, "Validation")
        self.tabs.addTab(self.events_text, "Events / Log")
        right_layout.addWidget(self.tabs)

        self.hint_label = QLabel(
            "Qt app memakai websocket backend service untuk probe, preview, preflight, execute, runtime, dan telemetry. "
            "Lot Mode=manual akan dinormalisasi mengikuti batas broker/capital dari service.",
            self,
        )
        self.hint_label.setWordWrap(True)
        right_layout.addWidget(self.hint_label)
        self._sync_button_states()

    def _make_text_card(self, title: str) -> dict[str, QWidget | QPlainTextEdit]:
        frame = QFrame(self)
        frame.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(frame)
        layout.addWidget(QLabel(title, self))
        text = QPlainTextEdit(self)
        text.setReadOnly(True)
        text.setMaximumBlockCount(200)
        layout.addWidget(text)
        return {"frame": frame, "text": text}

    def _wire_events(self) -> None:
        self.connect_service_button.clicked.connect(self.connect_service)
        self.check_mt5_button.clicked.connect(self.check_mt5)
        self.load_codex_button.clicked.connect(self.load_codex)
        self.refresh_button.clicked.connect(self.refresh_snapshot)
        self.preflight_button.clicked.connect(self.preflight)
        self.execute_button.clicked.connect(self.execute_manual)
        self.play_button.clicked.connect(self.play_runtime)
        self.stop_button.clicked.connect(self.stop_runtime)
        self.live_button.clicked.connect(self.toggle_live)
        self.approve_button.clicked.connect(self.approve_pending)
        self.reject_button.clicked.connect(self.reject_pending)
        self.load_telemetry_button.clicked.connect(self.load_telemetry)

        for widget in (
            self.symbol_combo.lineEdit(),
            self.stop_input,
            self.capital_input,
            self.manual_lot_input,
        ):
            if widget is not None:
                widget.textChanged.connect(self._schedule_live_preview)
        for combo in (
            self.symbol_combo,
            self.timeframe_combo,
            self.style_combo,
            self.capital_mode_combo,
            self.lot_mode_combo,
            self.side_combo,
        ):
            combo.currentTextChanged.connect(self._schedule_live_preview)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.event_timer.stop()
        self.preview_timer.stop()
        self.preview_poll_timer.stop()
        self.backend.close()
        super().closeEvent(event)

    def connect_service(self, checked: bool = False, *, show_errors: bool = True) -> bool:
        _ = checked
        url = self._service_url()
        try:
            if url == self.backend.managed_service_url():
                self.backend.start_managed_service()
            info = self.backend.connect(url)
        except Exception as exc:
            detail = self._format_exception_detail(exc)
            self._service_connected = False
            self._managed_service_owned = False
            self.service_status.setText(detail)
            self._append_log([f"service_error: {detail}"])
            self._sync_button_states()
            if show_errors:
                QMessageBox.warning(self, "Service connection failed", detail)
            return False
        host = str(info.get("host") or self.service_host_input.text().strip())
        port = str(info.get("port") or self.service_port_input.text().strip())
        self._service_connected = True
        managed_url = self.backend.managed_service_url()
        self._managed_service_owned = bool(url == managed_url and self.backend.is_managed_service_running())
        service_label = self.backend.managed_service_label() if self._managed_service_owned else "External"
        self.service_status.setText(f"{service_label} connected {host}:{port}")
        self._append_log([f"service_connected mode={service_label.lower()} ws://{host}:{port}"])
        self._sync_button_states()
        return True

    def _schedule_live_preview(self, *_args: object) -> None:
        if self._field_guard:
            self._sync_button_states()
            return
        self.preview_timer.start(self._preview_debounce_ms)

    def _refresh_preview_state(self) -> None:
        if self._field_guard or self._preview_refresh_inflight or not self._service_connected:
            self._sync_button_states()
            return
        symbol = self.symbol_combo.currentText().strip()
        if not symbol:
            self._sync_button_states()
            return
        self._preview_refresh_inflight = True
        try:
            result = self._send_backend_command("refresh_manual", self._manual_preview_params(), timeout=10.0)
        except Exception:
            self._sync_button_states()
            return
        finally:
            self._preview_refresh_inflight = False
        self._apply_refresh_result(result)

    def _refresh_preview_tick(self) -> None:
        if not self._service_connected or not self.isVisible() or self._runtime_running:
            return
        if self.snapshot is None:
            return
        self._refresh_preview_state()

    def check_mt5(self) -> None:
        try:
            result = self._send_backend_command("probe_mt5", self._probe_params())
        except Exception as exc:
            detail = self._format_exception_detail(exc)
            self.mt5_status.setText(detail)
            self._append_log([f"MT5 error: {detail}"])
            return
        terminal = result["terminal"]
        snapshot = result["snapshot"]
        self.mt5_status.setText("MT5 ready")
        self._set_symbol_choices(result.get("symbols") or [])
        self._sync_stop_distance_from_probe(snapshot)
        self.snapshot = {**(self.snapshot or {}), **dict(snapshot)}
        self._update_summary_cards()
        self._schedule_live_preview()
        self._append_log(
            [
                "mt5_probe:",
                f"- connected={terminal.get('connected')}",
                f"- terminal_trade_allowed={terminal.get('trade_allowed')}",
                f"- account_trade_allowed={terminal.get('account_trade_allowed')}",
                f"- symbol_trade_allowed={snapshot.get('symbol_trade_allowed')}",
                f"- broker_stop_min_points={snapshot.get('stops_level_points')}",
                f"- available_symbols={len(result.get('symbols') or [])}",
            ]
        )

    def load_codex(self) -> None:
        try:
            result = self._send_backend_command("probe_codex", self._codex_params())
        except Exception as exc:
            detail = self._format_exception_detail(exc)
            self.codex_status.setText(detail)
            self._append_log([f"Codex error: {detail}"])
            return
        version = str(result)
        self.codex_status.setText(version)
        self._append_log(
            [
                "codex_probe:",
                f"- command={self.codex_command_input.text().strip()}",
                f"- version={version}",
                f"- model={self._optional_str(self.model_combo.currentText()) or 'default'}",
                f"- work_folder={self._optional_str(self.codex_cwd_input.text()) or Path.cwd()}",
            ]
        )

    def refresh_snapshot(self) -> None:
        try:
            result = self._send_backend_command("refresh_manual", self._manual_preview_params(), timeout=10.0)
        except Exception as exc:
            self._append_log([f"Snapshot error: {self._format_exception_detail(exc)}"])
            return
        self._apply_refresh_result(result)

    def preflight(self) -> None:
        if self.snapshot is None:
            self.refresh_snapshot()
        if self.snapshot is None:
            return
        try:
            result = self._send_backend_command("preflight_manual", self._manual_preview_params(), timeout=10.0)
        except Exception as exc:
            self._append_log([f"Preflight error: {self._format_exception_detail(exc)}"])
            return
        self._apply_refresh_result(
            {
                "snapshot": result.get("snapshot"),
                "manual_order_snapshot": result.get("manual_order_snapshot"),
                "risk_sizing_snapshot": self.size_result,
            }
        )
        self._append_log(
            self._snapshot_lines()
            + self._manual_snapshot_lines()
            + [
                f"status={result.get('status')}",
                f"detail={result.get('detail')}",
                f"retcode={result.get('retcode')}",
                f"projected_margin_free={result.get('projected_margin_free')}",
            ]
        )
        self._update_summary_cards()
        self._sync_button_states()

    def execute_manual(self) -> None:
        if self.snapshot is None:
            self.refresh_snapshot()
        if self.snapshot is None:
            return
        try:
            result = self._send_backend_command(
                "execute_manual",
                {**self._manual_preview_params(), "live_enabled": self._live_enabled},
                timeout=10.0,
            )
        except Exception as exc:
            self._append_log([f"Execute error: {self._format_exception_detail(exc)}"])
            return
        self._apply_refresh_result(
            {
                "snapshot": result.get("snapshot"),
                "manual_order_snapshot": result.get("manual_order_snapshot"),
                "risk_sizing_snapshot": self.size_result,
            }
        )
        self._append_log(
            self._snapshot_lines()
            + self._manual_snapshot_lines()
            + [
                f"execution_mode={'LIVE' if self._live_enabled else 'DRY_RUN'}",
                "live_hint=Klik Enable Live dulu jika ingin order sungguhan."
                if not self._live_enabled
                else "live_hint=Live order path active",
                f"status={result.get('status')}",
                f"detail={result.get('detail')}",
                f"retcode={result.get('retcode')}",
                f"order={result.get('order')}",
                f"deal={result.get('deal')}",
            ]
        )
        self._update_summary_cards()
        self._sync_button_states()

    def play_runtime(self) -> None:
        try:
            self.load_codex()
            self.check_mt5()
            run_id = str(self._send_backend_command("start_runtime", self._runtime_params(), timeout=15.0))
        except Exception as exc:
            self._append_log([f"Runtime start error: {self._format_exception_detail(exc)}"])
            return
        self._runtime_running = True
        self.run_id_status.setText(run_id)
        self.runtime_status.setText(f"Starting run {run_id}")
        self.approval_status.setText("No pending live approval")
        self._append_log([f"runtime_starting run_id={run_id}", f"db_path={self._runtime_params().get('db_path')}"])
        self._sync_button_states()

    def stop_runtime(self) -> None:
        try:
            self._send_backend_command("stop_runtime", {}, timeout=10.0)
        except Exception as exc:
            self._append_log([f"Runtime stop error: {self._format_exception_detail(exc)}"])
            return
        self._runtime_running = False
        self.runtime_status.setText("Runtime stopped")
        self._sync_button_states()

    def toggle_live(self) -> None:
        enable_live = not self._live_enabled
        try:
            result = self._send_backend_command("set_live_enabled", {"enabled": enable_live}, timeout=10.0)
        except Exception as exc:
            self._append_log([f"Live toggle error: {self._format_exception_detail(exc)}"])
            return
        self._live_enabled = bool(result.get("live_enabled"))
        self.live_button.setText("Disable Live" if self._live_enabled else "Enable Live")
        self.runtime_status.setText("Live orders enabled" if self._live_enabled else "Live orders disabled")
        self._sync_button_states()

    def approve_pending(self) -> None:
        try:
            pending = self._send_backend_command("approve_pending", {}, timeout=10.0)
        except Exception as exc:
            self._append_log([f"Approval error: {self._format_exception_detail(exc)}"])
            return
        self._pending_approval = None
        self.approval_status.setText(f"Approved {pending.get('symbol')} {pending.get('side')} {pending.get('volume')}")
        self._append_log([f"approval_armed: {pending.get('symbol')} {pending.get('side')} {pending.get('volume')}"])
        self._sync_button_states()

    def reject_pending(self) -> None:
        try:
            pending = self._send_backend_command("reject_pending", {}, timeout=10.0)
        except Exception as exc:
            self._append_log([f"Reject error: {self._format_exception_detail(exc)}"])
            return
        self._pending_approval = None
        self.approval_status.setText("No pending live approval")
        self._append_log([f"approval_rejected: {pending.get('symbol')} {pending.get('side')} {pending.get('volume')}"])
        self._sync_button_states()

    def load_telemetry(self) -> None:
        try:
            result = self._send_backend_command("load_telemetry", self._telemetry_params(), timeout=10.0)
        except Exception as exc:
            self._append_log([f"Telemetry error: {self._format_exception_detail(exc)}"])
            return
        overview = result.get("overview")
        if overview is None:
            self._append_log(["no runtime runs found"])
            return
        run_id = str(overview.get("run_id") or "")
        health = result.get("health") or {}
        validation = result.get("validation") or {}
        lifecycle_rows = result.get("lifecycle_rows") or []
        self.run_id_status.setText(run_id)
        self.runtime_text.setPlainText(
            "\n".join(
                [
                    f"run_id={run_id}",
                    f"status={overview.get('status')}",
                    f"last_action={overview.get('last_action')}",
                    f"spread_points={overview.get('spread_points')}",
                    f"equity={overview.get('equity')}",
                    f"free_margin={overview.get('free_margin')}",
                    f"reject_rate={self._float_value(health.get('reject_rate')):.2%}",
                    f"filled_events={health.get('filled_events')}",
                    f"dry_run_events={health.get('dry_run_events')}",
                ]
            )
        )
        warnings = list(validation.get("warnings") or [])
        self.validation_text.setPlainText(
            "\n".join(
                [
                    f"total_trades={validation.get('total_trades')}",
                    f"win_rate={self._float_value(validation.get('win_rate')):.2%}",
                    f"profit_factor={self._float_value(validation.get('profit_factor')):.3f}",
                    f"expectancy_r={self._float_value(validation.get('expectancy_r')):.3f}",
                    "",
                    *[f"- {warning}" for warning in warnings],
                ]
            )
        )
        self.events_text.setPlainText(
            "\n".join(
                self._manual_snapshot_lines()
                + [""]
                + [f"- {row.get('symbol')} {row.get('side')} pnl={row.get('realized_pnl_cash')}" for row in lifecycle_rows[:10]]
            )
        )

    def _probe_params(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol_combo.currentText().strip(),
            "timeframe": self.timeframe_combo.currentText().strip(),
            "trading_style": self.style_combo.currentText(),
            "stop_distance_points": self._current_stop_distance_value(),
            "capital_mode": self.capital_mode_combo.currentText(),
            "capital_value": self._capital_allocation().value,
        }

    def _manual_preview_params(self) -> dict[str, Any]:
        params = self._probe_params()
        params.update(
            {
                "lot_mode": self.lot_mode_combo.currentText().strip() or "auto_max",
                "manual_lot": self._float_or_default(self.manual_lot_input.text(), default=0.0),
                "side": self.side_combo.currentText(),
                "db_path": str(Path(self.db_input.text().strip()).expanduser()),
            }
        )
        return params

    def _codex_params(self) -> dict[str, Any]:
        return {
            "codex_command": self.codex_command_input.text().strip() or "codex",
            "model": self._optional_str(self.model_combo.currentText()),
            "codex_cwd": self._optional_str(self.codex_cwd_input.text()),
            "timeout_seconds": 60,
        }

    def _runtime_params(self) -> dict[str, Any]:
        config = self._desktop_runtime_config()
        return {
            "symbol": config.symbol,
            "timeframe": config.timeframe,
            "trading_style": config.trading_style.value,
            "stop_distance_points": config.stop_distance_points,
            "capital_mode": config.capital_allocation.mode.value,
            "capital_value": config.capital_allocation.value,
            "db_path": config.db_path,
            "codex_command": config.codex_executable,
            "model": config.codex_model,
            "codex_cwd": config.codex_cwd,
            "codex_timeout_seconds": config.codex_timeout_seconds,
            "poll_interval_seconds": config.poll_interval_seconds,
            "session_state": config.session_state,
            "news_state": config.news_state,
            "run_id": config.run_id,
        }

    def _telemetry_params(self) -> dict[str, Any]:
        return {
            "db_path": str(Path(self.db_input.text().strip()).expanduser()),
            "run_id": self._optional_str(self.run_id_status.text()),
        }

    def _send_backend_command(self, name: str, params: dict[str, Any], *, timeout: float = 15.0) -> Any:
        if not self._service_connected and not self.connect_service(show_errors=False):
            raise RuntimeError("websocket service is not connected")
        return self.backend.request(name, params, timeout=timeout)

    def _desktop_runtime_config(self) -> DesktopRuntimeConfig:
        poll_interval = int(float(self.poll_interval_input.text()))
        if poll_interval <= 0:
            raise ValueError("poll interval must be positive")
        return DesktopRuntimeConfig(
            symbol=self.symbol_combo.currentText().strip(),
            timeframe=self.timeframe_combo.currentText().strip(),
            trading_style=TradingStyle(self.style_combo.currentText()),
            stop_distance_points=self._current_stop_distance_value(),
            capital_allocation=self._capital_allocation(),
            db_path=str(Path(self.db_input.text().strip()).expanduser()),
            codex_executable=self.codex_command_input.text().strip() or "codex",
            codex_model=self._optional_str(self.model_combo.currentText()),
            codex_cwd=self._optional_str(self.codex_cwd_input.text()),
            poll_interval_seconds=poll_interval,
        )

    def _pump_runtime_events(self) -> None:
        for event in self.backend.drain_events():
            name = str(event.get("name") or "")
            payload = dict(event.get("payload") or {})
            message = str(payload.get("message") or "")
            if name == "service_ready":
                self._service_connected = True
                self._managed_service_owned = bool(self.backend.is_managed_service_running())
                service_label = self.backend.managed_service_label() if self._managed_service_owned else "External"
                self.service_status.setText(
                    f"{service_label} connected {payload.get('host', self.service_host_input.text().strip())}:{payload.get('port', self.service_port_input.text().strip())}"
                )
            elif name == "runtime_started":
                self._runtime_running = True
                self.runtime_status.setText(message)
                if payload.get("run_id"):
                    self.run_id_status.setText(str(payload["run_id"]))
            elif name == "runtime_cycle":
                self.runtime_status.setText(self._short(message))
                runtime_snapshot = payload.get("snapshot")
                if isinstance(runtime_snapshot, dict) and runtime_snapshot:
                    self.snapshot = dict(runtime_snapshot)
                    self._update_summary_cards()
            elif name in {"runtime_error", "runtime_halted", "runtime_stopped"}:
                self._runtime_running = False
                self.runtime_status.setText(self._short(message))
                self._append_log([f"{name}: {message}"])
            elif name == "approval_pending":
                self._pending_approval = payload
                self.approval_status.setText("Pending approval")
                self._append_log([f"approval_pending: {payload}"])
            elif name in {"approval_armed", "approval_status"}:
                self.approval_status.setText(self._short(message))
            elif name == "approval_rejected":
                self._pending_approval = None
                self.approval_status.setText(self._short(message))
            elif name == "mt5_ready":
                self.mt5_status.setText("MT5 ready")
            elif name == "codex_ready":
                self.codex_status.setText(str(payload.get("version") or message))
            elif name == "live_toggle":
                self._live_enabled = bool(payload.get("enabled"))
                self.live_button.setText("Disable Live" if self._live_enabled else "Enable Live")
        self._sync_button_states()

    def _apply_refresh_result(self, result: dict[str, Any]) -> None:
        snapshot = result.get("snapshot")
        if isinstance(snapshot, dict):
            self.snapshot = snapshot
            self._apply_stop_distance_floor(self._float_value(snapshot.get("stops_level_points")))
        manual_snapshot = result.get("manual_order_snapshot")
        if isinstance(manual_snapshot, dict):
            self.manual_order_snapshot = manual_snapshot
        size_result = result.get("risk_sizing_snapshot")
        if isinstance(size_result, dict):
            self.size_result = size_result
        self._apply_manual_preview_constraints()
        self._update_summary_cards()
        self._sync_button_states()

    def _apply_manual_preview_constraints(self) -> None:
        if self.manual_order_snapshot is None or self.lot_mode_combo.currentText().strip() != "manual":
            return
        requested = self._float_or_default(self.manual_lot_input.text(), default=0.0)
        final_lot = self._float_value(self.manual_order_snapshot.get("final_lot"))
        resized = bool(self.manual_order_snapshot.get("resized_down"))
        if resized and final_lot > 0 and abs(requested - final_lot) > 1e-9:
            self._field_guard = True
            try:
                self.manual_lot_input.setText(f"{final_lot:.2f}")
            finally:
                self._field_guard = False

    def _update_summary_cards(self) -> None:
        self.market_card["text"].setPlainText("\n".join(self._snapshot_lines()) if self.snapshot is not None else "No snapshot")
        self.manual_card["text"].setPlainText("\n".join(self._manual_snapshot_lines()))
        self.risk_card["text"].setPlainText("\n".join(self._risk_snapshot_lines()))

    def _snapshot_lines(self) -> list[str]:
        if self.snapshot is None:
            return ["No snapshot"]
        return [
            f"symbol={self.snapshot.get('symbol')}",
            f"bid={self.snapshot.get('bid')}",
            f"ask={self.snapshot.get('ask')}",
            f"spread_points={self._float_value(self.snapshot.get('spread_points')):.2f}",
            f"tick_time={self.snapshot.get('tick_time') or 'n/a'}",
            f"equity={self.snapshot.get('equity')}",
            f"free_margin={self.snapshot.get('free_margin')}",
            f"trade_mode={self.snapshot.get('trade_mode')}",
            f"execution_mode={self.snapshot.get('execution_mode')}",
            f"filling_mode={self.snapshot.get('filling_mode')}",
        ]

    def _manual_snapshot_lines(self) -> list[str]:
        if self.manual_order_snapshot is None:
            return ["manual_order_snapshot=unavailable"]
        snap = self.manual_order_snapshot
        return [
            "manual_order_snapshot:",
            f"- lot_mode={snap.get('lot_mode') or 'auto_max'}",
            f"- requested_lot={self._float_value(snap.get('requested_lot')):.4f}",
            f"- manual_lot_field_used={snap.get('lot_mode') == 'manual'}",
            f"- final_lot={self._float_value(snap.get('final_lot')):.4f}",
            f"- capital_basis_usd={self._float_value(snap.get('allocation_cap_usd')):.2f}",
            f"- free_margin_cap_usd={self._float_value(snap.get('available_margin_cap_usd')):.2f}",
            f"- broker_min_lot={self._float_value(snap.get('broker_min_lot')):.4f}",
            f"- broker_max_lot={self._float_value(snap.get('broker_max_lot')):.4f}",
            f"- broker_lot_step={self._float_value(snap.get('broker_lot_step')):.4f}",
            f"- margin_for_min_lot_usd={self._float_value(snap.get('margin_for_min_lot_usd')):.2f}",
            f"- margin_for_final_lot_usd={self._float_value(snap.get('margin_for_final_lot_usd')):.2f}",
            f"- order_price={self._float_value(snap.get('order_price')):.5f}",
            f"- resized_down={bool(snap.get('resized_down'))}",
            f"- manual_order_result={'ok' if bool(snap.get('accepted')) else 'blocked'}",
            f"- why_blocked={snap.get('why_blocked') or 'n/a'}",
        ]

    def _risk_snapshot_lines(self) -> list[str]:
        if self.size_result is None:
            return ["sizing_snapshot=unavailable"]
        size = self.size_result
        return [
            "sizing_snapshot:",
            f"- final_lot={self._float_value(size.get('final_lot')):.4f}",
            f"- raw_lot_before_broker_rounding={self._float_value(size.get('raw_lot_before_broker_rounding')):.6f}",
            f"- effective_risk_pct={self._float_value(size.get('effective_risk_pct')):.2f}%",
            f"- risk_cash_budget_usd={self._float_value(size.get('risk_cash_budget_usd')):.2f}",
            f"- estimated_loss_at_final_lot_usd={self._float_value(size.get('estimated_loss_at_final_lot_usd')):.2f}",
            f"- sizing_result={'ok' if bool(size.get('accepted')) else 'blocked'}",
            f"- why_blocked={size.get('why_blocked') or 'n/a'}",
        ]

    def _capital_allocation(self) -> CapitalAllocation:
        mode = CapitalAllocationMode(self.capital_mode_combo.currentText())
        raw_value = float(self.capital_input.text())
        if mode is CapitalAllocationMode.FULL_EQUITY:
            return CapitalAllocation(mode=mode, value=100.0)
        if mode is CapitalAllocationMode.PERCENT_EQUITY:
            raw_value = min(max(raw_value, 0.0), 100.0)
        if mode is CapitalAllocationMode.FIXED_CASH:
            raw_value = max(raw_value, 0.0)
        return CapitalAllocation(mode=mode, value=raw_value)

    def _sync_stop_distance_from_probe(self, snapshot: dict[str, object]) -> None:
        stop_min = self._float_value(snapshot.get("stops_level_points"))
        self._apply_stop_distance_floor(stop_min)

    def _apply_stop_distance_floor(self, stop_min: float) -> None:
        self.stop_label.setText(
            f"Stop Loss Distance (points, min {stop_min:.0f})" if stop_min > 0 else "Stop Loss Distance (points)"
        )
        current = self._float_or_default(self.stop_input.text(), default=stop_min)
        if stop_min > 0 and current < stop_min:
            self._field_guard = True
            try:
                self.stop_input.setText(f"{stop_min:.0f}")
            finally:
                self._field_guard = False

    def _current_stop_distance_value(self) -> float:
        current = float(self.stop_input.text())
        stop_min = self._float_value((self.snapshot or {}).get("stops_level_points"))
        if stop_min > 0 and current < stop_min:
            self._field_guard = True
            try:
                self.stop_input.setText(f"{stop_min:.0f}")
            finally:
                self._field_guard = False
            return stop_min
        return current

    def _set_symbol_choices(self, symbols: list[str]) -> None:
        current = self.symbol_combo.currentText().strip()
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        self.symbol_combo.addItems(symbols or [current or "EURUSD"])
        if current:
            self.symbol_combo.setCurrentText(current)
        self.symbol_combo.blockSignals(False)

    def _service_url(self) -> str:
        host = self.service_host_input.text().strip() or "127.0.0.1"
        port = int(self.service_port_input.text().strip() or "8765")
        return f"ws://{host}:{port}"

    def _sync_button_states(self) -> None:
        connected = self._service_connected
        manual_execute_allowed = bool(
            self.manual_order_snapshot
            and bool(self.manual_order_snapshot.get("accepted"))
            and self._float_value(self.manual_order_snapshot.get("final_lot")) > 0
        )
        pending = self._pending_approval is not None
        for button in (
            self.load_codex_button,
            self.play_button,
            self.live_button,
            self.approve_button,
            self.reject_button,
            self.load_telemetry_button,
        ):
            button.setEnabled(connected)
        self.check_mt5_button.setEnabled(connected and not self._runtime_running)
        self.refresh_button.setEnabled(connected and not self._runtime_running)
        self.preflight_button.setEnabled(connected and not self._runtime_running)
        self.stop_button.setEnabled(connected and self._runtime_running)
        self.play_button.setEnabled(connected and not self._runtime_running)
        self.execute_button.setEnabled(connected and not self._runtime_running and manual_execute_allowed)
        self.approve_button.setEnabled(connected and pending)
        self.reject_button.setEnabled(connected and pending)
        self.live_button.setText("Disable Live" if self._live_enabled else "Enable Live")
        trade_setup_enabled = not self._runtime_running
        for widget in (
            self.symbol_combo,
            self.timeframe_combo,
            self.style_combo,
            self.stop_input,
            self.capital_mode_combo,
            self.capital_input,
            self.lot_mode_combo,
            self.side_combo,
            self.db_input,
        ):
            widget.setEnabled(trade_setup_enabled)
        self.manual_lot_input.setEnabled(trade_setup_enabled and self.lot_mode_combo.currentText().strip() == "manual")
        self.connect_service_button.setEnabled(not self._runtime_running)

    def _append_log(self, lines: list[str]) -> None:
        current = self.events_text.toPlainText().strip()
        merged = "\n".join(filter(None, [current, *lines]))
        self.events_text.setPlainText(merged)

    @staticmethod
    def _float_or_default(value: Any, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _float_value(cls, value: Any) -> float:
        return cls._float_or_default(value, default=0.0)

    @staticmethod
    def _short(message: str, limit: int = 140) -> str:
        normalized = " ".join(str(message).split())
        return normalized if len(normalized) <= limit else f"{normalized[: limit - 3]}..."

    @staticmethod
    def _optional_str(value: str) -> str | None:
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _format_exception_detail(exc: Exception) -> str:
        message = str(exc).strip() or exc.__class__.__name__
        if "No IPC connection" in message:
            return "MT5 lost IPC connection. Reopen or refocus MT5, then click Check MT5 again."
        if "account_info() failed" in message:
            return "MT5 account info could not be read. Check terminal connection and account login."
        if "timed out" in message and "codex exec" in message:
            return "Codex runtime timed out. Try a smaller model or load Codex again."
        return message


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = BotEaQtWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
