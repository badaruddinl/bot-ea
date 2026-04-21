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
        self.fail_service = False
        self.fail_mt5 = False
        self.fail_codex = False
        self.fail_ai_workspace = False
        self.fail_ai_documents = False
        self.fail_ai_context = False
        self.account_fingerprint = {
            "login": "123456",
            "server": "Broker-Demo",
            "broker": "Broker A",
            "is_live": False,
        }
        self.contexts = [
            {
                "context_key": "broker_a_broker_demo_123456",
                "context_path": "D:\\luthfi\\project\\bot-ea\\ai_context\\broker_a_broker_demo_123456",
                "is_mapped": True,
                "is_active": True,
                "last_runtime_state": "stopped",
                "last_shutdown_reason": "operator_stop",
            },
            {
                "context_key": "broker_a_broker_demo_123456_2",
                "context_path": "D:\\luthfi\\project\\bot-ea\\ai_context\\broker_a_broker_demo_123456_2",
                "is_mapped": False,
                "is_active": False,
                "last_runtime_state": "halted",
                "last_shutdown_reason": "account_changed",
            },
        ]
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
        if self.fail_service:
            raise RuntimeError("service unavailable")
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
        if name == "probe_service_ready":
            return {"host": "127.0.0.1", "port": 8765, "detail": "Service lokal siap digunakan."}
        if name == "probe_mt5_process":
            if self.fail_mt5:
                raise RuntimeError("MT5 belum terbuka")
            return {"running": True, "detail": "MetaTrader 5 terdeteksi dan bisa diakses."}
        if name == "probe_mt5_session":
            if self.fail_mt5:
                raise RuntimeError("MT5 session unavailable")
            return {"connected": True, "detail": "Sesi MT5 aktif dan data terminal bisa dibaca."}
        if name == "probe_account_fingerprint":
            if self.fail_mt5:
                raise RuntimeError("MT5 account unavailable")
            return {
                **self.account_fingerprint,
                "detail": "Akun aktif 123456 pada server Broker-Demo (Broker A).",
            }
        if name == "probe_symbol_baseline":
            if self.fail_mt5:
                raise RuntimeError("mt5 unavailable")
            return {
                "detail": "Simbol dasar EURUSD siap dibaca.",
                "snapshot": {
                    "symbol": "EURUSD",
                    "bid": 1.08,
                    "ask": 1.09,
                    "spread_points": 10.0,
                    "equity": 1000.0,
                    "free_margin": 900.0,
                    "symbol_trade_allowed": True,
                    "stops_level_points": 10.0,
                    "freeze_level_points": 0.0,
                    "trade_mode": "full",
                    "execution_mode": "market",
                    "filling_mode": "fok",
                    "account_fingerprint": dict(self.account_fingerprint),
                },
                "symbols": ["EURUSD", "XAUUSD"],
            }
        if name == "probe_mt5":
            if self.fail_mt5:
                raise RuntimeError("mt5 unavailable")
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
        if name == "probe_ai_runtime":
            if self.fail_codex:
                raise RuntimeError("codex unavailable")
            return {
                "version": "codex 1.0.0",
                "detail": "AI runtime siap: codex 1.0.0",
                "command": "codex",
                "resolved_path": "C:/mock/codex.exe",
            }
        if name == "probe_codex":
            if self.fail_codex:
                raise RuntimeError("codex unavailable")
            return "codex 1.0.0"
        if name == "probe_ai_workspace":
            if self.fail_ai_workspace:
                raise RuntimeError("Workspace AI belum siap")
            return {"detail": f"Workspace AI siap: {params.get('ai_workspace_path')}"}
        if name == "probe_ai_documents":
            if self.fail_ai_documents:
                raise RuntimeError("Dokumen AI belum siap")
            return {"detail": f"Dokumen AI siap: {params.get('ai_documents_path')}"}
        if name == "probe_ai_context_store":
            if self.fail_ai_context:
                raise RuntimeError("Folder context AI belum siap")
            return {"detail": f"Folder context AI siap: {params.get('ai_context_root')}"}
        if name == "validate_storage":
            return {"detail": f"Storage siap: {params.get('db_path')}"}
        if name == "build_resume_state":
            return {
                "detail": f"Context akun siap: {params.get('ai_context_root')}\\broker_demo_123456",
                "binding": {
                    "context_key": "broker_demo_123456_new",
                    "context_path": f"{params.get('ai_context_root')}\\broker_demo_123456",
                    "resume_prompt_path": f"{params.get('ai_context_root')}\\broker_demo_123456\\resume\\resume_prompt.md",
                    "profile_path": f"{params.get('ai_context_root')}\\broker_demo_123456\\profile.yaml",
                },
            }
        if name == "list_account_contexts":
            return {
                "fingerprint": dict(params.get("fingerprint") or self.account_fingerprint),
                "contexts": list(self.contexts),
            }
        if name == "select_account_context":
            context_key = str(params.get("context_key") or "")
            selected = next((ctx for ctx in self.contexts if ctx["context_key"] == context_key), None)
            if selected is None:
                raise RuntimeError("Context akun tidak ditemukan")
            return {
                "detail": f"Context akun dipilih: {context_key}",
                "binding": {
                    "context_key": context_key,
                    "context_path": selected["context_path"],
                    "resume_prompt_path": f"{selected['context_path']}\\resume\\resume_prompt.md",
                    "profile_path": f"{selected['context_path']}\\profile.yaml",
                },
            }
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
                    "account_fingerprint": dict(self.account_fingerprint),
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
                    "account_fingerprint": dict(self.account_fingerprint),
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
                    "account_fingerprint": dict(self.account_fingerprint),
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
                            "account_fingerprint": dict(self.account_fingerprint),
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
                "login": 123456,
                "server": "Broker-Demo",
                "company": "Broker A",
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
            self.assertIs(window.shell_stack.currentWidget(), window.startup_gate_page)
            self.assertFalse(window.nav_buttons[0].isEnabled())
            self.assertIn("Belum", window.gate_message.text())
            self.assertIn(window.symbol_combo.currentText(), {"EURUSD", "XAUUSD"})
            self.assertEqual(window.timeframe_combo.currentText(), "M15")
            self.assertEqual(window.service_status.text(), "Service disconnected")
            self.assertEqual(window.hero_title.text(), "Dasbor Bot")
            self.assertEqual(window.nav_group.title(), "Navigation")
            self.assertEqual(window.page_stack.count(), 5)
            self.assertIs(window.page_stack.widget(0), window.dashboard_page)
            self.assertIs(window.page_stack.widget(1), window.strategy_page)
            self.assertIs(window.page_stack.widget(2), window.history_page)
            self.assertIs(window.page_stack.widget(3), window.logs_page)
            self.assertIs(window.page_stack.widget(4), window.settings_page)
            self.assertIs(window.trade_control_scroll.widget(), window.trade_control_panel)
            self.assertTrue(hasattr(window, "dashboard_overview_frame"))
            self.assertTrue(hasattr(window, "dashboard_story_card"))
            self.assertTrue(hasattr(window, "history_summary_text"))
            self.assertTrue(hasattr(window, "history_operator_note"))
            self.assertTrue(hasattr(window, "logs_focus_panel"))
            self.assertTrue(hasattr(window, "settings_summary_text"))
            self.assertTrue(hasattr(window, "settings_operator_note"))
            self.assertTrue(hasattr(window, "reconnect_overlay"))
            self.assertTrue(hasattr(window, "account_review_card"))
            self.assertIs(window.strategy_page.layout().itemAt(4).widget(), window.trade_control_scroll)
            self.assertIs(window.dashboard_page.layout().itemAt(4).widget(), window.snapshot_dashboard)
            self.assertEqual(window.sidebar_mode_value.text(), "Dasbor")
            self.assertEqual(window.logs_page.layout().itemAt(1).widget(), window.logs_operator_note)
            self.assertIs(window.logs_page.layout().itemAt(2).widget(), window.logs_focus_panel)
            self.assertIs(window.logs_page.layout().itemAt(3).widget(), window.logs_group)
            self.assertEqual(window.dashboard_mode_value.text(), "IDLE")
            self.assertEqual(window.market_card["title"].text(), "Ringkasan Pasar")
            self.assertEqual(window.manual_card["title"].text(), "Ringkasan Order")
            self.assertEqual(window.risk_card["title"].text(), "Batas Risiko")
            self.assertEqual(window.tabs.tabText(0), "Feed Runtime")
            self.assertEqual(window.tabs.tabText(1), "Konsol Log")
            self.assertIn("#0b0f10", window.styleSheet())
            self.assertEqual(window.readiness_chips["service"]["value"].property("tone"), "warn")
            self.assertEqual(backend.start_managed_calls, 0)
            self.assertTrue(window.preview_poll_timer.isActive())
        finally:
            window.close()
            self.assertEqual(backend.stop_managed_calls, 1)

    def test_startup_gate_unlocks_workspace_after_successful_probes(self) -> None:
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
            QTest.qWait(150)
            app.processEvents()
            self.assertIs(window.shell_stack.currentWidget(), window.workspace_page)
            self.assertTrue(window.nav_buttons[0].isEnabled())
            commands = [name for name, _ in backend.requests]
            for required in (
                "probe_mt5_process",
                "probe_mt5_session",
                "probe_account_fingerprint",
                "probe_symbol_baseline",
                "probe_ai_runtime",
                "probe_ai_workspace",
                "probe_ai_documents",
                "probe_ai_context_store",
                "validate_storage",
                "build_resume_state",
            ):
                self.assertIn(required, commands)
            window.nav_buttons[1].click()
            app.processEvents()
            self.assertEqual(window.page_stack.currentWidget(), window.strategy_page)
            window.nav_buttons[4].click()
            app.processEvents()
            self.assertEqual(window.page_stack.currentWidget(), window.settings_page)
            self.assertIn("service_url=ws://127.0.0.1:8765", window.settings_summary_text.toPlainText())
        finally:
            window.close()

    def test_startup_gate_stays_locked_when_mt5_probe_fails(self) -> None:
        try:
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"PySide6 unavailable: {exc}")

        from bot_ea.qt_app import BotEaQtWindow

        app = QApplication.instance() or QApplication([])
        backend = FakeBackend()
        backend.fail_mt5 = True
        window = BotEaQtWindow(backend=backend)
        app.processEvents()
        try:
            QTest.qWait(150)
            app.processEvents()
            self.assertIs(window.shell_stack.currentWidget(), window.startup_gate_page)
            self.assertIn("mt5", window.gate_message.text().lower())
            self.assertFalse(window.nav_buttons[0].isEnabled())
        finally:
            window.close()

    def test_startup_gate_stays_locked_when_service_fails(self) -> None:
        try:
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"PySide6 unavailable: {exc}")

        from bot_ea.qt_app import BotEaQtWindow

        app = QApplication.instance() or QApplication([])
        backend = FakeBackend()
        backend.fail_service = True
        window = BotEaQtWindow(backend=backend)
        app.processEvents()
        try:
            QTest.qWait(150)
            app.processEvents()
            self.assertIs(window.shell_stack.currentWidget(), window.startup_gate_page)
            self.assertIn("service", window.gate_message.text().lower())
            self.assertFalse(window.nav_buttons[0].isEnabled())
        finally:
            window.close()

    def test_startup_gate_stays_locked_when_codex_probe_fails(self) -> None:
        try:
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"PySide6 unavailable: {exc}")

        from bot_ea.qt_app import BotEaQtWindow

        app = QApplication.instance() or QApplication([])
        backend = FakeBackend()
        backend.fail_codex = True
        window = BotEaQtWindow(backend=backend)
        app.processEvents()
        try:
            QTest.qWait(150)
            app.processEvents()
            self.assertIs(window.shell_stack.currentWidget(), window.startup_gate_page)
            self.assertTrue("codex" in window.gate_message.text().lower() or "ai runtime" in window.gate_message.text().lower())
            self.assertFalse(window.nav_buttons[0].isEnabled())
        finally:
            window.close()

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
                "probe_mt5_process",
                "probe_account_fingerprint",
                "probe_symbol_baseline",
                "probe_ai_runtime",
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
            self.assertEqual(window.run_id_status.property("tone"), "idle")
            self.assertEqual(window.readiness_chips["runtime"]["value"].property("tone"), "idle")
            self.assertEqual(window.dashboard_mode_value.text(), "IDLE")
            self.assertEqual(window.strategy_live_value.text(), "Disabled")
            self.assertIn("active_account=Broker A / Broker-Demo / 123456 (demo)", window.settings_summary_text.toPlainText())
            self.assertIn("run_id=run-123", window.runtime_text.toPlainText())
            self.assertIn("total_trades=3", window.validation_text.toPlainText())
            self.assertIn("run_id=run-123", window.history_summary_text.toPlainText())
            self.assertEqual(window.history_trade_count_value.text(), "3")
            self.assertIn("Latest tick: 2026-04-21T00:00:11+00:00", window.logs_focus_secondary.text())
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
            self.assertEqual(window.readiness_chips["service"]["value"].property("tone"), "ok")
            self.assertEqual(window.strategy_side_value.text(), "sell")
            self.assertEqual(window.dashboard_symbol_value.text(), "XAUUSD")
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

    def test_dev_mode_bypasses_operator_dependencies(self) -> None:
        try:
            from PySide6.QtWidgets import QApplication
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"PySide6 unavailable: {exc}")

        from bot_ea.qt_app import BotEaQtWindow

        app = QApplication.instance() or QApplication([])
        backend = FakeBackend()
        backend.fail_mt5 = True
        backend.fail_codex = True
        window = BotEaQtWindow(backend=backend)
        app.processEvents()
        try:
            window._enter_dev_mode()
            app.processEvents()
            self.assertIs(window.shell_stack.currentWidget(), window.workspace_page)
            self.assertEqual(window.mode_badge.text(), "DEV / MOCK MODE")
            self.assertTrue(window.nav_buttons[0].isEnabled())
        finally:
            window.close()

    def test_mt5_disconnect_shows_reconnect_overlay_and_safe_halt(self) -> None:
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
            window._runtime_running = True
            window._live_enabled = True
            window._pending_approval = {"symbol": "XAUUSD"}
            window._handle_mt5_disconnect("MT5 lost IPC connection", runtime_was_running=True)
            app.processEvents()
            self.assertTrue(window._mt5_overlay_active)
            self.assertFalse(window.reconnect_overlay.isHidden())
            self.assertFalse(window._runtime_running)
            self.assertFalse(window._live_enabled)
            self.assertFalse(window.play_button.isEnabled())
            self.assertIn("Safe halt", window.runtime_status.text())
        finally:
            window.close()

    def test_account_change_opens_review_flow(self) -> None:
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
            old_fp = dict(backend.account_fingerprint)
            new_fp = {**old_fp, "login": "789012"}
            window._active_account_fingerprint = old_fp
            window._handle_account_changed(old_fp, new_fp, runtime_was_running=False)
            app.processEvents()
            self.assertTrue(window._account_review_active)
            self.assertFalse(window.account_review_card.isHidden())
            self.assertFalse(window.play_button.isEnabled())
            self.assertIn("789012", window.account_review_new.text())
            self.assertIn("Context terpilih:", window.account_review_context.text())
            first_label = window.account_review_context.text()
            window.account_review_select_button.click()
            app.processEvents()
            self.assertNotEqual(first_label, window.account_review_context.text())
            backend.account_fingerprint = dict(new_fp)
            window._pending_account_fingerprint = new_fp
            window._use_pending_account_context()
            app.processEvents()
            self.assertTrue(window.account_review_card.isHidden())
            self.assertFalse(window._account_review_active)
            self.assertEqual(window._active_account_fingerprint["login"], "789012")
            commands = [name for name, _ in backend.requests]
            self.assertIn("list_account_contexts", commands)
            self.assertIn("select_account_context", commands)
            self.assertGreaterEqual(commands.count("probe_mt5_process"), 2)
            self.assertGreaterEqual(commands.count("probe_ai_runtime"), 2)
        finally:
            window.close()

    def test_account_change_while_runtime_active_restarts_gate_after_new_context(self) -> None:
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
            old_fp = dict(backend.account_fingerprint)
            new_fp = {**old_fp, "login": "789012"}
            window._active_account_fingerprint = old_fp
            window._runtime_running = True
            window._live_enabled = True
            window._handle_account_changed(old_fp, new_fp, runtime_was_running=True)
            app.processEvents()
            self.assertIn("Hard safe halt", window.runtime_status.text())
            backend.account_fingerprint = dict(new_fp)
            window._pending_account_fingerprint = new_fp
            window._create_pending_account_context()
            app.processEvents()
            self.assertTrue(window.account_review_card.isHidden())
            self.assertFalse(window._account_review_active)
            self.assertFalse(window._runtime_running)
            self.assertFalse(window._live_enabled)
            commands = [name for name, _ in backend.requests]
            self.assertIn("build_resume_state", commands)
            self.assertGreaterEqual(commands.count("probe_mt5_process"), 2)
            self.assertGreaterEqual(commands.count("probe_ai_runtime"), 2)
        finally:
            window.close()

    def test_qt_accessibility_defaults_expose_names_and_tab_flow(self) -> None:
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"PySide6 unavailable: {exc}")

        from bot_ea.qt_app import BotEaQtWindow

        app = QApplication.instance() or QApplication([])
        backend = FakeBackend()
        window = BotEaQtWindow(backend=backend)
        window.show()
        app.processEvents()
        try:
            QTest.qWait(150)
            app.processEvents()
            self.assertEqual(window.gate_primary_button.accessibleName(), "Mulai pemeriksaan dependency")
            self.assertEqual(window.gate_retry_button.accessibleName(), "Coba lagi pemeriksaan dependency")
            self.assertEqual(window.gate_dev_button.accessibleName(), "Masuk mode dev")
            self.assertEqual(window.codex_command_input.accessibleName(), "Command AI runtime")
            self.assertEqual(window.codex_cwd_input.accessibleName(), "Workspace AI")
            self.assertEqual(window.ai_documents_input.accessibleName(), "Dokumen AI")
            self.assertEqual(window.ai_context_input.accessibleName(), "Folder context AI")
            self.assertEqual(window.timeout_input.accessibleName(), "Timeout AI runtime")
            self.assertEqual(window.check_mt5_button.accessibleName(), "Cek MT5")
            self.assertEqual(window.load_codex_button.accessibleName(), "Cek AI runtime")
            self.assertEqual(window.refresh_button.accessibleName(), "Refresh data")

            window.check_mt5_button.setFocus()
            app.processEvents()
            self.assertIs(app.focusWidget(), window.check_mt5_button)
            QTest.keyClick(window, Qt.Key_Tab)
            app.processEvents()
            self.assertIs(app.focusWidget(), window.load_codex_button)
            QTest.keyClick(window, Qt.Key_Tab)
            app.processEvents()
            self.assertIs(app.focusWidget(), window.refresh_button)
        finally:
            window.close()

    def test_qt_workspace_layout_handles_wider_resize_without_collapsing_panels(self) -> None:
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QSplitter
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"PySide6 unavailable: {exc}")

        from bot_ea.qt_app import BotEaQtWindow

        app = QApplication.instance() or QApplication([])
        backend = FakeBackend()
        window = BotEaQtWindow(backend=backend)
        window.show()
        app.processEvents()
        try:
            QTest.qWait(150)
            app.processEvents()
            self.assertIs(window.shell_stack.currentWidget(), window.workspace_page)
            splitter = next(
                widget
                for widget in window.workspace_page.findChildren(QSplitter)
                if widget.orientation() == Qt.Horizontal and widget.count() == 2
            )
            left_width_before, right_width_before = splitter.sizes()
            self.assertGreaterEqual(left_width_before, 280)
            self.assertLessEqual(left_width_before, 320)
            self.assertGreater(right_width_before, left_width_before)
            self.assertEqual(window.page_stack.count(), 5)
            self.assertFalse(window.reconnect_overlay.isVisible())
            self.assertFalse(window.account_review_card.isVisible())

            window.resize(2200, 1700)
            app.processEvents()
            left_width_after, right_width_after = splitter.sizes()
            self.assertGreater(window.width(), 2000)
            self.assertGreater(window.height(), 1600)
            self.assertGreaterEqual(left_width_after, 280)
            self.assertLessEqual(left_width_after, 320)
            self.assertGreater(right_width_after, right_width_before)
            self.assertGreater(window.page_stack.width(), right_width_before)

            window.nav_buttons[2].click()
            app.processEvents()
            self.assertIs(window.page_stack.currentWidget(), window.history_page)
            history_sizes = window.history_splitter.sizes()
            self.assertEqual(len(history_sizes), 2)
            self.assertGreater(history_sizes[0], 0)
            self.assertGreater(history_sizes[1], 0)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
