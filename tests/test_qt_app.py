from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class QtAppTests(unittest.TestCase):
    def test_qt_window_constructs(self) -> None:
        try:
            from PySide6.QtWidgets import QApplication
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"PySide6 unavailable: {exc}")

        from bot_ea.qt_app import BotEaQtWindow

        app = QApplication.instance() or QApplication([])
        window = BotEaQtWindow()
        try:
            self.assertEqual(window.windowTitle(), "bot-ea Qt Desktop Runtime")
            self.assertEqual(window.symbol_combo.currentText(), "EURUSD")
            self.assertEqual(window.timeframe_combo.currentText(), "M15")
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
