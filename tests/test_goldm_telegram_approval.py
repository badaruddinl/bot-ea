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
        self.worker = TelegramApprovalWorker(
            store=self.store,
            client=self.client,  # type: ignore[arg-type]
            admin_chat_ids={"100"},
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


if __name__ == "__main__":
    unittest.main()
