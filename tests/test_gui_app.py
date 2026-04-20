from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tkinter as tk  # noqa: E402

from bot_ea.gui_app import LiveControlPanel  # noqa: E402
from bot_ea.models import CapitalAllocationMode  # noqa: E402


class FakeRuntimeCoordinator:
    def __init__(self) -> None:
        self.is_running = False
        self.live_enabled = False
        self.started_with = None
        self.mt5_trade_allowed = True
        self.pending_approval = None

    def probe_mt5(self, **_: object) -> dict:
        return {
            "terminal": {
                "connected": True,
                "trade_allowed": self.mt5_trade_allowed,
                "tradeapi_disabled": False,
                "account_trade_allowed": True,
                "account_trade_expert": True,
                "server": "Demo",
                "company": "Demo Broker",
                "path": "C:\\Program Files\\MetaTrader 5",
            },
            "snapshot": {
                "symbol": "EURUSD",
                "bid": 1.1,
                "ask": 1.1002,
                "spread_points": 2.0,
                "equity": 1000.0,
                "free_margin": 900.0,
                "symbol_trade_allowed": True,
            },
        }

    def probe_codex(self, **_: object) -> str:
        return "codex-cli fake"

    def start(self, config) -> str:
        self.started_with = config
        self.is_running = True
        return "run-123"

    def stop(self, join_timeout: float = 5.0) -> None:
        _ = join_timeout
        self.is_running = False
        self.live_enabled = False

    def set_live_enabled(self, enabled: bool) -> None:
        self.live_enabled = enabled

    def approve_pending_live_order(self):
        pending = self.pending_approval
        self.pending_approval = None
        return pending

    def reject_pending_live_order(self):
        pending = self.pending_approval
        self.pending_approval = None
        return pending

    def drain_events(self) -> list:
        return []


class GuiAppTests(unittest.TestCase):
    def _make_root(self) -> tk.Tk:
        try:
            root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover - environment-dependent
            self.skipTest(f"Tk unavailable in test environment: {exc}")
        root.withdraw()
        return root

    def test_capital_allocation_supports_fixed_cash(self) -> None:
        root = self._make_root()
        try:
            panel = LiveControlPanel(root)
            panel.allocation_mode_var.set(CapitalAllocationMode.FIXED_CASH.value)
            panel.allocation_var.set("250")
            allocation = panel._capital_allocation()
            self.assertEqual(allocation.mode, CapitalAllocationMode.FIXED_CASH)
            self.assertEqual(allocation.value, 250.0)
        finally:
            root.destroy()

    def test_capital_allocation_supports_percent_equity(self) -> None:
        root = self._make_root()
        try:
            panel = LiveControlPanel(root)
            panel.allocation_mode_var.set(CapitalAllocationMode.PERCENT_EQUITY.value)
            panel.allocation_var.set("35")
            allocation = panel._capital_allocation()
            self.assertEqual(allocation.mode, CapitalAllocationMode.PERCENT_EQUITY)
            self.assertEqual(allocation.value, 35.0)
        finally:
            root.destroy()

    def test_percent_equity_validation_rejects_values_above_100(self) -> None:
        root = self._make_root()
        try:
            panel = LiveControlPanel(root)
            panel.allocation_mode_var.set(CapitalAllocationMode.PERCENT_EQUITY.value)
            panel.allocation_var.set("250")
            with self.assertRaises(ValueError):
                panel._capital_allocation()
        finally:
            root.destroy()

    def test_play_runtime_uses_coordinator_and_updates_runtime_status(self) -> None:
        root = self._make_root()
        coordinator = FakeRuntimeCoordinator()
        try:
            panel = LiveControlPanel(root, runtime_coordinator=coordinator)
            panel.play_runtime()
            self.assertTrue(coordinator.is_running)
            self.assertIsNotNone(coordinator.started_with)
            self.assertIn("run-123", panel.runtime_status_var.get())
            self.assertEqual(panel.db_path_var.get(), coordinator.started_with.db_path)
        finally:
            root.destroy()

    def test_toggle_live_rejects_when_mt5_terminal_blocks_trading(self) -> None:
        root = self._make_root()
        coordinator = FakeRuntimeCoordinator()
        coordinator.is_running = True
        coordinator.mt5_trade_allowed = False
        try:
            panel = LiveControlPanel(root, runtime_coordinator=coordinator)
            panel.toggle_live()
            self.assertFalse(coordinator.live_enabled)
            self.assertEqual(panel.status_var.get(), "MT5 terminal blocks live trading")
        finally:
            root.destroy()

    def test_sync_runtime_controls_enables_approval_buttons_when_pending_exists(self) -> None:
        root = self._make_root()
        coordinator = FakeRuntimeCoordinator()
        coordinator.is_running = True
        coordinator.pending_approval = type("Pending", (), {"symbol": "EURUSD", "side": "buy", "volume": 0.01, "price": 1.1, "approval_key": "key", "run_id": "run-1"})()
        try:
            panel = LiveControlPanel(root, runtime_coordinator=coordinator)
            panel._sync_runtime_controls()
            assert panel.approve_button is not None
            assert panel.reject_button is not None
            self.assertFalse(panel.approve_button.instate(["disabled"]))
            self.assertFalse(panel.reject_button.instate(["disabled"]))
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
