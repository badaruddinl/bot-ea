from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gold_orchestrator.config import (
    ROOT,
    OrchestratorConfig,
    WorkerSpec,
    load_orchestrator_config,
)
from gold_orchestrator.runtime import GlobalOrchestrator
from gold_portfolio.locking import SingleInstanceLock, WorkerAlreadyRunning


class FakeTelegram:
    def __init__(self) -> None:
        self.updates: list[dict] = []
        self.sent: list[tuple[str, str]] = []
        self.command_menus: list[tuple[tuple[dict[str, str], ...], set[str]]] = []

    def get_updates(self, *, offset, timeout):
        del offset, timeout
        updates, self.updates = self.updates, []
        return updates

    def send_message(self, *, chat_id, text, **_kwargs):
        self.sent.append((str(chat_id), text))
        return {}

    def replace_commands(self, *, commands, chat_ids, include_default=True):
        del include_default
        self.command_menus.append((commands, set(chat_ids)))


class FakeProcess:
    next_pid = 4000

    def __init__(self, _command, **_kwargs) -> None:
        type(self).next_pid += 1
        self.pid = type(self).next_pid
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        del timeout
        return self.returncode

    def kill(self):
        self.returncode = -9


class GlobalOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.telegram = FakeTelegram()
        workers = {
            name: WorkerSpec(
                name=name,
                config_path=self.root / f"{name}.json",
                enabled_on_first_boot=False,
                health_path=self.root / name / "health.json",
                log_path=self.root / name / "worker.log",
            )
            for name in ("goldi", "goldm")
        }
        self.config = OrchestratorConfig(
            orchestrator_id="TEST_ORCHESTRATOR",
            python_executable=Path(sys.executable),
            poll_timeout_seconds=0,
            supervision_interval_seconds=1,
            heartbeat_seconds=3600,
            restart_delay_seconds=2,
            health_stale_seconds=120,
            shutdown_grace_seconds=1,
            state_path=self.root / "state.json",
            audit_path=self.root / "audit.jsonl",
            bot_token="test",
            admin_chat_ids=("123",),
            workers=workers,
        )
        self.now = 10.0
        self.runtime = GlobalOrchestrator(
            self.config,
            telegram_client=self.telegram,
            popen_factory=FakeProcess,
            monotonic=lambda: self.now,
        )

    def tearDown(self) -> None:
        for name in list(self.runtime._children):
            self.runtime.stop_worker(name, notify=False)
        self.temporary.cleanup()

    def test_admin_can_start_and_stop_each_worker(self) -> None:
        self.runtime.handle_command(actor_id="123", text="/goldi_on")
        process = self.runtime._children["goldi"]
        self.assertIsNone(process.poll())
        self.runtime.handle_command(actor_id="123", text="/goldi_off")
        self.assertTrue(process.terminated)
        state = json.loads(self.config.state_path.read_text(encoding="utf-8"))
        self.assertFalse(state["desired"]["goldi"])

    def test_non_admin_cannot_start_real_worker(self) -> None:
        self.runtime.handle_command(actor_id="999", text="/goldm_on")
        self.assertNotIn("goldm", self.runtime._children)
        self.assertIn("khusus admin", self.telegram.sent[-1][1])

    def test_polling_advances_offset_and_dispatches(self) -> None:
        self.telegram.updates = [
            {
                "update_id": 41,
                "message": {"chat": {"id": 123}, "text": "/goldi_on"},
            }
        ]
        self.assertEqual(self.runtime.poll_once(timeout=0), 1)
        state = json.loads(self.config.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["telegram_offset"], 42)
        self.assertIn("goldi", self.runtime._children)

    def test_dead_desired_worker_is_restarted_after_delay(self) -> None:
        self.runtime.set_desired("goldi", True)
        first = self.runtime._children["goldi"]
        first.returncode = 7
        self.runtime.supervise_once(now=10.0)
        self.assertNotIn("goldi", self.runtime._children)
        self.runtime.supervise_once(now=12.0)
        self.assertIn("goldi", self.runtime._children)
        self.assertNotEqual(first.pid, self.runtime._children["goldi"].pid)

    def test_health_error_is_reported_once_until_it_changes(self) -> None:
        self.runtime.set_desired("goldi", True)
        health = self.config.workers["goldi"].health_path
        health.parent.mkdir(parents=True, exist_ok=True)
        health.write_text(
            json.dumps(
                {
                    "status": "ERROR",
                    "detail": "MT5 disconnected",
                    "updated_at": "2026-08-20T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        before = len(self.telegram.sent)
        self.runtime.supervise_once(now=10.0)
        self.runtime.supervise_once(now=11.0)
        alerts = [text for _, text in self.telegram.sent[before:] if "WORKER ALERT" in text]
        self.assertEqual(len(alerts), 1)

    def test_help_distinguishes_signal_and_real_worker(self) -> None:
        help_text = self.runtime.help_text()
        self.assertIn("sinyal GOLD.i", help_text)
        self.assertIn("trading GOLDm real", help_text)

    def test_config_rejects_shared_mt5_executable(self) -> None:
        environment = {
            "TELEGRAM_BOT_TOKEN": "test",
            "TELEGRAM_ADMIN_CHAT_IDS": "123",
            "GOLDI_MT5_TERMINAL_PATH": "C:/same/terminal64.exe",
            "GOLDI_MT5_LOGIN": "108098316",
            "GOLDI_MT5_SERVER": "XMGlobal-MT5 5",
            "GOLDM_REAL_MT5_TERMINAL_PATH": "C:/same/terminal64.exe",
            "GOLDM_REAL_MT5_LOGIN": "391425346",
            "GOLDM_REAL_MT5_SERVER": "XMGlobal-MT5 14",
        }
        with patch.dict("os.environ", environment, clear=True):
            with self.assertRaisesRegex(ValueError, "different MT5 paths"):
                load_orchestrator_config(ROOT / "config/final/orchestrator.json")

    def test_single_instance_lock_rejects_duplicate_worker(self) -> None:
        lock_path = self.root / "worker.lock"
        with SingleInstanceLock(lock_path):
            with self.assertRaises(WorkerAlreadyRunning):
                with SingleInstanceLock(lock_path):
                    pass

    def test_initial_off_state_can_be_persisted_before_polling(self) -> None:
        self.assertFalse(self.config.state_path.exists())
        self.runtime._save_state()
        state = json.loads(self.config.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["desired"], {"goldi": False, "goldm": False})

    def test_command_menu_replaces_old_approval_commands(self) -> None:
        self.runtime.publish_command_menu()
        commands, chat_ids = self.telegram.command_menus[-1]
        names = {item["command"] for item in commands}
        self.assertEqual(chat_ids, {"123"})
        self.assertIn("goldi_on", names)
        self.assertIn("goldm_on", names)
        self.assertNotIn("pending", names)
        self.assertNotIn("control", names)


if __name__ == "__main__":
    unittest.main()
