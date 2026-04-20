from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
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
from .models import CapitalAllocation, CapitalAllocationMode, OperatingMode, PositionSizeRequest, RiskPolicy, TradingStyle
from .mt5_adapter import LiveMT5Adapter
from .mt5_execution_runtime import MT5ExecutionRuntime
from .polling_runtime import AIIntent, DecisionAction, MT5SnapshotProvider
from .risk_engine import RiskEngine
from .runtime_store import RuntimeStore
from .validation import build_runtime_validation_report


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
    ) -> None:
        super().__init__()
        self.setWindowTitle("bot-ea Qt Desktop Runtime")
        self.resize(1500, 920)

        self.adapter = adapter or LiveMT5Adapter()
        self.risk_engine = risk_engine or RiskEngine()
        self.risk_policy = risk_policy or RiskPolicy(
            base_risk_pct=1.0,
            max_total_open_risk_pct=2.0,
            daily_loss_limit_pct=3.0,
        )
        self.runtime_coordinator = runtime_coordinator or DesktopRuntimeCoordinator(risk_policy=self.risk_policy)

        self.snapshot = None
        self.size_result = None
        self.manual_order_snapshot: dict[str, float | str | bool] | None = None
        self._field_guard = False

        self._build_ui()
        self._wire_events()

        self.event_timer = QTimer(self)
        self.event_timer.timeout.connect(self._pump_runtime_events)
        self.event_timer.start(250)

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
        self.mt5_status = QLabel("MT5 unchecked", self)
        self.codex_status = QLabel("codex-cli unchecked", self)
        self.runtime_status = QLabel("Runtime stopped", self)
        self.run_id_status = QLabel("-", self)
        self.approval_status = QLabel("No pending live approval", self)
        status_grid.addWidget(QLabel("MT5"), 0, 0)
        status_grid.addWidget(self.mt5_status, 0, 1)
        status_grid.addWidget(QLabel("Codex"), 1, 0)
        status_grid.addWidget(self.codex_status, 1, 1)
        status_grid.addWidget(QLabel("Runtime"), 2, 0)
        status_grid.addWidget(self.runtime_status, 2, 1)
        status_grid.addWidget(QLabel("Run ID"), 3, 0)
        status_grid.addWidget(self.run_id_status, 3, 1)
        status_grid.addWidget(QLabel("Approval"), 4, 0)
        status_grid.addWidget(self.approval_status, 4, 1)
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
            "Lot Mode=manual berarti lot Anda dicek lalu di-resize turun jika terlalu besar. "
            "Stop loss minimum broker akan otomatis diterapkan setelah Check MT5 / Refresh.",
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
            self.codex_command_input,
            self.codex_cwd_input,
            self.poll_interval_input,
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
            self.model_combo,
        ):
            combo.currentTextChanged.connect(self._schedule_live_preview)

    def _schedule_live_preview(self) -> None:
        if self._field_guard or self.snapshot is None:
            self._sync_button_states()
            return
        QTimer.singleShot(150, self._refresh_preview_state)

    def _refresh_preview_state(self) -> None:
        if self.snapshot is None:
            self._sync_button_states()
            return
        try:
            if self.snapshot.symbol != self.symbol_combo.currentText().strip() or self.snapshot.timeframe != self.timeframe_combo.currentText().strip():
                self.snapshot = self._provider().get_snapshot()
            self._apply_realtime_constraints()
            self.size_result = self._size_result()
            self.manual_order_snapshot = self._manual_order_snapshot()
            self._update_summary_cards()
            self._sync_button_states()
        except Exception:
            self._sync_button_states()

    def check_mt5(self) -> None:
        try:
            result = self.runtime_coordinator.probe_mt5(
                symbol=self.symbol_combo.currentText().strip(),
                timeframe=self.timeframe_combo.currentText().strip(),
                trading_style=TradingStyle(self.style_combo.currentText()),
                stop_distance_points=self._current_stop_distance_value(),
                capital_allocation=self._capital_allocation(),
            )
        except Exception as exc:
            self.mt5_status.setText(self._format_exception_detail(exc))
            self._append_log([f"MT5 error: {self._format_exception_detail(exc)}"])
            return
        terminal = result["terminal"]
        snapshot = result["snapshot"]
        self.mt5_status.setText("MT5 ready")
        self._set_symbol_choices(result.get("symbols") or [])
        self._sync_stop_distance_from_probe(snapshot)
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
            version = self.runtime_coordinator.probe_codex(
                executable=self.codex_command_input.text().strip(),
                model=self._optional_str(self.model_combo.currentText()),
                cwd=self._optional_str(self.codex_cwd_input.text()),
            )
        except Exception as exc:
            self.codex_status.setText(self._format_exception_detail(exc))
            self._append_log([f"Codex error: {self._format_exception_detail(exc)}"])
            return
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
            self.snapshot = self._provider().get_snapshot()
            self._sync_stop_distance_from_symbol_snapshot(self.snapshot.symbol_snapshot)
            self.size_result = self._size_result()
            self.manual_order_snapshot = self._manual_order_snapshot()
        except Exception as exc:
            self._append_log([f"Snapshot error: {self._format_exception_detail(exc)}"])
            return
        self._update_summary_cards()
        self._sync_button_states()

    def preflight(self) -> None:
        if self.snapshot is None:
            self.refresh_snapshot()
        if self.snapshot is None:
            return
        try:
            self.size_result = self._size_result()
            self.manual_order_snapshot = self._manual_order_snapshot()
            runtime = MT5ExecutionRuntime(adapter=self.adapter, allow_live_orders=False)
            preview_size = SimpleNamespace(
                accepted=True,
                mode=OperatingMode.RECOMMEND,
                capital_base_cash=float((self.manual_order_snapshot or {}).get("allocation_cap_usd") or 0.0),
                recommended_minimum_allocation_cash=0.0,
                effective_risk_pct=0.0,
                risk_cash_budget=0.0,
                normalized_volume=float((self.manual_order_snapshot or {}).get("final_lot") or 0.0),
                estimated_loss_cash=0.0,
                stop_distance_points=self._current_stop_distance_value(),
                rejection_reason=None,
                warnings=[],
            )
            if not self.manual_order_snapshot or not bool(self.manual_order_snapshot.get("accepted")):
                self._append_log(self._manual_snapshot_lines() + ["status=REJECTED", f"detail={self.manual_order_snapshot.get('why_blocked') if self.manual_order_snapshot else 'manual lot blocked'}"])
            else:
                result = runtime.preflight(self.snapshot, self._intent("manual preflight"), preview_size)
                self._append_log(self._manual_snapshot_lines() + [f"status={result['status']}", f"detail={result['detail']}", f"retcode={result.get('retcode')}"])
        except Exception as exc:
            self._append_log([f"Preflight error: {self._format_exception_detail(exc)}"])
        self._update_summary_cards()
        self._sync_button_states()

    def execute_manual(self) -> None:
        if self.snapshot is None:
            self.refresh_snapshot()
        if self.snapshot is None:
            return
        self.manual_order_snapshot = self._manual_order_snapshot()
        if not self.manual_order_snapshot or not bool(self.manual_order_snapshot.get("accepted")):
            self._append_log(self._manual_snapshot_lines() + ["status=REJECTED", f"detail={self.manual_order_snapshot.get('why_blocked') if self.manual_order_snapshot else 'manual lot blocked'}"])
            self._sync_button_states()
            return
        try:
            runtime = MT5ExecutionRuntime(adapter=self.adapter, allow_live_orders=self.live_button.text() == "Disable Live")
            manual_size_result = SimpleNamespace(
                accepted=True,
                mode=OperatingMode.RECOMMEND,
                capital_base_cash=float(self.manual_order_snapshot.get("allocation_cap_usd") or 0.0),
                recommended_minimum_allocation_cash=0.0,
                effective_risk_pct=0.0,
                risk_cash_budget=0.0,
                normalized_volume=float(self.manual_order_snapshot.get("final_lot") or 0.0),
                estimated_loss_cash=0.0,
                stop_distance_points=self._current_stop_distance_value(),
                rejection_reason=None,
                warnings=[],
            )
            result = runtime.execute(self.snapshot, self._intent("manual execute"), manual_size_result)
            self._append_log(self._manual_snapshot_lines() + [f"status={result.get('status')}", f"detail={result.get('detail')}", f"retcode={result.get('retcode')}", f"order={result.get('order')}", f"deal={result.get('deal')}"])
        except Exception as exc:
            self._append_log([f"Execute error: {self._format_exception_detail(exc)}"])

    def play_runtime(self) -> None:
        try:
            self.load_codex()
            self.check_mt5()
            config = self._desktop_runtime_config()
            run_id = self.runtime_coordinator.start(config)
            self.run_id_status.setText(run_id)
            self.runtime_status.setText(f"Starting run {run_id}")
            self._append_log([f"runtime_starting run_id={run_id}", f"db_path={config.db_path}"])
        except Exception as exc:
            self._append_log([f"Runtime start error: {self._format_exception_detail(exc)}"])
        self._sync_button_states()

    def stop_runtime(self) -> None:
        self.runtime_coordinator.stop()
        self.runtime_status.setText("Runtime stopped")
        self._sync_button_states()

    def toggle_live(self) -> None:
        enable_live = self.live_button.text() == "Enable Live"
        try:
            self.runtime_coordinator.set_live_enabled(enable_live)
        except Exception as exc:
            self._append_log([f"Live toggle error: {self._format_exception_detail(exc)}"])
            return
        self.live_button.setText("Disable Live" if enable_live else "Enable Live")
        self._sync_button_states()

    def approve_pending(self) -> None:
        try:
            pending = self.runtime_coordinator.approve_pending_live_order()
            self.approval_status.setText(f"Approved {pending.symbol} {pending.side} {pending.volume}")
            self._append_log([f"approval_armed: {pending.symbol} {pending.side} {pending.volume}"])
        except Exception as exc:
            self._append_log([f"Approval error: {self._format_exception_detail(exc)}"])
        self._sync_button_states()

    def reject_pending(self) -> None:
        try:
            pending = self.runtime_coordinator.reject_pending_live_order()
            self.approval_status.setText("No pending live approval")
            self._append_log([f"approval_rejected: {pending.symbol} {pending.side} {pending.volume}"])
        except Exception as exc:
            self._append_log([f"Reject error: {self._format_exception_detail(exc)}"])
        self._sync_button_states()

    def load_telemetry(self) -> None:
        db_path = Path(self.db_input.text().strip())
        if not db_path.exists():
            self._append_log([f"runtime_db_missing={db_path}"])
            return
        store = RuntimeStore(str(db_path))
        run_id = self.run_id_status.text().strip() or self.runtime_coordinator.run_id
        overview = store.fetch_latest_run_overview(run_id=run_id or None) or store.fetch_latest_run_overview()
        if overview is None:
            self._append_log(["no runtime runs found"])
            return
        run_id = str(overview.get("run_id") or "")
        self.run_id_status.setText(run_id)
        health = store.fetch_execution_health_summary(run_id=run_id, limit=50)
        inputs = store.fetch_runtime_validation_inputs(run_id=run_id)
        report = build_runtime_validation_report(
            inputs["position_events"],
            inputs["execution_events"],
            starting_equity=float(inputs.get("starting_equity") or 0.0),
        )
        self.runtime_text.setPlainText(
            "\n".join(
                [
                    f"run_id={run_id}",
                    f"status={overview.get('status')}",
                    f"last_action={overview.get('last_action')}",
                    f"spread_points={overview.get('spread_points')}",
                    f"equity={overview.get('equity')}",
                    f"free_margin={overview.get('free_margin')}",
                    f"reject_rate={health.get('reject_rate', 0.0):.2%}",
                    f"filled_events={health.get('filled_events')}",
                    f"dry_run_events={health.get('dry_run_events')}",
                ]
            )
        )
        self.validation_text.setPlainText(
            "\n".join(
                [
                    f"total_trades={report.validation_summary.total_trades}",
                    f"win_rate={report.validation_summary.win_rate:.2%}",
                    f"profit_factor={report.validation_summary.profit_factor:.3f}",
                    f"expectancy_r={report.validation_summary.expectancy_r:.3f}",
                    f"total_pnl_cash={report.validation_summary.total_pnl_cash:.2f}",
                    "",
                    *[f"- {warning}" for warning in report.validation_summary.warnings + report.execution_quality.warnings],
                ]
            )
        )
        self.events_text.setPlainText(
            "\n".join(
                self._manual_snapshot_lines()
                + [""]
                + [f"- {trade.get('symbol')} {trade.get('side')} pnl={trade.get('realized_pnl_cash')}" for trade in inputs["lifecycle_rows"][:10]]
            )
        )

    def _pump_runtime_events(self) -> None:
        events = self.runtime_coordinator.drain_events()
        for event in events:
            if event.kind == "runtime_started":
                self.runtime_status.setText(event.message)
                if isinstance(event.payload.get("run_id"), str):
                    self.run_id_status.setText(str(event.payload["run_id"]))
            elif event.kind == "runtime_cycle":
                self.runtime_status.setText(self._short(event.message))
            elif event.kind in {"runtime_error", "runtime_halted", "runtime_stopped"}:
                self.runtime_status.setText(self._short(event.message))
                self._append_log([f"{event.kind}: {event.message}"])
            elif event.kind == "approval_pending":
                self.approval_status.setText("Pending approval")
                self._append_log([f"approval_pending: {event.payload}"])
            elif event.kind in {"approval_armed", "approval_status", "approval_rejected"}:
                self.approval_status.setText(self._short(event.message))
            elif event.kind == "mt5_ready":
                self.mt5_status.setText("MT5 ready")
            elif event.kind == "codex_ready":
                self.codex_status.setText(str(event.payload.get("version") or event.message))
            elif event.kind == "live_toggle":
                enabled = bool(event.payload.get("enabled"))
                self.live_button.setText("Disable Live" if enabled else "Enable Live")
        self._sync_button_states()

    def _update_summary_cards(self) -> None:
        self.market_card["text"].setPlainText("\n".join(self._snapshot_lines()) if self.snapshot is not None else "No snapshot")
        self.manual_card["text"].setPlainText("\n".join(self._manual_snapshot_lines()))
        self.risk_card["text"].setPlainText("\n".join(self._risk_snapshot_lines()))

    def _snapshot_lines(self) -> list[str]:
        if self.snapshot is None:
            return ["No snapshot"]
        return [
            f"symbol={self.snapshot.symbol}",
            f"bid={self.snapshot.bid}",
            f"ask={self.snapshot.ask}",
            f"spread_points={self.snapshot.spread_points:.2f}",
            f"equity={self.snapshot.account.equity}",
            f"free_margin={self.snapshot.account.free_margin}",
            f"trade_mode={self.snapshot.symbol_snapshot.trade_mode}",
            f"execution_mode={self.snapshot.symbol_snapshot.execution_mode}",
            f"filling_mode={self.snapshot.symbol_snapshot.filling_mode}",
        ]

    def _manual_order_limits(self) -> dict[str, float] | None:
        if self.snapshot is None:
            return None
        symbol = self.snapshot.symbol_snapshot
        side = self.side_combo.currentText()
        order_price = float(self.snapshot.ask if side == "buy" else self.snapshot.bid)
        allocation_cap = self._allocation_capital_basis()
        min_lot = float(symbol.volume_min or 0.0)
        max_lot = float(symbol.volume_max or 0.0)
        step = float(symbol.volume_step or 0.0)
        available_budget = min(allocation_cap, float(self.snapshot.account.free_margin))
        if min_lot <= 0 or max_lot <= 0 or step <= 0 or order_price <= 0:
            return None
        margin_min = self.adapter.estimate_margin(self.snapshot.symbol, min_lot, side, order_price)
        if not margin_min.success:
            return None
        affordable_max_lot = 0.0
        margin_for_affordable_max = 0.0
        if margin_min.required_margin <= available_budget:
            affordable_max_lot = min_lot
            margin_for_affordable_max = margin_min.required_margin
            current = min_lot
            max_steps = int(round((max_lot - min_lot) / step)) + 1
            for _ in range(max_steps):
                next_lot = round(current + step, 8)
                if next_lot > max_lot + 1e-9:
                    break
                margin = self.adapter.estimate_margin(self.snapshot.symbol, next_lot, side, order_price)
                if not margin.success or margin.required_margin > available_budget:
                    break
                affordable_max_lot = next_lot
                margin_for_affordable_max = margin.required_margin
                current = next_lot
        return {
            "allocation_cap_usd": allocation_cap,
            "available_margin_cap_usd": available_budget,
            "broker_min_lot": min_lot,
            "broker_max_lot": max_lot,
            "broker_lot_step": step,
            "order_price": order_price,
            "margin_for_min_lot_usd": margin_min.required_margin,
            "affordable_max_lot": affordable_max_lot,
            "margin_for_affordable_max_lot_usd": margin_for_affordable_max,
        }

    def _manual_order_snapshot(self) -> dict[str, float | str | bool] | None:
        limits = self._manual_order_limits()
        if limits is None:
            return None
        lot_mode = self.lot_mode_combo.currentText().strip() or "auto_max"
        allocation_cap = limits["allocation_cap_usd"]
        if allocation_cap <= 0:
            return {"accepted": False, "final_lot": 0.0, "lot_mode": lot_mode, "why_blocked": "capital allocation must be positive"}
        min_lot = limits["broker_min_lot"]
        max_lot = limits["broker_max_lot"]
        step = limits["broker_lot_step"]
        order_price = limits["order_price"]
        available_budget = limits["available_margin_cap_usd"]
        margin_for_min = limits["margin_for_min_lot_usd"]
        final_lot = limits["affordable_max_lot"]
        margin_for_final = limits["margin_for_affordable_max_lot_usd"]
        if margin_for_min > available_budget or final_lot <= 0:
            return {
                "accepted": False,
                "final_lot": 0.0,
                "lot_mode": lot_mode,
                "allocation_cap_usd": allocation_cap,
                "available_margin_cap_usd": available_budget,
                "broker_min_lot": min_lot,
                "broker_max_lot": max_lot,
                "broker_lot_step": step,
                "margin_for_min_lot_usd": margin_for_min,
                "why_blocked": "allocation cannot cover broker minimum lot margin",
            }
        requested_lot = 0.0
        resized = False
        why_blocked = "n/a"
        if lot_mode == "manual":
            try:
                requested_lot = float(self.manual_lot_input.text())
            except ValueError:
                return {"accepted": False, "final_lot": 0.0, "lot_mode": lot_mode, "why_blocked": "manual lot must be a valid number"}
            if requested_lot <= 0:
                return {"accepted": False, "final_lot": 0.0, "lot_mode": lot_mode, "why_blocked": "manual lot must be positive"}
            normalized_requested = round((int(max(requested_lot, min_lot) / step) * step), 8)
            if normalized_requested < min_lot:
                normalized_requested = min_lot
            if normalized_requested > final_lot:
                resized = True
                why_blocked = "manual lot resized down to max allowed by capital, margin, and broker"
            elif abs(normalized_requested - requested_lot) > 1e-9:
                resized = True
                why_blocked = "manual lot normalized to broker minimum / step"
            final_lot = min(normalized_requested, final_lot)
            margin = self.adapter.estimate_margin(self.snapshot.symbol, final_lot, self.side_combo.currentText(), order_price)
            if margin.success:
                margin_for_final = margin.required_margin
        return {
            "accepted": final_lot > 0,
            "lot_mode": lot_mode,
            "allocation_cap_usd": allocation_cap,
            "available_margin_cap_usd": available_budget,
            "broker_min_lot": min_lot,
            "broker_max_lot": max_lot,
            "broker_lot_step": step,
            "order_price": order_price,
            "requested_lot": requested_lot,
            "resized_down": resized,
            "final_lot": final_lot,
            "margin_for_min_lot_usd": margin_for_min,
            "margin_for_final_lot_usd": margin_for_final,
            "why_blocked": why_blocked if final_lot > 0 else "allocation cannot cover broker minimum lot margin",
        }

    def _manual_snapshot_lines(self) -> list[str]:
        if self.manual_order_snapshot is None:
            return ["manual_order_snapshot=unavailable"]
        snap = self.manual_order_snapshot
        return [
            "manual_order_snapshot:",
            f"- lot_mode={snap.get('lot_mode') or 'auto_max'}",
            f"- requested_lot={float(snap.get('requested_lot') or 0.0):.4f}",
            f"- final_lot={float(snap.get('final_lot') or 0.0):.4f}",
            f"- capital_basis_usd={float(snap.get('allocation_cap_usd') or 0.0):.2f}",
            f"- free_margin_cap_usd={float(snap.get('available_margin_cap_usd') or 0.0):.2f}",
            f"- broker_min_lot={float(snap.get('broker_min_lot') or 0.0):.4f}",
            f"- broker_max_lot={float(snap.get('broker_max_lot') or 0.0):.4f}",
            f"- broker_lot_step={float(snap.get('broker_lot_step') or 0.0):.4f}",
            f"- margin_for_min_lot_usd={float(snap.get('margin_for_min_lot_usd') or 0.0):.2f}",
            f"- margin_for_final_lot_usd={float(snap.get('margin_for_final_lot_usd') or 0.0):.2f}",
            f"- order_price={float(snap.get('order_price') or 0.0):.5f}",
            f"- resized_down={bool(snap.get('resized_down'))}",
            f"- manual_order_result={'ok' if bool(snap.get('accepted')) else 'blocked'}",
            f"- why_blocked={snap.get('why_blocked') or 'n/a'}",
        ]

    def _risk_snapshot_lines(self) -> list[str]:
        if self.snapshot is None or self.size_result is None:
            return ["sizing_snapshot=unavailable"]
        size = self.size_result
        symbol = self.snapshot.symbol_snapshot
        lot_at_min = symbol.volume_min if symbol.volume_min > 0 else 0.0
        min_lot_risk_cash = lot_at_min * size.loss_per_lot if lot_at_min > 0 and size.loss_per_lot > 0 else 0.0
        risk_pct_of_capital = ((size.risk_cash_budget / size.capital_base_cash) * 100.0) if size.capital_base_cash > 0 else 0.0
        return [
            "sizing_snapshot:",
            f"- final_lot={size.normalized_volume:.4f}",
            f"- raw_lot_before_broker_rounding={size.raw_volume:.6f}",
            f"- broker_min_lot={size.volume_min:.4f}",
            f"- broker_max_lot={size.volume_max:.4f}",
            f"- broker_lot_step={size.volume_step:.4f}",
            f"- capital_basis_usd={size.capital_base_cash:.2f}",
            f"- effective_risk_pct={size.effective_risk_pct:.2f}%",
            f"- risk_cash_budget_usd={size.risk_cash_budget:.2f}",
            f"- estimated_loss_at_final_lot_usd={size.estimated_loss_cash:.2f}",
            f"- estimated_loss_at_min_lot_usd={min_lot_risk_cash:.2f}",
            f"- broker_minimum_capital_hint_usd={size.recommended_minimum_allocation_cash:.2f}",
            f"- risk_budget_as_pct_of_capital={risk_pct_of_capital:.2f}%",
            f"- sizing_result={'ok' if size.accepted else 'blocked'}",
            f"- why_blocked={size.rejection_reason or 'n/a'}",
        ]

    def _size_result(self):
        return self.risk_engine.compute_position_size(
            PositionSizeRequest(
                account=self.snapshot.account,
                symbol=self.snapshot.symbol_snapshot,
                policy=self.snapshot.risk_policy,
                stop_distance_points=self._current_stop_distance_value(),
                trading_style=TradingStyle(self.style_combo.currentText()),
                capital_allocation=self._capital_allocation(),
            )
        )

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

    def _allocation_capital_basis(self) -> float:
        if self.snapshot is None:
            return 0.0
        account_equity = max(self.snapshot.account.equity, 0.0)
        allocation = self._capital_allocation()
        if allocation.mode is CapitalAllocationMode.FULL_EQUITY:
            return account_equity
        if allocation.mode is CapitalAllocationMode.PERCENT_EQUITY:
            return account_equity * (min(max(allocation.value, 0.0), 100.0) / 100.0)
        return min(max(allocation.value, 0.0), account_equity)

    def _sync_stop_distance_from_probe(self, snapshot: dict[str, object]) -> None:
        stop_min = float(snapshot.get("stops_level_points") or 0.0)
        self._apply_stop_distance_floor(stop_min)

    def _sync_stop_distance_from_symbol_snapshot(self, symbol_snapshot) -> None:
        stop_min = float(getattr(symbol_snapshot, "stops_level_points", 0.0) or 0.0)
        self._apply_stop_distance_floor(stop_min)

    def _apply_stop_distance_floor(self, stop_min: float) -> None:
        self.stop_label.setText(
            f"Stop Loss Distance (points, min {stop_min:.0f})" if stop_min > 0 else "Stop Loss Distance (points)"
        )
        try:
            current = float(self.stop_input.text())
        except ValueError:
            current = stop_min
        if stop_min > 0 and current < stop_min:
            self.stop_input.setText(f"{stop_min:.0f}")

    def _apply_manual_lot_realtime_bounds(self) -> None:
        if self.snapshot is None or self.lot_mode_combo.currentText().strip() != "manual":
            return
        limits = self._manual_order_limits()
        if limits is None:
            return
        min_lot = float(limits["broker_min_lot"])
        step = float(limits["broker_lot_step"])
        affordable_max_lot = float(limits["affordable_max_lot"])
        try:
            requested = float(self.manual_lot_input.text())
        except ValueError:
            return
        if requested <= 0:
            return
        clamped = max(requested, min_lot)
        normalized = round((int(clamped / step) * step), 8)
        if normalized < min_lot:
            normalized = min_lot
        if affordable_max_lot > 0 and normalized > affordable_max_lot:
            normalized = affordable_max_lot
        if abs(normalized - requested) > 1e-9:
            self.manual_lot_input.setText(f"{normalized:.2f}")

    def _apply_realtime_constraints(self) -> None:
        self._field_guard = True
        try:
            self._sync_stop_distance_from_symbol_snapshot(self.snapshot.symbol_snapshot)
            self._apply_manual_lot_realtime_bounds()
        finally:
            self._field_guard = False

    def _current_stop_distance_value(self) -> float:
        current = float(self.stop_input.text())
        if self.snapshot is None:
            return current
        stop_min = float(self.snapshot.symbol_snapshot.stops_level_points or 0.0)
        if stop_min > 0 and current < stop_min:
            self.stop_input.setText(f"{stop_min:.0f}")
            return stop_min
        return current

    def _intent(self, reason: str) -> AIIntent:
        side = self.side_combo.currentText()
        return AIIntent(
            action=DecisionAction.OPEN,
            side=side,
            reason=reason,
            stop_distance_points=self._current_stop_distance_value(),
            entry_price=self.snapshot.ask if side == "buy" else self.snapshot.bid,
        )

    def _set_symbol_choices(self, symbols: list[str]) -> None:
        current = self.symbol_combo.currentText().strip()
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        self.symbol_combo.addItems(symbols or [current or "EURUSD"])
        if current:
            self.symbol_combo.setCurrentText(current)
        self.symbol_combo.blockSignals(False)

    def _sync_button_states(self) -> None:
        running = self.runtime_coordinator.is_running
        pending = self.runtime_coordinator.pending_approval is not None
        manual_execute_allowed = bool(
            self.manual_order_snapshot
            and bool(self.manual_order_snapshot.get("accepted"))
            and float(self.manual_order_snapshot.get("final_lot") or 0.0) > 0
        )
        self.play_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.approve_button.setEnabled(pending)
        self.reject_button.setEnabled(pending)
        self.execute_button.setEnabled(manual_execute_allowed)

    def _append_log(self, lines: list[str]) -> None:
        current = self.events_text.toPlainText().strip()
        merged = "\n".join(filter(None, [current, *lines]))
        self.events_text.setPlainText(merged)

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
