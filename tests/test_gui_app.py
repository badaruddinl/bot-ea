from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tkinter as tk  # noqa: E402

from bot_ea.gui_app import LiveControlPanel  # noqa: E402
from bot_ea.models import CapitalAllocationMode  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
