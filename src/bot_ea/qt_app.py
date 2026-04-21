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
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .desktop_runtime import DesktopRuntimeConfig, DesktopRuntimeCoordinator
from .models import CapitalAllocation, CapitalAllocationMode, RiskPolicy, TradingStyle
from .mt5_adapter import LiveMT5Adapter
from .operator_state import OperatorRuntimeSettings, OperatorStateStore
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
            ai_workspace_path=self._optional_str(str(params.get("ai_workspace_path") or "")),
            ai_documents_path=self._optional_str(str(params.get("ai_documents_path") or "")),
            ai_context_path=self._optional_str(str(params.get("ai_context_path") or params.get("ai_context_root") or "")),
            resume_prompt_path=self._optional_str(str(params.get("resume_prompt_path") or "")),
            behavior_profile_path=self._optional_str(str(params.get("behavior_profile_path") or "")),
            account_fingerprint=dict(params.get("account_fingerprint") or {}) or None,
        )

    @staticmethod
    def _optional_str(value: str) -> str | None:
        normalized = value.strip()
        return normalized or None


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
    PROJECT_ROOT = Path(__file__).resolve().parents[2]

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
        self.project_root = self.PROJECT_ROOT
        self.state_store = OperatorStateStore(self.project_root)
        self.runtime_settings = self.state_store.load_runtime_settings()

        self.snapshot: dict[str, Any] | None = None
        self.size_result: dict[str, Any] | None = None
        self.manual_order_snapshot: dict[str, Any] | None = None
        self._field_guard = False
        self._service_connected = False
        self._managed_service_owned = False
        self._mt5_ready = False
        self._codex_ready = False
        self._runtime_running = False
        self._live_enabled = False
        self._pending_approval: dict[str, Any] | None = None
        self._telemetry_overview: dict[str, Any] | None = None
        self._telemetry_health: dict[str, Any] | None = None
        self._telemetry_validation: dict[str, Any] | None = None
        self._preview_debounce_ms = 150
        self._preview_refresh_inflight = False
        self._dev_mode_enabled = False
        self._mt5_overlay_active = False
        self._account_review_active = False
        self._startup_gate_active = True
        self._startup_probe_inflight = False
        self._startup_requirements = {}
        self._startup_requirement_details: dict[str, str] = {}
        self._startup_active_step = ""
        self._active_account_fingerprint: dict[str, Any] | None = None
        self._active_context_binding: dict[str, Any] | None = None
        self._pending_account_fingerprint: dict[str, Any] | None = None
        self._pending_account_contexts: list[dict[str, Any]] = []
        self._selected_pending_context_index = 0

        self._build_ui()
        self._apply_runtime_settings_to_form()
        self._apply_accessibility_defaults()
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
        QTimer.singleShot(0, self._start_startup_gate)

    def _apply_obsidian_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #0b0f10;
                color: #e8e1d6;
            }
            QToolBar {
                background: #11161a;
                border: 1px solid #1f2a31;
                spacing: 8px;
                padding: 8px;
            }
            QToolButton {
                color: #e8e1d6;
                background: #141c20;
                border: 1px solid #24323a;
                border-radius: 10px;
                padding: 8px 12px;
                font: 600 11pt "Cascadia Mono";
            }
            QWidget#workspaceRoot {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0b0f10, stop:1 #11171b);
            }
            QWidget#leftRail, QWidget#rightRail {
                background: transparent;
            }
            QWidget#leftRail {
                min-width: 280px;
                max-width: 320px;
            }
            QGroupBox#sidebarPanel {
                background: #10161a;
                border-color: #1d2a31;
            }
            QGroupBox {
                background: #11161a;
                border: 1px solid #1e2a31;
                border-radius: 16px;
                margin-top: 18px;
                padding: 14px 14px 12px 14px;
                font: 700 11pt "Segoe UI";
                color: #f4eee3;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 6px;
                color: #8fe0d0;
            }
            QLabel {
                color: #d7d0c3;
                font: 10.5pt "Segoe UI";
            }
            QLabel#heroEyebrow {
                color: #77c7ff;
                font: 700 10pt "Cascadia Mono";
                letter-spacing: 2px;
                text-transform: uppercase;
            }
            QLabel#heroTitle {
                color: #f5efe2;
                font: 700 19pt "Segoe UI";
            }
            QLabel#heroSubtitle {
                color: #96a6a8;
                font: 10.5pt "Segoe UI";
            }
            QFrame#heroCard, QFrame#statusChip, QFrame#metricCard, QFrame#dataCard {
                background: #12181c;
                border: 1px solid #213038;
                border-radius: 18px;
            }
            QFrame#dataCardAccent {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #152027, stop:1 #11181d);
                border: 1px solid #33515d;
                border-radius: 22px;
            }
            QFrame#heroCard {
                padding: 16px;
            }
            QFrame#statusChip {
                padding: 12px;
            }
            QFrame#metricCard {
                padding: 16px;
            }
            QLabel#chipTitle {
                color: #7f9498;
                font: 700 9pt "Cascadia Mono";
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            QLabel#chipValue {
                color: #e8e1d6;
                font: 700 10.5pt "Segoe UI";
            }
            QLabel#metricTitle {
                color: #7f9498;
                font: 700 9pt "Cascadia Mono";
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            QLabel#metricValue {
                color: #f5efe2;
                font: 700 15pt "Cascadia Mono";
            }
            QLabel#cardTitle {
                color: #f5efe2;
                font: 700 11.5pt "Segoe UI";
            }
            QLabel#cardCaption {
                color: #87979c;
                font: 9.5pt "Segoe UI";
            }
            QLineEdit, QComboBox, QPlainTextEdit, QTabWidget::pane {
                background: #0f1417;
                color: #e8e1d6;
                border: 1px solid #26353d;
                border-radius: 12px;
                selection-background-color: #2c6a74;
                selection-color: #f5efe2;
                font: 10pt "Cascadia Mono";
            }
            QLineEdit, QComboBox {
                padding: 6px 8px;
                min-height: 22px;
            }
            QComboBox::drop-down {
                border: none;
                width: 26px;
            }
            QPlainTextEdit {
                padding: 10px;
            }
            QPushButton {
                background: #162126;
                color: #f2eadf;
                border: 1px solid #27414b;
                border-radius: 12px;
                padding: 8px 10px;
                font: 700 9.3pt "Cascadia Mono";
            }
            QPushButton:hover {
                background: #1b2a30;
            }
            QPushButton#navButton {
                text-align: left;
                padding: 10px 12px;
                font: 700 10pt "Segoe UI";
                background: #10171b;
                border-color: #203039;
            }
            QPushButton#navButton:checked {
                background: #1f3841;
                border-color: #4d8ea0;
                color: #f8f3ea;
            }
            QPushButton:disabled {
                color: #718186;
                background: #101518;
                border-color: #1a2328;
            }
            QTabBar::tab {
                background: #141a1e;
                color: #96a6a8;
                border: 1px solid #223039;
                padding: 9px 14px;
                margin-right: 6px;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                font: 700 9.5pt "Cascadia Mono";
            }
            QTabBar::tab:selected {
                color: #f5efe2;
                background: #1c262b;
                border-color: #2a4650;
            }
            QSplitter::handle {
                background: #182126;
                width: 2px;
            }
            QLabel#chipValue[tone="ok"], QLabel#metricValue[tone="ok"] {
                color: #7ce0b7;
            }
            QLabel#chipValue[tone="warn"], QLabel#metricValue[tone="warn"] {
                color: #f4c56a;
            }
            QLabel#chipValue[tone="error"], QLabel#metricValue[tone="error"] {
                color: #ff8e87;
            }
            QLabel#chipValue[tone="idle"], QLabel#metricValue[tone="idle"] {
                color: #9db0b4;
            }
            QLabel#chipValue[tone="live"], QLabel#metricValue[tone="live"] {
                color: #77c7ff;
            }
            """
        )

    def _make_status_chip(self, title: str, value: QLabel) -> QFrame:
        frame = QFrame(self)
        frame.setObjectName("statusChip")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        title_label = QLabel(title.upper(), frame)
        title_label.setObjectName("chipTitle")
        value.setObjectName("chipValue")
        layout.addWidget(title_label)
        layout.addWidget(value)
        return frame

    def _make_metric_card(self, title: str, value: QLabel, caption: str) -> QFrame:
        frame = QFrame(self)
        frame.setObjectName("metricCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        title_label = QLabel(title.upper(), frame)
        title_label.setObjectName("metricTitle")
        value.setObjectName("metricValue")
        caption_label = QLabel(caption, frame)
        caption_label.setObjectName("cardCaption")
        caption_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(value)
        layout.addWidget(caption_label)
        return frame

    @staticmethod
    def _configure_form_layout(form: QFormLayout) -> None:
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("workspaceRoot")
        self.setCentralWidget(central)
        self._apply_obsidian_theme()
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        self.runbook_button = QPushButton("Runbook", self)
        self.runbook_button.clicked.connect(
            lambda: self._append_log([f"Runbook: {self.project_root / 'docs' / 'desktop-runtime-runbook.md'}"])
        )

        self.shell_stack = QStackedWidget(self)
        root.addWidget(self.shell_stack)

        self.startup_gate_page = QWidget(self)
        startup_layout = QVBoxLayout(self.startup_gate_page)
        startup_layout.setContentsMargins(80, 60, 80, 60)
        startup_layout.setSpacing(18)
        self.gate_card = QFrame(self.startup_gate_page)
        self.gate_card.setObjectName("heroCard")
        gate_card_layout = QVBoxLayout(self.gate_card)
        gate_card_layout.setContentsMargins(24, 24, 24, 24)
        gate_card_layout.setSpacing(12)
        self.gate_title = QLabel("Persiapan Sistem", self.gate_card)
        self.gate_title.setObjectName("heroTitle")
        self.gate_subtitle = QLabel(
            "Workspace trading akan terbuka setelah service, MT5, akun, AI runtime, dokumen, context, dan storage tervalidasi.",
            self.gate_card,
        )
        self.gate_subtitle.setObjectName("heroSubtitle")
        self.gate_subtitle.setWordWrap(True)
        gate_card_layout.addWidget(self.gate_title)
        gate_card_layout.addWidget(self.gate_subtitle)
        self.gate_message = QLabel("Memulai pemeriksaan dependency...", self.gate_card)
        self.gate_message.setObjectName("cardCaption")
        self.gate_message.setWordWrap(True)
        gate_card_layout.addWidget(self.gate_message)
        self.gate_status_group = QGroupBox("Status Kesiapan", self.gate_card)
        gate_status_layout = QVBoxLayout(self.gate_status_group)
        gate_status_layout.setContentsMargins(12, 18, 12, 12)
        gate_status_layout.setSpacing(10)
        self.gate_step_labels: dict[str, QLabel] = {}
        for key, title in (
            ("service", "Service Lokal"),
            ("mt5_process", "MetaTrader 5"),
            ("mt5_session", "Sesi MT5"),
            ("account", "Akun Aktif"),
            ("symbol", "Simbol Dasar"),
            ("ai_runtime", "AI Runtime"),
            ("ai_workspace", "Workspace AI"),
            ("ai_documents", "Dokumen AI"),
            ("ai_context", "Context / History"),
            ("storage", "Storage"),
            ("resume_state", "Resume State"),
            ("workspace", "Workspace Utama"),
        ):
            label = QLabel("Belum diperiksa", self.gate_status_group)
            self.gate_step_labels[key] = label
            gate_status_layout.addWidget(self._make_status_chip(title, label))
        self.gate_service_status = self.gate_step_labels["service"]
        self.gate_mt5_status = self.gate_step_labels["mt5_session"]
        self.gate_codex_status = self.gate_step_labels["ai_runtime"]
        gate_card_layout.addWidget(self.gate_status_group)
        gate_button_row = QHBoxLayout()
        gate_button_row.setSpacing(10)
        self.gate_primary_button = QPushButton("Mulai Pemeriksaan", self.gate_card)
        self.gate_retry_button = QPushButton("Coba Lagi", self.gate_card)
        self.gate_dev_button = QPushButton("Masuk Mode Dev", self.gate_card)
        gate_button_row.addWidget(self.gate_primary_button)
        gate_button_row.addWidget(self.gate_retry_button)
        gate_button_row.addWidget(self.gate_dev_button)
        gate_button_row.addStretch(1)
        gate_card_layout.addLayout(gate_button_row)
        startup_layout.addStretch(1)
        startup_layout.addWidget(self.gate_card, 0, Qt.AlignCenter)
        startup_layout.addStretch(1)
        self.shell_stack.addWidget(self.startup_gate_page)

        self.workspace_page = QWidget(self)
        workspace_layout = QVBoxLayout(self.workspace_page)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(14)
        splitter = QSplitter(Qt.Horizontal, self.workspace_page)
        workspace_layout.addWidget(splitter)

        left_panel = QWidget(self)
        left_panel.setObjectName("leftRail")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        splitter.addWidget(left_panel)
        left_panel.setMinimumWidth(280)
        left_panel.setMaximumWidth(320)

        right_panel = QWidget(self)
        right_panel.setObjectName("rightRail")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)
        splitter.addWidget(right_panel)
        splitter.setSizes([300, 1180])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self.sidebar_intro_card = QFrame(self)
        self.sidebar_intro_card.setObjectName("heroCard")
        sidebar_intro_layout = QVBoxLayout(self.sidebar_intro_card)
        sidebar_intro_layout.setContentsMargins(16, 14, 16, 14)
        sidebar_intro_layout.setSpacing(4)
        sidebar_intro_eyebrow = QLabel("Navigation", self.sidebar_intro_card)
        sidebar_intro_eyebrow.setObjectName("heroEyebrow")
        sidebar_intro_title = QLabel("Menu Utama", self.sidebar_intro_card)
        sidebar_intro_title.setObjectName("heroTitle")
        sidebar_intro_subtitle = QLabel(
            "Navigasi utama operator. Kontrol trading utama tetap berada di area kerja sebelah kanan.",
            self.sidebar_intro_card,
        )
        sidebar_intro_subtitle.setObjectName("heroSubtitle")
        sidebar_intro_subtitle.setWordWrap(True)
        sidebar_intro_layout.addWidget(sidebar_intro_eyebrow)
        sidebar_intro_layout.addWidget(sidebar_intro_title)
        sidebar_intro_layout.addWidget(sidebar_intro_subtitle)
        left_layout.addWidget(self.sidebar_intro_card)

        self.nav_group = QGroupBox("Navigation", self)
        self.nav_group.setObjectName("sidebarPanel")
        nav_layout = QVBoxLayout(self.nav_group)
        nav_layout.setContentsMargins(12, 20, 12, 12)
        nav_layout.setSpacing(8)
        self.nav_buttons: list[QPushButton] = []
        for index, label in enumerate(("Dasbor", "Strategi", "Riwayat", "Log", "Pengaturan")):
            button = QPushButton(label, self)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setObjectName("navButton")
            self.nav_buttons.append(button)
            nav_layout.addWidget(button)
        left_layout.addWidget(self.nav_group)

        self.hero_card = QFrame(self)
        self.hero_card.setObjectName("heroCard")
        hero_layout = QVBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(18, 16, 18, 16)
        hero_layout.setSpacing(4)
        self.hero_eyebrow = QLabel("Panel Bot", self.hero_card)
        self.hero_eyebrow.setObjectName("heroEyebrow")
        self.hero_title = QLabel("Dasbor Bot", self.hero_card)
        self.hero_title.setObjectName("heroTitle")
        self.hero_subtitle = QLabel(
            "Status sistem, kesiapan operator, dan kontrol trading terpusat di workspace ini.",
            self.hero_card,
        )
        self.hero_subtitle.setObjectName("heroSubtitle")
        self.hero_subtitle.setWordWrap(True)
        hero_layout.addWidget(self.hero_eyebrow)
        hero_layout.addWidget(self.hero_title)
        hero_layout.addWidget(self.hero_subtitle)
        self.mode_badge = QLabel("OPERATOR MODE", self.hero_card)
        self.mode_badge.setObjectName("chipValue")
        hero_layout.addWidget(self.mode_badge, 0, Qt.AlignLeft)
        self.top_status_row = QGridLayout()
        self.top_status_row.setHorizontalSpacing(10)
        self.top_status_row.setVerticalSpacing(10)
        hero_layout.addLayout(self.top_status_row)
        self.app_bar_actions = QHBoxLayout()
        self.app_bar_actions.setSpacing(8)
        hero_layout.addLayout(self.app_bar_actions)
        self.reconnect_overlay = QFrame(self)
        self.reconnect_overlay.setObjectName("dataCardAccent")
        reconnect_layout = QVBoxLayout(self.reconnect_overlay)
        reconnect_layout.setContentsMargins(16, 16, 16, 16)
        reconnect_layout.setSpacing(6)
        self.reconnect_title = QLabel("Menunggu MetaTrader 5", self.reconnect_overlay)
        self.reconnect_title.setObjectName("cardTitle")
        self.reconnect_message = QLabel(
            "Terminal MT5 tidak tersedia. Trading dibekukan sampai koneksi kembali stabil.",
            self.reconnect_overlay,
        )
        self.reconnect_message.setWordWrap(True)
        reconnect_layout.addWidget(self.reconnect_title)
        reconnect_layout.addWidget(self.reconnect_message)
        self.reconnect_overlay.hide()
        right_layout.addWidget(self.reconnect_overlay)
        self.account_review_card = QFrame(self)
        self.account_review_card.setObjectName("dataCardAccent")
        account_review_layout = QVBoxLayout(self.account_review_card)
        account_review_layout.setContentsMargins(16, 16, 16, 16)
        account_review_layout.setSpacing(6)
        self.account_review_title = QLabel("Review Perubahan Akun", self.account_review_card)
        self.account_review_title.setObjectName("cardTitle")
        self.account_review_message = QLabel(
            "Aplikasi mendeteksi akun MT5 baru. Review context akun sebelum trading dilanjutkan.",
            self.account_review_card,
        )
        self.account_review_message.setWordWrap(True)
        self.account_review_old = QLabel("-", self.account_review_card)
        self.account_review_new = QLabel("-", self.account_review_card)
        self.account_review_context = QLabel("Context akun belum dimuat.", self.account_review_card)
        self.account_review_context.setWordWrap(True)
        account_review_layout.addWidget(self.account_review_title)
        account_review_layout.addWidget(self.account_review_message)
        account_review_layout.addWidget(self.account_review_old)
        account_review_layout.addWidget(self.account_review_new)
        account_review_layout.addWidget(self.account_review_context)
        review_button_row = QHBoxLayout()
        self.account_review_use_button = QPushButton("Gunakan akun ini", self.account_review_card)
        self.account_review_cancel_button = QPushButton("Batalkan", self.account_review_card)
        self.account_review_select_button = QPushButton("Pilih context akun", self.account_review_card)
        self.account_review_new_context_button = QPushButton("Buat context baru", self.account_review_card)
        for button in (
            self.account_review_use_button,
            self.account_review_cancel_button,
            self.account_review_select_button,
            self.account_review_new_context_button,
        ):
            review_button_row.addWidget(button)
        review_button_row.addStretch(1)
        account_review_layout.addLayout(review_button_row)
        self.account_review_card.hide()
        right_layout.addWidget(self.account_review_card)
        right_layout.addWidget(self.hero_card)

        self.service_group = QGroupBox("Backend Service", self)
        self.service_group.setObjectName("sidebarPanel")
        service_form = QFormLayout(self.service_group)
        self._configure_form_layout(service_form)
        self.service_host_input = QLineEdit("127.0.0.1", self)
        self.service_port_input = QLineEdit("8765", self)
        service_form.addRow("Host", self.service_host_input)
        service_form.addRow("Port", self.service_port_input)
        left_layout.addWidget(self.service_group)

        self.trade_group = QGroupBox("Parameter Trading", self)
        trade_form = QFormLayout(self.trade_group)
        self._configure_form_layout(trade_form)
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
        self.db_input = QLineEdit(str(self.project_root / "bot_ea_runtime.db"), self)

        trade_form.addRow("Simbol", self.symbol_combo)
        trade_form.addRow("Timeframe", self.timeframe_combo)
        trade_form.addRow("Gaya Strategi", self.style_combo)
        trade_form.addRow(self.stop_label, self.stop_input)
        trade_form.addRow("Mode Modal", self.capital_mode_combo)
        trade_form.addRow("Modal Dipakai (USD)", self.capital_input)
        trade_form.addRow("Mode Lot", self.lot_mode_combo)
        trade_form.addRow("Request Lot Manual", self.manual_lot_input)
        trade_form.addRow("Sisi Order Manual", self.side_combo)
        trade_form.addRow("File Runtime DB", self.db_input)

        self.codex_group = QGroupBox("AI Runtime", self)
        codex_form = QFormLayout(self.codex_group)
        self._configure_form_layout(codex_form)
        self.codex_command_input = QLineEdit("codex", self)
        self.model_combo = QComboBox(self)
        self.model_combo.setEditable(True)
        self.model_combo.addItems(self.CODEX_MODEL_PRESETS)
        self.model_combo.setCurrentText("gpt-5.4-mini")
        self.codex_cwd_input = QLineEdit(str(self.project_root / "ai_workspace"), self)
        self.ai_documents_input = QLineEdit(str(self.project_root / "ai_documents"), self)
        self.ai_context_input = QLineEdit(str(self.project_root / "ai_context"), self)
        self.timeout_input = QLineEdit("60", self)
        self.poll_interval_input = QLineEdit("30", self)
        codex_form.addRow("Command AI Runtime", self.codex_command_input)
        codex_form.addRow("Model Default", self.model_combo)
        codex_form.addRow("Workspace AI", self.codex_cwd_input)
        codex_form.addRow("Dokumen AI", self.ai_documents_input)
        codex_form.addRow("Context Root", self.ai_context_input)
        codex_form.addRow("Timeout (s)", self.timeout_input)
        codex_form.addRow("Cek Market Tiap (s)", self.poll_interval_input)

        self.action_group = QGroupBox("Tombol Eksekusi", self)
        action_layout = QGridLayout(self.action_group)
        action_layout.setHorizontalSpacing(10)
        action_layout.setVerticalSpacing(10)
        self.connect_service_button = QPushButton("Service", self)
        self.check_mt5_button = QPushButton("Cek MT5", self)
        self.load_codex_button = QPushButton("Cek AI Runtime", self)
        self.refresh_button = QPushButton("Refresh Data", self)
        self.preflight_button = QPushButton("Cek Safety", self)
        self.execute_button = QPushButton("Eksekusi Order", self)
        self.play_button = QPushButton("Mulai Bot", self)
        self.stop_button = QPushButton("Berhenti Bot", self)
        self.live_button = QPushButton("Aktifkan Live", self)
        self.approve_button = QPushButton("Setujui Proposal", self)
        self.reject_button = QPushButton("Tolak Proposal", self)
        self.load_telemetry_button = QPushButton("Lihat Telemetri", self)
        for button, tooltip in (
            (self.connect_service_button, "Start or connect the websocket service"),
            (self.refresh_button, "Refresh manual preview from broker snapshot"),
            (self.execute_button, "Execute a manual order when runtime is idle"),
            (self.live_button, "Arm or disarm live runtime submissions"),
            (self.approve_button, "Approve the pending live order"),
            (self.reject_button, "Reject the pending live order"),
            (self.load_telemetry_button, "Load runtime telemetry and validation"),
        ):
            button.setToolTip(tooltip)
        self.sidebar_actions_group = QGroupBox("Tindakan Cepat", self)
        self.sidebar_actions_group.setObjectName("sidebarPanel")
        sidebar_actions_layout = QVBoxLayout(self.sidebar_actions_group)
        sidebar_actions_layout.setContentsMargins(12, 20, 12, 12)
        sidebar_actions_layout.setSpacing(8)
        for button in (
            self.connect_service_button,
            self.play_button,
            self.stop_button,
            self.live_button,
            self.load_telemetry_button,
            self.runbook_button,
        ):
            sidebar_actions_layout.addWidget(button)
        left_layout.addWidget(self.sidebar_actions_group)
        self.sidebar_summary_card = QFrame(self)
        self.sidebar_summary_card.setObjectName("metricCard")
        sidebar_summary_layout = QVBoxLayout(self.sidebar_summary_card)
        sidebar_summary_layout.setContentsMargins(14, 14, 14, 14)
        sidebar_summary_layout.setSpacing(4)
        self.sidebar_mode_label = QLabel("Current page", self.sidebar_summary_card)
        self.sidebar_mode_label.setObjectName("metricTitle")
        self.sidebar_mode_value = QLabel("Dasbor", self.sidebar_summary_card)
        self.sidebar_mode_value.setObjectName("metricValue")
        self.sidebar_endpoint_note = QLabel("Runtime endpoint not connected", self.sidebar_summary_card)
        self.sidebar_endpoint_note.setObjectName("cardCaption")
        self.sidebar_endpoint_note.setWordWrap(True)
        sidebar_summary_layout.addWidget(self.sidebar_mode_label)
        sidebar_summary_layout.addWidget(self.sidebar_mode_value)
        sidebar_summary_layout.addWidget(self.sidebar_endpoint_note)
        left_layout.addWidget(self.sidebar_summary_card)
        for idx, button in enumerate(
            [
                self.check_mt5_button,
                self.load_codex_button,
                self.refresh_button,
                self.preflight_button,
                self.execute_button,
                self.approve_button,
                self.reject_button,
            ]
        ):
            action_layout.addWidget(button, idx // 2, idx % 2)
        action_layout.setColumnStretch(0, 1)
        action_layout.setColumnStretch(1, 1)
        left_layout.addStretch(1)

        self.status_group = QGroupBox("Status Kesiapan", self)
        status_grid = QGridLayout(self.status_group)
        status_grid.setContentsMargins(10, 18, 10, 10)
        status_grid.setHorizontalSpacing(12)
        status_grid.setVerticalSpacing(12)
        self.service_status = QLabel("Service disconnected", self)
        self.mt5_status = QLabel("MT5 belum dicek", self)
        self.codex_status = QLabel("AI runtime belum dicek", self)
        self.runtime_status = QLabel("Bot berhenti", self)
        self.run_id_status = QLabel("-", self)
        self.approval_status = QLabel("No pending live approval", self)
        self.readiness_chips = {
            "service": {"frame": self._make_status_chip("Service", self.service_status), "value": self.service_status},
            "mt5": {"frame": self._make_status_chip("MT5", self.mt5_status), "value": self.mt5_status},
            "codex": {"frame": self._make_status_chip("AI Runtime", self.codex_status), "value": self.codex_status},
            "runtime": {"frame": self._make_status_chip("Bot", self.runtime_status), "value": self.runtime_status},
            "approval": {"frame": self._make_status_chip("Approval", self.approval_status), "value": self.approval_status},
        }
        self.run_id_card = self._make_metric_card("Run ID", self.run_id_status, "Active runtime session / audit cursor")
        for idx, key in enumerate(("service", "mt5", "codex", "runtime", "approval")):
            self.top_status_row.addWidget(self.readiness_chips[key]["frame"], idx // 3, idx % 3)
        for button in (self.check_mt5_button, self.load_codex_button, self.refresh_button):
            self.app_bar_actions.addWidget(button)
        self.app_bar_actions.addStretch(1)

        self.status_group_summary = QLabel(
            "Top app bar carries live readiness chips. This panel keeps the active run cursor and dashboard guidance.",
            self.status_group,
        )
        self.status_group_summary.setObjectName("cardCaption")
        self.status_group_summary.setWordWrap(True)
        status_grid.addWidget(self.run_id_card, 0, 0, 1, 2)
        status_grid.addWidget(self.status_group_summary, 1, 0, 1, 2)

        self.page_stack = QStackedWidget(self)
        right_layout.addWidget(self.page_stack, 1)

        self.trade_control_panel = QFrame(self)
        self.trade_control_panel.setObjectName("dataCard")
        trade_control_layout = QVBoxLayout(self.trade_control_panel)
        trade_control_layout.setContentsMargins(14, 14, 14, 14)
        trade_control_layout.setSpacing(10)
        trade_panel_title = QLabel("Panel Bot", self.trade_control_panel)
        trade_panel_title.setObjectName("cardTitle")
        trade_panel_caption = QLabel(
            "Kontrol trading, konfigurasi runtime, dan alur approval operator.",
            self.trade_control_panel,
        )
        trade_panel_caption.setObjectName("cardCaption")
        trade_panel_caption.setWordWrap(True)
        trade_control_layout.addWidget(trade_panel_title)
        trade_control_layout.addWidget(trade_panel_caption)
        trade_control_layout.addWidget(self.trade_group)
        trade_control_layout.addWidget(self.action_group)
        self.hint_label = QLabel(
            "Operator hint: manual lot requests are still normalized by broker/capital constraints from the backend preview.",
            self.trade_control_panel,
        )
        self.hint_label.setObjectName("heroSubtitle")
        self.hint_label.setWordWrap(True)
        trade_control_layout.addWidget(self.hint_label)
        trade_control_layout.addStretch(1)
        self.trade_control_scroll = QScrollArea(self)
        self.trade_control_scroll.setWidgetResizable(True)
        self.trade_control_scroll.setWidget(self.trade_control_panel)
        self.trade_control_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.snapshot_dashboard = QFrame(self)
        self.snapshot_dashboard.setObjectName("dataCard")
        snapshot_dashboard_layout = QVBoxLayout(self.snapshot_dashboard)
        snapshot_dashboard_layout.setContentsMargins(14, 14, 14, 14)
        snapshot_dashboard_layout.setSpacing(12)
        snapshot_dashboard_title = QLabel("Kartu Ringkasan", self.snapshot_dashboard)
        snapshot_dashboard_title.setObjectName("cardTitle")
        snapshot_dashboard_caption = QLabel(
            "Status market, ringkasan order, dan proyeksi sizing/risk yang aktif.",
            self.snapshot_dashboard,
        )
        snapshot_dashboard_caption.setObjectName("cardCaption")
        snapshot_dashboard_caption.setWordWrap(True)
        snapshot_dashboard_layout.addWidget(snapshot_dashboard_title)
        snapshot_dashboard_layout.addWidget(snapshot_dashboard_caption)
        snapshot_dashboard_layout.addWidget(self.status_group)

        summary_row = QGridLayout()
        summary_row.setHorizontalSpacing(12)
        summary_row.setVerticalSpacing(12)
        self.market_card = self._make_text_card("Ringkasan Pasar", "Symbol/tick realtime dan konteks broker")
        self.manual_card = self._make_text_card("Ringkasan Order", "Lot final, margin, dan jalur order manual")
        self.risk_card = self._make_text_card("Batas Risiko", "Sizing, loss budget, dan blocker")
        summary_row.addWidget(self.market_card["frame"], 0, 0, 1, 2)
        summary_row.addWidget(self.manual_card["frame"], 1, 0)
        summary_row.addWidget(self.risk_card["frame"], 1, 1)
        snapshot_dashboard_layout.addLayout(summary_row)
        self.logs_group = QGroupBox("Telemetry / Logs", self)
        logs_layout = QVBoxLayout(self.logs_group)
        logs_layout.setContentsMargins(10, 18, 10, 10)
        self.tabs = QTabWidget(self)
        self.runtime_text = QPlainTextEdit(self)
        self.runtime_text.setReadOnly(True)
        self.validation_text = QPlainTextEdit(self)
        self.validation_text.setReadOnly(True)
        self.events_text = QPlainTextEdit(self)
        self.events_text.setReadOnly(True)
        self.tabs.addTab(self.runtime_text, "Feed Runtime")
        self.tabs.addTab(self.events_text, "Konsol Log")
        logs_layout.addWidget(self.tabs)

        self.dashboard_page = QWidget(self)
        dashboard_page_layout = QVBoxLayout(self.dashboard_page)
        dashboard_page_layout.setContentsMargins(0, 0, 0, 0)
        dashboard_page_layout.setSpacing(12)
        dashboard_title = QLabel("Ikhtisar Dasbor", self.dashboard_page)
        dashboard_title.setObjectName("cardTitle")
        dashboard_caption = QLabel(
            "Status sistem, snapshot market, dan ringkasan operator dalam satu tempat.",
            self.dashboard_page,
        )
        dashboard_caption.setObjectName("cardCaption")
        dashboard_caption.setWordWrap(True)
        self.dashboard_overview_frame = QFrame(self.dashboard_page)
        self.dashboard_overview_frame.setObjectName("dataCardAccent")
        dashboard_overview_layout = QGridLayout(self.dashboard_overview_frame)
        dashboard_overview_layout.setContentsMargins(14, 14, 14, 14)
        dashboard_overview_layout.setHorizontalSpacing(12)
        dashboard_overview_layout.setVerticalSpacing(12)
        self.dashboard_connection_value = QLabel("Offline", self.dashboard_overview_frame)
        self.dashboard_symbol_value = QLabel("EURUSD", self.dashboard_overview_frame)
        self.dashboard_lot_value = QLabel("--", self.dashboard_overview_frame)
        self.dashboard_risk_value = QLabel("--", self.dashboard_overview_frame)
        self.dashboard_mode_value = QLabel("Idle", self.dashboard_overview_frame)
        self.dashboard_spread_value = QLabel("--", self.dashboard_overview_frame)
        dashboard_overview_layout.addWidget(
            self._make_metric_card("Connection", self.dashboard_connection_value, "Transport + runtime readiness"),
            0,
            0,
        )
        dashboard_overview_layout.addWidget(
            self._make_metric_card("Focus Symbol", self.dashboard_symbol_value, "Current symbol and side context"),
            0,
            1,
        )
        dashboard_overview_layout.addWidget(
            self._make_metric_card("Manual Lot", self.dashboard_lot_value, "Normalized order size from preview"),
            1,
            0,
        )
        dashboard_overview_layout.addWidget(
            self._make_metric_card("Risk Budget", self.dashboard_risk_value, "Current risk budget from sizing snapshot"),
            1,
            1,
        )
        dashboard_overview_layout.addWidget(
            self._make_metric_card("Runtime Mode", self.dashboard_mode_value, "Idle, dry-run, or live runtime posture"),
            0,
            2,
        )
        dashboard_overview_layout.addWidget(
            self._make_metric_card("Spread", self.dashboard_spread_value, "Latest spread observed on the focused symbol"),
            1,
            2,
        )
        self.dashboard_story_card = QFrame(self.dashboard_page)
        self.dashboard_story_card.setObjectName("dataCard")
        dashboard_story_layout = QVBoxLayout(self.dashboard_story_card)
        dashboard_story_layout.setContentsMargins(14, 14, 14, 14)
        dashboard_story_layout.setSpacing(6)
        self.dashboard_story_title = QLabel("Mission Control", self.dashboard_story_card)
        self.dashboard_story_title.setObjectName("cardTitle")
        self.dashboard_story_caption = QLabel(
            "Use this surface as the operator landing page: confirm transport, inspect market state, then branch into Strategy or History.",
            self.dashboard_story_card,
        )
        self.dashboard_story_caption.setObjectName("cardCaption")
        self.dashboard_story_caption.setWordWrap(True)
        self.dashboard_story_text = QPlainTextEdit(self.dashboard_story_card)
        self.dashboard_story_text.setReadOnly(True)
        self.dashboard_story_text.setMaximumBlockCount(120)
        dashboard_story_layout.addWidget(self.dashboard_story_title)
        dashboard_story_layout.addWidget(self.dashboard_story_caption)
        dashboard_story_layout.addWidget(self.dashboard_story_text)
        dashboard_page_layout.addWidget(dashboard_title)
        dashboard_page_layout.addWidget(dashboard_caption)
        dashboard_page_layout.addWidget(self.dashboard_overview_frame)
        dashboard_page_layout.addWidget(self.dashboard_story_card)
        dashboard_page_layout.addWidget(self.snapshot_dashboard, 1)

        self.strategy_page = QWidget(self)
        strategy_page_layout = QVBoxLayout(self.strategy_page)
        strategy_page_layout.setContentsMargins(0, 0, 0, 0)
        strategy_page_layout.setSpacing(12)
        strategy_title = QLabel("Strategy Workspace", self.strategy_page)
        strategy_title.setObjectName("cardTitle")
        strategy_caption = QLabel(
            "Configure trade setup, capital management, and execution controls from one focused page.",
            self.strategy_page,
        )
        strategy_caption.setObjectName("cardCaption")
        strategy_caption.setWordWrap(True)
        self.strategy_metric_row = QGridLayout()
        self.strategy_metric_row.setHorizontalSpacing(12)
        self.strategy_metric_row.setVerticalSpacing(12)
        self.strategy_style_value = QLabel(self.style_combo.currentText(), self.strategy_page)
        self.strategy_side_value = QLabel(self.side_combo.currentText(), self.strategy_page)
        self.strategy_live_value = QLabel("Disabled", self.strategy_page)
        self.strategy_metric_row.addWidget(
            self._make_metric_card("Style", self.strategy_style_value, "Active trading style for the focused setup"),
            0,
            0,
        )
        self.strategy_metric_row.addWidget(
            self._make_metric_card("Manual Side", self.strategy_side_value, "Manual execution side when action is allowed"),
            0,
            1,
        )
        self.strategy_metric_row.addWidget(
            self._make_metric_card("Live Toggle", self.strategy_live_value, "Live runtime submission state"),
            0,
            2,
        )
        self.strategy_note_card = QFrame(self.strategy_page)
        self.strategy_note_card.setObjectName("dataCard")
        strategy_note_layout = QVBoxLayout(self.strategy_note_card)
        strategy_note_layout.setContentsMargins(14, 14, 14, 14)
        strategy_note_layout.setSpacing(6)
        strategy_note_title = QLabel("Execution Lane", self.strategy_note_card)
        strategy_note_title.setObjectName("cardTitle")
        strategy_note_caption = QLabel(
            "Strategy keeps every setup control in one scrollable lane so the operator can work top-to-bottom without losing context.",
            self.strategy_note_card,
        )
        strategy_note_caption.setObjectName("cardCaption")
        strategy_note_caption.setWordWrap(True)
        strategy_note_layout.addWidget(strategy_note_title)
        strategy_note_layout.addWidget(strategy_note_caption)
        strategy_page_layout.addWidget(strategy_title)
        strategy_page_layout.addWidget(strategy_caption)
        strategy_page_layout.addLayout(self.strategy_metric_row)
        strategy_page_layout.addWidget(self.strategy_note_card)
        strategy_page_layout.addWidget(self.trade_control_scroll, 1)

        self.history_page = QWidget(self)
        history_page_layout = QVBoxLayout(self.history_page)
        history_page_layout.setContentsMargins(0, 0, 0, 0)
        history_page_layout.setSpacing(12)
        history_title = QLabel("History + Validation", self.history_page)
        history_title.setObjectName("cardTitle")
        history_caption = QLabel(
            "Use telemetry loads to inspect validation output and historical runtime notes.",
            self.history_page,
        )
        history_caption.setObjectName("cardCaption")
        history_caption.setWordWrap(True)
        self.history_metric_row = QGridLayout()
        self.history_metric_row.setHorizontalSpacing(12)
        self.history_metric_row.setVerticalSpacing(12)
        self.history_status_value = QLabel("No run loaded", self.history_page)
        self.history_action_value = QLabel("NO_TRADE", self.history_page)
        self.history_trade_count_value = QLabel("--", self.history_page)
        self.history_expectancy_value = QLabel("--", self.history_page)
        self.history_metric_row.addWidget(
            self._make_metric_card("Run Status", self.history_status_value, "Latest telemetry status"),
            0,
            0,
        )
        self.history_metric_row.addWidget(
            self._make_metric_card("Last Action", self.history_action_value, "Latest recorded runtime decision"),
            0,
            1,
        )
        self.history_metric_row.addWidget(
            self._make_metric_card("Trades", self.history_trade_count_value, "Validated trade count"),
            0,
            2,
        )
        self.history_metric_row.addWidget(
            self._make_metric_card("Expectancy", self.history_expectancy_value, "Validation expectancy in R"),
            0,
            3,
        )
        self.history_operator_note = QFrame(self.history_page)
        self.history_operator_note.setObjectName("dataCard")
        history_operator_layout = QVBoxLayout(self.history_operator_note)
        history_operator_layout.setContentsMargins(14, 14, 14, 14)
        history_operator_layout.setSpacing(6)
        history_operator_title = QLabel("Review Notes", self.history_operator_note)
        history_operator_title.setObjectName("cardTitle")
        self.history_operator_text = QLabel(
            "Telemetry loads here after a run; treat this page as post-trade review, not live execution.",
            self.history_operator_note,
        )
        self.history_operator_text.setObjectName("cardCaption")
        self.history_operator_text.setWordWrap(True)
        history_operator_layout.addWidget(history_operator_title)
        history_operator_layout.addWidget(self.history_operator_text)
        self.history_panel = QFrame(self)
        self.history_panel.setObjectName("dataCard")
        history_panel_layout = QVBoxLayout(self.history_panel)
        history_panel_layout.setContentsMargins(14, 14, 14, 14)
        history_panel_layout.setSpacing(10)
        self.history_load_button = QPushButton("Load Telemetry", self.history_panel)
        self.history_summary_text = QPlainTextEdit(self.history_panel)
        self.history_summary_text.setReadOnly(True)
        self.history_summary_text.setMaximumBlockCount(200)
        self.history_splitter = QSplitter(Qt.Horizontal, self.history_panel)
        self.history_summary_card = QFrame(self.history_splitter)
        self.history_summary_card.setObjectName("dataCard")
        history_summary_card_layout = QVBoxLayout(self.history_summary_card)
        history_summary_card_layout.setContentsMargins(12, 12, 12, 12)
        history_summary_card_layout.setSpacing(8)
        history_summary_card_layout.addWidget(self.history_load_button)
        history_summary_card_layout.addWidget(self.history_summary_text, 1)
        self.history_validation_card = QFrame(self.history_splitter)
        self.history_validation_card.setObjectName("dataCard")
        history_validation_card_layout = QVBoxLayout(self.history_validation_card)
        history_validation_card_layout.setContentsMargins(12, 12, 12, 12)
        history_validation_card_layout.setSpacing(8)
        history_validation_title = QLabel("Validation Detail", self.history_validation_card)
        history_validation_title.setObjectName("cardTitle")
        history_validation_card_layout.addWidget(history_validation_title)
        history_validation_card_layout.addWidget(self.validation_text, 1)
        self.history_splitter.addWidget(self.history_summary_card)
        self.history_splitter.addWidget(self.history_validation_card)
        self.history_splitter.setSizes([420, 720])
        history_page_layout.addWidget(history_title)
        history_page_layout.addWidget(history_caption)
        history_page_layout.addLayout(self.history_metric_row)
        history_page_layout.addWidget(self.history_operator_note)
        history_page_layout.addWidget(self.history_panel, 1)
        history_panel_layout.addWidget(self.history_splitter, 1)

        self.logs_page = QWidget(self)
        logs_page_layout = QVBoxLayout(self.logs_page)
        logs_page_layout.setContentsMargins(0, 0, 0, 0)
        logs_page_layout.setSpacing(12)
        self.logs_metric_row = QGridLayout()
        self.logs_metric_row.setHorizontalSpacing(12)
        self.logs_metric_row.setVerticalSpacing(12)
        self.logs_endpoint_value = QLabel("Disconnected", self.logs_page)
        self.logs_runtime_value = QLabel("Stopped", self.logs_page)
        self.logs_tick_value = QLabel("n/a", self.logs_page)
        self.logs_metric_row.addWidget(
            self._make_metric_card("Endpoint", self.logs_endpoint_value, "Connected websocket service"),
            0,
            0,
        )
        self.logs_metric_row.addWidget(
            self._make_metric_card("Runtime", self.logs_runtime_value, "Runtime loop and live mode status"),
            0,
            1,
        )
        self.logs_metric_row.addWidget(
            self._make_metric_card("Last Tick", self.logs_tick_value, "Most recent market tick seen in UI"),
            0,
            2,
        )
        self.logs_operator_note = QFrame(self.logs_page)
        self.logs_operator_note.setObjectName("dataCard")
        logs_operator_note_layout = QVBoxLayout(self.logs_operator_note)
        logs_operator_note_layout.setContentsMargins(14, 14, 14, 14)
        logs_operator_note_layout.setSpacing(6)
        logs_operator_title = QLabel("Operator Log Deck", self.logs_operator_note)
        logs_operator_title.setObjectName("cardTitle")
        logs_operator_caption = QLabel(
            "Runtime feed stays on one tab, event console on another. Use this page as the focused audit surface during sessions.",
            self.logs_operator_note,
        )
        logs_operator_caption.setObjectName("cardCaption")
        logs_operator_caption.setWordWrap(True)
        logs_operator_note_layout.addWidget(logs_operator_title)
        logs_operator_note_layout.addWidget(logs_operator_caption)
        self.logs_focus_panel = QFrame(self.logs_page)
        self.logs_focus_panel.setObjectName("dataCardAccent")
        logs_focus_layout = QHBoxLayout(self.logs_focus_panel)
        logs_focus_layout.setContentsMargins(14, 14, 14, 14)
        logs_focus_layout.setSpacing(12)
        self.logs_focus_primary = QLabel("Watch runtime feed for execution phase changes.", self.logs_focus_panel)
        self.logs_focus_primary.setObjectName("cardTitle")
        self.logs_focus_secondary = QLabel(
            "Use Log Console for operator breadcrumbs and runtime incidents.",
            self.logs_focus_panel,
        )
        self.logs_focus_secondary.setObjectName("cardCaption")
        self.logs_focus_secondary.setWordWrap(True)
        logs_focus_layout.addWidget(self.logs_focus_primary, 1)
        logs_focus_layout.addWidget(self.logs_focus_secondary, 1)
        logs_page_layout.addLayout(self.logs_metric_row)
        logs_page_layout.addWidget(self.logs_operator_note)
        logs_page_layout.addWidget(self.logs_focus_panel)
        logs_page_layout.addWidget(self.logs_group, 1)

        self.settings_page = QWidget(self)
        settings_page_layout = QVBoxLayout(self.settings_page)
        settings_page_layout.setContentsMargins(0, 0, 0, 0)
        settings_page_layout.setSpacing(12)
        settings_title = QLabel("Settings + Transport", self.settings_page)
        settings_title.setObjectName("cardTitle")
        settings_caption = QLabel(
            "Manage websocket transport, Codex defaults, and service ownership from this page.",
            self.settings_page,
        )
        settings_caption.setObjectName("cardCaption")
        settings_caption.setWordWrap(True)
        self.settings_metric_row = QGridLayout()
        self.settings_metric_row.setHorizontalSpacing(12)
        self.settings_metric_row.setVerticalSpacing(12)
        self.settings_endpoint_value = QLabel("ws://127.0.0.1:8765", self.settings_page)
        self.settings_model_value = QLabel(self.model_combo.currentText() or "default", self.settings_page)
        self.settings_poll_value = QLabel(self.poll_interval_input.text(), self.settings_page)
        self.settings_db_value = QLabel(Path(self.db_input.text()).name, self.settings_page)
        self.settings_metric_row.addWidget(
            self._make_metric_card("Endpoint", self.settings_endpoint_value, "Current websocket target"),
            0,
            0,
        )
        self.settings_metric_row.addWidget(
            self._make_metric_card("Model", self.settings_model_value, "Codex model preset for runtime"),
            0,
            1,
        )
        self.settings_metric_row.addWidget(
            self._make_metric_card("Poll (s)", self.settings_poll_value, "Runtime market polling interval"),
            0,
            2,
        )
        self.settings_metric_row.addWidget(
            self._make_metric_card("DB", self.settings_db_value, "Runtime database file"),
            0,
            3,
        )
        self.settings_panel = QFrame(self)
        self.settings_panel.setObjectName("dataCard")
        settings_panel_layout = QVBoxLayout(self.settings_panel)
        settings_panel_layout.setContentsMargins(14, 14, 14, 14)
        settings_panel_layout.setSpacing(12)
        self.settings_summary_text = QPlainTextEdit(self.settings_panel)
        self.settings_summary_text.setReadOnly(True)
        self.settings_summary_text.setMaximumBlockCount(100)
        self.settings_operator_note = QLabel(
            "Settings is the transport rack: endpoint, Codex defaults, poll cadence, and runtime database location.",
            self.settings_panel,
        )
        self.settings_operator_note.setObjectName("cardCaption")
        self.settings_operator_note.setWordWrap(True)
        settings_panel_layout.addWidget(self.service_group)
        settings_panel_layout.addWidget(self.codex_group)
        settings_panel_layout.addWidget(self.settings_operator_note)
        settings_panel_layout.addWidget(self.settings_summary_text)
        settings_panel_layout.addStretch(1)
        settings_page_layout.addWidget(settings_title)
        settings_page_layout.addWidget(settings_caption)
        settings_page_layout.addLayout(self.settings_metric_row)
        settings_page_layout.addWidget(self.settings_panel, 1)

        for page in (
            self.dashboard_page,
            self.strategy_page,
            self.history_page,
            self.logs_page,
            self.settings_page,
        ):
            self.page_stack.addWidget(page)
        self.shell_stack.addWidget(self.workspace_page)
        self.shell_stack.setCurrentWidget(self.startup_gate_page)
        self._sync_button_states()

    def _apply_runtime_settings_to_form(self) -> None:
        settings = self.runtime_settings
        self.service_host_input.setText(settings.service_host)
        self.service_port_input.setText(str(settings.service_port))
        self.codex_command_input.setText(settings.ai_runtime_command)
        self.model_combo.setCurrentText(settings.default_model)
        self.codex_cwd_input.setText(settings.ai_workspace_path)
        self.ai_documents_input.setText(settings.ai_documents_path)
        self.ai_context_input.setText(settings.ai_context_root)
        self.poll_interval_input.setText(str(settings.poll_interval_seconds))
        self.timeout_input.setText(str(settings.timeout_seconds))
        self.db_input.setText(settings.db_path)
        self.symbol_combo.setCurrentText(settings.symbol)
        self.timeframe_combo.setCurrentText(settings.timeframe)
        self.style_combo.setCurrentText(settings.trading_style)
        self.stop_input.setText(f"{settings.stop_distance_points:.0f}")
        self.capital_mode_combo.setCurrentText(settings.capital_mode)
        self.capital_input.setText(f"{settings.capital_value:.0f}")

    def _collect_runtime_settings_from_form(self) -> OperatorRuntimeSettings:
        return OperatorRuntimeSettings(
            mode="dev" if self._dev_mode_enabled else "operator",
            ai_runtime_command=self.codex_command_input.text().strip() or "codex",
            ai_runtime_executable_path="",
            ai_workspace_path=self.codex_cwd_input.text().strip() or str(self.project_root / "ai_workspace"),
            ai_documents_path=self.ai_documents_input.text().strip() or str(self.project_root / "ai_documents"),
            ai_context_root=self.ai_context_input.text().strip() or str(self.project_root / "ai_context"),
            default_model=self._optional_str(self.model_combo.currentText()) or "gpt-5.4-mini",
            timeout_seconds=max(int(self._float_or_default(self.timeout_input.text(), default=60.0)), 1),
            strict_startup_gate=not self._dev_mode_enabled,
            allow_dev_bypass=True,
            service_host=self.service_host_input.text().strip() or "127.0.0.1",
            service_port=int(self.service_port_input.text().strip() or "8765"),
            db_path=str(Path(self.db_input.text().strip() or "bot_ea_runtime.db").expanduser()),
            poll_interval_seconds=max(int(self._float_or_default(self.poll_interval_input.text(), default=30.0)), 1),
            symbol=self.symbol_combo.currentText().strip() or "EURUSD",
            timeframe=self.timeframe_combo.currentText().strip() or "M15",
            trading_style=self.style_combo.currentText().strip() or "intraday",
            stop_distance_points=self._current_stop_distance_value(),
            capital_mode=self.capital_mode_combo.currentText(),
            capital_value=self._capital_allocation().value,
        )

    def _persist_runtime_settings(self) -> None:
        self.runtime_settings = self._collect_runtime_settings_from_form()
        self.state_store.save_runtime_settings(self.runtime_settings)

    def _apply_accessibility_defaults(self) -> None:
        self.gate_primary_button.setAccessibleName("Mulai pemeriksaan dependency")
        self.gate_retry_button.setAccessibleName("Coba lagi pemeriksaan dependency")
        self.gate_dev_button.setAccessibleName("Masuk mode dev")
        self.codex_command_input.setAccessibleName("Command AI runtime")
        self.codex_cwd_input.setAccessibleName("Workspace AI")
        self.ai_documents_input.setAccessibleName("Dokumen AI")
        self.ai_context_input.setAccessibleName("Folder context AI")
        self.timeout_input.setAccessibleName("Timeout AI runtime")
        self.check_mt5_button.setAccessibleName("Cek MT5")
        self.load_codex_button.setAccessibleName("Cek AI runtime")
        self.refresh_button.setAccessibleName("Refresh data")
        QWidget.setTabOrder(self.gate_primary_button, self.gate_retry_button)
        QWidget.setTabOrder(self.gate_retry_button, self.gate_dev_button)
        QWidget.setTabOrder(self.check_mt5_button, self.load_codex_button)
        QWidget.setTabOrder(self.load_codex_button, self.refresh_button)

    def _make_text_card(self, title: str, caption: str) -> dict[str, QWidget | QPlainTextEdit]:
        frame = QFrame(self)
        frame.setObjectName("dataCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)
        title_label = QLabel(title, frame)
        title_label.setObjectName("cardTitle")
        caption_label = QLabel(caption, frame)
        caption_label.setObjectName("cardCaption")
        caption_label.setWordWrap(True)
        text = QPlainTextEdit(self)
        text.setReadOnly(True)
        text.setMaximumBlockCount(200)
        layout.addWidget(title_label)
        layout.addWidget(caption_label)
        layout.addWidget(text)
        return {"frame": frame, "text": text, "title": title_label, "caption": caption_label}

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _set_chip_tone(self, chip_key: str, tone: str) -> None:
        chip = self.readiness_chips[chip_key]
        chip["value"].setProperty("tone", tone)
        self._repolish(chip["value"])

    def _set_metric_tone(self, tone: str) -> None:
        self.run_id_status.setProperty("tone", tone)
        self._repolish(self.run_id_status)

    def _refresh_status_presentation(self) -> None:
        self._set_chip_tone("service", "ok" if self._service_connected else "warn")
        mt5_text = self.mt5_status.text().lower()
        if "ready" in mt5_text:
            self._set_chip_tone("mt5", "ok")
        elif "unchecked" in mt5_text or "belum" in mt5_text:
            self._set_chip_tone("mt5", "idle")
        else:
            self._set_chip_tone("mt5", "warn")

        codex_text = self.codex_status.text().lower()
        if "unchecked" in codex_text or "belum" in codex_text:
            self._set_chip_tone("codex", "idle")
        elif "error" in codex_text or "failed" in codex_text:
            self._set_chip_tone("codex", "warn")
        else:
            self._set_chip_tone("codex", "ok")

        if self._runtime_running:
            self._set_chip_tone("runtime", "live" if self._live_enabled else "ok")
        else:
            self._set_chip_tone("runtime", "idle")

        if self._pending_approval is not None:
            self._set_chip_tone("approval", "warn")
        elif "approved" in self.approval_status.text().lower():
            self._set_chip_tone("approval", "ok")
        else:
            self._set_chip_tone("approval", "idle")

        self._set_metric_tone("live" if self._runtime_running and self.run_id_status.text().strip() != "-" else "idle")
        self._refresh_page_summaries()

    def _refresh_page_summaries(self) -> None:
        current_page = self.nav_buttons[self.page_stack.currentIndex()].text() if self.nav_buttons else "Dashboard"
        self.sidebar_mode_value.setText(current_page)
        self.sidebar_endpoint_note.setText(self._service_url() if self._service_connected else "Runtime endpoint not connected")

        snapshot = self.snapshot or {}
        size_result = self.size_result or {}
        manual = self.manual_order_snapshot or {}
        self.dashboard_connection_value.setText("Connected" if self._service_connected else "Offline")
        self.dashboard_symbol_value.setText(str(snapshot.get("symbol") or self.symbol_combo.currentText() or "-"))
        final_lot = self._float_value(manual.get("final_lot"))
        self.dashboard_lot_value.setText(f"{final_lot:.2f}" if final_lot > 0 else "--")
        risk_budget = self._float_value(size_result.get("risk_cash_budget_usd"))
        self.dashboard_risk_value.setText(f"${risk_budget:.2f}" if risk_budget > 0 else "--")
        self.dashboard_mode_value.setText(
            "LIVE" if self._runtime_running and self._live_enabled else ("RUNNING" if self._runtime_running else "IDLE")
        )
        spread_points = self._float_value(snapshot.get("spread_points"))
        self.dashboard_spread_value.setText(f"{spread_points:.2f} pts" if spread_points > 0 else "--")
        self.dashboard_story_text.setPlainText(
            "\n".join(
                [
                    f"page={current_page}",
                    f"service={'connected' if self._service_connected else 'offline'}",
                    f"runtime={'live' if self._runtime_running and self._live_enabled else ('running' if self._runtime_running else 'idle')}",
                    f"symbol={snapshot.get('symbol') or self.symbol_combo.currentText() or '-'}",
                    f"manual_lot={final_lot:.2f}" if final_lot > 0 else "manual_lot=--",
                    f"approval={self.approval_status.text()}",
                    f"account={self._format_account_fingerprint(self._active_account_fingerprint)}",
                ]
            )
        )

        self.strategy_style_value.setText(self.style_combo.currentText())
        self.strategy_side_value.setText(self.side_combo.currentText())
        self.strategy_live_value.setText("Enabled" if self._live_enabled else "Disabled")

        overview = self._telemetry_overview or {}
        validation = self._telemetry_validation or {}
        self.history_status_value.setText(str(overview.get("status") or self.runtime_status.text() or "No run loaded"))
        self.history_action_value.setText(str(overview.get("last_action") or "NO_TRADE"))
        total_trades = validation.get("total_trades")
        self.history_trade_count_value.setText(str(total_trades) if total_trades is not None else "--")
        expectancy = validation.get("expectancy_r")
        expectancy_value = self._float_value(expectancy) if expectancy is not None else 0.0
        self.history_expectancy_value.setText(f"{expectancy_value:.2f}R" if expectancy is not None else "--")
        self.history_operator_text.setText(
            "Telemetry review ready."
            if overview
            else "Telemetry loads here after a run; treat this page as post-trade review, not live execution."
        )
        if not self.history_summary_text.toPlainText().strip():
            self.history_summary_text.setPlainText(
                "\n".join(
                    [
                        "Load telemetry to populate run summaries, validation context, and lifecycle highlights.",
                        "",
                        "This page is intended for historical review rather than live execution.",
                    ]
                )
            )

        self.logs_endpoint_value.setText("Managed" if self._managed_service_owned else ("Connected" if self._service_connected else "Offline"))
        self.logs_runtime_value.setText("Live" if self._runtime_running and self._live_enabled else ("Running" if self._runtime_running else "Stopped"))
        self.logs_tick_value.setText(str(snapshot.get("tick_time") or "n/a"))
        self.logs_focus_primary.setText(
            "Watch runtime feed for execution phase changes."
            if not self._runtime_running
            else f"Runtime active on {snapshot.get('symbol') or self.symbol_combo.currentText() or '-'}."
        )
        self.logs_focus_secondary.setText(
            f"Latest tick: {snapshot.get('tick_time') or 'n/a'} | Approval: {self.approval_status.text()}"
        )

        self.settings_endpoint_value.setText(self._service_url())
        self.settings_model_value.setText(self._optional_str(self.model_combo.currentText()) or "default")
        self.settings_poll_value.setText(self.poll_interval_input.text().strip() or "30")
        self.settings_db_value.setText(Path(self.db_input.text().strip() or "bot_ea_runtime.db").name)
        self.settings_summary_text.setPlainText(
            "\n".join(
                [
                    f"service_url={self._service_url()}",
                    f"service_mode={'managed' if self._managed_service_owned else 'external'}",
                    f"ai_runtime_command={self.codex_command_input.text().strip() or 'codex'}",
                    f"default_model={self._optional_str(self.model_combo.currentText()) or 'default'}",
                    f"ai_workspace={self._optional_str(self.codex_cwd_input.text()) or (self.project_root / 'ai_workspace')}",
                    f"ai_documents={self._optional_str(self.ai_documents_input.text()) or (self.project_root / 'ai_documents')}",
                    f"ai_context_root={self._optional_str(self.ai_context_input.text()) or (self.project_root / 'ai_context')}",
                    f"context_path={(self._active_context_binding or {}).get('context_path') or '-'}",
                    f"active_account={self._format_account_fingerprint(self._active_account_fingerprint)}",
                    f"poll_interval_seconds={self.poll_interval_input.text().strip() or '30'}",
                    f"timeout_seconds={self.timeout_input.text().strip() or '60'}",
                    f"runtime_db={self.db_input.text().strip()}",
                ]
            )
        )

    def _select_page(self, index: int) -> None:
        if self._startup_gate_active and not self._dev_mode_enabled:
            return
        if index < 0 or index >= self.page_stack.count():
            return
        self.page_stack.setCurrentIndex(index)
        for idx, button in enumerate(self.nav_buttons):
            button.setChecked(idx == index)
        page_titles = {
            0: ("Dasbor Bot", "Status sistem, ringkasan market, dan panduan operator."),
            1: ("Strategi", "Atur parameter trading, modal, dan tombol eksekusi."),
            2: ("Riwayat", "Tinjau validasi, telemetry, dan lifecycle trading."),
            3: ("Log", "Baca feed runtime dan event sistem tanpa meninggalkan workspace."),
            4: ("Pengaturan", "Kelola transport service dan default AI runtime."),
        }
        title, subtitle = page_titles.get(index, ("Dasbor Bot", self.hero_subtitle.text()))
        self.hero_title.setText(title)
        self.hero_subtitle.setText(subtitle)
        self._refresh_page_summaries()

    def _start_startup_gate(self) -> None:
        self._persist_runtime_settings()
        self._startup_gate_active = True
        self._startup_probe_inflight = False
        self._startup_requirements = {key: False for key in self.gate_step_labels}
        self._startup_requirement_details = {key: "Belum diperiksa" for key in self.gate_step_labels}
        self._startup_active_step = "service"
        self._mt5_ready = False
        self._codex_ready = False
        self._mt5_overlay_active = False
        self._account_review_active = False
        self.reconnect_overlay.hide()
        self.account_review_card.hide()
        self.shell_stack.setCurrentWidget(self.startup_gate_page)
        for key, label in self.gate_step_labels.items():
            self._set_startup_requirement(key, False, self._startup_requirement_details.get(key, "Belum diperiksa"))
        self._update_startup_gate_ui()
        QTimer.singleShot(0, self._run_startup_probe_sequence)

    def _startup_probe_steps(self) -> list[tuple[str, str, Any]]:
        return [
            ("service", "Menyalakan service lokal", self._probe_service_ready),
            ("mt5_process", "Menunggu MetaTrader 5", self._probe_mt5_process),
            ("mt5_session", "Membaca sesi MT5", self._probe_mt5_session),
            ("account", "Validasi akun aktif", self._probe_account_fingerprint),
            ("symbol", "Memuat simbol dasar", self._probe_symbol_baseline),
            ("ai_runtime", "Menemukan AI runtime", self._probe_ai_runtime),
            ("ai_workspace", "Validasi workspace AI", self._probe_ai_workspace),
            ("ai_documents", "Validasi dokumen AI", self._probe_ai_documents),
            ("ai_context", "Validasi context/history", self._probe_ai_context),
            ("storage", "Validasi storage", self._probe_storage),
            ("resume_state", "Menyiapkan resume state", self._build_resume_state),
        ]

    def _run_startup_probe_sequence(self) -> None:
        if self._startup_probe_inflight or self._dev_mode_enabled:
            return
        self._startup_probe_inflight = True
        try:
            for key, title, callback in self._startup_probe_steps():
                self._startup_active_step = key
                self.gate_message.setText(title)
                self._update_startup_gate_ui()
                try:
                    detail = callback()
                except Exception as exc:
                    self._set_startup_requirement(key, False, self._format_exception_detail(exc))
                    return
                self._set_startup_requirement(key, True, detail)
            self._set_startup_requirement("workspace", True, "Workspace utama siap dibuka.")
            self._unlock_workspace()
        finally:
            self._startup_probe_inflight = False
            self._update_startup_gate_ui()

    def _set_startup_requirement(self, name: str, ok: bool, detail: str) -> None:
        self._startup_requirements[name] = ok
        self._startup_requirement_details[name] = detail if detail else ("Siap" if ok else "Belum siap")
        label = self.gate_step_labels[name]
        label.setText(self._startup_requirement_details[name])
        tone = "ok" if ok else ("warn" if detail and "Belum" not in detail else "idle")
        label.setProperty("tone", tone)
        self._repolish(label)

    def _update_startup_gate_ui(self) -> None:
        if self._dev_mode_enabled:
            self.gate_message.setText("Mode dev aktif. Workspace dibuka tanpa semua dependency operator.")
            self.gate_subtitle.setText("DEV / MOCK MODE aktif. MT5 dan AI runtime tidak wajib untuk membuka workspace.")
            return
        blocked = [key for key, passed in self._startup_requirements.items() if not passed]
        if blocked:
            first_blocked = blocked[0]
            detail = self._startup_requirement_details.get(first_blocked, "Belum siap")
            self.gate_subtitle.setText(
                "Mode operator mengharuskan service, MT5, akun, AI runtime, dokumen, context, dan storage siap."
            )
            self.gate_message.setText(detail)
        else:
            self.gate_message.setText("Semua dependency inti siap. Membuka workspace...")

    def _unlock_workspace(self) -> None:
        self._startup_gate_active = False
        self.mode_badge.setText("DEV / MOCK MODE" if self._dev_mode_enabled else "OPERATOR MODE")
        self.shell_stack.setCurrentWidget(self.workspace_page)
        self._sync_button_states()

    def _enter_dev_mode(self) -> None:
        self._dev_mode_enabled = True
        self._startup_gate_active = False
        self._persist_runtime_settings()
        self.gate_message.setText("DEV / MOCK MODE aktif.")
        self.mode_badge.setText("DEV / MOCK MODE")
        self.shell_stack.setCurrentWidget(self.workspace_page)
        self._sync_button_states()

    def _workspace_unlocked(self) -> bool:
        return not self._startup_gate_active or self._dev_mode_enabled

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
        self.history_load_button.clicked.connect(self.load_telemetry)
        for index, button in enumerate(self.nav_buttons):
            button.clicked.connect(lambda _checked=False, idx=index: self._select_page(idx))
        self.gate_primary_button.clicked.connect(self._run_startup_probe_sequence)
        self.gate_retry_button.clicked.connect(self._run_startup_probe_sequence)
        self.gate_dev_button.clicked.connect(self._enter_dev_mode)
        self.account_review_use_button.clicked.connect(self._use_pending_account_context)
        self.account_review_select_button.clicked.connect(self._select_next_pending_account_context)
        self.account_review_new_context_button.clicked.connect(self._create_pending_account_context)
        self.account_review_cancel_button.clicked.connect(self._cancel_account_review)

        for widget in (
            self.symbol_combo.lineEdit(),
            self.stop_input,
            self.capital_input,
            self.manual_lot_input,
            self.timeout_input,
            self.ai_documents_input,
            self.ai_context_input,
            self.codex_cwd_input,
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
        self._persist_runtime_settings()
        self.backend.close()
        super().closeEvent(event)

    def _probe_service_ready(self) -> str:
        if not self.connect_service(show_errors=False):
            raise RuntimeError(self.service_status.text())
        return self.service_status.text()

    def _probe_mt5_process(self) -> str:
        result = self._send_backend_command("probe_mt5_process", {})
        return str(result.get("detail") or "MetaTrader 5 terdeteksi.")

    def _probe_mt5_session(self) -> str:
        result = self._send_backend_command("probe_mt5_session", {})
        return str(result.get("detail") or "Sesi MT5 aktif.")

    def _probe_account_fingerprint(self) -> str:
        result = self._send_backend_command("probe_account_fingerprint", {})
        fingerprint = {
            "login": str(result.get("login") or ""),
            "server": str(result.get("server") or ""),
            "broker": str(result.get("broker") or ""),
            "is_live": result.get("is_live"),
        }
        self._apply_account_fingerprint(fingerprint, runtime_was_running=False)
        return str(result.get("detail") or "Akun aktif tervalidasi.")

    def _probe_symbol_baseline(self) -> str:
        result = self._send_backend_command("probe_symbol_baseline", self._probe_params())
        snapshot = dict(result.get("snapshot") or {})
        self.snapshot = {**(self.snapshot or {}), **snapshot}
        self._set_symbol_choices(result.get("symbols") or [])
        self._sync_stop_distance_from_probe(snapshot)
        self._update_summary_cards()
        return str(result.get("detail") or "Simbol dasar siap.")

    def _probe_ai_runtime(self) -> str:
        result = self._send_backend_command("probe_ai_runtime", self._ai_runtime_probe_params())
        detail = str(result.get("detail") or result.get("version") or "AI runtime siap.")
        self._codex_ready = True
        self.codex_status.setText(str(result.get("version") or detail))
        return detail

    def _probe_ai_workspace(self) -> str:
        result = self._send_backend_command("probe_ai_workspace", self._ai_runtime_probe_params())
        return str(result.get("detail") or "Workspace AI siap.")

    def _probe_ai_documents(self) -> str:
        result = self._send_backend_command("probe_ai_documents", self._ai_runtime_probe_params())
        return str(result.get("detail") or "Dokumen AI siap.")

    def _probe_ai_context(self) -> str:
        result = self._send_backend_command("probe_ai_context_store", self._ai_runtime_probe_params())
        return str(result.get("detail") or "Context AI siap.")

    def _probe_storage(self) -> str:
        result = self._send_backend_command("validate_storage", self._ai_runtime_probe_params())
        return str(result.get("detail") or "Storage siap.")

    def _build_resume_state(self) -> str:
        if self._active_account_fingerprint is None:
            raise RuntimeError("Fingerprint akun belum tersedia.")
        result = self._send_backend_command(
            "build_resume_state",
            {
                **self._ai_runtime_probe_params(),
                "fingerprint": self._active_account_fingerprint,
                "create_new": False,
            },
        )
        self._active_context_binding = dict(result.get("binding") or {})
        return str(result.get("detail") or "Resume state siap.")

    def _apply_account_fingerprint(self, fingerprint: dict[str, Any], *, runtime_was_running: bool) -> None:
        if self._active_account_fingerprint is None:
            self._active_account_fingerprint = dict(fingerprint)
            return
        if self._active_account_fingerprint == fingerprint:
            return
        self._pending_account_fingerprint = dict(fingerprint)
        self._handle_account_changed(self._active_account_fingerprint, fingerprint, runtime_was_running=runtime_was_running)

    def _handle_account_changed(
        self,
        old_fingerprint: dict[str, Any],
        new_fingerprint: dict[str, Any],
        *,
        runtime_was_running: bool,
    ) -> None:
        self._pending_account_fingerprint = dict(new_fingerprint)
        self._account_review_active = True
        self._mt5_overlay_active = False
        self.reconnect_overlay.hide()
        self.account_review_old.setText(f"Akun lama: {self._format_account_fingerprint(old_fingerprint)}")
        self.account_review_new.setText(f"Akun baru: {self._format_account_fingerprint(new_fingerprint)}")
        self.account_review_message.setText(
            "Runtime dihentikan demi keamanan karena fingerprint akun MT5 berubah."
            if runtime_was_running
            else "Akun MT5 berubah. Review context akun sebelum trading dilanjutkan."
        )
        self.account_review_card.show()
        self._runtime_running = False
        self._live_enabled = False
        self._pending_approval = None
        self.runtime_status.setText("Hard safe halt: akun MT5 berubah")
        self.approval_status.setText("Review akun baru dibutuhkan")
        self._load_pending_account_contexts()
        self._sync_button_states()

    def _handle_mt5_disconnect(self, detail: str, *, runtime_was_running: bool) -> None:
        self._mt5_ready = False
        self._mt5_overlay_active = True
        self._account_review_active = False
        self.account_review_card.hide()
        self.reconnect_message.setText(
            "Runtime dihentikan demi keamanan. Nyalakan kembali MT5 lalu tunggu reconnect otomatis."
            if runtime_was_running
            else detail,
        )
        self.reconnect_overlay.show()
        if runtime_was_running:
            self._runtime_running = False
            self._live_enabled = False
            self._pending_approval = None
            self.runtime_status.setText("Safe halt: koneksi MT5 hilang")
            self.approval_status.setText("Tidak ada approval aktif")
        self.mt5_status.setText(detail)
        self._sync_button_states()

    def _clear_mt5_disconnect_overlay(self) -> None:
        self._mt5_overlay_active = False
        self.reconnect_overlay.hide()
        self._sync_button_states()

    def _load_pending_account_contexts(self) -> None:
        self._pending_account_contexts = []
        self._selected_pending_context_index = 0
        if self._pending_account_fingerprint is None:
            self.account_review_context.setText("Context akun belum tersedia.")
            return
        try:
            result = self._send_backend_command(
                "list_account_contexts",
                {
                    **self._ai_runtime_probe_params(),
                    "fingerprint": self._pending_account_fingerprint,
                },
            )
        except Exception as exc:
            self.account_review_context.setText(
                f"Gagal memuat daftar context akun: {self._format_exception_detail(exc)}"
            )
            return
        self._pending_account_contexts = list(result.get("contexts") or [])
        self._selected_pending_context_index = 0
        self._refresh_pending_account_context_label()

    def _refresh_pending_account_context_label(self) -> None:
        if not self._pending_account_contexts:
            self.account_review_context.setText(
                "Belum ada context existing untuk akun ini. Pilih `Buat context baru` atau gunakan default binding."
            )
            return
        current = self._pending_account_contexts[self._selected_pending_context_index]
        mapping = "mapped" if current.get("is_mapped") else "existing"
        self.account_review_context.setText(
            "Context terpilih: "
            f"{current.get('context_key')} "
            f"({mapping}, state={current.get('last_runtime_state') or 'unknown'}, "
            f"shutdown={current.get('last_shutdown_reason') or 'n/a'})"
        )

    def _select_next_pending_account_context(self) -> None:
        if not self._pending_account_contexts:
            self._load_pending_account_contexts()
            if not self._pending_account_contexts:
                return
        self._selected_pending_context_index = (
            self._selected_pending_context_index + 1
        ) % len(self._pending_account_contexts)
        self._refresh_pending_account_context_label()

    def _use_pending_account_context(self) -> None:
        if self._pending_account_fingerprint is None:
            return
        selected_context_key = None
        if self._pending_account_contexts:
            selected_context_key = self._pending_account_contexts[self._selected_pending_context_index].get("context_key")
        command_name = "select_account_context" if selected_context_key else "build_resume_state"
        payload = {
            **self._ai_runtime_probe_params(),
            "fingerprint": self._pending_account_fingerprint,
            "create_new": False,
        }
        if selected_context_key:
            payload["context_key"] = selected_context_key
        result = self._send_backend_command(command_name, payload)
        self._active_account_fingerprint = dict(self._pending_account_fingerprint)
        self._active_context_binding = dict(result.get("binding") or {})
        self._pending_account_fingerprint = None
        self._pending_account_contexts = []
        self._selected_pending_context_index = 0
        self._account_review_active = False
        self.account_review_card.hide()
        self.runtime_status.setText("Akun baru diterima. Menjalankan readiness ulang.")
        self.approval_status.setText("Tidak ada approval aktif")
        self._start_startup_gate()

    def _create_pending_account_context(self) -> None:
        if self._pending_account_fingerprint is None:
            return
        result = self._send_backend_command(
            "build_resume_state",
            {
                **self._ai_runtime_probe_params(),
                "fingerprint": self._pending_account_fingerprint,
                "create_new": True,
            },
        )
        self._active_account_fingerprint = dict(self._pending_account_fingerprint)
        self._active_context_binding = dict(result.get("binding") or {})
        self._pending_account_fingerprint = None
        self._pending_account_contexts = []
        self._selected_pending_context_index = 0
        self._account_review_active = False
        self.account_review_card.hide()
        self.runtime_status.setText("Context akun baru dibuat. Menjalankan readiness ulang.")
        self.approval_status.setText("Tidak ada approval aktif")
        self._start_startup_gate()

    def _cancel_account_review(self) -> None:
        self._account_review_active = False
        self._pending_account_fingerprint = None
        self._pending_account_contexts = []
        self._selected_pending_context_index = 0
        self.account_review_card.hide()
        self._start_startup_gate()

    @staticmethod
    def _format_account_fingerprint(fingerprint: dict[str, Any] | None) -> str:
        if not fingerprint:
            return "tidak diketahui"
        broker = str(fingerprint.get("broker") or "broker")
        server = str(fingerprint.get("server") or "server")
        login = str(fingerprint.get("login") or "akun")
        mode = "live" if fingerprint.get("is_live") else "demo"
        return f"{broker} / {server} / {login} ({mode})"

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
        except Exception as exc:
            detail = self._format_exception_detail(exc)
            if self._workspace_unlocked():
                self._handle_mt5_disconnect(detail, runtime_was_running=self._runtime_running)
            self._sync_button_states()
            return
        finally:
            self._preview_refresh_inflight = False
        self._apply_refresh_result(result)
        self._clear_mt5_disconnect_overlay()

    def _refresh_preview_tick(self) -> None:
        if self._startup_gate_active or not self._service_connected or not self.isVisible():
            return
        if self._account_review_active:
            return
        if self._mt5_overlay_active:
            try:
                self.check_mt5(silent=True)
                self._clear_mt5_disconnect_overlay()
            except Exception:
                return
        elif self.snapshot is not None and not self._runtime_running:
            self._refresh_preview_state()

    def check_mt5(self, *, silent: bool = False) -> None:
        try:
            self._probe_mt5_process()
            self._probe_mt5_session()
            account_result = self._send_backend_command("probe_account_fingerprint", {})
            result = self._send_backend_command("probe_symbol_baseline", self._probe_params())
        except Exception as exc:
            detail = self._format_exception_detail(exc)
            self._mt5_ready = False
            self.mt5_status.setText(detail)
            self._append_log([f"MT5 error: {detail}"])
            if self._workspace_unlocked() and not silent:
                self._handle_mt5_disconnect(detail, runtime_was_running=self._runtime_running)
            if silent:
                raise
            return
        snapshot = result["snapshot"]
        fingerprint = {
            "login": str(account_result.get("login") or ""),
            "server": str(account_result.get("server") or ""),
            "broker": str(account_result.get("broker") or ""),
            "is_live": account_result.get("is_live"),
        }
        self._apply_account_fingerprint(fingerprint, runtime_was_running=self._runtime_running)
        self._mt5_ready = True
        self.mt5_status.setText("MT5 ready")
        self._set_symbol_choices(result.get("symbols") or [])
        self._sync_stop_distance_from_probe(snapshot)
        self.snapshot = {**(self.snapshot or {}), **dict(snapshot)}
        self._update_summary_cards()
        self._schedule_live_preview()
        self._clear_mt5_disconnect_overlay()
        self._append_log(
            [
                "mt5_probe:",
                f"- account={self._format_account_fingerprint(fingerprint)}",
                f"- symbol_trade_allowed={snapshot.get('symbol_trade_allowed')}",
                f"- broker_stop_min_points={snapshot.get('stops_level_points')}",
                f"- available_symbols={len(result.get('symbols') or [])}",
            ]
        )

    def load_codex(self) -> None:
        try:
            self._persist_runtime_settings()
            result = self._send_backend_command("probe_ai_runtime", self._ai_runtime_probe_params())
            self._send_backend_command("probe_ai_workspace", self._ai_runtime_probe_params())
            self._send_backend_command("probe_ai_documents", self._ai_runtime_probe_params())
            self._send_backend_command("probe_ai_context_store", self._ai_runtime_probe_params())
            if self._active_account_fingerprint is not None:
                resume = self._send_backend_command(
                    "build_resume_state",
                    {**self._ai_runtime_probe_params(), "fingerprint": self._active_account_fingerprint, "create_new": False},
                )
                self._active_context_binding = dict(resume.get("binding") or {})
        except Exception as exc:
            detail = self._format_exception_detail(exc)
            self._codex_ready = False
            self.codex_status.setText(detail)
            self._append_log([f"Codex error: {detail}"])
            return
        version = str(result.get("version") or result.get("detail") or "")
        self._codex_ready = True
        self.codex_status.setText(version)
        self._append_log(
            [
                "codex_probe:",
                f"- command={self.codex_command_input.text().strip()}",
                f"- version={version}",
                f"- model={self._optional_str(self.model_combo.currentText()) or 'default'}",
                f"- workspace={self._optional_str(self.codex_cwd_input.text()) or (self.project_root / 'ai_workspace')}",
                f"- documents={self._optional_str(self.ai_documents_input.text()) or (self.project_root / 'ai_documents')}",
                f"- context_root={self._optional_str(self.ai_context_input.text()) or (self.project_root / 'ai_context')}",
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
        self.runtime_status.setText(f"Memulai bot {run_id}")
        self.approval_status.setText("Tidak ada approval aktif")
        self._append_log([f"runtime_starting run_id={run_id}", f"db_path={self._runtime_params().get('db_path')}"])
        self._sync_button_states()

    def stop_runtime(self) -> None:
        try:
            self._send_backend_command("stop_runtime", {}, timeout=10.0)
        except Exception as exc:
            self._append_log([f"Runtime stop error: {self._format_exception_detail(exc)}"])
            return
        self._runtime_running = False
        self.runtime_status.setText("Bot berhenti")
        self._sync_button_states()

    def toggle_live(self) -> None:
        enable_live = not self._live_enabled
        try:
            result = self._send_backend_command("set_live_enabled", {"enabled": enable_live}, timeout=10.0)
        except Exception as exc:
            self._append_log([f"Live toggle error: {self._format_exception_detail(exc)}"])
            return
        self._live_enabled = bool(result.get("live_enabled"))
        self.live_button.setText("Nonaktifkan Live" if self._live_enabled else "Aktifkan Live")
        self.runtime_status.setText("Live aktif" if self._live_enabled else "Live nonaktif")
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
        self._telemetry_overview = dict(overview)
        self._telemetry_health = dict(health)
        self._telemetry_validation = dict(validation)
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
        self.history_summary_text.setPlainText(
            "\n".join(
                [
                    f"run_id={run_id}",
                    f"status={overview.get('status')}",
                    f"last_action={overview.get('last_action')}",
                    f"filled_events={health.get('filled_events')}",
                    f"dry_run_events={health.get('dry_run_events')}",
                    f"reject_rate={self._float_value(health.get('reject_rate')):.2%}",
                    "",
                    "Recent lifecycle:",
                    *[f"- {row.get('symbol')} {row.get('side')} pnl={row.get('realized_pnl_cash')}" for row in lifecycle_rows[:10]],
                ]
            )
        )
        self._refresh_page_summaries()
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
            "timeout_seconds": max(int(self._float_or_default(self.timeout_input.text(), default=60.0)), 1),
        }

    def _ai_runtime_probe_params(self) -> dict[str, Any]:
        settings = self._collect_runtime_settings_from_form()
        return {
            **settings.to_dict(),
            "codex_command": settings.ai_runtime_command,
            "model": settings.default_model,
            "codex_cwd": settings.ai_workspace_path,
            "ai_workspace_path": settings.ai_workspace_path,
            "ai_documents_path": settings.ai_documents_path,
            "ai_context_root": settings.ai_context_root,
            "db_path": settings.db_path,
            "poll_interval_seconds": settings.poll_interval_seconds,
            "timeout_seconds": settings.timeout_seconds,
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
            "ai_workspace_path": self.codex_cwd_input.text().strip(),
            "ai_documents_path": self.ai_documents_input.text().strip(),
            "ai_context_root": self.ai_context_input.text().strip(),
            "ai_context_path": (self._active_context_binding or {}).get("context_path"),
            "resume_prompt_path": (self._active_context_binding or {}).get("resume_prompt_path"),
            "behavior_profile_path": (self._active_context_binding or {}).get("profile_path"),
            "account_fingerprint": self._active_account_fingerprint,
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
            codex_timeout_seconds=max(int(self._float_or_default(self.timeout_input.text(), default=60.0)), 1),
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
                    fingerprint = runtime_snapshot.get("account_fingerprint")
                    if isinstance(fingerprint, dict):
                        self._apply_account_fingerprint(fingerprint, runtime_was_running=True)
                    self._update_summary_cards()
                self._clear_mt5_disconnect_overlay()
            elif name == "runtime_safe_halt":
                stop_reason = str(payload.get("stop_reason") or "")
                if stop_reason == "account_changed":
                    self._pending_account_fingerprint = dict(payload.get("actual_account_fingerprint") or {})
                    self._handle_account_changed(
                        dict(payload.get("expected_account_fingerprint") or self._active_account_fingerprint or {}),
                        dict(payload.get("actual_account_fingerprint") or {}),
                        runtime_was_running=True,
                    )
                else:
                    self._handle_mt5_disconnect(self._short(message), runtime_was_running=True)
            elif name == "account_changed":
                self._pending_account_fingerprint = dict(payload.get("actual_account_fingerprint") or {})
                self._handle_account_changed(
                    dict(payload.get("expected_account_fingerprint") or self._active_account_fingerprint or {}),
                    dict(payload.get("actual_account_fingerprint") or {}),
                    runtime_was_running=True,
                )
            elif name in {"runtime_error", "runtime_halted", "runtime_stopped"}:
                self._runtime_running = False
                self.runtime_status.setText(self._short(message))
                self._append_log([f"{name}: {message}"])
                if "ipc" in message.lower() or "mt5" in message.lower():
                    self._handle_mt5_disconnect(self._short(message), runtime_was_running=True)
            elif name == "approval_pending":
                self._pending_approval = payload
                self.approval_status.setText("Menunggu approval")
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
                self.live_button.setText("Nonaktifkan Live" if self._live_enabled else "Aktifkan Live")
        self._sync_button_states()

    def _apply_refresh_result(self, result: dict[str, Any]) -> None:
        snapshot = result.get("snapshot")
        if isinstance(snapshot, dict):
            self.snapshot = snapshot
            self._apply_stop_distance_floor(self._float_value(snapshot.get("stops_level_points")))
            fingerprint = snapshot.get("account_fingerprint")
            if isinstance(fingerprint, dict):
                self._apply_account_fingerprint(fingerprint, runtime_was_running=self._runtime_running)
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
        trading_blocked = self._mt5_overlay_active or self._account_review_active
        manual_execute_allowed = bool(
            self.manual_order_snapshot
            and bool(self.manual_order_snapshot.get("accepted"))
            and self._float_value(self.manual_order_snapshot.get("final_lot")) > 0
        )
        pending = self._pending_approval is not None
        if self._startup_gate_active and not self._dev_mode_enabled:
            for button in (
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
            ):
                button.setEnabled(False)
            for widget in (
                self.symbol_combo,
                self.timeframe_combo,
                self.style_combo,
                self.stop_input,
                self.capital_mode_combo,
                self.capital_input,
                self.lot_mode_combo,
                self.manual_lot_input,
                self.side_combo,
                self.db_input,
                self.service_host_input,
                self.service_port_input,
                self.codex_command_input,
                self.model_combo,
                self.codex_cwd_input,
                self.ai_documents_input,
                self.ai_context_input,
                self.timeout_input,
                self.poll_interval_input,
            ):
                widget.setEnabled(False)
            for button in self.nav_buttons:
                button.setEnabled(False)
            self.gate_primary_button.setEnabled(not self._startup_probe_inflight)
            self.gate_retry_button.setEnabled(not self._startup_probe_inflight)
            self.gate_dev_button.setEnabled(True)
            self._refresh_status_presentation()
            return
        if trading_blocked:
            for button in (
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
            ):
                button.setEnabled(False)
            self.load_telemetry_button.setEnabled(connected)
            self.connect_service_button.setEnabled(not self._runtime_running)
            for widget in (
                self.symbol_combo,
                self.timeframe_combo,
                self.style_combo,
                self.stop_input,
                self.capital_mode_combo,
                self.capital_input,
                self.lot_mode_combo,
                self.manual_lot_input,
                self.side_combo,
                self.db_input,
            ):
                widget.setEnabled(False)
            for button in self.nav_buttons:
                button.setEnabled(True)
            self.live_button.setText("Nonaktifkan Live" if self._live_enabled else "Aktifkan Live")
            self._refresh_status_presentation()
            return
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
        self.live_button.setText("Nonaktifkan Live" if self._live_enabled else "Aktifkan Live")
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
                self.codex_cwd_input,
                self.ai_documents_input,
                self.ai_context_input,
                self.timeout_input,
        ):
            widget.setEnabled(trade_setup_enabled)
        self.manual_lot_input.setEnabled(trade_setup_enabled and self.lot_mode_combo.currentText().strip() == "manual")
        self.connect_service_button.setEnabled(not self._runtime_running)
        for button in self.nav_buttons:
            button.setEnabled(True)
        self.gate_primary_button.setEnabled(True)
        self.gate_retry_button.setEnabled(True)
        self.gate_dev_button.setEnabled(True)
        self._refresh_status_presentation()

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
