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
        self.sent_details: list[dict] = []
        self.edited_markups: list[dict] = []
        self.edited_texts: list[dict] = []
        self.callback_answers: list[dict] = []
        self.command_menus: list[tuple[tuple[dict[str, str], ...], set[str]]] = []
        self.next_message_id = 100

    def get_updates(self, *, offset, timeout):
        del offset, timeout
        updates, self.updates = self.updates, []
        return updates

    def send_message(self, *, chat_id, text, **kwargs):
        self.sent.append((str(chat_id), text))
        self.next_message_id += 1
        detail = {
            "chat_id": str(chat_id),
            "text": text,
            "message_id": self.next_message_id,
            **kwargs,
        }
        self.sent_details.append(detail)
        return {"message_id": self.next_message_id}

    def answer_callback_query(self, **kwargs):
        self.callback_answers.append(kwargs)

    def edit_message_reply_markup(self, **kwargs):
        self.edited_markups.append(kwargs)

    def edit_message_text(self, **kwargs):
        self.edited_texts.append(kwargs)

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
        self.assertIn("/start", self.telegram.sent[-1][1])

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
        self.assertIn("entry demo GOLD.i", help_text)
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

    def test_online_notice_is_suppressed_during_rapid_restart(self) -> None:
        self.assertTrue(self.runtime._announce_online())
        self.assertFalse(self.runtime._announce_online())
        online_messages = [
            text for _, text in self.telegram.sent if "ORCHESTRATOR ONLINE" in text
        ]
        self.assertEqual(len(online_messages), 1)

    def test_command_menu_replaces_old_approval_commands(self) -> None:
        self.runtime.publish_command_menu()
        commands, chat_ids = self.telegram.command_menus[-1]
        names = {item["command"] for item in commands}
        self.assertEqual(chat_ids, {"123"})
        self.assertEqual(names, {"status", "pending", "subscribers", "help"})
        self.assertIn("pending", names)
        self.assertNotIn("control", names)

        public_commands, public_chat_ids = self.telegram.command_menus[0]
        self.assertEqual(public_chat_ids, set())
        self.assertEqual(
            {item["command"] for item in public_commands},
            {"start"},
        )

    def test_approval_is_goldi_subscription_only(self) -> None:
        self.runtime.handle_command(
            actor_id="-999",
            text="/start",
            chat={"id": -999, "title": "Goldi Viewers", "type": "group"},
        )
        self.assertIn("-999", self.runtime._state["goldi_pending"])
        self.assertNotIn("goldm", self.runtime._children)
        request_card = next(
            item
            for item in self.telegram.sent_details
            if item["chat_id"] == "123" and "Permintaan akses" in item["text"]
        )
        buttons = request_card["reply_markup"]["inline_keyboard"][0]
        self.assertEqual(
            {item["callback_data"] for item in buttons},
            {
                "goldi_sub:prompt_approve:-999",
                "goldi_sub:prompt_deny:-999",
            },
        )
        pending_menu = self.telegram.command_menus[-1]
        self.assertEqual(pending_menu[1], {"-999"})
        self.assertEqual(
            {item["command"] for item in pending_menu[0]},
            {"subscription"},
        )

        self.runtime.handle_command(actor_id="123", text="/pending")
        tracked = self.runtime._state["goldi_approval_messages"]["-999"]
        self.assertEqual(len(tracked), 2)

        self.runtime.handle_callback(
            {
                "id": "callback-prompt",
                "from": {"id": 123},
                "data": "goldi_sub:prompt_approve:-999",
                "message": {
                    "message_id": request_card["message_id"],
                    "chat": {"id": 123},
                },
            }
        )
        self.assertNotIn("-999", self.runtime._state["goldi_subscribers"])
        self.assertIn("KONFIRMASI", self.telegram.edited_texts[-1]["text"])

        self.runtime.handle_callback(
            {
                "id": "callback-confirm",
                "from": {"id": 123},
                "data": "goldi_sub:confirm_approve:-999",
                "message": {
                    "message_id": request_card["message_id"],
                    "chat": {"id": 123},
                },
            }
        )
        self.assertEqual(self.runtime._state["goldi_subscribers"], ["-999"])
        self.assertNotIn("-999", self.runtime._state["goldi_pending"])
        self.assertIn(
            ("-999", "Akses notifikasi entry GOLD.i telah disetujui."),
            self.telegram.sent,
        )
        self.assertIn("STATUS PERMINTAAN", self.telegram.edited_texts[-1]["text"])
        self.assertEqual(
            self.telegram.edited_texts[-1]["reply_markup"],
            {"inline_keyboard": []},
        )
        self.assertGreaterEqual(len(self.telegram.edited_markups), 2)
        approved_menu = self.telegram.command_menus[-1]
        self.assertEqual(approved_menu[1], {"-999"})
        self.assertEqual(
            {item["command"] for item in approved_menu[0]},
            {"subscription", "stop"},
        )

    def test_worker_panel_buttons_follow_opposite_state_with_confirmation(self) -> None:
        self.runtime.handle_command(actor_id="123", text="/status")
        panel = self.telegram.sent_details[-1]
        first_button = panel["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(first_button["text"], "▶️ Hidupkan GOLD.i DEMO")
        self.assertEqual(first_button["callback_data"], "worker:prompt:goldi_on")

        callback_message = {
            "message_id": panel["message_id"],
            "chat": {"id": 123},
        }
        self.runtime.handle_callback(
            {
                "id": "worker-prompt",
                "from": {"id": 123},
                "data": "worker:prompt:goldi_on",
                "message": callback_message,
            }
        )
        self.assertFalse(self.runtime._state["desired"]["goldi"])
        confirmation = self.telegram.edited_texts[-1]
        self.assertIn("Yakin", confirmation["text"])
        confirm_button = confirmation["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(confirm_button["callback_data"], "worker:confirm:goldi_on")

        self.runtime.handle_callback(
            {
                "id": "worker-confirm",
                "from": {"id": 123},
                "data": "worker:confirm:goldi_on",
                "message": callback_message,
            }
        )
        self.assertTrue(self.runtime._state["desired"]["goldi"])
        status = self.telegram.edited_texts[-1]
        self.assertIn("STATUS DIPERBARUI", status["text"])
        new_button = status["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(new_button["text"], "⏹ Matikan GOLD.i DEMO")
        self.assertEqual(new_button["callback_data"], "worker:prompt:goldi_off")

    def test_subscriber_cannot_control_goldm(self) -> None:
        self.runtime._state["goldi_subscribers"] = ["999"]
        self.runtime.handle_command(actor_id="999", text="/goldm_on")
        self.assertNotIn("goldm", self.runtime._children)

    def test_failed_callback_isolated_and_later_update_still_processed(self) -> None:
        original_edit = self.telegram.edit_message_text

        def fail_edit(**_kwargs):
            raise RuntimeError("simulated edit failure")

        self.telegram.edit_message_text = fail_edit
        self.telegram.updates = [
            {
                "update_id": 50,
                "callback_query": {
                    "id": "broken-callback",
                    "from": {"id": 123},
                    "data": "worker:refresh",
                    "message": {"message_id": 10, "chat": {"id": 123}},
                },
            },
            {
                "update_id": 51,
                "message": {"chat": {"id": 123}, "text": "/help"},
            },
        ]

        self.assertEqual(self.runtime.poll_once(timeout=0), 2)
        self.telegram.edit_message_text = original_edit
        self.assertEqual(self.runtime._state["telegram_offset"], 52)
        self.assertTrue(any("GOLD worker control" in text for _, text in self.telegram.sent))
        audit = self.config.audit_path.read_text(encoding="utf-8")
        self.assertIn("TELEGRAM_UPDATE_FAILED", audit)
        self.assertTrue(
            any(
                item.get("text") == "Diproses…"
                for item in self.telegram.callback_answers
            )
        )


if __name__ == "__main__":
    unittest.main()
