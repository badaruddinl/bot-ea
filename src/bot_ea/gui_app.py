from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace

from .desktop_runtime import DesktopRuntimeConfig, DesktopRuntimeCoordinator
from .models import CapitalAllocation, CapitalAllocationMode, OperatingMode, PositionSizeRequest, RiskPolicy, TradingStyle
from .mt5_adapter import LiveMT5Adapter
from .mt5_execution_runtime import MT5ExecutionRuntime
from .polling_runtime import AIIntent, DecisionAction, MT5SnapshotProvider
from .risk_engine import RiskEngine
from .runtime_store import RuntimeStore
from .validation import build_runtime_validation_report


class LiveControlPanel:
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
        root: tk.Tk,
        *,
        adapter: LiveMT5Adapter | None = None,
        runtime_coordinator: DesktopRuntimeCoordinator | None = None,
        risk_engine: RiskEngine | None = None,
        risk_policy: RiskPolicy | None = None,
    ) -> None:
        self.root = root
        self.root.title("bot-ea Desktop Runtime")
        self.adapter = adapter or LiveMT5Adapter()
        self.risk_engine = risk_engine or RiskEngine()
        self.risk_policy = risk_policy or RiskPolicy(
            base_risk_pct=1.0,
            max_total_open_risk_pct=2.0,
            daily_loss_limit_pct=3.0,
        )
        self.runtime_coordinator = runtime_coordinator or DesktopRuntimeCoordinator(risk_policy=self.risk_policy)

        self.symbol_var = tk.StringVar(value="EURUSD")
        self.timeframe_var = tk.StringVar(value="M15")
        self.style_var = tk.StringVar(value=TradingStyle.INTRADAY.value)
        self.stop_var = tk.StringVar(value="200")
        self.stop_label_var = tk.StringVar(value="Stop Distance (points)")
        self.allocation_mode_var = tk.StringVar(value=CapitalAllocationMode.FIXED_CASH.value)
        self.allocation_label_var = tk.StringVar(value="Capital To Use (USD)")
        self.allocation_var = tk.StringVar(value="250")
        self.lot_mode_var = tk.StringVar(value="auto_max")
        self.manual_lot_var = tk.StringVar(value="0.01")
        self.side_var = tk.StringVar(value="buy")
        self.db_path_var = tk.StringVar(value=str(Path.cwd() / "bot_ea_runtime.db"))
        self.codex_executable_var = tk.StringVar(value="codex")
        self.codex_model_var = tk.StringVar(value="")
        self.codex_cwd_var = tk.StringVar(value=str(Path.cwd()))
        self.poll_interval_var = tk.StringVar(value="30")
        self.allow_live_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")
        self.health_var = tk.StringVar(value="No runtime DB loaded")
        self.mt5_status_var = tk.StringVar(value="MT5 unchecked")
        self.codex_status_var = tk.StringVar(value="codex-cli unchecked")
        self.runtime_status_var = tk.StringVar(value="Runtime stopped")
        self.approval_status_var = tk.StringVar(value="No pending live approval")
        self.live_button_text_var = tk.StringVar(value="Enable Live")
        self.current_run_id_var = tk.StringVar(value="")
        self.snapshot = None
        self.size_result = None
        self.manual_order_snapshot: dict[str, float | str | bool] | None = None
        self.play_button: ttk.Button | None = None
        self.stop_button: ttk.Button | None = None
        self.live_button: ttk.Button | None = None
        self.approve_button: ttk.Button | None = None
        self.reject_button: ttk.Button | None = None
        self.execute_button: ttk.Button | None = None
        self.symbol_combo: ttk.Combobox | None = None
        self.timeframe_combo: ttk.Combobox | None = None
        self.model_combo: ttk.Combobox | None = None
        self._field_trace_guard = False
        self._realtime_after_id: str | None = None
        self._build()
        self._bind_realtime_fields()
        self.root.after(250, self._pump_runtime_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(7, weight=1)

        market_fields = [
            ("Symbol (from MT5)", self.symbol_var),
            ("Timeframe", self.timeframe_var),
            ("Strategy Style", self.style_var),
            (self.stop_label_var, self.stop_var),
            ("Capital Mode", self.allocation_mode_var),
            (self.allocation_label_var, self.allocation_var),
            ("Lot Mode", self.lot_mode_var),
            ("Manual Lot Request", self.manual_lot_var),
            ("Manual Side Only", self.side_var),
            ("Log File (Runtime DB)", self.db_path_var),
        ]
        codex_fields = [
            ("Codex Command", self.codex_executable_var),
            ("AI Model (preset/manual)", self.codex_model_var),
            ("Codex Work Folder", self.codex_cwd_var),
            ("Check Market Every (s)", self.poll_interval_var),
        ]

        market_frame = ttk.LabelFrame(frame, text="Market / Runtime")
        market_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        market_frame.columnconfigure(1, weight=1)
        self._build_fields(market_frame, market_fields)

        codex_frame = ttk.LabelFrame(frame, text="Codex CLI")
        codex_frame.grid(row=0, column=1, sticky="nsew", pady=(0, 8))
        codex_frame.columnconfigure(1, weight=1)
        self._build_fields(codex_frame, codex_fields)

        status_frame = ttk.LabelFrame(frame, text="Readiness")
        status_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        status_frame.columnconfigure(1, weight=1)
        ttk.Label(status_frame, text="MT5").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Label(status_frame, textvariable=self.mt5_status_var, wraplength=900, justify="left").grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(status_frame, text="Codex CLI").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Label(status_frame, textvariable=self.codex_status_var, wraplength=900, justify="left").grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(status_frame, text="Background Runtime").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Label(status_frame, textvariable=self.runtime_status_var, wraplength=900, justify="left").grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(status_frame, text="Current Run").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Label(status_frame, textvariable=self.current_run_id_var, wraplength=900, justify="left").grid(row=3, column=1, sticky="w", pady=2)
        ttk.Label(status_frame, text="Approval").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Label(status_frame, textvariable=self.approval_status_var, wraplength=900, justify="left").grid(row=4, column=1, sticky="w", pady=2)

        control_bar = ttk.Frame(frame)
        control_bar.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Button(control_bar, text="Check MT5", command=self.check_mt5).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(control_bar, text="Load Codex", command=self.load_codex).grid(row=0, column=1, padx=(0, 6))
        self.play_button = ttk.Button(control_bar, text="Play Runtime", command=self.play_runtime)
        self.play_button.grid(row=0, column=2, padx=(0, 6))
        self.stop_button = ttk.Button(control_bar, text="Stop Runtime", command=self.stop_runtime)
        self.stop_button.grid(row=0, column=3, padx=(0, 6))
        self.live_button = ttk.Button(control_bar, textvariable=self.live_button_text_var, command=self.toggle_live)
        self.live_button.grid(row=0, column=4, padx=(0, 6))
        self.approve_button = ttk.Button(control_bar, text="Approve Pending", command=self.approve_pending_order)
        self.approve_button.grid(row=0, column=5, padx=(0, 6))
        self.reject_button = ttk.Button(control_bar, text="Reject Pending", command=self.reject_pending_order)
        self.reject_button.grid(row=0, column=6, padx=(0, 6))

        manual_bar = ttk.Frame(frame)
        manual_bar.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Button(manual_bar, text="Refresh", command=self.refresh).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(manual_bar, text="Preflight", command=self.preflight).grid(row=0, column=1, padx=(0, 6))
        self.execute_button = ttk.Button(manual_bar, text="Execute", command=self.execute)
        self.execute_button.grid(row=0, column=2, padx=(0, 6))
        ttk.Button(manual_bar, text="Load Telemetry", command=self.load_telemetry).grid(row=0, column=3, padx=(0, 6))
        ttk.Checkbutton(manual_bar, text="Allow Live Orders", variable=self.allow_live_var).grid(row=0, column=4, sticky="w")

        ttk.Label(
            frame,
            text="Manual Side Only dipakai untuk tombol Execute manual. Lot Mode=manual berarti lot Anda dicek lalu di-resize turun jika terlalu besar.",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Label(
            frame,
            text="Stop Distance = jarak stop untuk hitung risk. Runtime DB = file log bot. Codex Work Folder = folder kerja Codex.",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(frame, textvariable=self.health_var).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.output = tk.Text(frame, width=120, height=30, wrap="word")
        self.output.grid(row=7, column=0, columnspan=2, sticky="nsew")
        ttk.Label(frame, textvariable=self.status_var).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._sync_runtime_controls()

    def _build_fields(self, parent: ttk.LabelFrame | ttk.Frame, fields: list[tuple[str | tk.StringVar, tk.StringVar]]) -> None:
        for row, (label, variable) in enumerate(fields):
            if isinstance(label, tk.StringVar):
                ttk.Label(parent, textvariable=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
                label_key = label.get()
            else:
                ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
                label_key = label
            if label_key in {"Symbol (from MT5)", "Timeframe", "Strategy Style", "Capital Mode", "Lot Mode", "Manual Side Only", "AI Model (preset/manual)"}:
                if label_key == "Symbol (from MT5)":
                    values = [self.symbol_var.get()]
                    state = "normal"
                elif label_key == "Timeframe":
                    values = list(self.TIMEFRAME_OPTIONS)
                    state = "readonly"
                elif label_key == "Strategy Style":
                    values = list(self.STYLE_OPTIONS)
                    state = "readonly"
                elif label_key == "Capital Mode":
                    values = list(self.ALLOCATION_MODE_OPTIONS)
                    state = "readonly"
                elif label_key == "Lot Mode":
                    values = list(self.LOT_MODE_OPTIONS)
                    state = "readonly"
                elif label_key == "Manual Side Only":
                    values = list(self.MANUAL_SIDE_OPTIONS)
                    state = "readonly"
                else:
                    values = list(self.CODEX_MODEL_PRESETS)
                    state = "normal"
                combo = ttk.Combobox(parent, textvariable=variable, values=values, state=state, width=18)
                combo.grid(row=row, column=1, sticky="ew", pady=4)
                if label_key == "Capital Mode":
                    combo.bind("<<ComboboxSelected>>", lambda _event: self._sync_allocation_label())
                if label_key == "Symbol (from MT5)":
                    self.symbol_combo = combo
                elif label_key == "Timeframe":
                    self.timeframe_combo = combo
                elif label_key == "AI Model (preset/manual)":
                    self.model_combo = combo
            else:
                ttk.Entry(parent, textvariable=variable, width=18).grid(row=row, column=1, sticky="ew", pady=4)

    def _bind_realtime_fields(self) -> None:
        traced_vars = (
            self.symbol_var,
            self.timeframe_var,
            self.style_var,
            self.stop_var,
            self.allocation_mode_var,
            self.allocation_var,
            self.lot_mode_var,
            self.manual_lot_var,
            self.side_var,
        )
        for variable in traced_vars:
            variable.trace_add("write", self._on_realtime_field_changed)

    def _on_realtime_field_changed(self, *_args) -> None:
        if self._field_trace_guard:
            return
        if self._realtime_after_id is not None:
            self.root.after_cancel(self._realtime_after_id)
        self._realtime_after_id = self.root.after(150, self._run_realtime_field_sync)

    def _run_realtime_field_sync(self) -> None:
        self._realtime_after_id = None
        if self.snapshot is None:
            self._sync_runtime_controls()
            return
        symbol_changed = (
            self.snapshot.symbol != self.symbol_var.get().strip()
            or self.snapshot.timeframe != self.timeframe_var.get().strip()
        )
        if symbol_changed:
            try:
                self.snapshot = self._provider().get_snapshot()
            except Exception:
                self._sync_runtime_controls()
                return
        self._apply_realtime_constraints()
        try:
            self.size_result = self._size_result()
        except Exception:
            self.size_result = None
        self.manual_order_snapshot = self._manual_order_snapshot()
        self._sync_runtime_controls()

    def check_mt5(self) -> None:
        try:
            result = self.runtime_coordinator.probe_mt5(
                symbol=self.symbol_var.get().strip(),
                timeframe=self.timeframe_var.get().strip(),
                trading_style=TradingStyle(self.style_var.get()),
                stop_distance_points=float(self.stop_var.get()),
                capital_allocation=self._capital_allocation(),
            )
        except Exception as exc:
            self.mt5_status_var.set("MT5 probe failed")
            self._handle_panel_error(exc, fallback_status="MT5 probe failed")
            return
        terminal = result["terminal"]
        snapshot = result["snapshot"]
        self._set_symbol_choices(result.get("symbols") or [])
        self._sync_stop_distance_from_probe(snapshot)
        self.mt5_status_var.set(
            " ".join(
                [
                    "connected" if terminal.get("connected") else "disconnected",
                    f"terminal_trade_allowed={terminal.get('trade_allowed')}",
                    f"account_trade_allowed={terminal.get('account_trade_allowed')}",
                    f"symbol_trade_allowed={snapshot.get('symbol_trade_allowed')}",
                ]
            )
        )
        self.status_var.set("MT5 readiness checked")
        self._write(
            [
                "mt5_probe:",
                f"- connected={terminal.get('connected')}",
                f"- terminal_trade_allowed={terminal.get('trade_allowed')}",
                f"- tradeapi_disabled={terminal.get('tradeapi_disabled')}",
                f"- account_trade_allowed={terminal.get('account_trade_allowed')}",
                f"- account_trade_expert={terminal.get('account_trade_expert')}",
                f"- server={terminal.get('server')}",
                f"- company={terminal.get('company')}",
                f"- path={terminal.get('path')}",
                "",
                "snapshot:",
                f"- symbol={snapshot.get('symbol')}",
                f"- bid={snapshot.get('bid')}",
                f"- ask={snapshot.get('ask')}",
                f"- spread_points={snapshot.get('spread_points')}",
                f"- equity={snapshot.get('equity')}",
                f"- free_margin={snapshot.get('free_margin')}",
                f"- broker_stop_min_points={snapshot.get('stops_level_points')}",
                f"- broker_freeze_points={snapshot.get('freeze_level_points')}",
                f"- available_symbols={len(result.get('symbols') or [])}",
            ]
        )

    def load_codex(self) -> None:
        try:
            version = self.runtime_coordinator.probe_codex(
                executable=self.codex_executable_var.get().strip(),
                model=self._optional_str(self.codex_model_var.get()),
                cwd=self._optional_str(self.codex_cwd_var.get()),
            )
        except Exception as exc:
            self.codex_status_var.set("codex-cli probe failed")
            self._handle_panel_error(exc, fallback_status="codex-cli probe failed")
            return
        self.codex_status_var.set(version)
        self.status_var.set("codex-cli ready")
        self._write(
            [
                "codex_probe:",
                f"- command={self.codex_executable_var.get().strip()}",
                f"- version={version}",
                f"- model={self._optional_str(self.codex_model_var.get()) or 'default'}",
                f"- work_folder={self._optional_str(self.codex_cwd_var.get()) or Path.cwd()}",
                "- model_list_note=codex-cli local help does not expose a reliable list-models command, so this field uses presets plus manual input",
            ]
        )

    def play_runtime(self) -> None:
        if self.runtime_coordinator.is_running:
            self.status_var.set("Runtime already running")
            return
        try:
            self.load_codex()
            self.check_mt5()
            config = self._desktop_runtime_config()
            run_id = self.runtime_coordinator.start(config)
        except Exception as exc:
            self._handle_panel_error(exc, fallback_status="Runtime failed to start")
            return
        self.db_path_var.set(config.db_path)
        self.current_run_id_var.set(run_id)
        self.approval_status_var.set("No pending live approval")
        self.runtime_status_var.set(f"Starting run {run_id}")
        self.status_var.set("Background runtime starting")
        self._append_output([f"runtime_starting run_id={run_id}", f"db_path={config.db_path}"])
        self._sync_runtime_controls()

    def stop_runtime(self) -> None:
        if not self.runtime_coordinator.is_running:
            self.status_var.set("Runtime already stopped")
            self._sync_runtime_controls()
            return
        self.runtime_coordinator.stop()
        self.runtime_status_var.set("Stopping runtime")
        self.status_var.set("Stopping background runtime")
        self._sync_runtime_controls()

    def toggle_live(self) -> None:
        if not self.runtime_coordinator.is_running:
            self.status_var.set("Start runtime first")
            self._append_output(["runtime_live_toggle_failed=runtime not running"])
            return
        try:
            probe = self.runtime_coordinator.probe_mt5(
                symbol=self.symbol_var.get().strip(),
                timeframe=self.timeframe_var.get().strip(),
                trading_style=TradingStyle(self.style_var.get()),
                stop_distance_points=float(self.stop_var.get()),
                capital_allocation=self._capital_allocation(),
            )
        except Exception as exc:
            self._handle_panel_error(exc, fallback_status="Live toggle failed")
            return
        terminal = probe["terminal"]
        enable_live = not self.runtime_coordinator.live_enabled
        if enable_live and not terminal.get("trade_allowed"):
            self.status_var.set("MT5 terminal blocks live trading")
            self._append_output(
                [
                    "live_toggle_rejected:",
                    f"terminal_trade_allowed={terminal.get('trade_allowed')}",
                    f"account_trade_allowed={terminal.get('account_trade_allowed')}",
                    f"tradeapi_disabled={terminal.get('tradeapi_disabled')}",
                ]
            )
            return
        self.runtime_coordinator.set_live_enabled(enable_live)
        self.allow_live_var.set(enable_live)
        self.runtime_status_var.set("Live orders enabled" if enable_live else "Live orders disabled")
        self.status_var.set("Live mode updated")
        self._sync_runtime_controls()

    def approve_pending_order(self) -> None:
        try:
            pending = self.runtime_coordinator.approve_pending_live_order()
        except Exception as exc:
            self._handle_panel_error(exc, fallback_status="Approve pending failed")
            return
        self.approval_status_var.set(f"Approved {pending.symbol} {pending.side} {pending.volume}")
        self._append_output(
            [
                "approval_armed:",
                f"run_id={pending.run_id}",
                f"symbol={pending.symbol}",
                f"side={pending.side}",
                f"volume={pending.volume}",
                f"price={pending.price}",
                f"approval_key={pending.approval_key}",
            ]
        )
        self.status_var.set("Pending live order approved")
        self._sync_runtime_controls()

    def reject_pending_order(self) -> None:
        try:
            pending = self.runtime_coordinator.reject_pending_live_order()
        except Exception as exc:
            self._handle_panel_error(exc, fallback_status="Reject pending failed")
            return
        self.approval_status_var.set("No pending live approval")
        self._append_output(
            [
                "approval_rejected:",
                f"run_id={pending.run_id}",
                f"symbol={pending.symbol}",
                f"side={pending.side}",
                f"volume={pending.volume}",
                f"price={pending.price}",
            ]
        )
        self.status_var.set("Pending live order rejected")
        self._sync_runtime_controls()

    def refresh(self) -> None:
        try:
            self.snapshot = self._provider().get_snapshot()
        except Exception as exc:
            self._handle_panel_error(exc, fallback_status="Snapshot refresh failed")
            return
        self._sync_stop_distance_from_symbol_snapshot(self.snapshot.symbol_snapshot)
        try:
            self.size_result = self._size_result()
        except Exception as exc:
            self.size_result = None
            self._handle_panel_error(exc, fallback_status="Sizing preview failed")
            return
        self.manual_order_snapshot = self._manual_order_snapshot()
        self._write(self._snapshot_lines() + [""] + self._manual_order_snapshot_lines() + [""] + self._sizing_snapshot_lines())
        self.status_var.set("Snapshot refreshed")
        self._sync_runtime_controls()

    def preflight(self) -> None:
        if self.snapshot is None:
            self.refresh()
        if self.snapshot is None:
            return
        try:
            self.size_result = self._size_result()
        except Exception as exc:
            self._handle_panel_error(exc, fallback_status="Preflight failed")
            return
        try:
            intent = self._intent("manual preflight")
            runtime = MT5ExecutionRuntime(adapter=self.adapter, allow_live_orders=False)
            result = runtime.preflight(self.snapshot, intent, self.size_result)
        except Exception as exc:
            self._handle_panel_error(exc, fallback_status="Preflight failed")
            return
        lines = [
            f"accepted={self.size_result.accepted}",
            f"mode={self.size_result.mode.value}",
            f"capital_base_cash={self.size_result.capital_base_cash}",
            f"allocation_mode={self.allocation_mode_var.get()}",
            f"allocation_value={self.allocation_var.get()}",
            f"volume={self.size_result.normalized_volume}",
            f"risk_cash_budget={self.size_result.risk_cash_budget}",
            f"status={result['status']}",
            f"detail={result['detail']}",
            f"retcode={result.get('retcode')}",
            f"projected_margin_free={result.get('projected_margin_free')}",
        ]
        if self.size_result.rejection_reason:
            lines.append(f"rejection_reason={self.size_result.rejection_reason}")
        for warning in self.size_result.warnings:
            lines.append(f"warning={warning}")
        self.manual_order_snapshot = self._manual_order_snapshot()
        lines.extend(["", *self._manual_order_snapshot_lines(), "", *self._sizing_snapshot_lines()])
        self._write(lines)
        self.status_var.set("Preflight complete")
        self._sync_runtime_controls()

    def execute(self) -> None:
        if self.snapshot is None or self.size_result is None:
            self.preflight()
        if self.snapshot is None or self.size_result is None:
            return
        try:
            self.manual_order_snapshot = self._manual_order_snapshot()
            if not self.manual_order_snapshot or not bool(self.manual_order_snapshot.get("accepted")):
                detail = str((self.manual_order_snapshot or {}).get("why_blocked") or "manual lot snapshot blocked")
                self._write(self._snapshot_lines() + [""] + self._manual_order_snapshot_lines() + ["", f"status=REJECTED", f"detail={detail}"])
                self.status_var.set("Execution blocked")
                self._sync_runtime_controls()
                return
            runtime = MT5ExecutionRuntime(adapter=self.adapter, allow_live_orders=self.allow_live_var.get())
            manual_size_result = SimpleNamespace(
                accepted=True,
                mode=OperatingMode.RECOMMEND,
                capital_base_cash=float(self.manual_order_snapshot.get("allocation_cap_usd") or 0.0),
                recommended_minimum_allocation_cash=0.0,
                effective_risk_pct=0.0,
                risk_cash_budget=0.0,
                normalized_volume=float(self.manual_order_snapshot.get("final_lot") or 0.0),
                estimated_loss_cash=0.0,
                stop_distance_points=float(self.stop_var.get()),
                rejection_reason=None,
                warnings=[],
            )
            result = runtime.execute(self.snapshot, self._intent("manual execute"), manual_size_result)
        except Exception as exc:
            self._handle_panel_error(exc, fallback_status="Execution failed")
            return
        self._write(
            self._snapshot_lines()
            + [""]
            + self._manual_order_snapshot_lines()
            + [""]
            + [
                f"status={result.get('status')}",
                f"detail={result.get('detail')}",
                f"retcode={result.get('retcode')}",
                f"order={result.get('order')}",
                f"deal={result.get('deal')}",
                f"price={result.get('price')}",
            ]
        )
        self.status_var.set("Execution attempted")
        self._sync_runtime_controls()

    def load_telemetry(self) -> None:
        store = RuntimeStore(self.db_path_var.get().strip())
        if not Path(store.db_path).exists():
            self.health_var.set("Runtime DB not found")
            self._write([f"runtime_db_missing={store.db_path}"])
            return
        target_run_id = self.current_run_id_var.get().strip() or self.runtime_coordinator.run_id
        overview = store.fetch_latest_run_overview(run_id=target_run_id or None)
        if overview is None:
            overview = store.fetch_latest_run_overview()
        if overview is None:
            self.health_var.set("Runtime DB loaded but no runs found")
            self._write(["no runtime runs found"])
            return
        run_id = str(overview.get("run_id") or "")
        self.current_run_id_var.set(run_id)
        health = store.fetch_execution_health_summary(run_id=run_id, limit=50)
        events = store.fetch_recent_execution_events(run_id=run_id, limit=10)
        rejections = store.fetch_recent_rejections(run_id=run_id, limit=10)
        positions = store.fetch_recent_position_events(run_id=run_id, limit=10)
        latest_guard = store.fetch_latest_risk_guard(run_id=run_id)
        validation_inputs = store.fetch_runtime_validation_inputs(run_id=run_id)
        validation_report = build_runtime_validation_report(
            validation_inputs["position_events"],
            validation_inputs["execution_events"],
            starting_equity=float(validation_inputs.get("starting_equity") or 0.0),
        )
        self.health_var.set(
            " ".join(
                [
                    f"run={overview.get('run_id')}",
                    f"status={overview.get('status')}",
                    f"spread={overview.get('spread_points')}",
                    f"equity={overview.get('equity')}",
                    f"free_margin={overview.get('free_margin')}",
                    f"fills={health.get('filled_events')}",
                    f"reject_rate={health.get('reject_rate', 0.0):.1%}",
                    f"mode={'live' if self.runtime_coordinator.live_enabled else 'dry-run'}",
                ]
            )
        )
        lines = [
            f"run_id={overview.get('run_id')}",
            f"status={overview.get('status')}",
            f"last_cycle={overview.get('polled_at')}",
            f"last_action={overview.get('last_action')}",
            f"spread_points={overview.get('spread_points')}",
            f"equity={overview.get('equity')}",
            f"free_margin={overview.get('free_margin')}",
            f"stop_reason={overview.get('stop_reason')}",
            f"runtime_mode={'live' if self.runtime_coordinator.live_enabled else 'dry-run'}",
            "",
            "validation_summary:",
            f"- total_trades={validation_report.validation_summary.total_trades}",
            f"- win_rate={validation_report.validation_summary.win_rate:.2%}",
            f"- profit_factor={validation_report.validation_summary.profit_factor:.3f}",
            f"- expectancy_r={validation_report.validation_summary.expectancy_r:.3f}",
            f"- total_pnl_cash={validation_report.validation_summary.total_pnl_cash:.2f}",
            f"- max_drawdown_cash={validation_report.validation_summary.max_drawdown_cash:.2f}",
            f"- max_drawdown_pct={validation_report.validation_summary.max_drawdown_pct:.2f}%",
            "",
            "execution_quality_run_scoped:",
            f"- total_order_attempts={validation_report.execution_quality.total_order_attempts}",
            f"- rejected_orders={validation_report.execution_quality.rejected_orders}",
            f"- reject_rate={validation_report.execution_quality.reject_rate:.2%}",
            f"- avg_spread_points={validation_report.execution_quality.average_entry_spread_points:.2f}",
            f"- avg_slippage_points={validation_report.execution_quality.average_slippage_points:.2f}",
            f"- avg_fill_latency_ms={validation_report.execution_quality.average_fill_latency_ms:.2f}",
            f"- spread_coverage={validation_report.execution_quality.entry_spread_observed_trades}/{validation_report.execution_quality.total_trade_records}",
            f"- slippage_coverage={validation_report.execution_quality.slippage_observed_trades}/{validation_report.execution_quality.total_trade_records}",
            f"- latency_coverage={validation_report.execution_quality.fill_latency_observed_trades}/{validation_report.execution_quality.total_trade_records}",
            "",
            "execution_health:",
            f"- total_events={health.get('total_events')}",
            f"- filled_events={health.get('filled_events')}",
            f"- dry_run_events={health.get('dry_run_events')}",
            f"- rejected_events={health.get('rejected_events')}",
            f"- reject_rate={health.get('reject_rate', 0.0):.2%}",
            f"- average_slippage_points={health.get('average_slippage_points', 0.0):.2f}",
            f"- average_fill_latency_ms={health.get('average_fill_latency_ms', 0.0):.2f}",
            "",
            "risk_guard:",
        ]
        if latest_guard is None:
            lines.append("- none")
        else:
            payload = latest_guard.get("payload_json") or {}
            lines.extend(
                [
                    f"- polled_at={latest_guard.get('polled_at')}",
                    f"- allowed={bool(latest_guard.get('allowed'))}",
                    f"- mode={latest_guard.get('mode')}",
                    f"- rejection_reason={latest_guard.get('rejection_reason')}",
                    f"- normalized_volume={latest_guard.get('normalized_volume')}",
                    f"- risk_cash_budget={latest_guard.get('risk_cash_budget')}",
                    f"- recommended_minimum_allocation_cash={payload.get('recommended_minimum_allocation_cash')}",
                    f"- warnings={payload.get('warnings')}",
                ]
            )
        lines.extend(["", "recent_positions:"])
        for position in positions:
            lines.append(
                " ".join(
                    [
                        f"- [{position.get('status')}]",
                        f"time={position.get('polled_at')}",
                        f"{position.get('symbol')}",
                        f"{position.get('side')}",
                        f"volume={position.get('volume')}",
                        f"entry={position.get('entry_price')}",
                        f"pnl={position.get('realized_pnl_cash')}",
                    ]
                )
            )
        lines.extend(["", "recent_execution_events:"])
        for event in events:
            lines.append(
                " ".join(
                    [
                        f"- [{event.get('status')}]",
                        f"time={event.get('polled_at')}",
                        f"attempt={event.get('attempt_id')}",
                        f"{event.get('symbol')}",
                        f"{event.get('side')}",
                        f"retcode={event.get('retcode')}",
                        f"slippage={event.get('slippage_points')}",
                        f"latency_ms={event.get('fill_latency_ms')}",
                        f"detail={event.get('detail')}",
                    ]
                )
            )
        lines.append("")
        lines.append("recent_rejections:")
        for rejection in rejections:
            lines.append(
                " ".join(
                    [
                        f"- [{rejection.get('source')}]",
                        f"time={rejection.get('polled_at')}",
                        f"cycle={rejection.get('cycle_id')}",
                        f"status={rejection.get('status')}",
                        f"detail={rejection.get('detail')}",
                    ]
                )
            )
        lines.append("")
        lines.append("validation_warnings:")
        for warning in validation_report.warnings + validation_report.validation_summary.warnings + validation_report.execution_quality.warnings:
            lines.append(f"- {warning}")
        lines.append("")
        lines.append("trade_lifecycle_rows:")
        for trade in validation_inputs["lifecycle_rows"][:5]:
            lines.append(
                " ".join(
                    [
                        f"- [{trade.get('lifecycle_status')}]",
                        f"{trade.get('symbol')}",
                        f"{trade.get('side')}",
                        f"entry={trade.get('entry_price')}",
                        f"exit={trade.get('exit_price')}",
                        f"pnl={trade.get('realized_pnl_cash')}",
                    ]
                )
            )
        self._write(lines)
        self.status_var.set("Telemetry loaded")

    def _desktop_runtime_config(self) -> DesktopRuntimeConfig:
        poll_interval = int(float(self.poll_interval_var.get()))
        if poll_interval <= 0:
            raise ValueError("poll interval must be positive")
        db_path = str(Path(self.db_path_var.get().strip()).expanduser())
        return DesktopRuntimeConfig(
            symbol=self.symbol_var.get().strip(),
            timeframe=self.timeframe_var.get().strip(),
            trading_style=TradingStyle(self.style_var.get()),
            stop_distance_points=float(self.stop_var.get()),
            capital_allocation=self._capital_allocation(),
            db_path=db_path,
            codex_executable=self.codex_executable_var.get().strip() or "codex",
            codex_model=self._optional_str(self.codex_model_var.get()),
            codex_cwd=self._optional_str(self.codex_cwd_var.get()),
            poll_interval_seconds=poll_interval,
        )

    def _provider(self) -> MT5SnapshotProvider:
        stop_distance_points = self._normalized_stop_distance_value()
        return MT5SnapshotProvider(
            adapter=self.adapter,
            symbol=self.symbol_var.get().strip(),
            timeframe=self.timeframe_var.get().strip(),
            risk_policy=self.risk_policy,
            trading_style=TradingStyle(self.style_var.get()),
            stop_distance_points=stop_distance_points,
            capital_allocation=self._capital_allocation(),
            session_state="manual",
            news_state="unknown",
        )

    def _snapshot_lines(self) -> list[str]:
        assert self.snapshot is not None
        return [
            f"symbol={self.snapshot.symbol}",
            f"bid={self.snapshot.bid}",
            f"ask={self.snapshot.ask}",
            f"spread_points={self.snapshot.spread_points:.2f}",
            f"equity={self.snapshot.account.equity}",
            f"free_margin={self.snapshot.account.free_margin}",
            f"allocation_mode={self.allocation_mode_var.get()}",
            f"allocation_value={self.allocation_var.get()}",
            f"trade_allowed={self.snapshot.symbol_snapshot.trade_allowed}",
            f"trade_mode={self.snapshot.symbol_snapshot.trade_mode}",
            f"order_mode={self.snapshot.symbol_snapshot.order_mode}",
            f"execution_mode={self.snapshot.symbol_snapshot.execution_mode}",
            f"filling_mode={self.snapshot.symbol_snapshot.filling_mode}",
        ]

    def _manual_order_snapshot(self) -> dict[str, float | str | bool] | None:
        limits = self._manual_order_limits()
        if limits is None:
            return None
        lot_mode = self.lot_mode_var.get().strip() or "auto_max"
        allocation_cap = limits["allocation_cap_usd"]
        if allocation_cap <= 0:
            return {
                "accepted": False,
                "final_lot": 0.0,
                "lot_mode": lot_mode,
                "why_blocked": "capital allocation must be positive",
            }
        min_lot = limits["broker_min_lot"]
        max_lot = limits["broker_max_lot"]
        step = limits["broker_lot_step"]
        order_price = limits["order_price"]
        available_budget = limits["available_margin_cap_usd"]
        margin_for_min = limits["margin_for_min_lot_usd"]
        final_lot = limits["affordable_max_lot"]
        margin_for_final = limits["margin_for_affordable_max_lot_usd"]
        if min_lot <= 0 or step <= 0 or max_lot <= 0 or order_price <= 0:
            return {
                "accepted": False,
                "final_lot": 0.0,
                "lot_mode": lot_mode,
                "why_blocked": "symbol volume or price configuration is invalid",
            }
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
                requested_lot = float(self.manual_lot_var.get())
            except ValueError:
                return {
                    "accepted": False,
                    "final_lot": 0.0,
                    "lot_mode": lot_mode,
                    "why_blocked": "manual lot must be a valid number",
                }
            if requested_lot <= 0:
                return {
                    "accepted": False,
                    "final_lot": 0.0,
                    "lot_mode": lot_mode,
                    "why_blocked": "manual lot must be positive",
                }
            normalized_requested = round((int(max(requested_lot, min_lot) / step) * step), 8)
            if normalized_requested < min_lot:
                normalized_requested = min_lot
            if normalized_requested < min_lot:
                return {
                    "accepted": False,
                    "final_lot": 0.0,
                    "lot_mode": lot_mode,
                    "requested_lot": requested_lot,
                    "broker_min_lot": min_lot,
                    "why_blocked": "manual lot is below broker minimum lot",
                }
            if normalized_requested > final_lot:
                resized = True
                why_blocked = "manual lot resized down to max allowed by capital, margin, and broker"
            elif abs(normalized_requested - requested_lot) > 1e-9:
                resized = True
                why_blocked = "manual lot normalized to broker minimum / step"
            final_lot = min(normalized_requested, final_lot)
            margin = self.adapter.estimate_margin(self.snapshot.symbol, final_lot, self.side_var.get(), order_price)
            margin_for_final = margin.required_margin if margin.success else margin_for_final
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

    def _manual_order_limits(self) -> dict[str, float] | None:
        if self.snapshot is None:
            return None
        symbol = self.snapshot.symbol_snapshot
        side = self.side_var.get()
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

    def _manual_order_snapshot_lines(self) -> list[str]:
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

    def _sizing_snapshot_lines(self) -> list[str]:
        if self.snapshot is None or self.size_result is None:
            return ["sizing_snapshot=unavailable"]
        size = self.size_result
        symbol = self.snapshot.symbol_snapshot
        lot_at_min = symbol.volume_min if symbol.volume_min > 0 else 0.0
        min_lot_risk_cash = lot_at_min * size.loss_per_lot if lot_at_min > 0 and size.loss_per_lot > 0 else 0.0
        risk_pct_of_capital = (
            (size.risk_cash_budget / size.capital_base_cash) * 100.0
            if size.capital_base_cash > 0
            else 0.0
        )
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
        stop_distance_points = self._normalized_stop_distance_value()
        return self.risk_engine.compute_position_size(
            PositionSizeRequest(
                account=self.snapshot.account,
                symbol=self.snapshot.symbol_snapshot,
                policy=self.snapshot.risk_policy,
                stop_distance_points=stop_distance_points,
                trading_style=TradingStyle(self.style_var.get()),
                capital_allocation=self._capital_allocation(),
            )
        )

    def _allocation_capital_basis(self) -> float:
        account_equity = max(self.snapshot.account.equity, 0.0) if self.snapshot is not None else 0.0
        allocation = self._capital_allocation()
        if allocation.mode is CapitalAllocationMode.FULL_EQUITY:
            return account_equity
        if allocation.mode is CapitalAllocationMode.PERCENT_EQUITY:
            pct = min(max(allocation.value, 0.0), 100.0)
            return account_equity * (pct / 100.0)
        return min(max(allocation.value, 0.0), account_equity)

    def _intent(self, reason: str) -> AIIntent:
        side = self.side_var.get()
        stop_distance_points = self._normalized_stop_distance_value()
        return AIIntent(
            action=DecisionAction.OPEN,
            side=side,
            reason=reason,
            stop_distance_points=stop_distance_points,
            entry_price=self.snapshot.ask if side == "buy" else self.snapshot.bid,
        )

    def _capital_allocation(self) -> CapitalAllocation:
        mode = CapitalAllocationMode(self.allocation_mode_var.get())
        raw_value = float(self.allocation_var.get())
        if mode is CapitalAllocationMode.FULL_EQUITY:
            return CapitalAllocation(mode=mode, value=100.0)
        if mode is CapitalAllocationMode.PERCENT_EQUITY and not 0.0 <= raw_value <= 100.0:
            raise ValueError("percent_equity allocation must be between 0 and 100")
        if mode is CapitalAllocationMode.FIXED_CASH and raw_value < 0.0:
            raise ValueError("fixed_cash allocation must be non-negative")
        return CapitalAllocation(mode=mode, value=raw_value)

    def _sync_allocation_label(self) -> None:
        mode = CapitalAllocationMode(self.allocation_mode_var.get())
        if mode is CapitalAllocationMode.PERCENT_EQUITY:
            self.allocation_label_var.set("Capital To Use (% Equity)")
            return
        if mode is CapitalAllocationMode.FULL_EQUITY:
            self.allocation_label_var.set("Capital To Use (Full Equity)")
            return
        self.allocation_label_var.set("Capital To Use (USD)")

    def _set_symbol_choices(self, symbols: list[str]) -> None:
        if self.symbol_combo is None:
            return
        values = tuple(symbols) if symbols else (self.symbol_var.get(),)
        self.symbol_combo.configure(values=values)
        current = self.symbol_var.get().strip()
        if current not in values and values:
            self.symbol_var.set(values[0])

    def _apply_realtime_constraints(self) -> None:
        self._field_trace_guard = True
        try:
            self._sync_stop_distance_from_symbol_snapshot(self.snapshot.symbol_snapshot)
            self._apply_manual_lot_realtime_bounds()
        finally:
            self._field_trace_guard = False

    def _apply_manual_lot_realtime_bounds(self) -> None:
        if self.snapshot is None or self.lot_mode_var.get().strip() != "manual":
            return
        limits = self._manual_order_limits()
        if limits is None:
            return
        min_lot = float(limits["broker_min_lot"])
        step = float(limits["broker_lot_step"])
        affordable_max_lot = float(limits["affordable_max_lot"])
        try:
            requested = float(self.manual_lot_var.get())
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
            self.manual_lot_var.set(f"{normalized:.2f}")

    def _sync_stop_distance_from_probe(self, snapshot: dict[str, object]) -> None:
        stop_min = float(snapshot.get("stops_level_points") or 0.0)
        self._apply_stop_distance_floor(stop_min)

    def _sync_stop_distance_from_symbol_snapshot(self, symbol_snapshot) -> None:
        stop_min = float(getattr(symbol_snapshot, "stops_level_points", 0.0) or 0.0)
        self._apply_stop_distance_floor(stop_min)

    def _apply_stop_distance_floor(self, stop_min: float) -> None:
        if stop_min > 0:
            self.stop_label_var.set(f"Stop Distance (points, min {stop_min:.0f})")
        else:
            self.stop_label_var.set("Stop Distance (points)")
        try:
            current = float(self.stop_var.get())
        except ValueError:
            current = stop_min
        if stop_min > 0 and current < stop_min:
            self.stop_var.set(f"{stop_min:.0f}")

    def _normalized_stop_distance_value(self) -> float:
        try:
            current = float(self.stop_var.get())
        except ValueError as exc:
            raise ValueError("stop distance must be a valid number") from exc
        if self.snapshot is None:
            return current
        stop_min = float(self.snapshot.symbol_snapshot.stops_level_points or 0.0)
        if stop_min > 0 and current < stop_min:
            self.stop_var.set(f"{stop_min:.0f}")
            return stop_min
        return current

    def _pump_runtime_events(self) -> None:
        try:
            for event in self.runtime_coordinator.drain_events():
                self._handle_runtime_event(event.kind, event.message, event.payload)
        finally:
            self.root.after(250, self._pump_runtime_events)

    def _handle_runtime_event(self, kind: str, message: str, payload: dict[str, object]) -> None:
        if kind == "runtime_started":
            self.runtime_status_var.set(self._summarize_runtime_message(message))
            db_path = payload.get("db_path")
            if isinstance(db_path, str):
                self.db_path_var.set(db_path)
            run_id = payload.get("run_id")
            if isinstance(run_id, str):
                self.current_run_id_var.set(run_id)
        elif kind == "runtime_cycle":
            self.runtime_status_var.set(self._summarize_runtime_message(message))
            overview = payload.get("overview") if isinstance(payload.get("overview"), dict) else {}
            health = payload.get("health") if isinstance(payload.get("health"), dict) else {}
            if isinstance(payload.get("run_id"), str):
                self.current_run_id_var.set(str(payload.get("run_id")))
            self.health_var.set(
                " ".join(
                    [
                        f"run={overview.get('run_id')}",
                        f"status={overview.get('status')}",
                        f"last_action={payload.get('action')}",
                        f"fills={health.get('filled_events')}",
                        f"reject_rate={health.get('reject_rate', 0.0):.1%}" if isinstance(health.get("reject_rate"), (int, float)) else "reject_rate=n/a",
                        f"mode={'live' if payload.get('live_enabled') else 'dry-run'}",
                    ]
                ).strip()
            )
            if self.db_path_var.get().strip():
                self.load_telemetry()
        elif kind in {"runtime_stopped", "runtime_error", "runtime_halted"}:
            self.runtime_status_var.set(self._summarize_runtime_message(message))
            if kind == "runtime_error":
                self._append_output(
                    [
                        "runtime_error_detail:",
                        f"- {message}",
                        "- hint=lihat MT5 terminal, lalu klik Check MT5 lagi. Jika error terkait Codex, klik Load Codex lagi.",
                    ]
                )
            if kind != "runtime_error":
                self.approval_status_var.set("No pending live approval")
        elif kind == "mt5_ready":
            self.mt5_status_var.set(self._summarize_runtime_message(message))
        elif kind == "codex_ready":
            version = payload.get("version")
            self.codex_status_var.set(self._summarize_runtime_message(str(version or message)))
        elif kind == "live_toggle":
            enabled = bool(payload.get("enabled"))
            self.allow_live_var.set(enabled)
            self.runtime_status_var.set(self._summarize_runtime_message(message))
        elif kind == "approval_pending":
            self.approval_status_var.set(self._summarize_runtime_message(message))
            self._append_output(
                [
                    "approval_pending:",
                    f"symbol={payload.get('symbol')}",
                    f"side={payload.get('side')}",
                    f"volume={payload.get('volume')}",
                    f"price={payload.get('price')}",
                    f"approval_key={payload.get('approval_key')}",
                ]
            )
        elif kind in {"approval_armed", "approval_rejected", "approval_status"}:
            self.approval_status_var.set(self._summarize_runtime_message(message))
        self.status_var.set(self._summarize_runtime_message(message))
        self._sync_runtime_controls()

    def _sync_runtime_controls(self) -> None:
        running = self.runtime_coordinator.is_running
        live_enabled = self.runtime_coordinator.live_enabled
        pending = self.runtime_coordinator.pending_approval is not None
        manual_execute_allowed = bool(
            self.manual_order_snapshot
            and bool(self.manual_order_snapshot.get("accepted"))
            and float(self.manual_order_snapshot.get("final_lot") or 0.0) > 0
        )
        if self.play_button is not None:
            self.play_button.state(["disabled"] if running else ["!disabled"])
        if self.stop_button is not None:
            self.stop_button.state(["!disabled"] if running else ["disabled"])
        if self.live_button is not None:
            self.live_button.state(["!disabled"] if running else ["disabled"])
        if self.approve_button is not None:
            self.approve_button.state(["!disabled"] if pending else ["disabled"])
        if self.reject_button is not None:
            self.reject_button.state(["!disabled"] if pending else ["disabled"])
        if self.execute_button is not None:
            self.execute_button.state(["!disabled"] if manual_execute_allowed else ["disabled"])
        self.live_button_text_var.set("Disable Live" if live_enabled else "Enable Live")

    def _handle_panel_error(self, exc: Exception, *, fallback_status: str) -> None:
        detailed = self._format_exception_detail(exc)
        self.status_var.set(self._summarize_runtime_message(f"{fallback_status}: {detailed}"))
        self._write([f"error={detailed}"])

    def _write(self, lines: list[str]) -> None:
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, "\n".join(lines))

    def _append_output(self, lines: list[str]) -> None:
        existing = self.output.get("1.0", tk.END).strip()
        merged = "\n".join(filter(None, [existing, *lines]))
        self._write(merged.splitlines())

    def _on_close(self) -> None:
        self.runtime_coordinator.stop(join_timeout=1.0)
        shutdown = getattr(self.adapter, "shutdown", None)
        if callable(shutdown):
            shutdown()
        self.root.destroy()

    @staticmethod
    def _optional_str(value: str) -> str | None:
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _summarize_runtime_message(message: str, *, limit: int = 120) -> str:
        normalized = " ".join(str(message).split())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[: limit - 3]}..."

    @staticmethod
    def _format_exception_detail(exc: Exception) -> str:
        message = str(exc).strip() or exc.__class__.__name__
        if "No IPC connection" in message:
            return "MT5 lost IPC connection. Reopen or refocus MT5, then click Check MT5 again."
        if "account_info() failed" in message:
            return "MT5 account info could not be read. Check terminal connection and account login."
        if "Command '['" in message and "codex" in message:
            return "Codex runtime command failed. Click Load Codex again and check model/work folder."
        return message


def main() -> None:
    root = tk.Tk()
    LiveControlPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
