from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from goldm_signal.notify.telegram import TelegramBotClient

from .config import ROOT, OrchestratorConfig, WorkerSpec

PUBLIC_GOLDI_COMMANDS: tuple[dict[str, str], ...] = (
    {"command": "start", "description": "Minta akses notifikasi GOLD.i"},
)


PENDING_GOLDI_COMMANDS: tuple[dict[str, str], ...] = (
    {"command": "subscription", "description": "Cek status akses GOLD.i"},
)


APPROVED_GOLDI_COMMANDS: tuple[dict[str, str], ...] = (
    {"command": "subscription", "description": "Cek status akses GOLD.i"},
    {"command": "stop", "description": "Berhenti menerima GOLD.i"},
)


ORCHESTRATOR_BOT_COMMANDS: tuple[dict[str, str], ...] = (
    {"command": "status", "description": "Status kedua worker GOLD"},
    {"command": "pending", "description": "Permintaan akses GOLD.i"},
    {"command": "subscribers", "description": "Subscriber GOLD.i aktif"},
    {"command": "help", "description": "Daftar perintah orchestrator"},
)
AUDIT_MAX_BYTES = 5 * 1024 * 1024
AUDIT_BACKUPS = 3


class GlobalOrchestrator:
    """One Telegram poller and watchdog for both final portfolio workers."""

    def __init__(
        self,
        config: OrchestratorConfig,
        *,
        telegram_client: TelegramBotClient | None = None,
        popen_factory=subprocess.Popen,
        monotonic=time.monotonic,
    ) -> None:
        self.config = config
        self.telegram = telegram_client or TelegramBotClient(
            bot_token=config.bot_token,
            timeout_seconds=max(10.0, float(config.poll_timeout_seconds + 5)),
        )
        self._popen_factory = popen_factory
        self._monotonic = monotonic
        self._state = self._load_state()
        self._children: dict[str, subprocess.Popen[Any]] = {}
        self._logs: dict[str, Any] = {}
        self._stop_event = threading.Event()
        self._last_supervision = 0.0
        self._last_heartbeat = 0.0
        self._next_restart: dict[str, float] = {}
        self._failure_counts: dict[str, int] = {}
        self._reported_problem: dict[str, str] = {}

    def run_forever(self) -> None:
        self._validate_bot_identity()
        self._install_signal_handlers()
        self._save_state()
        try:
            self.publish_command_menu()
        except Exception as exc:
            self._audit_runtime_failure("TELEGRAM_MENU_SYNC_FAILED", exc)
        try:
            self._announce_online()
        except Exception as exc:
            self._audit_runtime_failure("ONLINE_NOTICE_FAILED", exc)
        self._last_heartbeat = self._monotonic()
        self._audit("ORCHESTRATOR_ONLINE", {"pid": os.getpid()})
        try:
            while not self._stop_event.is_set():
                now = self._monotonic()
                if now - self._last_supervision >= self.config.supervision_interval_seconds:
                    self.supervise_once(now=now)
                    self._last_supervision = now
                if now - self._last_heartbeat >= self.config.heartbeat_seconds:
                    self._send_all(self.status_text(title="SCHEDULED HEARTBEAT"))
                    self._last_heartbeat = now
                try:
                    self.poll_once(timeout=self.config.poll_timeout_seconds)
                except Exception as exc:
                    self._audit_runtime_failure("TELEGRAM_POLL_FAILED", exc)
                    self._stop_event.wait(min(5.0, self.config.supervision_interval_seconds))
        finally:
            for name in list(self._children):
                self.stop_worker(name, notify=False)
            self._audit("ORCHESTRATOR_STOPPED", {})

    def _validate_bot_identity(self) -> None:
        expected = (self.config.expected_bot_username or "").strip().lstrip("@")
        if not expected:
            return
        identity = self.telegram.get_me()
        observed = str(identity.get("username") or "").strip().lstrip("@")
        if not observed or observed.casefold() != expected.casefold():
            raise RuntimeError(
                f"Telegram bot identity mismatch: expected @{expected}, "
                f"got @{observed or 'unknown'}"
            )

    def _audit_runtime_failure(self, event: str, exc: Exception) -> None:
        with suppress(Exception):
            self._audit(
                event,
                {
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                },
            )

    def _announce_online(self) -> bool:
        now = datetime.now(UTC)
        raw_previous = str(self._state.get("last_online_notice_at") or "")
        try:
            previous = datetime.fromisoformat(raw_previous)
            elapsed = (now - previous.astimezone(UTC)).total_seconds()
        except ValueError:
            elapsed = 300.0
        if elapsed < 300.0:
            return False
        self._send_all(
            f"🟢 ORCHESTRATOR ONLINE\n"
            f"Worker: {self._desired_summary()}\n"
            f"Waktu: {self._human_time(now)}"
        )
        self._state["last_online_notice_at"] = now.isoformat()
        self._save_state()
        return True

    def publish_command_menu(self) -> None:
        self.telegram.replace_commands(
            commands=PUBLIC_GOLDI_COMMANDS,
            chat_ids=set(),
        )
        self.telegram.replace_commands(
            commands=ORCHESTRATOR_BOT_COMMANDS,
            chat_ids=set(self.config.admin_chat_ids),
            include_default=False,
        )
        subscribers = set(self._state.get("goldi_subscribers") or [])
        pending = set((self._state.get("goldi_pending") or {}).keys())
        for chat_id in sorted(pending - subscribers, key=int):
            self._safe_set_subscription_menu(chat_id, "pending")
        for chat_id in sorted(subscribers, key=int):
            self._safe_set_subscription_menu(chat_id, "approved")
        self._audit(
            "TELEGRAM_COMMAND_MENU_UPDATED",
            {"commands": [item["command"] for item in ORCHESTRATOR_BOT_COMMANDS]},
        )

    def _set_subscription_menu(self, chat_id: str, state: str) -> None:
        commands = (
            APPROVED_GOLDI_COMMANDS
            if state == "approved"
            else PENDING_GOLDI_COMMANDS
            if state == "pending"
            else PUBLIC_GOLDI_COMMANDS
        )
        self.telegram.replace_commands(
            commands=commands,
            chat_ids={chat_id},
            include_default=False,
        )

    def _safe_set_subscription_menu(self, chat_id: str, state: str) -> None:
        try:
            self._set_subscription_menu(chat_id, state)
        except Exception as exc:
            self._audit_runtime_failure("SUBSCRIPTION_MENU_SYNC_FAILED", exc)

    def request_stop(self) -> None:
        self._stop_event.set()

    def poll_once(self, *, timeout: int = 0) -> int:
        offset = int(self._state.get("telegram_offset") or 0) or None
        updates = self.telegram.get_updates(offset=offset, timeout=timeout)
        handled = 0
        for update in updates:
            update_id = int(update.get("update_id") or 0)
            if update_id:
                self._state["telegram_offset"] = update_id + 1
            try:
                callback = update.get("callback_query") or {}
                if callback:
                    handled += 1
                    self.handle_callback(callback)
                    continue
                message = update.get("message") or {}
                chat = message.get("chat") or {}
                actor_id = str(chat.get("id") or "")
                text = str(message.get("text") or "").strip()
                if not text:
                    continue
                handled += 1
                self.handle_command(actor_id=actor_id, text=text, chat=chat)
            except Exception as exc:
                self._audit_runtime_failure(
                    "TELEGRAM_UPDATE_FAILED",
                    exc,
                )
                callback = update.get("callback_query") or {}
                self._safe_answer_callback(
                    str(callback.get("id") or ""),
                    "Aksi gagal diproses. Bot tetap aktif; coba Refresh.",
                    show_alert=True,
                )
            finally:
                if update_id:
                    self._save_state()
        return handled

    def handle_command(
        self,
        *,
        actor_id: str,
        text: str,
        chat: dict[str, Any] | None = None,
    ) -> None:
        command_parts = text.split()
        command = command_parts[0].split("@", 1)[0].lower()
        arguments = command_parts[1:]
        if actor_id not in set(self.config.admin_chat_ids):
            self._handle_public_command(
                actor_id=actor_id,
                command=command,
                chat=chat or {},
            )
            return
        if command in {"/start", "/help"}:
            response = self.help_text()
        elif command in {"/status", "/workers", "/heartbeat"}:
            self.supervise_once(now=self._monotonic())
            self._send_worker_panel(actor_id)
            return
        elif command in {"/goldi_on", "/goldm_on"}:
            name = command[1:].removesuffix("_on")
            response = self.set_desired(name, True)
        elif command in {"/goldi_off", "/goldm_off"}:
            name = command[1:].removesuffix("_off")
            response = self.set_desired(name, False)
        elif command == "/all_on":
            responses = [self.set_desired(name, True) for name in ("goldi", "goldm")]
            response = "\n".join(responses)
        elif command == "/all_off":
            responses = [self.set_desired(name, False) for name in ("goldi", "goldm")]
            response = "\n".join(responses)
        elif command == "/pending":
            response = self._send_pending_cards(actor_id)
        elif command == "/subscribers":
            response = self._send_subscriber_cards(actor_id)
        elif command in {"/approve", "/deny", "/remove"}:
            if not arguments:
                response = f"Gunakan {command} <chat_id>."
            else:
                self._send_subscription_confirmation(
                    actor_id=actor_id,
                    action=command.lstrip("/"),
                    target_id=arguments[0],
                )
                return
        else:
            response = "Perintah tidak dikenal. Gunakan /help."
        self.telegram.send_message(chat_id=actor_id, text=response)

    def handle_callback(self, callback: dict[str, Any]) -> None:
        callback_id = str(callback.get("id") or "")
        actor = callback.get("from") or {}
        actor_id = str(actor.get("id") or "")
        data = str(callback.get("data") or "")
        if actor_id not in set(self.config.admin_chat_ids):
            self._safe_answer_callback(
                callback_id,
                "Tombol ini khusus admin.",
                show_alert=True,
            )
            self._audit("UNAUTHORIZED_CALLBACK", {"actor_id": actor_id})
            return
        if data.startswith("worker:"):
            self._handle_worker_callback(callback)
            return
        parts = data.split(":", 2)
        if (
            len(parts) != 3
            or parts[0] != "goldi_sub"
            or parts[1]
            not in {
                "prompt_approve",
                "prompt_deny",
                "prompt_remove",
                "confirm_approve",
                "confirm_deny",
                "confirm_remove",
                "cancel_approve",
                "cancel_deny",
                "cancel_remove",
            }
        ):
            self._safe_answer_callback(
                callback_id,
                "Aksi tidak dikenal.",
                show_alert=True,
            )
            return
        self._safe_answer_callback(callback_id, "Diproses…")
        message = callback.get("message") or {}
        message_chat = message.get("chat") or {}
        message_chat_id = str(message_chat.get("id") or "")
        message_id = int(message.get("message_id") or 0)
        phase, action = parts[1].split("_", 1)
        target_id = parts[2]
        result = ""
        if phase == "prompt":
            label = self._subscription_action_label(action, target_id)
            text = f"⚠️ KONFIRMASI\n\n{label}\n\nYakin menjalankan tindakan ini?"
            markup = {
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ Yakin",
                            "callback_data": f"goldi_sub:confirm_{action}:{target_id}",
                        },
                        {
                            "text": "↩️ Batal",
                            "callback_data": f"goldi_sub:cancel_{action}:{target_id}",
                        },
                    ]
                ]
            }
            result = "Pilih Yakin atau Batal."
        elif phase == "cancel":
            text, markup = self._subscription_card_for_action(action, target_id)
            result = "Tindakan dibatalkan."
        else:
            result = self._admin_subscription_action(
                command=f"/{action}",
                target_id=target_id,
            )
            icon = "✅" if action in {"approve", "remove"} else "❌"
            text = f"{icon} STATUS PERMINTAAN\n\n{result}"
            markup = {"inline_keyboard": []}
        if message_chat_id and message_id:
            self.telegram.edit_message_text(
                chat_id=message_chat_id,
                message_id=message_id,
                text=text,
                reply_markup=markup,
            )

    def _safe_answer_callback(
        self,
        callback_id: str,
        text: str,
        *,
        show_alert: bool = False,
    ) -> None:
        if not callback_id:
            return
        try:
            self.telegram.answer_callback_query(
                callback_query_id=callback_id,
                text=text[:180],
                show_alert=show_alert,
            )
        except Exception as exc:
            self._audit_runtime_failure("CALLBACK_ANSWER_FAILED", exc)

    def _handle_public_command(
        self,
        *,
        actor_id: str,
        command: str,
        chat: dict[str, Any],
    ) -> None:
        if command == "/start":
            subscribers = set(self._state.get("goldi_subscribers") or [])
            if actor_id in subscribers:
                response = "Akses notifikasi GOLD.i sudah aktif."
            else:
                pending = dict(self._state.get("goldi_pending") or {})
                if actor_id in pending:
                    response = "Permintaan akses GOLD.i masih menunggu keputusan admin."
                else:
                    display_name = str(
                        chat.get("title")
                        or chat.get("username")
                        or " ".join(
                            item
                            for item in (
                                str(chat.get("first_name") or "").strip(),
                                str(chat.get("last_name") or "").strip(),
                            )
                            if item
                        )
                        or "Tanpa nama"
                    )
                    pending[actor_id] = {
                        "requested_at": datetime.now(UTC).isoformat(),
                        "display_name": display_name,
                        "chat_type": str(chat.get("type") or "unknown"),
                    }
                    self._state["goldi_pending"] = pending
                    self._save_state()
                    self._safe_set_subscription_menu(actor_id, "pending")
                    response = "Permintaan akses GOLD.i dikirim ke admin."
                    self._send_goldi_approval_cards(actor_id, pending[actor_id])
                    self._audit(
                        "GOLDI_SUBSCRIPTION_REQUESTED",
                        {"chat_id": actor_id, "display_name": display_name},
                    )
        elif command == "/subscription":
            subscribers = set(self._state.get("goldi_subscribers") or [])
            pending = dict(self._state.get("goldi_pending") or {})
            if actor_id in subscribers:
                response = "Status GOLD.i: APPROVED."
            elif actor_id in pending:
                response = "Status GOLD.i: PENDING."
            else:
                response = "Status GOLD.i: belum terdaftar. Gunakan /start."
        elif command == "/stop":
            subscribers = set(self._state.get("goldi_subscribers") or [])
            subscribers.discard(actor_id)
            pending = dict(self._state.get("goldi_pending") or {})
            pending.pop(actor_id, None)
            subscriber_details = dict(self._state.get("goldi_subscriber_details") or {})
            subscriber_details.pop(actor_id, None)
            self._state["goldi_subscribers"] = sorted(subscribers, key=int)
            self._state["goldi_pending"] = pending
            self._state["goldi_subscriber_details"] = subscriber_details
            self._clear_approval_buttons(actor_id)
            self._safe_set_subscription_menu(actor_id, "unregistered")
            self._save_state()
            response = "Notifikasi GOLD.i dihentikan."
            self._audit("GOLDI_SUBSCRIPTION_STOPPED", {"chat_id": actor_id})
        else:
            response = "Perintah publik: /start, /subscription, /stop."
            self._audit("UNAUTHORIZED_COMMAND", {"actor_id": actor_id})
        self.telegram.send_message(chat_id=actor_id, text=response)

    @staticmethod
    def _approval_markup(target_id: str) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "✅ Approve",
                        "callback_data": f"goldi_sub:prompt_approve:{target_id}",
                    },
                    {
                        "text": "❌ Reject",
                        "callback_data": f"goldi_sub:prompt_deny:{target_id}",
                    },
                ]
            ]
        }

    @staticmethod
    def _subscription_action_label(action: str, target_id: str) -> str:
        labels = {
            "approve": "Setujui akses notifikasi GOLD.i",
            "deny": "Tolak permintaan akses GOLD.i",
            "remove": "Hapus akses subscriber GOLD.i",
        }
        return f"{labels.get(action, 'Aksi tidak dikenal')}\nChat ID: {target_id}"

    def _subscription_card_for_action(
        self,
        action: str,
        target_id: str,
    ) -> tuple[str, dict[str, Any]]:
        if action in {"approve", "deny"}:
            values = dict((self._state.get("goldi_pending") or {}).get(target_id) or {})
            return (
                self._approval_card_text(target_id, values),
                self._approval_markup(target_id),
            )
        values = dict((self._state.get("goldi_subscriber_details") or {}).get(target_id) or {})
        return (
            self._subscriber_card_text(target_id, values),
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "🗑 Hapus akses",
                            "callback_data": f"goldi_sub:prompt_remove:{target_id}",
                        }
                    ]
                ]
            },
        )

    def _send_subscription_confirmation(
        self,
        *,
        actor_id: str,
        action: str,
        target_id: str,
    ) -> None:
        normalized = self._normalize_chat_id(target_id)
        if normalized is None:
            self.telegram.send_message(
                chat_id=actor_id,
                text="Chat ID harus berupa angka positif atau negatif, selain 0.",
            )
            return
        self.telegram.send_message(
            chat_id=actor_id,
            text=(
                "⚠️ KONFIRMASI\n\n"
                f"{self._subscription_action_label(action, normalized)}\n\n"
                "Yakin menjalankan tindakan ini?"
            ),
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ Yakin",
                            "callback_data": f"goldi_sub:confirm_{action}:{normalized}",
                        },
                        {
                            "text": "↩️ Batal",
                            "callback_data": f"goldi_sub:cancel_{action}:{normalized}",
                        },
                    ]
                ]
            },
        )

    def _approval_card_text(
        self,
        target_id: str,
        values: dict[str, Any],
    ) -> str:
        return (
            "🔐 Permintaan akses GOLD.i\n"
            f"Nama: {values.get('display_name', 'Tanpa nama')}\n"
            f"Chat ID: {target_id}\n"
            f"Jenis chat: {values.get('chat_type', 'unknown')}\n"
            f"Waktu: {self._human_time(values.get('requested_at'))}"
        )

    @staticmethod
    def _subscriber_card_text(
        target_id: str,
        values: dict[str, Any],
    ) -> str:
        return (
            "🔔 Subscriber GOLD.i\n"
            f"Nama: {values.get('display_name', 'Tanpa nama')}\n"
            f"Chat ID: {target_id}\n"
            f"Jenis chat: {values.get('chat_type', 'unknown')}"
        )

    def _send_goldi_approval_cards(
        self,
        target_id: str,
        values: dict[str, Any],
        *,
        recipients: tuple[str, ...] | None = None,
    ) -> int:
        text = self._approval_card_text(target_id, values)
        messages = dict(self._state.get("goldi_approval_messages") or {})
        tracked = list(messages.get(target_id) or [])
        sent = 0
        for admin_id in recipients or self.config.admin_chat_ids:
            result = self.telegram.send_message(
                chat_id=admin_id,
                text=text,
                reply_markup=self._approval_markup(target_id),
            )
            message_id = int((result or {}).get("message_id") or 0)
            if message_id > 0:
                tracked.append({"chat_id": str(admin_id), "message_id": message_id})
            sent += 1
        messages[target_id] = tracked[-20:]
        self._state["goldi_approval_messages"] = messages
        self._save_state()
        return sent

    def _send_pending_cards(self, actor_id: str) -> str:
        pending = dict(self._state.get("goldi_pending") or {})
        if not pending:
            return "Tidak ada permintaan GOLD.i pending."
        for target_id, values in sorted(pending.items(), key=lambda item: int(item[0])):
            self._send_goldi_approval_cards(
                target_id,
                dict(values or {}),
                recipients=(actor_id,),
            )
        return f"{len(pending)} permintaan GOLD.i ditampilkan dengan tombol keputusan."

    def _admin_subscription_action(self, *, command: str, target_id: str) -> str:
        normalized = self._normalize_chat_id(target_id)
        if normalized is None:
            return "Chat ID harus berupa angka positif atau negatif, selain 0."
        target_id = normalized
        pending = dict(self._state.get("goldi_pending") or {})
        subscribers = set(self._state.get("goldi_subscribers") or [])
        subscriber_details = dict(self._state.get("goldi_subscriber_details") or {})
        if command == "/approve":
            request_details = dict(pending.pop(target_id, {}) or {})
            subscribers.add(target_id)
            subscriber_details[target_id] = request_details
            result = f"GOLD.i subscriber APPROVED: {target_id}"
            target_message = "Akses notifikasi entry GOLD.i telah disetujui."
            event = "GOLDI_SUBSCRIPTION_APPROVED"
        elif command == "/deny":
            pending.pop(target_id, None)
            subscribers.discard(target_id)
            subscriber_details.pop(target_id, None)
            result = f"Permintaan GOLD.i ditolak: {target_id}"
            target_message = "Permintaan akses notifikasi GOLD.i ditolak."
            event = "GOLDI_SUBSCRIPTION_DENIED"
        else:
            pending.pop(target_id, None)
            subscribers.discard(target_id)
            subscriber_details.pop(target_id, None)
            result = f"GOLD.i subscriber dihapus: {target_id}"
            target_message = "Akses notifikasi GOLD.i dihentikan oleh admin."
            event = "GOLDI_SUBSCRIPTION_REMOVED"
        self._state["goldi_pending"] = pending
        self._state["goldi_subscribers"] = sorted(subscribers, key=int)
        self._state["goldi_subscriber_details"] = subscriber_details
        self._clear_approval_buttons(target_id)
        self._safe_set_subscription_menu(
            target_id,
            "approved" if command == "/approve" else "unregistered",
        )
        self._save_state()
        self.telegram.send_message(chat_id=target_id, text=target_message)
        self._audit(event, {"chat_id": target_id})
        return result

    @staticmethod
    def _normalize_chat_id(value: object) -> str | None:
        text = str(value).strip()
        if not text or not text.isascii():
            return None
        digits = text[1:] if text.startswith("-") else text
        if not digits.isdecimal():
            return None
        number = int(text)
        return str(number) if number != 0 else None

    def _clear_approval_buttons(self, target_id: str) -> None:
        messages = dict(self._state.get("goldi_approval_messages") or {})
        tracked = list(messages.pop(target_id, []) or [])
        for item in tracked:
            try:
                self.telegram.edit_message_reply_markup(
                    chat_id=str(item["chat_id"]),
                    message_id=int(item["message_id"]),
                    reply_markup={"inline_keyboard": []},
                )
            except Exception as exc:
                self._audit(
                    "GOLDI_APPROVAL_BUTTON_CLEAR_FAILED",
                    {
                        "target_id": target_id,
                        "chat_id": item.get("chat_id"),
                        "message_id": item.get("message_id"),
                        "error": type(exc).__name__,
                    },
                )
        self._state["goldi_approval_messages"] = messages

    @staticmethod
    def _human_time(value: object) -> str:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value or "-")
        return parsed.astimezone().strftime("%d %b %Y • %H:%M %Z")

    def pending_text(self) -> str:
        pending = dict(self._state.get("goldi_pending") or {})
        if not pending:
            return "Tidak ada permintaan GOLD.i pending."
        return "GOLD.i PENDING\n" + "\n".join(
            f"{chat_id} • {values.get('display_name', 'Tanpa nama')} • "
            f"{self._human_time(values.get('requested_at', '-'))}"
            for chat_id, values in sorted(pending.items(), key=lambda item: int(item[0]))
        )

    def subscribers_text(self) -> str:
        subscribers = list(self._state.get("goldi_subscribers") or [])
        if not subscribers:
            return "Belum ada subscriber GOLD.i."
        return "GOLD.i SUBSCRIBERS\n" + "\n".join(
            sorted((str(item) for item in subscribers), key=int)
        )

    def _send_subscriber_cards(self, actor_id: str) -> str:
        subscribers = sorted(
            (str(item) for item in (self._state.get("goldi_subscribers") or [])),
            key=int,
        )
        if not subscribers:
            return "Belum ada subscriber GOLD.i."
        details = dict(self._state.get("goldi_subscriber_details") or {})
        for target_id in subscribers:
            values = dict(details.get(target_id) or {})
            self.telegram.send_message(
                chat_id=actor_id,
                text=self._subscriber_card_text(target_id, values),
                reply_markup={
                    "inline_keyboard": [
                        [
                            {
                                "text": "🗑 Hapus akses",
                                "callback_data": f"goldi_sub:prompt_remove:{target_id}",
                            }
                        ]
                    ]
                },
            )
        return f"{len(subscribers)} subscriber GOLD.i ditampilkan."

    def _worker_panel_markup(self) -> dict[str, Any]:
        desired = dict(self._state.get("desired") or {})
        goldi_on = bool(desired.get("goldi", False))
        goldm_on = bool(desired.get("goldm", False))
        rows = [
            [
                {
                    "text": ("⏹ Matikan GOLD.i DEMO" if goldi_on else "▶️ Hidupkan GOLD.i DEMO"),
                    "callback_data": (
                        "worker:prompt:goldi_off" if goldi_on else "worker:prompt:goldi_on"
                    ),
                }
            ],
            [
                {
                    "text": ("⏹ Matikan GOLDm REAL" if goldm_on else "🔴 Hidupkan GOLDm REAL"),
                    "callback_data": (
                        "worker:prompt:goldm_off" if goldm_on else "worker:prompt:goldm_on"
                    ),
                }
            ],
        ]
        if goldi_on or goldm_on:
            rows.append(
                [
                    {
                        "text": "⏹ Matikan Semua",
                        "callback_data": "worker:prompt:all_off",
                    }
                ]
            )
        rows.append([{"text": "🔄 Refresh", "callback_data": "worker:refresh"}])
        return {"inline_keyboard": rows}

    def _worker_panel_text(self) -> str:
        desired = dict(self._state.get("desired") or {})
        lines = ["🎛 KONTROL WORKER GOLD", ""]
        for name, label in (("goldi", "GOLD.i DEMO"), ("goldm", "GOLDm REAL")):
            spec = self.config.workers[name]
            process = self._children.get(name)
            running = process is not None and process.poll() is None
            enabled = bool(desired.get(name, spec.enabled_on_first_boot))
            health = self._read_health(spec.health_path)
            state_icon = "🟢" if enabled and running else "🟡" if enabled else "⚫"
            lines.append(
                f"{state_icon} {label}: "
                f"{'ON' if enabled else 'OFF'} • "
                f"{'RUNNING' if running else 'STOPPED'}"
            )
            if health.get("login"):
                lines.append(
                    f"   Akun {health['login']} • saldo {float(health.get('balance') or 0):.2f} USD"
                )
            if health.get("updated_at"):
                lines.append(f"   Update: {self._human_time(health['updated_at'])}")
        lines.extend(
            [
                "",
                "Tombol selalu menunjukkan aksi berikutnya.",
                "GOLDm adalah akun REAL.",
            ]
        )
        return "\n".join(lines)

    def _send_worker_panel(self, chat_id: str) -> None:
        self.telegram.send_message(
            chat_id=chat_id,
            text=self._worker_panel_text(),
            reply_markup=self._worker_panel_markup(),
        )

    def _handle_worker_callback(self, callback: dict[str, Any]) -> None:
        callback_id = str(callback.get("id") or "")
        self._safe_answer_callback(callback_id, "Diproses…")
        data = str(callback.get("data") or "")
        parts = data.split(":")
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "")
        message_id = int(message.get("message_id") or 0)
        result = "Status diperbarui."
        if parts == ["worker", "refresh"]:
            text = self._worker_panel_text()
            markup = self._worker_panel_markup()
        elif len(parts) == 3 and parts[0] == "worker" and parts[1] == "prompt":
            action = parts[2]
            label = self._worker_action_label(action)
            text = f"⚠️ KONFIRMASI\n\n{label}\n\nYakin menjalankan tindakan ini?"
            markup = {
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ Yakin",
                            "callback_data": f"worker:confirm:{action}",
                        },
                        {
                            "text": "↩️ Batal",
                            "callback_data": f"worker:cancel:{action}",
                        },
                    ]
                ]
            }
            result = "Pilih Yakin atau Batal."
        elif len(parts) == 3 and parts[0] == "worker" and parts[1] == "cancel":
            text = self._worker_panel_text()
            markup = self._worker_panel_markup()
            result = "Tindakan dibatalkan."
        elif len(parts) == 3 and parts[0] == "worker" and parts[1] == "confirm":
            result = self._execute_worker_action(parts[2])
            text = f"✅ STATUS DIPERBARUI\n{result}\n\n{self._worker_panel_text()}"
            markup = self._worker_panel_markup()
        else:
            text = self._worker_panel_text()
            markup = self._worker_panel_markup()
            result = "Aksi worker tidak dikenal."
        if chat_id and message_id:
            self.telegram.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=markup,
            )

    @staticmethod
    def _worker_action_label(action: str) -> str:
        labels = {
            "goldi_on": "Hidupkan worker GOLD.i DEMO",
            "goldi_off": "Matikan worker GOLD.i DEMO",
            "goldm_on": "Hidupkan worker GOLDm REAL",
            "goldm_off": "Matikan worker GOLDm REAL",
            "all_off": "Matikan semua worker",
        }
        return labels.get(action, "Tindakan worker tidak dikenal")

    def _execute_worker_action(self, action: str) -> str:
        if action == "goldi_on":
            return self.set_desired("goldi", True, notify_worker=False)
        if action == "goldi_off":
            return self.set_desired("goldi", False, notify_worker=False)
        if action == "goldm_on":
            return self.set_desired("goldm", True, notify_worker=False)
        if action == "goldm_off":
            return self.set_desired("goldm", False, notify_worker=False)
        if action == "all_off":
            return "\n".join(
                self.set_desired(name, False, notify_worker=False) for name in ("goldi", "goldm")
            )
        return "Aksi worker tidak dikenal."

    def set_desired(
        self,
        name: str,
        enabled: bool,
        *,
        notify_worker: bool = True,
    ) -> str:
        self._require_worker(name)
        desired = dict(self._state.get("desired") or {})
        desired[name] = enabled
        self._state["desired"] = desired
        self._save_state()
        if enabled:
            result = self.start_worker(name, notify=notify_worker)
        else:
            result = self.stop_worker(name, notify=False)
        self._audit("DESIRED_CHANGED", {"worker": name, "enabled": enabled})
        return result

    def start_worker(self, name: str, *, notify: bool = True) -> str:
        spec = self._require_worker(name)
        current = self._children.get(name)
        if current is not None and current.poll() is None:
            return f"{name}=ALREADY_RUNNING pid={current.pid}"
        spec.log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = spec.log_path.open("a", encoding="utf-8", buffering=1)
        command = [
            str(self.config.python_executable),
            str(ROOT / "scripts" / "run-final-portfolio-worker.py"),
            "--config",
            str(spec.config_path),
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = self._popen_factory(
                command,
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        except Exception:
            log_handle.close()
            raise
        self._children[name] = process
        self._logs[name] = log_handle
        self._next_restart.pop(name, None)
        self._audit("WORKER_STARTED", {"worker": name, "pid": process.pid})
        if notify:
            self._send_all(f"WORKER STARTED\n{name}=RUNNING pid={process.pid}")
        return f"{name}=STARTED pid={process.pid}"

    def stop_worker(self, name: str, *, notify: bool = True) -> str:
        self._require_worker(name)
        process = self._children.pop(name, None)
        if process is None or process.poll() is not None:
            self._close_log(name)
            return f"{name}=STOPPED"
        process.terminate()
        try:
            process.wait(timeout=self.config.shutdown_grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        self._close_log(name)
        self._audit("WORKER_STOPPED", {"worker": name, "pid": process.pid})
        if notify:
            self._send_all(f"WORKER STOPPED\n{name}=STOPPED")
        return f"{name}=STOPPED"

    def supervise_once(self, *, now: float | None = None) -> None:
        current_time = self._monotonic() if now is None else now
        desired = dict(self._state.get("desired") or {})
        for name, spec in self.config.workers.items():
            process = self._children.get(name)
            enabled = bool(desired.get(name, spec.enabled_on_first_boot))
            if not enabled:
                if process is not None and process.poll() is None:
                    self.stop_worker(name)
                continue
            if process is None or process.poll() is not None:
                if process is not None:
                    exit_code = process.poll()
                    self._close_log(name)
                    self._children.pop(name, None)
                    problem = f"process exited code={exit_code}"
                    self._report_problem(name, problem)
                    failures = self._failure_counts.get(name, 0) + 1
                    self._failure_counts[name] = failures
                    restart_delay = min(
                        self.config.restart_delay_seconds * (2 ** (failures - 1)),
                        300.0,
                    )
                    self._next_restart.setdefault(name, current_time + restart_delay)
                if current_time >= self._next_restart.get(name, 0.0):
                    self.start_worker(
                        name,
                        notify=self._failure_counts.get(name, 0) == 0,
                    )
                continue
            health = self._read_health(spec.health_path)
            problem = self._health_problem(health)
            if problem:
                self._report_problem(name, problem)
            else:
                self._reported_problem.pop(name, None)
                self._failure_counts.pop(name, None)

    def status_text(self, *, title: str = "WORKER STATUS") -> str:
        lines = [self.config.orchestrator_id, title]
        desired = dict(self._state.get("desired") or {})
        for name, spec in self.config.workers.items():
            process = self._children.get(name)
            running = process is not None and process.poll() is None
            health = self._read_health(spec.health_path)
            health_status = str(health.get("status") or "NO_HEALTH")
            updated = str(health.get("updated_at") or "-")
            account = ""
            if health.get("login"):
                account = (
                    f" login={health['login']} balance={float(health.get('balance') or 0):.2f}"
                    f" equity={float(health.get('equity') or 0):.2f}"
                )
            lines.append(
                f"{name}: desired={'ON' if desired.get(name, spec.enabled_on_first_boot) else 'OFF'} "
                f"process={'RUNNING' if running else 'STOPPED'} health={health_status} "
                f"updated={updated}{account}"
            )
        return "\n".join(lines)

    @staticmethod
    def help_text() -> str:
        return (
            "GOLD worker control (admin only)\n"
            "/workers atau /status - status lengkap\n"
            "/goldi_on /goldi_off - entry demo GOLD.i\n"
            "/goldm_on /goldm_off - trading GOLDm real\n"
            "/all_on /all_off - kedua worker\n"
            "/pending /subscribers - audience GOLD.i\n"
            "/approve ID /deny ID /remove ID - kelola GOLD.i\n"
            "/heartbeat - buka panel kontrol worker"
        )

    def send_shutdown_notice(self, detail: str = "Windows shutdown event received") -> None:
        self._send_all(f"{self.config.orchestrator_id} SHUTDOWN\n{detail}")
        self._audit("SHUTDOWN_NOTICE", {"detail": detail})

    def _desired_summary(self) -> str:
        desired = dict(self._state.get("desired") or {})
        return ",".join(
            f"{name}={'ON' if desired.get(name, spec.enabled_on_first_boot) else 'OFF'}"
            for name, spec in self.config.workers.items()
        )

    def _load_state(self) -> dict[str, Any]:
        if self.config.state_path.exists():
            payload = json.loads(self.config.state_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("goldi_pending", {})
                payload.setdefault("goldi_subscribers", [])
                payload.setdefault("goldi_subscriber_details", {})
                payload.setdefault("goldi_approval_messages", {})
                return payload
        return {
            "telegram_offset": 0,
            "goldi_pending": {},
            "goldi_subscribers": [],
            "goldi_subscriber_details": {},
            "goldi_approval_messages": {},
            "desired": {
                name: spec.enabled_on_first_boot for name, spec in self.config.workers.items()
            },
        }

    def _save_state(self) -> None:
        self.config.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.config.state_path)

    def _audit(self, event: str, fields: dict[str, Any]) -> None:
        self.config.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._rotate_audit()
        payload = {
            "time": datetime.now(UTC).isoformat(),
            "event": event,
            **fields,
        }
        with self.config.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")

    def _rotate_audit(self) -> None:
        path = self.config.audit_path
        try:
            if path.stat().st_size < AUDIT_MAX_BYTES:
                return
        except FileNotFoundError:
            return
        oldest = Path(f"{path}.{AUDIT_BACKUPS}")
        if oldest.exists():
            oldest.unlink()
        for index in range(AUDIT_BACKUPS - 1, 0, -1):
            source = Path(f"{path}.{index}")
            if source.exists():
                os.replace(source, Path(f"{path}.{index + 1}"))
        os.replace(path, Path(f"{path}.1"))

    def _send_all(self, text: str) -> None:
        for chat_id in self.config.admin_chat_ids:
            self.telegram.send_message(chat_id=chat_id, text=text)

    def _require_worker(self, name: str) -> WorkerSpec:
        normalized = name.strip().lower()
        if normalized not in self.config.workers:
            raise ValueError(f"unknown worker: {name}")
        return self.config.workers[normalized]

    def _close_log(self, name: str) -> None:
        handle = self._logs.pop(name, None)
        if handle is not None:
            handle.close()

    @staticmethod
    def _read_health(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _health_problem(self, health: dict[str, Any]) -> str:
        if not health:
            return "health file missing"
        status = str(health.get("status") or "").upper()
        if status == "ERROR":
            return f"worker health ERROR: {health.get('detail', '-')}"
        raw_updated = str(health.get("updated_at") or "")
        try:
            updated = datetime.fromisoformat(raw_updated)
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - updated.astimezone(UTC)).total_seconds()
        except ValueError:
            return "invalid health timestamp"
        if age > self.config.health_stale_seconds:
            return f"health heartbeat stale age={int(age)}s"
        return ""

    def _report_problem(self, name: str, problem: str) -> None:
        if self._reported_problem.get(name) == problem:
            return
        self._reported_problem[name] = problem
        self._audit("WORKER_PROBLEM", {"worker": name, "problem": problem})
        self._send_all(f"WORKER ALERT\n{name}: {problem}")

    def _install_signal_handlers(self) -> None:
        def stop_handler(_signum, _frame) -> None:
            self.request_stop()

        for signal_name in ("SIGINT", "SIGTERM"):
            signal_value = getattr(signal, signal_name, None)
            if signal_value is not None:
                signal.signal(signal_value, stop_handler)
