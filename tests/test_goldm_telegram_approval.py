from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from goldm_signal.notify import ApprovedTelegramSender, TelegramApprovalWorker
from goldm_signal.storage import SignalStore
from goldm_signal.strategy import SetupRecord


class FakeTelegramClient:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.callback_answers: list[dict[str, Any]] = []
        self.fail_once_for: set[str] = set()

    def get_updates(self, *, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        del timeout
        updates = [
            update
            for update in self.updates
            if offset is None or int(update["update_id"]) >= offset
        ]
        self.updates = []
        return updates

    def send_message(
        self,
        *,
        chat_id: str | int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_id = str(chat_id)
        if normalized_id in self.fail_once_for:
            self.fail_once_for.remove(normalized_id)
            raise RuntimeError("temporary failure")
        message = {
            "chat_id": normalized_id,
            "text": text,
            "reply_markup": reply_markup,
        }
        self.messages.append(message)
        return message

    def answer_callback_query(
        self, *, callback_query_id: str, text: str, show_alert: bool = False
    ) -> None:
        self.callback_answers.append(
            {"id": callback_query_id, "text": text, "show_alert": show_alert}
        )


class GoldMTelegramApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.store = SignalStore(Path(self.tempdir.name) / "signal.db")
        self.store.initialize()
        self.client = FakeTelegramClient()
        self.account = {
            "login": "108098316",
            "server": "XMGlobal-MT5",
            "broker": "XM Global Limited",
            "is_live": False,
            "trade_allowed": True,
        }
        self.worker = TelegramApprovalWorker(
            store=self.store,
            client=self.client,  # type: ignore[arg-type]
            admin_chat_ids={"100"},
            account_probe=lambda: dict(self.account),
        )

    def test_start_is_pending_until_admin_approves_callback(self) -> None:
        self.worker.process_update(self._start_update(1, "200", "alice"))

        subscriber = self.store.telegram_subscriber("200")
        assert subscriber is not None
        self.assertEqual(subscriber["status"], "PENDING")
        self.assertEqual(self.store.approved_telegram_chat_ids(), ["100"])
        approval_message = next(
            item for item in self.client.messages if item["chat_id"] == "100"
        )
        buttons = approval_message["reply_markup"]["inline_keyboard"][0]
        self.assertEqual(buttons[0]["callback_data"], "approve:200")

        self.worker.process_update(self._callback_update(2, "100", "approve:200"))

        subscriber = self.store.telegram_subscriber("200")
        assert subscriber is not None
        self.assertEqual(subscriber["status"], "APPROVED")
        self.assertEqual(set(self.store.approved_telegram_chat_ids()), {"100", "200"})
        self.assertTrue(
            any(
                item["chat_id"] == "200" and "sekarang aktif" in item["text"]
                for item in self.client.messages
            )
        )

    def test_non_admin_cannot_approve(self) -> None:
        self.worker.process_update(self._start_update(1, "200", "alice"))
        self.worker.process_update(self._callback_update(2, "300", "approve:200"))

        subscriber = self.store.telegram_subscriber("200")
        assert subscriber is not None
        self.assertEqual(subscriber["status"], "PENDING")
        self.assertTrue(self.client.callback_answers[-1]["show_alert"])

    def test_broadcast_excludes_pending_and_rejected_subscribers(self) -> None:
        self.worker.process_update(self._start_update(1, "200", "approved_user"))
        self.worker.process_update(self._callback_update(2, "100", "approve:200"))
        self.worker.process_update(self._start_update(3, "300", "pending_user"))
        self.worker.process_update(self._start_update(4, "400", "rejected_user"))
        self.worker.process_update(self._callback_update(5, "100", "reject:400"))
        event = self._enqueue_signal()
        self.client.messages.clear()

        sender = ApprovedTelegramSender(
            store=self.store, client=self.client  # type: ignore[arg-type]
        )
        sender(event)

        recipients = {item["chat_id"] for item in self.client.messages}
        self.assertEqual(recipients, {"100", "200"})
        self.assertNotIn("300", recipients)
        self.assertNotIn("400", recipients)

    def test_live_account_event_is_delivered_only_to_root_admin(self) -> None:
        self.worker.process_update(self._start_update(1, "200", "approved_user"))
        self.worker.process_update(self._callback_update(2, "100", "approve:200"))
        event = self._enqueue_signal()
        self.store.update_outbox_payload(
            int(event["id"]),
            {
                "text": "REAL position opened",
                "account_scope": "live",
                "audience": "approved",
            },
        )
        event = self.store.pending()[0]
        self.client.messages.clear()

        sender = ApprovedTelegramSender(
            store=self.store,
            client=self.client,  # type: ignore[arg-type]
            admin_chat_ids={"100"},
        )
        sender(event)

        self.assertEqual(
            [item["chat_id"] for item in self.client.messages],
            ["100"],
        )

    def test_retry_does_not_resend_to_successful_recipient(self) -> None:
        self.worker.process_update(self._start_update(1, "200", "alice"))
        self.worker.process_update(self._callback_update(2, "100", "approve:200"))
        event = self._enqueue_signal()
        self.client.messages.clear()
        self.client.fail_once_for.add("200")
        sender = ApprovedTelegramSender(
            store=self.store, client=self.client  # type: ignore[arg-type]
        )

        with self.assertRaisesRegex(RuntimeError, "1 approved subscriber"):
            sender(event)
        self.assertEqual([item["chat_id"] for item in self.client.messages], ["100"])

        sender(event)
        self.assertEqual(
            [item["chat_id"] for item in self.client.messages], ["100", "200"]
        )

    def test_update_offset_is_persisted(self) -> None:
        self.client.updates.append(self._start_update(42, "200", "alice"))

        self.assertEqual(self.worker.run_once(timeout=0), 1)
        self.assertEqual(self.store.telegram_update_offset(), 43)

    def test_non_admin_admin_command_is_rejected_before_dispatch(self) -> None:
        self.worker.process_update(self._start_update(1, "200", "alice"))
        self.client.messages.clear()

        self.worker.process_update(self._message_update(2, "200", "/snapshot"))

        self.assertEqual(len(self.client.messages), 1)
        self.assertIn("khusus root admin", self.client.messages[0]["text"])
        self.assertIn("/signal — sinyal demo terakhir", self.client.messages[0]["text"])
        self.assertNotIn("/control", self.client.messages[0]["text"])

    def test_public_signal_and_history_commands_require_approved_access(self) -> None:
        self.worker.process_update(self._start_update(1, "200", "alice"))
        self.client.messages.clear()

        self.worker.process_update(self._message_update(2, "200", "/signal"))

        self.assertEqual(len(self.client.messages), 1)
        self.assertIn("subscriber APPROVED", self.client.messages[0]["text"])

    def test_approved_user_can_only_use_public_read_only_commands(self) -> None:
        self.worker.process_update(self._start_update(1, "200", "alice"))
        self.worker.process_update(self._callback_update(2, "100", "approve:200"))
        self._enqueue_signal()
        self.client.messages.clear()

        self.worker.process_update(self._message_update(3, "200", "/signal"))
        self.worker.process_update(self._message_update(4, "200", "/history"))
        self.worker.process_update(self._message_update(5, "200", "/health"))

        texts = [item["text"] for item in self.client.messages]
        self.assertIn("bukan sinyal baru", texts[0])
        self.assertIn("GOLD.i# ENTRY_READY", texts[0])
        self.assertIn("5 EVENT TERBARU", texts[1])
        self.assertIn("khusus root admin", texts[2])
        self.assertNotIn("HEALTH SNAPSHOT", texts[2])

    def test_public_snapshots_hide_live_events_but_admin_can_read_them(self) -> None:
        self.worker.process_update(self._start_update(1, "200", "alice"))
        self.worker.process_update(self._callback_update(2, "100", "approve:200"))
        event = self._enqueue_signal()
        self.store.update_outbox_payload(
            int(event["id"]),
            {
                "text": "REAL secret event",
                "account_scope": "live",
                "audience": "admin_only",
            },
        )
        self.client.messages.clear()

        self.worker.process_update(self._message_update(3, "200", "/signal"))
        self.worker.process_update(self._message_update(4, "200", "/history"))
        self.worker.process_update(self._message_update(5, "100", "/signal"))

        texts = [item["text"] for item in self.client.messages]
        self.assertIn("Belum ada data", texts[0])
        self.assertIn("Belum ada event", texts[1])
        self.assertIn("REAL secret event", texts[2])

    def test_watch_snapshot_reports_no_data_without_creating_an_entry(self) -> None:
        self.client.messages.clear()

        self.worker.process_update(self._message_update(1, "100", "/watch"))

        self.assertEqual(len(self.client.messages), 1)
        self.assertIn("Belum ada data", self.client.messages[0]["text"])
        self.assertEqual(self.store.recent_events(), [])

    def test_control_panel_is_root_admin_only(self) -> None:
        self.worker.process_update(self._message_update(1, "100", "/control"))
        self.assertIn("CONTROL PANEL GOLDM", self.client.messages[-1]["text"])
        self.assertIsNotNone(self.client.messages[-1]["reply_markup"])

        self.worker.process_update(self._message_update(2, "200", "/control"))
        self.assertIn("khusus root admin", self.client.messages[-1]["text"])

    def test_users_can_be_revoked_with_admin_button(self) -> None:
        self.worker.process_update(self._message_update(1, "200", "/start"))
        self.worker.process_update(self._callback_update(2, "100", "approve:200"))

        self.worker.process_update(self._message_update(3, "100", "/users"))

        keyboard = self.client.messages[-1]["reply_markup"]["inline_keyboard"]
        revoke = next(
            button["callback_data"]
            for row in keyboard
            for button in row
            if button["callback_data"] == "reject:200"
        )
        self.worker.process_update(self._callback_update(4, "100", revoke))
        subscribers = self.store.telegram_subscribers(status="REJECTED")
        self.assertEqual([item["chat_id"] for item in subscribers], ["200"])

    def test_demo_mode_requires_two_clicks_and_binds_current_account(self) -> None:
        self.worker.process_update(self._callback_update(1, "100", "ctl:mode:demo"))
        self.assertEqual(self.store.runtime_settings(prefix="trade."), {})
        confirm_data = self.client.messages[-1]["reply_markup"]["inline_keyboard"][0][0][
            "callback_data"
        ]

        self.worker.process_update(self._callback_update(2, "100", confirm_data))

        settings = self.store.runtime_settings(prefix="trade.")
        self.assertEqual(settings["trade.execution_mode"], "demo")
        self.assertEqual(settings["trade.expected_login"], "108098316")
        self.assertEqual(settings["trade.expected_server"], "XMGlobal-MT5")
        self.assertEqual(settings["trade.live_consent"], "")

    def test_live_mode_requires_real_account_and_explicit_second_click(self) -> None:
        self.worker.process_update(self._callback_update(1, "100", "ctl:mode:live"))
        self.assertTrue(self.client.callback_answers[-1]["show_alert"])
        self.assertEqual(self.store.runtime_settings(prefix="trade."), {})

        self.account["is_live"] = True
        self.worker.process_update(self._callback_update(2, "100", "ctl:mode:live"))
        confirm_data = self.client.messages[-1]["reply_markup"]["inline_keyboard"][0][0][
            "callback_data"
        ]
        self.assertEqual(self.store.runtime_settings(prefix="trade."), {})
        self.worker.process_update(self._callback_update(3, "100", confirm_data))

        settings = self.store.runtime_settings(prefix="trade.")
        self.assertEqual(settings["trade.execution_mode"], "live")
        self.assertEqual(settings["trade.live_consent"], "I_UNDERSTAND_LIVE_ORDERS")

    def test_account_change_between_stage_and_confirm_is_rejected(self) -> None:
        self.worker.process_update(self._callback_update(1, "100", "ctl:mode:demo"))
        confirm_data = self.client.messages[-1]["reply_markup"]["inline_keyboard"][0][0][
            "callback_data"
        ]
        self.account["login"] = "999999"

        self.worker.process_update(self._callback_update(2, "100", confirm_data))

        self.assertEqual(self.store.runtime_settings(prefix="trade."), {})
        self.assertTrue(self.client.callback_answers[-1]["show_alert"])

    def test_expired_control_confirmation_is_rejected(self) -> None:
        self.store.stage_admin_action(
            token="expired",
            action_type="risk_change",
            payload={"settings": {"trade.risk_pct": 1.0}},
            requested_by="100",
            expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        )

        self.worker.process_update(
            self._callback_update(1, "100", "ctl:confirm:expired")
        )

        self.assertEqual(self.store.runtime_settings(prefix="trade."), {})
        self.assertIn("EXPIRED", self.client.callback_answers[-1]["text"])
        self.assertTrue(self.client.callback_answers[-1]["show_alert"])

    def test_off_mode_is_an_immediate_emergency_stop(self) -> None:
        self.store.set_runtime_settings(
            {
                "trade.execution_mode": "demo",
                "trade.live_consent": "I_UNDERSTAND_LIVE_ORDERS",
            },
            updated_by="100",
        )

        self.worker.process_update(self._callback_update(1, "100", "ctl:mode:off"))

        settings = self.store.runtime_settings(prefix="trade.")
        self.assertEqual(settings["trade.execution_mode"], "off")
        self.assertEqual(settings["trade.live_consent"], "")

    def _enqueue_signal(self) -> dict[str, Any]:
        record = SetupRecord(
            "setup-1",
            "GOLD.i#",
            "BUY",
            4320.0,
            datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc),
        )
        self.store.save_setup(record)
        self.store.enqueue(
            setup_id=record.setup_id,
            event_type="ENTRY_READY",
            payload={"text": "GOLD.i# ENTRY_READY"},
        )
        return self.store.pending()[0]

    @staticmethod
    def _start_update(update_id: int, chat_id: str, username: str) -> dict[str, Any]:
        return {
            "update_id": update_id,
            "message": {
                "text": "/start",
                "chat": {
                    "id": int(chat_id),
                    "type": "private",
                    "username": username,
                    "first_name": username.title(),
                },
            },
        }

    @staticmethod
    def _callback_update(update_id: int, actor_id: str, data: str) -> dict[str, Any]:
        return {
            "update_id": update_id,
            "callback_query": {
                "id": f"callback-{update_id}",
                "from": {"id": int(actor_id)},
                "data": data,
            },
        }

    @staticmethod
    def _message_update(update_id: int, chat_id: str, text: str) -> dict[str, Any]:
        return {
            "update_id": update_id,
            "message": {
                "text": text,
                "chat": {"id": int(chat_id), "type": "private"},
            },
        }


if __name__ == "__main__":
    unittest.main()
