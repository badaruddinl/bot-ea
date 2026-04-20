from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from pathlib import Path

from .models import CapitalAllocation, CapitalAllocationMode, PositionSizeRequest, RiskPolicy, TradingStyle
from .mt5_adapter import LiveMT5Adapter
from .mt5_execution_runtime import MT5ExecutionRuntime
from .polling_runtime import AIIntent, DecisionAction, MT5SnapshotProvider
from .risk_engine import RiskEngine
from .runtime_store import RuntimeStore


class LiveControlPanel:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("bot-ea Live Control")
        self.adapter = LiveMT5Adapter()
        self.risk_engine = RiskEngine()
        self.risk_policy = RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0)
        self.symbol_var = tk.StringVar(value="XAUUSD")
        self.timeframe_var = tk.StringVar(value="M15")
        self.style_var = tk.StringVar(value=TradingStyle.INTRADAY.value)
        self.stop_var = tk.StringVar(value="200")
        self.allocation_mode_var = tk.StringVar(value=CapitalAllocationMode.FIXED_CASH.value)
        self.allocation_label_var = tk.StringVar(value="Allocation Cash (USD)")
        self.allocation_var = tk.StringVar(value="250")
        self.side_var = tk.StringVar(value="buy")
        self.db_path_var = tk.StringVar(value=str(Path.cwd() / "bot_ea_runtime.db"))
        self.allow_live_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")
        self.health_var = tk.StringVar(value="No runtime DB loaded")
        self.snapshot = None
        self.size_result = None
        self._build()

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        fields = [
            ("Symbol", self.symbol_var),
            ("Timeframe", self.timeframe_var),
            ("Style", self.style_var),
            ("Stop Points", self.stop_var),
            ("Allocation Mode", self.allocation_mode_var),
            (self.allocation_label_var, self.allocation_var),
            ("Side", self.side_var),
            ("Runtime DB", self.db_path_var),
        ]
        for row, (label, variable) in enumerate(fields):
            ttk.Label(frame, textvariable=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4) if isinstance(label, tk.StringVar) else ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            if (label if isinstance(label, str) else label.get()) in {"Style", "Allocation Mode", "Side"}:
                label_key = label if isinstance(label, str) else label.get()
                if label_key == "Style":
                    values = [style.value for style in TradingStyle]
                elif label_key == "Allocation Mode":
                    values = [mode.value for mode in CapitalAllocationMode]
                else:
                    values = ["buy", "sell"]
                combo = ttk.Combobox(frame, textvariable=variable, values=values, state="readonly", width=18)
                combo.grid(
                    row=row, column=1, sticky="ew", pady=4
                )
                if label_key == "Allocation Mode":
                    combo.bind("<<ComboboxSelected>>", lambda _event: self._sync_allocation_label())
            else:
                ttk.Entry(frame, textvariable=variable, width=18).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Checkbutton(frame, text="Allow Live Orders", variable=self.allow_live_var).grid(
            row=len(fields), column=0, columnspan=2, sticky="w", pady=(8, 4)
        )
        button_bar = ttk.Frame(frame)
        button_bar.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="w", pady=(8, 8))
        ttk.Button(button_bar, text="Refresh", command=self.refresh).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(button_bar, text="Preflight", command=self.preflight).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(button_bar, text="Execute", command=self.execute).grid(row=0, column=2)
        ttk.Button(button_bar, text="Load Telemetry", command=self.load_telemetry).grid(row=0, column=3, padx=(6, 0))
        ttk.Label(frame, textvariable=self.health_var).grid(row=len(fields) + 2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.output = tk.Text(frame, width=100, height=28, wrap="word")
        self.output.grid(row=len(fields) + 3, column=0, columnspan=2, sticky="nsew")
        ttk.Label(frame, textvariable=self.status_var).grid(row=len(fields) + 4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(len(fields) + 3, weight=1)

    def refresh(self) -> None:
        try:
            self.snapshot = self._provider().get_snapshot()
        except ValueError as exc:
            self.status_var.set("Invalid allocation input")
            self._write([f"error={exc}"])
            return
        self.size_result = None
        self._write(
            [
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
        )
        self.status_var.set("Snapshot refreshed")

    def preflight(self) -> None:
        if self.snapshot is None:
            self.refresh()
        if self.snapshot is None:
            return
        try:
            self.size_result = self._size_result()
        except ValueError as exc:
            self.status_var.set("Invalid allocation input")
            self._write([f"error={exc}"])
            return
        intent = self._intent("manual preflight")
        runtime = MT5ExecutionRuntime(adapter=self.adapter, allow_live_orders=False)
        result = runtime.preflight(self.snapshot, intent, self.size_result)
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
        self._write(lines)
        self.status_var.set("Preflight complete")

    def execute(self) -> None:
        if self.snapshot is None or self.size_result is None:
            self.preflight()
        assert self.snapshot is not None
        assert self.size_result is not None
        runtime = MT5ExecutionRuntime(adapter=self.adapter, allow_live_orders=self.allow_live_var.get())
        result = runtime.execute(self.snapshot, self._intent("manual execute"), self.size_result)
        self._write(
            [
                f"status={result.get('status')}",
                f"detail={result.get('detail')}",
                f"retcode={result.get('retcode')}",
                f"order={result.get('order')}",
                f"deal={result.get('deal')}",
                f"price={result.get('price')}",
            ]
        )
        self.status_var.set("Execution attempted")

    def load_telemetry(self) -> None:
        store = RuntimeStore(self.db_path_var.get().strip())
        if not Path(store.db_path).exists():
            self.health_var.set("Runtime DB not found")
            self._write([f"runtime_db_missing={store.db_path}"])
            return
        overview = store.fetch_latest_run_overview()
        health = store.fetch_execution_health_summary(limit=50)
        events = store.fetch_recent_execution_events(limit=10)
        rejections = store.fetch_recent_rejections(limit=10)
        positions = store.fetch_recent_position_events(limit=10)
        latest_guard = store.fetch_latest_risk_guard()
        if overview is None:
            self.health_var.set("Runtime DB loaded but no runs found")
            self._write(["no runtime runs found"])
            return
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
        lines.extend(
            [
                "",
            "recent_positions:",
            ]
        )
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
        lines.extend(
            [
                "",
            "recent_execution_events:",
            ]
        )
        for event in events:
            lines.append(
                " ".join(
                    [
                        f"- [{event.get('status')}]",
                        f"time={event.get('polled_at')}",
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
        self._write(lines)
        self.status_var.set("Telemetry loaded")

    def _provider(self) -> MT5SnapshotProvider:
        return MT5SnapshotProvider(
            adapter=self.adapter,
            symbol=self.symbol_var.get().strip(),
            timeframe=self.timeframe_var.get().strip(),
            risk_policy=self.risk_policy,
            trading_style=TradingStyle(self.style_var.get()),
            stop_distance_points=float(self.stop_var.get()),
            capital_allocation=self._capital_allocation(),
            session_state="manual",
            news_state="unknown",
        )

    def _size_result(self):
        return self.risk_engine.compute_position_size(
            PositionSizeRequest(
                account=self.snapshot.account,
                symbol=self.snapshot.symbol_snapshot,
                policy=self.snapshot.risk_policy,
                stop_distance_points=float(self.stop_var.get()),
                trading_style=TradingStyle(self.style_var.get()),
                capital_allocation=self._capital_allocation(),
            )
        )

    def _intent(self, reason: str) -> AIIntent:
        side = self.side_var.get()
        return AIIntent(
            action=DecisionAction.OPEN,
            side=side,
            reason=reason,
            stop_distance_points=float(self.stop_var.get()),
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
            self.allocation_label_var.set("Allocation (% Equity)")
            return
        if mode is CapitalAllocationMode.FULL_EQUITY:
            self.allocation_label_var.set("Allocation (Full Equity)")
            return
        self.allocation_label_var.set("Allocation Cash (USD)")

    def _write(self, lines: list[str]) -> None:
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, "\n".join(lines))


def main() -> None:
    root = tk.Tk()
    LiveControlPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
