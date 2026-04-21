from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.models import AccountSnapshot, SymbolSnapshot  # noqa: E402
from bot_ea.mt5_adapter import PriceTickSnapshot, TerminalStatusSnapshot  # noqa: E402
from bot_ea.operator_state import AccountFingerprint  # noqa: E402
from bot_ea.websocket_service import BotEaWebSocketService  # noqa: E402


class FakeAdapter:
    def __init__(self, ticks: list[tuple[float, float]] | None = None) -> None:
        self._ticks = list(ticks or [(4800.0, 4800.2)])
        self._tick_index = 0
        self.validated_requests: list[dict] = []
        self.sent_requests: list[dict] = []

    def load_account_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(
            equity=1000.0,
            balance=1000.0,
            free_margin=900.0,
            margin_level=400.0,
            trade_allowed=True,
            trade_expert=True,
        )

    def load_symbol_snapshot(self, symbol: str) -> SymbolSnapshot:
        return SymbolSnapshot(
            name=symbol,
            instrument_class="metal",
            risk_weight=1.0,
            point=0.01,
            tick_size=0.01,
            tick_value=0.1,
            volume_min=0.01,
            volume_max=50.0,
            volume_step=0.01,
            spread_points=17.0,
            stops_level_points=10.0,
            freeze_level_points=0.0,
            trade_allowed=True,
            trade_mode="full",
            order_mode="market",
            execution_mode="market",
            filling_mode="fok",
            bid=4700.0,
            ask=4700.2,
            price=4700.2,
        )

    def load_price_tick(self, symbol: str) -> PriceTickSnapshot:
        index = min(self._tick_index, len(self._ticks) - 1)
        bid, ask = self._ticks[index]
        self._tick_index += 1
        return PriceTickSnapshot(symbol=symbol, bid=bid, ask=ask, time=f"2026-04-21T00:00:0{self._tick_index}+00:00")

    def load_terminal_status(self) -> TerminalStatusSnapshot:
        return TerminalStatusSnapshot(
            connected=True,
            trade_allowed=True,
            tradeapi_disabled=False,
            path="C:\\Program Files\\MetaTrader 5",
            server="Demo-Server",
            company="Demo Broker",
            account_trade_allowed=True,
            account_trade_expert=True,
        )

    def load_available_symbols(self) -> list[str]:
        return ["EURUSD", "XAUUSD"]

    def estimate_margin(self, symbol: str, volume: float, order_type: str, price: float):
        _ = symbol, order_type
        required = volume * price * 0.02
        return type("Margin", (), {"required_margin": required, "success": True, "detail": "ok"})()

    def validate_order(self, request: dict):
        self.validated_requests.append(dict(request))
        return type(
            "Validation",
            (),
            {
                "accepted": True,
                "detail": "ok",
                "projected_margin_free": 850.0,
                "projected_margin_level": 350.0,
                "retcode": 0,
            },
        )()

    def send_order(self, request: dict):
        self.sent_requests.append(dict(request))
        return type(
            "Send",
            (),
            {
                "accepted": True,
                "detail": "filled",
                "retcode": 0,
                "order": 123,
                "deal": 456,
                "volume": request.get("volume"),
                "price": request.get("price"),
                "bid": 4800.0,
                "ask": 4800.2,
                "request_id": 1,
                "retcode_external": 0,
            },
        )()

    def shutdown(self) -> None:
        return None


class WebSocketServiceTests(unittest.TestCase):
    def _fingerprint(self, **overrides) -> dict[str, object]:
        payload: dict[str, object] = {
            "login": "123456",
            "server": "Demo-Server",
            "broker": "Demo Broker",
            "is_live": False,
        }
        payload.update(overrides)
        return payload

    def _manual_params(self, tmpdir: str, **overrides) -> dict[str, object]:
        params: dict[str, object] = {
            "symbol": "XAUUSD",
            "timeframe": "M15",
            "trading_style": "intraday",
            "stop_distance_points": 10,
            "capital_mode": "fixed_cash",
            "capital_value": 100,
            "lot_mode": "manual",
            "manual_lot": 1.0,
            "side": "buy",
            "db_path": str(Path(tmpdir) / "runtime.db"),
        }
        params.update(overrides)
        return params

    def _context_params(self, tmpdir: str, **overrides) -> dict[str, object]:
        params = {
            **self._manual_params(tmpdir),
            "ai_context_root": str(Path(tmpdir) / "ai_context"),
            "fingerprint": self._fingerprint(),
        }
        params.update(overrides)
        return params

    def test_refresh_manual_command_returns_latest_tick_snapshot(self) -> None:
        async def run_test() -> None:
            adapter = FakeAdapter(ticks=[(4800.0, 4800.2), (4801.0, 4801.3)])
            service = BotEaWebSocketService(adapter_factory=lambda: adapter)
            with tempfile.TemporaryDirectory() as tmpdir:
                response = await service._handle_command(
                    {
                        "id": "1",
                        "name": "refresh_manual",
                        "params": self._manual_params(tmpdir),
                    }
                )
                self.assertTrue(response["ok"])
                result = response["result"]
                self.assertIn("snapshot", result)
                self.assertIn("manual_order_snapshot", result)
                self.assertEqual(result["snapshot"]["symbol"], "XAUUSD")
                self.assertEqual(result["snapshot"]["bid"], 4801.0)
                self.assertEqual(result["snapshot"]["ask"], 4801.3)
                self.assertEqual(result["snapshot"]["tick_time"], "2026-04-21T00:00:02+00:00")
                self.assertEqual(result["manual_order_snapshot"]["order_price"], 4801.3)

        asyncio.run(run_test())

    def test_preflight_manual_uses_latest_tick_for_request_price(self) -> None:
        async def run_test() -> None:
            adapter = FakeAdapter(ticks=[(4800.0, 4800.2), (4802.0, 4802.4)])
            service = BotEaWebSocketService(adapter_factory=lambda: adapter)
            with tempfile.TemporaryDirectory() as tmpdir:
                response = await service._handle_command(
                    {
                        "id": "2",
                        "name": "preflight_manual",
                        "params": self._manual_params(tmpdir),
                    }
                )
                self.assertTrue(response["ok"])
                result = response["result"]
                self.assertEqual(result["status"], "PRECHECK_OK")
                self.assertEqual(result["snapshot"]["tick_time"], "2026-04-21T00:00:02+00:00")
                self.assertEqual(result["request"]["price"], 4802.4)
                self.assertEqual(result["manual_order_snapshot"]["order_price"], 4802.4)
                self.assertEqual(adapter.validated_requests[0]["price"], 4802.4)

        asyncio.run(run_test())

    def test_execute_manual_uses_latest_tick_for_live_send_price(self) -> None:
        async def run_test() -> None:
            adapter = FakeAdapter(ticks=[(4800.0, 4800.2), (4803.0, 4803.5)])
            service = BotEaWebSocketService(adapter_factory=lambda: adapter)
            with tempfile.TemporaryDirectory() as tmpdir:
                response = await service._handle_command(
                    {
                        "id": "3",
                        "name": "execute_manual",
                        "params": self._manual_params(tmpdir, live_enabled=True),
                    }
                )
                self.assertTrue(response["ok"])
                result = response["result"]
                self.assertEqual(result["status"], "FILLED")
                self.assertEqual(result["snapshot"]["tick_time"], "2026-04-21T00:00:02+00:00")
                self.assertEqual(result["request"]["price"], 4803.5)
                self.assertEqual(result["manual_order_snapshot"]["order_price"], 4803.5)
                self.assertEqual(adapter.validated_requests[0]["price"], 4803.5)
                self.assertEqual(adapter.sent_requests[0]["price"], 4803.5)

        asyncio.run(run_test())

    def test_start_runtime_command_builds_runtime_config(self) -> None:
        class FakeCoordinator:
            def __init__(self) -> None:
                self.started_config = None
                self.is_running = False

            def start(self, config):
                self.started_config = config
                return "run-123"

            def drain_events(self):
                return []

        async def run_test() -> None:
            coordinator = FakeCoordinator()
            service = BotEaWebSocketService(adapter_factory=FakeAdapter, runtime_coordinator=coordinator)
            with tempfile.TemporaryDirectory() as tmpdir:
                params = self._context_params(tmpdir)
                built = await service._handle_command({"id": "4a", "name": "build_resume_state", "params": params})
                binding = built["result"]["binding"]
                response = await service._handle_command(
                    {
                        "id": "4",
                        "name": "start_runtime",
                        "params": {
                            **self._manual_params(tmpdir),
                            "codex_command": "codex",
                            "model": "gpt-5.4-mini",
                            "codex_cwd": str(Path(tmpdir)),
                            "codex_timeout_seconds": 60,
                            "poll_interval_seconds": 30,
                            "ai_workspace_path": str(Path(tmpdir) / "ai_workspace"),
                            "ai_documents_path": str(Path(tmpdir) / "ai_documents"),
                            "ai_context_path": binding["context_path"],
                            "resume_prompt_path": binding["resume_prompt_path"],
                            "behavior_profile_path": binding["profile_path"],
                            "account_fingerprint": self._fingerprint(),
                            "session_state": "asia_session",
                            "news_state": "quiet",
                        },
                    }
                )
                self.assertTrue(response["ok"])
                self.assertEqual(response["result"], "run-123")
                self.assertIsNotNone(coordinator.started_config)
                self.assertEqual(coordinator.started_config.symbol, "XAUUSD")
                self.assertEqual(coordinator.started_config.codex_executable, "codex")
                self.assertEqual(coordinator.started_config.codex_model, "gpt-5.4-mini")
                self.assertEqual(coordinator.started_config.codex_cwd, str(Path(tmpdir)))
                self.assertEqual(coordinator.started_config.ai_workspace_path, str(Path(tmpdir) / "ai_workspace"))
                self.assertEqual(coordinator.started_config.ai_documents_path, str(Path(tmpdir) / "ai_documents"))
                self.assertEqual(coordinator.started_config.ai_context_path, binding["context_path"])
                self.assertEqual(coordinator.started_config.resume_prompt_path, binding["resume_prompt_path"])
                self.assertEqual(coordinator.started_config.behavior_profile_path, binding["profile_path"])
                self.assertEqual(coordinator.started_config.account_fingerprint, self._fingerprint())
                self.assertEqual(coordinator.started_config.session_state, "asia_session")
                self.assertEqual(coordinator.started_config.news_state, "quiet")

        asyncio.run(run_test())

    def test_start_runtime_command_forwards_account_scoped_continuity_inputs(self) -> None:
        class FakeCoordinator:
            def __init__(self) -> None:
                self.started_config = None
                self.is_running = False

            def start(self, config):
                self.started_config = config
                return "run-context"

            def drain_events(self):
                return []

        async def run_test() -> None:
            coordinator = FakeCoordinator()
            with tempfile.TemporaryDirectory() as tmpdir:
                service = BotEaWebSocketService(
                    adapter_factory=FakeAdapter,
                    runtime_coordinator=coordinator,
                    project_root=tmpdir,
                )
                params = self._context_params(tmpdir)
                built = await service._handle_command({"id": "ctx-1", "name": "build_resume_state", "params": params})
                binding = built["result"]["binding"]
                workspace = str((Path(tmpdir) / "workspace").resolve())
                documents = str((Path(tmpdir) / "documents").resolve())

                response = await service._handle_command(
                    {
                        "id": "ctx-2",
                        "name": "start_runtime",
                        "params": {
                            **self._manual_params(tmpdir),
                            "codex_command": "codex",
                            "model": "gpt-5.4-mini",
                            "codex_cwd": workspace,
                            "codex_timeout_seconds": 75,
                            "poll_interval_seconds": 45,
                            "session_state": "resume_ready",
                            "news_state": "calm",
                            "ai_workspace_path": workspace,
                            "ai_documents_path": documents,
                            "ai_context_path": binding["context_path"],
                            "resume_prompt_path": binding["resume_prompt_path"],
                            "behavior_profile_path": binding["profile_path"],
                            "account_fingerprint": dict(params["fingerprint"]),
                        },
                    }
                )

                self.assertTrue(response["ok"])
                self.assertEqual(response["result"], "run-context")
                self.assertIsNotNone(coordinator.started_config)
                self.assertEqual(coordinator.started_config.ai_workspace_path, workspace)
                self.assertEqual(coordinator.started_config.ai_documents_path, documents)
                self.assertEqual(coordinator.started_config.ai_context_path, binding["context_path"])
                self.assertEqual(coordinator.started_config.resume_prompt_path, binding["resume_prompt_path"])
                self.assertEqual(coordinator.started_config.behavior_profile_path, binding["profile_path"])
                self.assertEqual(coordinator.started_config.account_fingerprint, params["fingerprint"])
                self.assertEqual(coordinator.started_config.codex_cwd, workspace)
                self.assertEqual(coordinator.started_config.codex_timeout_seconds, 75)
                self.assertEqual(coordinator.started_config.poll_interval_seconds, 45)
                self.assertEqual(coordinator.started_config.session_state, "resume_ready")
                self.assertEqual(coordinator.started_config.news_state, "calm")

        asyncio.run(run_test())

    def test_manual_mt5_commands_rejected_while_runtime_running(self) -> None:
        class FakeCoordinator:
            is_running = True

            def drain_events(self):
                return []

        async def run_test() -> None:
            service = BotEaWebSocketService(adapter_factory=FakeAdapter, runtime_coordinator=FakeCoordinator())
            with tempfile.TemporaryDirectory() as tmpdir:
                with self.assertRaises(RuntimeError) as ctx:
                    await service._handle_command(
                        {
                            "id": "5",
                            "name": "refresh_manual",
                            "params": self._manual_params(tmpdir),
                        }
                    )
                self.assertIn("disabled while runtime is running", str(ctx.exception))

        asyncio.run(run_test())

    def test_load_runtime_state_command_returns_empty_before_context_is_built(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                service = BotEaWebSocketService(adapter_factory=FakeAdapter, project_root=tmpdir)
                response = await service._handle_command({"id": "6", "name": "load_runtime_state", "params": {}})
                self.assertTrue(response["ok"])
                self.assertEqual(
                    response["result"],
                    {"exists": False, "runtime_state": None, "binding": None},
                )

        asyncio.run(run_test())

    def test_load_runtime_state_command_returns_binding_for_active_context(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                service = BotEaWebSocketService(adapter_factory=FakeAdapter, project_root=tmpdir)
                params = self._context_params(tmpdir)
                built = await service._handle_command({"id": "6b", "name": "build_resume_state", "params": params})
                binding = built["result"]["binding"]

                response = await service._handle_command({"id": "6c", "name": "load_runtime_state", "params": params})
                self.assertTrue(response["ok"])
                result = response["result"]
                self.assertTrue(result["exists"])
                self.assertEqual(result["runtime_state"]["context_key"], binding["context_key"])
                self.assertEqual(result["runtime_state"]["context_path"], binding["context_path"])
                self.assertEqual(result["runtime_state"]["active_account_fingerprint"], params["fingerprint"])
                self.assertEqual(result["binding"]["mapping_source"], "runtime_state")
                self.assertEqual(result["binding"]["fingerprint"], params["fingerprint"])
                self.assertEqual(result["binding"]["context_key"], binding["context_key"])
                self.assertEqual(result["binding"]["context_path"], binding["context_path"])
                self.assertEqual(result["binding"]["profile_path"], binding["profile_path"])
                self.assertEqual(result["binding"]["resume_prompt_path"], binding["resume_prompt_path"])

        asyncio.run(run_test())

    def test_load_runtime_state_command_uses_persisted_context_without_params(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                service = BotEaWebSocketService(adapter_factory=FakeAdapter, project_root=tmpdir)
                params = self._context_params(tmpdir)
                built = await service._handle_command({"id": "6d", "name": "build_resume_state", "params": params})
                binding = built["result"]["binding"]

                response = await service._handle_command({"id": "6e", "name": "load_runtime_state", "params": {}})
                self.assertTrue(response["ok"])
                result = response["result"]
                self.assertTrue(result["exists"])
                self.assertEqual(result["binding"]["mapping_source"], "runtime_state")
                self.assertEqual(result["binding"]["context_key"], binding["context_key"])
                self.assertEqual(result["binding"]["context_path"], binding["context_path"])
                self.assertEqual(result["binding"]["resume_prompt_path"], binding["resume_prompt_path"])

        asyncio.run(run_test())

    def test_list_account_contexts_command_lists_existing_variants(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                service = BotEaWebSocketService(adapter_factory=FakeAdapter, project_root=tmpdir)
                params = self._context_params(tmpdir)
                fingerprint = AccountFingerprint.from_payload(dict(params["fingerprint"]))
                await service._handle_command({"id": "7", "name": "build_resume_state", "params": params})
                await service._handle_command(
                    {
                        "id": "8",
                        "name": "build_resume_state",
                        "params": {**params, "create_new": True},
                    }
                )

                response = await service._handle_command({"id": "9", "name": "list_account_contexts", "params": params})
                self.assertTrue(response["ok"])
                result = response["result"]
                self.assertEqual(result["base_context_key"], fingerprint.key)
                self.assertEqual(result["mapped_context_key"], f"{fingerprint.key}_2")
                self.assertEqual(result["active_context_key"], f"{fingerprint.key}_2")
                contexts = {item["context_key"]: item for item in result["contexts"]}
                self.assertEqual(set(contexts), {fingerprint.key, f"{fingerprint.key}_2"})
                self.assertFalse(contexts[fingerprint.key]["is_mapped"])
                self.assertTrue(contexts[f"{fingerprint.key}_2"]["is_mapped"])
                self.assertTrue(contexts[f"{fingerprint.key}_2"]["is_active"])

        asyncio.run(run_test())

    def test_load_runtime_state_command_returns_runtime_binding_for_selected_context(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                service = BotEaWebSocketService(adapter_factory=FakeAdapter, project_root=tmpdir)
                params = self._context_params(tmpdir)
                built = await service._handle_command({"id": "9a", "name": "build_resume_state", "params": params})

                response = await service._handle_command({"id": "9b", "name": "load_runtime_state", "params": params})
                self.assertTrue(response["ok"])
                result = response["result"]
                self.assertTrue(result["exists"])
                self.assertEqual(result["runtime_state"]["context_key"], built["result"]["binding"]["context_key"])
                self.assertEqual(result["binding"]["mapping_source"], "runtime_state")
                self.assertEqual(result["binding"]["context_path"], built["result"]["binding"]["context_path"])
                self.assertEqual(result["binding"]["resume_prompt_path"], built["result"]["binding"]["resume_prompt_path"])
                self.assertEqual(result["binding"]["profile_path"], built["result"]["binding"]["profile_path"])

        asyncio.run(run_test())

    def test_list_account_contexts_reports_mapped_and_active_context_independently(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                service = BotEaWebSocketService(adapter_factory=FakeAdapter, project_root=tmpdir)
                params = self._context_params(tmpdir)
                fingerprint = AccountFingerprint.from_payload(dict(params["fingerprint"]))
                await service._handle_command({"id": "9c", "name": "build_resume_state", "params": params})
                newer = await service._handle_command(
                    {
                        "id": "9d",
                        "name": "build_resume_state",
                        "params": {**params, "create_new": True},
                    }
                )
                service.state_store.update_runtime_state({"context_key": fingerprint.key})

                response = await service._handle_command({"id": "9e", "name": "list_account_contexts", "params": params})
                self.assertTrue(response["ok"])
                result = response["result"]
                contexts = {item["context_key"]: item for item in result["contexts"]}
                self.assertEqual(result["mapped_context_key"], newer["result"]["binding"]["context_key"])
                self.assertEqual(result["active_context_key"], fingerprint.key)
                self.assertTrue(contexts[newer["result"]["binding"]["context_key"]]["is_mapped"])
                self.assertFalse(contexts[newer["result"]["binding"]["context_key"]]["is_active"])
                self.assertTrue(contexts[fingerprint.key]["is_active"])
                self.assertFalse(contexts[fingerprint.key]["is_mapped"])

        asyncio.run(run_test())

    def test_select_account_context_command_updates_mapping_and_runtime_state(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                service = BotEaWebSocketService(adapter_factory=FakeAdapter, project_root=tmpdir)
                params = self._context_params(tmpdir)
                fingerprint = AccountFingerprint.from_payload(dict(params["fingerprint"]))
                await service._handle_command({"id": "10", "name": "build_resume_state", "params": params})
                await service._handle_command(
                    {
                        "id": "11",
                        "name": "build_resume_state",
                        "params": {**params, "create_new": True},
                    }
                )

                select_response = await service._handle_command(
                    {
                        "id": "12",
                        "name": "select_account_context",
                        "params": {**params, "context_key": fingerprint.key},
                    }
                )
                self.assertTrue(select_response["ok"])
                self.assertEqual(select_response["result"]["binding"]["context_key"], fingerprint.key)
                self.assertEqual(select_response["result"]["binding"]["mapping_source"], "selected")

                runtime_state = await service._handle_command({"id": "13", "name": "load_runtime_state", "params": params})
                self.assertTrue(runtime_state["ok"])
                self.assertEqual(runtime_state["result"]["runtime_state"]["context_key"], fingerprint.key)
                self.assertEqual(runtime_state["result"]["binding"]["context_key"], fingerprint.key)

                listed = await service._handle_command({"id": "14", "name": "list_account_contexts", "params": params})
                contexts = {item["context_key"]: item for item in listed["result"]["contexts"]}
                self.assertEqual(listed["result"]["mapped_context_key"], fingerprint.key)
                self.assertEqual(listed["result"]["active_context_key"], fingerprint.key)
                self.assertTrue(contexts[fingerprint.key]["is_mapped"])
                self.assertTrue(contexts[fingerprint.key]["is_active"])

        asyncio.run(run_test())

    def test_select_account_context_command_can_create_new_variant(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                service = BotEaWebSocketService(adapter_factory=FakeAdapter, project_root=tmpdir)
                params = self._context_params(tmpdir)
                fingerprint = AccountFingerprint.from_payload(dict(params["fingerprint"]))
                await service._handle_command({"id": "15", "name": "build_resume_state", "params": params})

                response = await service._handle_command(
                    {
                        "id": "16",
                        "name": "select_account_context",
                        "params": {**params, "create_new": True},
                    }
                )
                self.assertTrue(response["ok"])
                self.assertEqual(response["result"]["binding"]["context_key"], f"{fingerprint.key}_2")
                self.assertEqual(response["result"]["binding"]["mapping_source"], "new_context")

        asyncio.run(run_test())

    def test_select_account_context_command_rejects_context_for_other_account(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                service = BotEaWebSocketService(adapter_factory=FakeAdapter, project_root=tmpdir)
                params = self._context_params(tmpdir)
                await service._handle_command({"id": "17", "name": "build_resume_state", "params": params})

                with self.assertRaises(RuntimeError) as ctx:
                    await service._handle_command(
                        {
                            "id": "18",
                            "name": "select_account_context",
                            "params": {**params, "context_key": "other_broker_other_server_999"},
                        }
                    )
                self.assertIn("tidak cocok dengan fingerprint", str(ctx.exception))

        asyncio.run(run_test())

    def test_select_account_context_command_rejects_invalid_context_key(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                service = BotEaWebSocketService(adapter_factory=FakeAdapter, project_root=tmpdir)
                params = self._context_params(tmpdir)
                await service._handle_command({"id": "19", "name": "build_resume_state", "params": params})

                with self.assertRaises(RuntimeError) as ctx:
                    await service._handle_command(
                        {
                            "id": "20",
                            "name": "select_account_context",
                            "params": {**params, "context_key": "../broker_demo_demo_server_123456"},
                        }
                    )
                self.assertIn("tidak cocok dengan fingerprint", str(ctx.exception))

        asyncio.run(run_test())

    def test_select_account_context_command_rejects_invalid_context_key_path(self) -> None:
        async def run_test() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                service = BotEaWebSocketService(adapter_factory=FakeAdapter, project_root=tmpdir)
                params = self._context_params(tmpdir)
                fingerprint = AccountFingerprint.from_payload(dict(params["fingerprint"]))
                await service._handle_command({"id": "19", "name": "build_resume_state", "params": params})

                with self.assertRaises(RuntimeError) as ctx:
                    await service._handle_command(
                        {
                            "id": "20",
                            "name": "select_account_context",
                            "params": {**params, "context_key": f"{fingerprint.key}_..\\escape"},
                        }
                    )
                self.assertIn("context_key tidak valid", str(ctx.exception))

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
