from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from goldm_signal.notify import ApprovedTelegramSender, TelegramApprovalWorker
from goldm_signal.storage import SignalStore, telegram_poll_db_identity
from goldm_signal.strategy import SetupRecord


class FakeTelegramClient:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.callback_answers: list[dict[str, Any]] = []
        self.fail_once_for: set[str] = set()
        self.get_updates_error: Exception | None = None
        self.raw_updates_result: Any = None

    def get_updates(self, *, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        del timeout
        if self.get_updates_error is not None:
            error = self.get_updates_error
            self.get_updates_error = None
            raise error
        if self.raw_updates_result is not None:
            return self.raw_updates_result
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
        self.release_id = "a" * 40
        self.session_sha256 = hashlib.sha256(b"test-ea-session").hexdigest()
        self.db_identity = telegram_poll_db_identity(self.store.path)
        self.deployment_nonce_sha256 = hashlib.sha256(b"b" * 32).hexdigest()
        self.release_manifest_sha256 = hashlib.sha256(b"release-manifest").hexdigest()
        self.runtime_config_sha256 = hashlib.sha256(b"runtime-config").hexdigest()
        self.production_config_sha256 = hashlib.sha256(b"production-config").hexdigest()
        self.worker_instance_id = "1" * 32
        self.store.start_telegram_poll_readiness(
            release_id=self.release_id,
            session_sha256=self.session_sha256,
            db_identity=self.db_identity,
            deployment_nonce_sha256=self.deployment_nonce_sha256,
            release_manifest_sha256=self.release_manifest_sha256,
            runtime_config_sha256=self.runtime_config_sha256,
            production_config_sha256=self.production_config_sha256,
            worker_instance_id=self.worker_instance_id,
            worker_started_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
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
            readiness_worker_instance_id=self.worker_instance_id,
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

    def test_admin_ids_must_be_positive_private_user_ids(self) -> None:
        for invalid_id in {"0", "-100", "not-a-user"}:
            with self.subTest(invalid_id=invalid_id), self.assertRaises(ValueError):
                TelegramApprovalWorker(
                    store=self.store,
                    client=self.client,  # type: ignore[arg-type]
                    admin_chat_ids={invalid_id},
                    readiness_worker_instance_id=self.worker_instance_id,
                )
            with self.subTest(sender_id=invalid_id), self.assertRaises(ValueError):
                ApprovedTelegramSender(
                    store=self.store,
                    client=self.client,  # type: ignore[arg-type]
                    admin_chat_ids={invalid_id},
                )

    def test_group_member_admin_identity_cannot_use_privileged_commands(self) -> None:
        self.worker.process_update(
            {
                "update_id": 1,
                "message": {
                    "text": "/control",
                    "from": {"id": 100},
                    "chat": {"id": -9001, "type": "group"},
                },
            }
        )
        self.assertIn("khusus root admin", self.client.messages[-1]["text"])
        self.assertNotIn("CONTROL PANEL", self.client.messages[-1]["text"])

    def test_callback_requires_admins_own_private_chat(self) -> None:
        self.worker.process_update(
            {
                "update_id": 1,
                "callback_query": {
                    "id": "group-callback",
                    "from": {"id": 100},
                    "message": {"chat": {"id": -9001, "type": "group"}},
                    "data": "ctl:mode:off",
                },
            }
        )
        self.assertTrue(self.client.callback_answers[-1]["show_alert"])
        self.assertIn("chat private", self.client.callback_answers[-1]["text"])
        self.assertEqual(self.store.runtime_settings(prefix="trade."), {})

    def test_private_chat_id_cannot_impersonate_admin_actor(self) -> None:
        self.worker.process_update(
            {
                "update_id": 1,
                "message": {
                    "text": "/control",
                    "from": {"id": 200},
                    "chat": {"id": 100, "type": "private"},
                },
            }
        )
        self.assertIn("khusus root admin", self.client.messages[-1]["text"])
        self.assertNotIn("CONTROL PANEL", self.client.messages[-1]["text"])

    def test_non_admin_group_member_cannot_start_or_stop_the_group(self) -> None:
        self.store.request_telegram_subscription(
            chat_id="-9001",
            username="group",
            first_name="GoldM",
            last_name="",
        )
        self.store.set_telegram_subscription_status(
            chat_id="-9001", status="APPROVED", decided_by="100"
        )

        for command in ("/stop", "/start"):
            with self.subTest(command=command):
                self.worker.process_update(
                    {
                        "update_id": 1,
                        "message": {
                            "text": command,
                            "from": {"id": 222},
                            "chat": {"id": -9001, "type": "group"},
                        },
                    }
                )
                subscriber = self.store.telegram_subscriber("-9001")
                assert subscriber is not None
                self.assertEqual(subscriber["status"], "APPROVED")
                self.assertIn(
                    "hanya boleh mengubah chat private",
                    self.client.messages[-1]["text"],
                )

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

    def test_missing_or_unknown_event_scope_is_admin_only(self) -> None:
        event = self._enqueue_signal()
        self.store.update_outbox_payload(int(event["id"]), {"text": "unknown scope"})
        event = self.store.pending()[0]
        self.client.messages.clear()

        sender = ApprovedTelegramSender(
            store=self.store,
            client=self.client,  # type: ignore[arg-type]
            admin_chat_ids={"100"},
        )
        sender(event)

        self.assertEqual([item["chat_id"] for item in self.client.messages], ["100"])
        self.assertEqual(
            self.store.recent_events(limit=5, include_admin_only=False), []
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

    def test_processing_failure_degrades_readiness_and_replays_only_poison_update(
        self,
    ) -> None:
        first = self._start_update(1, "200", "alice")
        poison = self._start_update(2, "201", "poison")
        self.client.updates.extend([first, poison])
        processed_ids: list[int] = []

        def process(update: dict[str, Any]) -> None:
            update_id = int(update["update_id"])
            processed_ids.append(update_id)
            if update_id == 2:
                raise ValueError("sensitive poison payload")

        with patch.object(self.worker, "process_update", side_effect=process):
            with self.assertRaisesRegex(RuntimeError, "processing_error") as caught:
                self.worker.run_once(timeout=0)
            self.assertNotIn("sensitive poison payload", str(caught.exception))
            self.assertEqual(self.store.telegram_update_offset(), 2)

            # Simulate Telegram returning the same batch again.  The durable
            # per-update offset excludes update 1, so its side effects cannot
            # be repeated while the poison update remains fail-closed.
            self.client.updates.extend([first, poison])
            with self.assertRaisesRegex(RuntimeError, "processing_error"):
                self.worker.run_once(timeout=0)

        self.assertEqual(processed_ids, [1, 2, 2])
        readiness = self.store.telegram_poll_readiness(
            expected_release_id=self.release_id,
            expected_session_sha256=self.session_sha256,
            expected_db_identity=self.db_identity,
            expected_deployment_nonce_sha256=self.deployment_nonce_sha256,
            expected_release_manifest_sha256=self.release_manifest_sha256,
            expected_runtime_config_sha256=self.runtime_config_sha256,
            expected_production_config_sha256=self.production_config_sha256,
            not_before=datetime.now(timezone.utc) - timedelta(minutes=1),
            max_age_seconds=30,
        )
        self.assertFalse(readiness["ready"])
        self.assertEqual(readiness["evidence"]["last_error_kind"], "processing_error")
        self.assertEqual(readiness["evidence"]["success_count"], 0)

    def test_offset_persistence_failure_never_marks_poll_ready(self) -> None:
        self.client.updates.append(self._start_update(7, "200", "alice"))

        with (
            patch.object(self.worker, "process_update") as process_update,
            patch.object(
                self.store,
                "set_telegram_update_offset",
                side_effect=OSError("sensitive database path"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "offset_error") as caught:
                self.worker.run_once(timeout=0)

        process_update.assert_called_once()
        self.assertNotIn("sensitive database path", str(caught.exception))
        self.assertIsNone(self.store.telegram_update_offset())
        readiness = self.store.telegram_poll_readiness(
            expected_release_id=self.release_id,
            expected_session_sha256=self.session_sha256,
            expected_db_identity=self.db_identity,
            expected_deployment_nonce_sha256=self.deployment_nonce_sha256,
            expected_release_manifest_sha256=self.release_manifest_sha256,
            expected_runtime_config_sha256=self.runtime_config_sha256,
            expected_production_config_sha256=self.production_config_sha256,
            not_before=datetime.now(timezone.utc) - timedelta(minutes=1),
            max_age_seconds=30,
        )
        self.assertFalse(readiness["ready"])
        self.assertEqual(readiness["evidence"]["last_error_kind"], "offset_error")
        self.assertEqual(readiness["evidence"]["success_count"], 0)

    def test_valid_empty_poll_marks_current_worker_ready(self) -> None:
        before = self.store.telegram_poll_readiness(
            expected_release_id=self.release_id,
            expected_session_sha256=self.session_sha256,
            expected_db_identity=self.db_identity,
            expected_deployment_nonce_sha256=self.deployment_nonce_sha256,
            expected_release_manifest_sha256=self.release_manifest_sha256,
            expected_runtime_config_sha256=self.runtime_config_sha256,
            expected_production_config_sha256=self.production_config_sha256,
            not_before=datetime.now(timezone.utc) - timedelta(minutes=1),
            max_age_seconds=30,
        )
        self.assertFalse(before["ready"])

        self.assertEqual(self.worker.run_once(timeout=0), 0)

        after = self.store.telegram_poll_readiness(
            expected_release_id=self.release_id,
            expected_session_sha256=self.session_sha256,
            expected_db_identity=self.db_identity,
            expected_deployment_nonce_sha256=self.deployment_nonce_sha256,
            expected_release_manifest_sha256=self.release_manifest_sha256,
            expected_runtime_config_sha256=self.runtime_config_sha256,
            expected_production_config_sha256=self.production_config_sha256,
            not_before=datetime.now(timezone.utc) - timedelta(minutes=1),
            max_age_seconds=30,
        )
        self.assertTrue(after["ready"])
        self.assertEqual(after["evidence"]["success_count"], 1)

    def test_duplicate_poller_conflict_never_marks_ready_or_persists_secrets(self) -> None:
        class DuplicatePollerConflict(RuntimeError):
            code = 409

        secret_marker = "bot123456:DO-NOT-PERSIST-session-nonce"
        self.client.get_updates_error = DuplicatePollerConflict(secret_marker)

        with self.assertRaisesRegex(RuntimeError, "telegram_conflict") as caught:
            self.worker.run_once(timeout=0)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertNotIn(secret_marker, str(caught.exception))

        readiness = self.store.telegram_poll_readiness(
            expected_release_id=self.release_id,
            expected_session_sha256=self.session_sha256,
            expected_db_identity=self.db_identity,
            expected_deployment_nonce_sha256=self.deployment_nonce_sha256,
            expected_release_manifest_sha256=self.release_manifest_sha256,
            expected_runtime_config_sha256=self.runtime_config_sha256,
            expected_production_config_sha256=self.production_config_sha256,
            not_before=datetime.now(timezone.utc) - timedelta(minutes=1),
            max_age_seconds=30,
        )
        self.assertFalse(readiness["ready"])
        self.assertEqual(readiness["evidence"]["last_error_kind"], "telegram_conflict")
        with self.store._connect() as connection:
            persisted = connection.execute(
                "SELECT state_value FROM telegram_bot_state "
                "WHERE state_key = 'telegram_poll_readiness_v1'"
            ).fetchone()[0]
        self.assertNotIn(secret_marker, persisted)
        self.assertNotIn("test-ea-session", persisted)
        self.assertNotIn("b" * 32, persisted)

        # A later success cannot hide an overlapping getUpdates poller.  The
        # conflict poisons this worker epoch until an operator resolves it and
        # starts a new exact deployment/task instance.
        self.client.get_updates_error = None
        self.assertEqual(self.worker.run_once(timeout=0), 0)
        poisoned = self.store.telegram_poll_readiness(
            expected_release_id=self.release_id,
            expected_session_sha256=self.session_sha256,
            expected_db_identity=self.db_identity,
            expected_deployment_nonce_sha256=self.deployment_nonce_sha256,
            expected_release_manifest_sha256=self.release_manifest_sha256,
            expected_runtime_config_sha256=self.runtime_config_sha256,
            expected_production_config_sha256=self.production_config_sha256,
            not_before=datetime.now(timezone.utc) - timedelta(minutes=1),
            max_age_seconds=30,
        )
        self.assertFalse(poisoned["ready"])
        self.assertEqual(poisoned["reason"], "telegram_conflict_observed")
        self.assertEqual(poisoned["evidence"]["conflict_count"], 1)
        self.assertEqual(poisoned["evidence"]["last_result"], "success")

    def test_malformed_success_payload_does_not_mark_ready(self) -> None:
        self.client.raw_updates_result = [{"update_id": "not-an-integer"}]

        with self.assertRaisesRegex(RuntimeError, "invalid data"):
            self.worker.run_once(timeout=0)

        readiness = self.store.telegram_poll_readiness(
            expected_release_id=self.release_id,
            expected_session_sha256=self.session_sha256,
            expected_db_identity=self.db_identity,
            expected_deployment_nonce_sha256=self.deployment_nonce_sha256,
            expected_release_manifest_sha256=self.release_manifest_sha256,
            expected_runtime_config_sha256=self.runtime_config_sha256,
            expected_production_config_sha256=self.production_config_sha256,
            not_before=datetime.now(timezone.utc) - timedelta(minutes=1),
            max_age_seconds=30,
        )
        self.assertFalse(readiness["ready"])
        self.assertEqual(readiness["evidence"]["last_error_kind"], "invalid_response")

    def test_poll_error_after_ready_degrades_until_new_success(self) -> None:
        self.assertEqual(self.worker.run_once(timeout=0), 0)
        self.client.get_updates_error = TimeoutError("contains-sensitive-url")

        with self.assertRaisesRegex(RuntimeError, "transport_timeout"):
            self.worker.run_once(timeout=0)

        degraded = self.store.telegram_poll_readiness(
            expected_release_id=self.release_id,
            expected_session_sha256=self.session_sha256,
            expected_db_identity=self.db_identity,
            expected_deployment_nonce_sha256=self.deployment_nonce_sha256,
            expected_release_manifest_sha256=self.release_manifest_sha256,
            expected_runtime_config_sha256=self.runtime_config_sha256,
            expected_production_config_sha256=self.production_config_sha256,
            not_before=datetime.now(timezone.utc) - timedelta(minutes=1),
            max_age_seconds=30,
        )
        self.assertFalse(degraded["ready"])
        self.assertEqual(degraded["reason"], "latest_poll_failed")

        self.assertEqual(self.worker.run_once(timeout=0), 0)
        recovered = self.store.telegram_poll_readiness(
            expected_release_id=self.release_id,
            expected_session_sha256=self.session_sha256,
            expected_db_identity=self.db_identity,
            expected_deployment_nonce_sha256=self.deployment_nonce_sha256,
            expected_release_manifest_sha256=self.release_manifest_sha256,
            expected_runtime_config_sha256=self.runtime_config_sha256,
            expected_production_config_sha256=self.production_config_sha256,
            not_before=datetime.now(timezone.utc) - timedelta(minutes=1),
            max_age_seconds=30,
        )
        self.assertTrue(recovered["ready"])
        self.assertEqual(recovered["evidence"]["last_result"], "success")

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
        self.assertIn(
            "Engine aktif (read-only): D7_CHANNEL_CONTINUATION",
            self.client.messages[-1]["text"],
        )
        self.assertIn("Entry side policy: ALL", self.client.messages[-1]["text"])
        self.assertIsNotNone(self.client.messages[-1]["reply_markup"])
        callbacks = {
            button["callback_data"]
            for row in self.client.messages[-1]["reply_markup"]["inline_keyboard"]
            for button in row
        }
        self.assertIn("ctl:entry_side:all", callbacks)
        self.assertIn("ctl:entry_side:buy_only", callbacks)
        self.assertIn("ctl:entry_side:sell_only", callbacks)
        self.assertIn("ctl:notification_side:all", callbacks)
        self.assertIn("ctl:notification_side:buy_only", callbacks)
        self.assertIn("ctl:notification_side:sell_only", callbacks)
        self.assertIn("Notification side filter: ALL", self.client.messages[-1]["text"])
        self.assertIn("ctl:r1:on", callbacks)
        self.assertIn("ctl:r2:off", callbacks)
        self.assertIn("ctl:r3:on", callbacks)
        self.assertIn("Risk sizing lot/posisi", self.client.messages[-1]["text"])
        self.assertIn("posisi terbuka memakai snapshot", self.client.messages[-1]["text"])

        self.worker.process_update(self._message_update(2, "200", "/control"))
        self.assertIn("khusus root admin", self.client.messages[-1]["text"])

    def test_entry_side_policy_requires_two_clicks_and_updates_runtime(self) -> None:
        self.worker.process_update(
            self._callback_update(1, "100", "ctl:entry_side:buy_only")
        )
        self.assertEqual(self.store.runtime_settings(prefix="trade."), {})
        confirm_data = self.client.messages[-1]["reply_markup"]["inline_keyboard"][0][0][
            "callback_data"
        ]

        self.worker.process_update(self._callback_update(2, "100", confirm_data))

        settings = self.store.runtime_settings(prefix="trade.")
        self.assertEqual(settings["trade.entry_side_policy"], "BUY_ONLY")

    def test_invalid_entry_side_callback_fails_closed_without_staging(self) -> None:
        self.worker.process_update(
            self._callback_update(1, "100", "ctl:entry_side:sideways")
        )

        self.assertEqual(self.store.runtime_settings(prefix="trade."), {})
        self.assertTrue(self.client.callback_answers[-1]["show_alert"])
        self.assertIn("tidak valid", self.client.callback_answers[-1]["text"])

    def test_notification_side_filter_requires_two_clicks(self) -> None:
        self.worker.process_update(
            self._callback_update(1, "100", "ctl:notification_side:sell_only")
        )
        self.assertEqual(self.store.runtime_settings(prefix="trade."), {})
        self.assertIn("Penyimpanan sinyal", self.client.messages[-1]["text"])
        confirm_data = self.client.messages[-1]["reply_markup"]["inline_keyboard"][0][0][
            "callback_data"
        ]

        self.worker.process_update(self._callback_update(2, "100", confirm_data))

        settings = self.store.runtime_settings(prefix="trade.")
        self.assertEqual(
            settings["trade.notification_side_filter"], "SELL_ONLY"
        )

    def test_show_profile_filters_only_directional_strategy_delivery(self) -> None:
        self.store.set_runtime_settings(
            {"trade.notification_side_filter": "BUY_ONLY"},
            updated_by="100",
        )
        directional = self._enqueue_directional_event(
            setup_id="sell-strategy", event_type="SNIPER_SIGNAL", side="SELL"
        )
        self.client.messages.clear()
        sender = ApprovedTelegramSender(
            store=self.store,
            client=self.client,  # type: ignore[arg-type]
            admin_chat_ids={"100"},
        )

        sender(directional)

        self.assertEqual(self.client.messages, [])
        self.assertTrue(
            any(
                row["setup_id"] == "sell-strategy"
                for row in self.store.recent_events(limit=100)
            )
        )

        safety = self._enqueue_directional_event(
            setup_id="sell-position", event_type="POSITION_OPENED", side="SELL"
        )
        sender(safety)
        self.assertEqual([item["chat_id"] for item in self.client.messages], ["100"])
        self.assertIn("POSITION_OPENED", self.client.messages[0]["text"])

    def test_admin_only_mt5_event_bypasses_show_filter_but_verified_demo_does_not(self) -> None:
        self.store.set_runtime_settings(
            {"trade.notification_side_filter": "BUY_ONLY"},
            updated_by="100",
        )
        blocked = self._enqueue_directional_event(
            setup_id="unverified-sell", event_type="SNIPER_SIGNAL", side="SELL"
        )
        payload = dict(blocked["payload"])
        payload.update(
            source="mt5_expert_log",
            event_account_binding_verified=False,
            audience="approved",
        )
        self.store.update_outbox_payload(int(blocked["id"]), payload)
        blocked = next(
            row
            for row in self.store.pending()
            if row["setup_id"] == "unverified-sell"
        )
        self.client.messages.clear()
        sender = ApprovedTelegramSender(
            store=self.store,
            client=self.client,  # type: ignore[arg-type]
            admin_chat_ids={"100"},
        )

        sender(blocked)

        self.assertEqual([item["chat_id"] for item in self.client.messages], ["100"])

        verified = self._enqueue_directional_event(
            setup_id="verified-sell", event_type="SNIPER_SIGNAL", side="SELL"
        )
        payload = dict(verified["payload"])
        payload.update(
            source="mt5_expert_log",
            event_account_binding_verified=True,
            audience="approved",
        )
        self.store.update_outbox_payload(int(verified["id"]), payload)
        verified = next(
            row
            for row in self.store.pending()
            if row["setup_id"] == "verified-sell"
        )
        self.client.messages.clear()

        sender(verified)

        self.assertEqual(self.client.messages, [])

    def test_invalid_show_profile_blocks_strategy_and_warns_admin(self) -> None:
        self.worker.process_update(self._start_update(1, "200", "approved_user"))
        self.worker.process_update(self._callback_update(2, "100", "approve:200"))
        self.store.set_runtime_settings(
            {"trade.notification_side_filter": "SIDEWAYS"},
            updated_by="100",
        )
        event = self._enqueue_directional_event(
            setup_id="invalid-show", event_type="SNIPER_OUTCOME", side="BUY"
        )
        self.client.messages.clear()
        sender = ApprovedTelegramSender(
            store=self.store,
            client=self.client,  # type: ignore[arg-type]
            admin_chat_ids={"100"},
        )

        sender(event)

        self.assertEqual([item["chat_id"] for item in self.client.messages], ["100"])
        self.assertIn("DIBLOKIR FAIL-CLOSED", self.client.messages[0]["text"])
        self.assertIn("SIDEWAYS", self.client.messages[0]["text"])
        self.assertTrue(
            any(
                row["setup_id"] == "invalid-show"
                for row in self.store.recent_events(limit=100)
            )
        )

    def test_r_management_toggle_requires_two_clicks_for_future_positions(self) -> None:
        self.worker.process_update(
            self._callback_update(1, "100", "ctl:r2:off")
        )
        self.assertEqual(self.store.runtime_settings(prefix="trade."), {})
        self.assertIn("posisi terbuka tidak berubah", self.client.messages[-1]["text"])
        confirm_data = self.client.messages[-1]["reply_markup"]["inline_keyboard"][0][0][
            "callback_data"
        ]

        self.worker.process_update(self._callback_update(2, "100", confirm_data))

        settings = self.store.runtime_settings(prefix="trade.")
        self.assertIs(settings["trade.r2_protection_enabled"], False)

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

    def test_live_mode_is_blocked_by_default_deployment_switch(self) -> None:
        self.worker.process_update(self._callback_update(1, "100", "ctl:mode:live"))
        self.assertTrue(self.client.callback_answers[-1]["show_alert"])
        self.assertEqual(self.store.runtime_settings(prefix="trade."), {})

        self.account["is_live"] = True
        self.worker.process_update(self._callback_update(2, "100", "ctl:mode:live"))
        self.assertTrue(self.client.callback_answers[-1]["show_alert"])
        self.assertIn("GOLDM_ALLOW_LIVE_ACTIVATION=false", self.client.callback_answers[-1]["text"])
        self.assertEqual(self.store.runtime_settings(prefix="trade."), {})

    def test_unlocked_live_mode_requires_explicit_second_click(self) -> None:
        self.account["is_live"] = True
        with patch.dict("os.environ", {"GOLDM_ALLOW_LIVE_ACTIVATION": "true"}):
            self.worker.process_update(
                self._callback_update(1, "100", "ctl:mode:live")
            )
            confirm_data = self.client.messages[-1]["reply_markup"]["inline_keyboard"][0][0][
                "callback_data"
            ]
            self.assertEqual(self.store.runtime_settings(prefix="trade."), {})
            self.worker.process_update(
                self._callback_update(2, "100", confirm_data)
            )

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

    def test_health_is_green_only_with_fresh_matching_session_evidence(self) -> None:
        now = datetime.now(timezone.utc)
        self.store.record_mt5_bridge_health(
            session_fingerprint="a" * 64,
            files_discovered=1,
            tracked_cursors=1,
            matched_events=1,
            mismatched_events=0,
            provider_failures=0,
            observed_at=now,
        )

        self.worker.process_update(self._message_update(1, "100", "/health"))

        self.assertIn("🟢 SEHAT", self.client.messages[-1]["text"])
        self.assertIn("session cocok", self.client.messages[-1]["text"])
        self.assertNotIn("a" * 64, self.client.messages[-1]["text"])

    def test_health_reports_stale_instead_of_false_green(self) -> None:
        self.store.record_mt5_bridge_health(
            session_fingerprint="b" * 64,
            files_discovered=1,
            tracked_cursors=1,
            matched_events=1,
            mismatched_events=0,
            provider_failures=0,
            observed_at=datetime.now(timezone.utc) - timedelta(minutes=31),
        )

        self.worker.process_update(self._message_update(1, "100", "/health"))

        self.assertIn("🟡 STALE", self.client.messages[-1]["text"])
        self.assertNotIn("🟢 SEHAT", self.client.messages[-1]["text"])

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
            payload={
                "text": "GOLD.i# ENTRY_READY",
                "account_scope": "demo",
                "audience": "approved",
            },
        )
        return self.store.pending()[0]

    def _enqueue_directional_event(
        self, *, setup_id: str, event_type: str, side: str
    ) -> dict[str, Any]:
        record = SetupRecord(
            setup_id,
            "GOLD.i#",
            side,
            4320.0,
            datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc),
        )
        self.store.save_setup(record)
        self.store.enqueue(
            setup_id=record.setup_id,
            event_type=event_type,
            payload={
                "text": f"{event_type} {side}",
                "fields": {"side": side},
                "account_scope": "demo",
                "audience": "approved",
            },
        )
        return next(
            row for row in self.store.pending() if row["setup_id"] == setup_id
        )

    @staticmethod
    def _start_update(update_id: int, chat_id: str, username: str) -> dict[str, Any]:
        return {
            "update_id": update_id,
            "message": {
                "text": "/start",
                "from": {"id": int(chat_id)},
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
                "message": {
                    "chat": {"id": int(actor_id), "type": "private"}
                },
                "data": data,
            },
        }

    @staticmethod
    def _message_update(update_id: int, chat_id: str, text: str) -> dict[str, Any]:
        return {
            "update_id": update_id,
            "message": {
                "text": text,
                "from": {"id": int(chat_id)},
                "chat": {"id": int(chat_id), "type": "private"},
            },
        }


if __name__ == "__main__":
    unittest.main()
