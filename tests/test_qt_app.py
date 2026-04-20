from __future__ import annotations

import os
import socket
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class FakeBackend:
    def __init__(self) -> None:
        self.connected_urls: list[str] = []
        self.requests: list[tuple[str, dict]] = []
        self.events: list[dict] = []
        self.start_managed_calls = 0
        self.stop_managed_calls = 0
        self._managed_running = False
        self.refresh_counter = 0
        self._manual_snapshot = {
            "lot_mode": "manual",
            "requested_lot": 1.0,
            "final_lot": 0.01,
            "allocation_cap_usd": 20.0,
            "available_margin_cap_usd": 20.0,
            "broker_min_lot": 0.01,
            "broker_max_lot": 50.0,
            "broker_lot_step": 0.01,
            "margin_for_min_lot_usd": 9.6,
            "margin_for_final_lot_usd": 9.6,
            "order_price": 4797.91,
            "resized_down": True,
            "accepted": True,
            "why_blocked": "manual lot resized down to max allowed by capital, margin, and broker",
        }

    def connect(self, url: str) -> dict:
        self.connected_urls.append(url)
        return {"host": "127.0.0.1", "port": 8765}

    def start_managed_service(self) -> dict:
        self.start_managed_calls += 1
        self._managed_running = True
        return {"host": "127.0.0.1", "port": 8765}

    def stop_managed_service(self) -> None:
        self.stop_managed_calls += 1
        self._managed_running = False

    def is_managed_service_running(self) -> bool:
        return self._managed_running

    def managed_service_url(self) -> str:
        return "ws://127.0.0.1:8765"

    def managed_service_label(self) -> str:
        return "App-managed"

    def request(self, name: str, params: dict, timeout: float = 15.0):
        _ = timeout
        self.requests.append((name, dict(params)))
        if name == "probe_mt5":
            return {
                "terminal": {
                    "connected": True,
                    "trade_allowed": True,
                    "account_trade_allowed": True,
                },
                "snapshot": {
                    "symbol_trade_allowed": True,
                    "stops_level_points": 10.0,
                },
                "symbols": ["EURUSD", "XAUUSD"],
            }
        if name == "probe_codex":
            return "codex 1.0.0"
        if name == "refresh_manual":
            self.refresh_counter += 1
            return {
                "snapshot": {
                    "symbol": "XAUUSD",
                    "bid": 4797.74 + self.refresh_counter,
                    "ask": 4797.91 + self.refresh_counter,
                    "spread_points": 17.0,
                    "equity": 1000.0,
                    "free_margin": 900.0,
                    "stops_level_points": 10.0,
                    "trade_mode": "full",
                    "execution_mode": "market",
                    "filling_mode": "fok",
                    "tick_time": f"2026-04-21T00:00:{self.refresh_counter:02d}+00:00",
                },
                "manual_order_snapshot": dict(self._manual_snapshot),
                "risk_sizing_snapshot": {
                    "accepted": True,
                    "final_lot": 0.01,
                    "raw_lot_before_broker_rounding": 0.0123,
                    "effective_risk_pct": 1.0,
                    "risk_cash_budget_usd": 10.0,
                    "estimated_loss_at_final_lot_usd": 9.6,
                    "why_blocked": "n/a",
                },
            }
        if name == "preflight_manual":
            return {
                "status": "PRECHECK_OK",
                "detail": "ok",
                "retcode": 0,
                "projected_margin_free": 890.4,
                "snapshot": {
                    "symbol": "XAUUSD",
                    "bid": 4801.0,
                    "ask": 4801.17,
                    "spread_points": 17.0,
                    "equity": 1000.0,
                    "free_margin": 890.4,
                    "stops_level_points": 10.0,
                    "trade_mode": "full",
                    "execution_mode": "market",
                    "filling_mode": "fok",
                    "tick_time": "2026-04-21T00:00:09+00:00",
                },
                "manual_order_snapshot": dict(self._manual_snapshot),
            }
        if name == "execute_manual":
            return {
                "status": "DRY_RUN_OK",
                "detail": "filled",
                "retcode": 0,
                "order": 123,
                "deal": 456,
                "snapshot": {
                    "symbol": "XAUUSD",
                    "bid": 4802.0,
                    "ask": 4802.17,
                    "spread_points": 17.0,
                    "equity": 1000.0,
                    "free_margin": 890.4,
                    "stops_level_points": 10.0,
                    "trade_mode": "full",
                    "execution_mode": "market",
                    "filling_mode": "fok",
                    "tick_time": "2026-04-21T00:00:10+00:00",
                },
                "manual_order_snapshot": dict(self._manual_snapshot),
            }
        if name == "start_runtime":
            self.events.append(
                {
                    "name": "runtime_started",
                    "payload": {
                        "message": "runtime started",
                        "run_id": "run-123",
                    },
                }
            )
            self.events.append(
                {
                    "name": "runtime_cycle",
                    "payload": {
                        "message": "runtime cycle",
                        "run_id": "run-123",
                        "snapshot": {
                            "symbol": "XAUUSD",
                            "bid": 4803.0,
                            "ask": 4803.17,
                            "spread_points": 17.0,
                            "tick_time": "2026-04-21T00:00:11+00:00",
                            "equity": 999.0,
                            "free_margin": 888.0,
                            "trade_mode": "full",
                            "execution_mode": "market",
                            "filling_mode": "fok",
                        },
                    },
                }
            )
            return "run-123"
        if name == "stop_runtime":
            self.events.append(
                {
                    "name": "runtime_stopped",
                    "payload": {
                        "message": "runtime stopped",
                    },
                }
            )
            return {"stopped": True}
        if name == "load_telemetry":
            return {
                "overview": {
                    "run_id": "run-123",
                    "status": "running",
                    "last_action": "OPEN",
                    "spread_points": 17.0,
                    "equity": 1000.0,
                    "free_margin": 900.0,
                },
                "health": {
                    "reject_rate": 0.1,
                    "filled_events": 2,
                    "dry_run_events": 1,
                },
                "validation": {
                    "total_trades": 3,
                    "win_rate": 2 / 3,
                    "profit_factor": 1.5,
                    "expectancy_r": 0.4,
                    "warnings": ["spread drift"],
                },
                "lifecycle_rows": [
                    {"symbol": "XAUUSD", "side": "buy", "realized_pnl_cash": 12.5},
                ],
            }
        if name == "set_live_enabled":
            enabled = bool(params.get("enabled"))
            self.events.append({"name": "live_toggle", "payload": {"enabled": enabled}})
            return {"live_enabled": enabled}
        if name == "approve_pending":
            return {"symbol": "XAUUSD", "side": "buy", "volume": 0.01}
        if name == "reject_pending":
            return {"symbol": "XAUUSD", "side": "buy", "volume": 0.01}
        raise AssertionError(f"Unexpected command: {name}")

    def drain_events(self) -> list[dict]:
        events = list(self.events)
        self.events.clear()
        return events

    def close(self) -> None:
        self.stop_managed_service()
        return None

    def request_count(self, name: str) -> int:
        return sum(1 for request_name, _params in self.requests if request_name == name)


class QtAppTests(unittest.TestCase):
    def _make_adapter(self):
        from bot_ea.mt5_adapter import MockMT5Adapter

        return MockMT5Adapter(
            account_info={
                "equity": 1000.0,
                "balance": 1000.0,
                "margin_free": 900.0,
                "margin_level": 400.0,
                "trade_allowed": True,
                "trade_expert": True,
            },
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

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def test_qt_window_constructs(self) -> None:
        try:
            from PySide6.QtWidgets import QApplication
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"PySide6 unavailable: {exc}")

        from bot_ea.qt_app import BotEaQtWindow

        app = QApplication.instance() or QApplication([])
        backend = FakeBackend()
        window = BotEaQtWindow(backend=backend)
        app.processEvents()
        try:
            self.assertEqual(window.windowTitle(), "bot-ea Qt Desktop Runtime")
            self.assertEqual(window.symbol_combo.currentText(), "EURUSD")
            self.assertEqual(window.timeframe_combo.currentText(), "M15")
            self.assertEqual(window.service_status.text(), "App-managed connected 127.0.0.1:8765")
            self.assertEqual(backend.connected_urls[-1], "ws://127.0.0.1:8765")
            self.assertEqual(backend.start_managed_calls, 1)
            self.assertTrue(window.preview_poll_timer.isActive())
        finally:
            window.close()
            self.assertEqual(backend.stop_managed_calls, 1)

    def test_qt_primary_actions_use_websocket_backend(self) -> None:
        try:
            from PySide6.QtWidgets import QApplication
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"PySide6 unavailable: {exc}")

        from bot_ea.qt_app import BotEaQtWindow

        app = QApplication.instance() or QApplication([])
        backend = FakeBackend()
        window = BotEaQtWindow(backend=backend)
        app.processEvents()
        try:
            window.event_timer.stop()
            window.preview_timer.stop()
            window.symbol_combo.setCurrentText("XAUUSD")
            window.capital_input.setText("20")
            window.manual_lot_input.setText("1.00")

            window.check_mt5()
            window.load_codex()
            window.refresh_snapshot()
            window.preflight()
            window.execute_manual()
            window.play_runtime()
            window._pump_runtime_events()
            self.assertIn("tick_time=2026-04-21T00:00:11+00:00", window.market_card["text"].toPlainText())
            self.assertFalse(window.check_mt5_button.isEnabled())
            self.assertFalse(window.refresh_button.isEnabled())
            self.assertFalse(window.execute_button.isEnabled())
            self.assertFalse(window.symbol_combo.isEnabled())
            window.load_telemetry()
            window.stop_runtime()
            window._pump_runtime_events()

            commands = [name for name, _ in backend.requests]
            for required in (
                "probe_mt5",
                "probe_codex",
                "refresh_manual",
                "preflight_manual",
                "execute_manual",
                "start_runtime",
                "load_telemetry",
                "stop_runtime",
            ):
                self.assertIn(required, commands)

            self.assertIn("symbol=XAUUSD", window.market_card["text"].toPlainText())
            self.assertIn("tick_time=2026-04-21T00:00:11+00:00", window.market_card["text"].toPlainText())
            self.assertIn("manual_order_snapshot:", window.manual_card["text"].toPlainText())
            self.assertIn("sizing_snapshot:", window.risk_card["text"].toPlainText())
            self.assertEqual(window.run_id_status.text(), "run-123")
            self.assertIn("run_id=run-123", window.runtime_text.toPlainText())
            self.assertIn("total_trades=3", window.validation_text.toPlainText())
        finally:
            window.close()

    def test_qt_realtime_field_changes_trigger_debounced_preview(self) -> None:
        try:
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"PySide6 unavailable: {exc}")

        from bot_ea.qt_app import BotEaQtWindow

        app = QApplication.instance() or QApplication([])
        backend = FakeBackend()
        window = BotEaQtWindow(backend=backend)
        app.processEvents()
        try:
            self.assertEqual(backend.request_count("refresh_manual"), 0)

            window.symbol_combo.setCurrentText("XAUUSD")
            window.capital_input.setText("20")
            window.stop_input.setText("50")
            window.side_combo.setCurrentText("sell")
            window.lot_mode_combo.setCurrentText("manual")
            window.manual_lot_input.setText("1.00")

            self.assertEqual(backend.request_count("refresh_manual"), 0)
            QTest.qWait(window._preview_debounce_ms + 100)
            app.processEvents()

            self.assertEqual(backend.request_count("refresh_manual"), 1)
            refresh_name, refresh_params = next(
                (name, params) for name, params in backend.requests if name == "refresh_manual"
            )
            self.assertEqual(refresh_name, "refresh_manual")
            self.assertEqual(refresh_params["symbol"], "XAUUSD")
            self.assertEqual(refresh_params["side"], "sell")
            self.assertEqual(refresh_params["lot_mode"], "manual")
            self.assertEqual(refresh_params["manual_lot"], 1.0)
            self.assertEqual(refresh_params["capital_value"], 20.0)
            self.assertEqual(refresh_params["stop_distance_points"], 50.0)
            self.assertIn("symbol=XAUUSD", window.market_card["text"].toPlainText())
            self.assertIn("tick_time=2026-04-21T00:00:01+00:00", window.market_card["text"].toPlainText())
            self.assertIn("final_lot=0.0100", window.manual_card["text"].toPlainText())
            self.assertTrue(window.execute_button.isEnabled())
        finally:
            window.close()

    def test_qt_backend_can_run_app_managed_service_without_external_shell(self) -> None:
        from bot_ea.qt_app import QtBotEaWebSocketBackend

        backend = QtBotEaWebSocketBackend(
            host="127.0.0.1",
            port=self._free_port(),
            adapter=self._make_adapter(),
        )
        try:
            self.assertFalse(backend.is_managed_service_running())
            backend.start_managed_service()
            self.assertTrue(backend.is_managed_service_running())
            info = backend.connect(backend.managed_service_url())
            self.assertEqual(info["host"], "127.0.0.1")
            result = backend.request(
                "refresh_manual",
                {
                    "symbol": "XAUUSD",
                    "timeframe": "M15",
                    "trading_style": "intraday",
                    "stop_distance_points": 10,
                    "capital_mode": "fixed_cash",
                    "capital_value": 100,
                    "lot_mode": "manual",
                    "manual_lot": 0.01,
                    "side": "buy",
                    "db_path": str(Path.cwd() / "bot_ea_runtime.db"),
                },
                timeout=10.0,
            )
            self.assertEqual(result["snapshot"]["symbol"], "XAUUSD")
            self.assertIn("manual_order_snapshot", result)
        finally:
            backend.close()
            self.assertFalse(backend.is_managed_service_running())


if __name__ == "__main__":
    unittest.main()
