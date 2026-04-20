from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class QtAppTests(unittest.TestCase):
    def _make_adapter(self):
        from bot_ea.mt5_adapter import MockMT5Adapter

        return MockMT5Adapter(
            account_info={"equity": 1000.0, "balance": 1000.0, "margin_free": 900.0, "margin_level": 400.0},
            symbols={
                "XAUUSD": {
                    "name": "XAUUSD",
                    "point": 0.01,
                    "trade_tick_size": 0.01,
                    "trade_tick_value": 0.1,
                    "volume_min": 0.01,
                    "volume_max": 50.0,
                    "volume_step": 0.01,
                    "spread": 17,
                    "trade_stops_level": 10,
                    "trade_freeze_level": 0,
                    "visible": True,
                    "bid": 4797.74,
                    "ask": 4797.91,
                    "price": 4797.91,
                }
            },
        )

    def test_qt_window_constructs(self) -> None:
        try:
            from PySide6.QtWidgets import QApplication
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"PySide6 unavailable: {exc}")

        from bot_ea.qt_app import BotEaQtWindow

        app = QApplication.instance() or QApplication([])
        window = BotEaQtWindow(adapter=self._make_adapter())
        try:
            self.assertEqual(window.windowTitle(), "bot-ea Qt Desktop Runtime")
            self.assertEqual(window.symbol_combo.currentText(), "EURUSD")
            self.assertEqual(window.timeframe_combo.currentText(), "M15")
        finally:
            window.close()

    def test_qt_refresh_snapshot_populates_cards(self) -> None:
        try:
            from PySide6.QtWidgets import QApplication
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"PySide6 unavailable: {exc}")

        from bot_ea.qt_app import BotEaQtWindow

        app = QApplication.instance() or QApplication([])
        window = BotEaQtWindow(adapter=self._make_adapter())
        try:
            window.symbol_combo.setCurrentText("XAUUSD")
            window.capital_input.setText("20")
            window.refresh_snapshot()
            self.assertIn("symbol=XAUUSD", window.market_card["text"].toPlainText())
            self.assertIn("manual_order_snapshot:", window.manual_card["text"].toPlainText())
            self.assertIn("sizing_snapshot:", window.risk_card["text"].toPlainText())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
