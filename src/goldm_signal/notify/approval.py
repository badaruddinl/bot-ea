from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.database import SignalStore
from .telegram import TelegramBotClient


_DECISION_PATTERN = re.compile(r"^(approve|reject):(-?\d+)$")


class TelegramApprovalWorker:
    """Process subscription commands and enforce administrator approval."""

    def __init__(
        self,
        *,
        store: SignalStore,
        client: TelegramBotClient,
        admin_chat_ids: set[str | int],
    ) -> None:
        normalized_admins = {str(chat_id) for chat_id in admin_chat_ids if str(chat_id)}
        if not normalized_admins:
            raise ValueError("At least one Telegram administrator chat ID is required")
        self.store = store
        self.client = client
        self.admin_chat_ids = normalized_admins
        for chat_id in self.admin_chat_ids:
            self.store.ensure_telegram_admin(chat_id)

    def run_once(self, *, timeout: int = 20) -> int:
        updates = self.client.get_updates(
            offset=self.store.telegram_update_offset(), timeout=timeout
        )
        processed = 0
        for update in updates:
            self.process_update(update)
            update_id = int(update["update_id"])
            self.store.set_telegram_update_offset(update_id + 1)
            processed += 1
        return processed

    def run_forever(self, *, timeout: int = 20, retry_delay_seconds: float = 3.0) -> None:
        while True:
            try:
                self.run_once(timeout=timeout)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"Telegram approval polling failed: {exc}", flush=True)
                time.sleep(retry_delay_seconds)

    def process_update(self, update: dict[str, Any]) -> None:
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            self._handle_callback(callback)
            return
        message = update.get("message")
        if isinstance(message, dict):
            self._handle_message(message)

    def _handle_message(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        if not chat_id:
            return
        text = str(message.get("text", "")).strip()
        command, _, argument = text.partition(" ")
        command = command.split("@", 1)[0].lower()
        argument = argument.strip()

        if command == "/start":
            self._request_access(chat)
        elif command == "/status":
            self._send_status(chat_id)
        elif command == "/snapshot":
            self._send_snapshot(chat_id)
        elif command == "/signal":
            self._send_event_snapshot(
                chat_id,
                title="🔔 SNAPSHOT • SINYAL ENTRY TERAKHIR",
                event_types=("SNIPER_SIGNAL", "ENTRY_READY"),
            )
        elif command == "/watch":
            self._send_event_snapshot(
                chat_id,
                title="🟡 SNAPSHOT • WATCH TERAKHIR",
                event_types=(
                    "SNIPER_EARLY_CANDIDATE",
                    "SNIPER_EARLY_PROMOTED",
                    "SNIPER_EARLY_CANCELLED",
                ),
            )
        elif command == "/history":
            self._send_history(chat_id)
        elif command == "/health":
            self._send_health(chat_id)
        elif command == "/stop":
            self._unsubscribe(chat_id)
        elif command in {"/approve", "/reject"}:
            self._admin_command(chat_id, command[1:].upper(), argument)
        elif command == "/pending":
            self._list_subscribers(chat_id, "PENDING")
        elif command == "/subscribers":
            self._list_subscribers(chat_id, "APPROVED")
        elif text.startswith("/"):
            self.client.send_message(
                chat_id=chat_id,
                text=(
                    "Perintah tersedia:\n"
                    "/snapshot — ringkasan bot\n"
                    "/signal — sinyal entry terakhir\n"
                    "/watch — kandidat terakhir\n"
                    "/history — 5 event terbaru\n"
                    "/health — kesehatan worker\n"
                    "/status — status akses\n"
                    "/stop — hentikan notifikasi"
                ),
            )

    def _request_access(self, chat: dict[str, Any]) -> None:
        chat_id = str(chat["id"])
        if chat_id in self.admin_chat_ids:
            self.store.ensure_telegram_admin(chat_id)
            self.client.send_message(
                chat_id=chat_id,
                text="✅ Akses admin aktif. Anda menerima seluruh notifikasi GOLD.i#.",
            )
            return

        subscriber, needs_review = self.store.request_telegram_subscription(
            chat_id=chat_id,
            username=str(chat.get("username") or ""),
            first_name=str(chat.get("first_name") or ""),
            last_name=str(chat.get("last_name") or ""),
        )
        if subscriber["status"] == "APPROVED":
            self.client.send_message(
                chat_id=chat_id,
                text="✅ Akses Anda sudah disetujui. Notifikasi GOLD.i# aktif.",
            )
            return

        self.client.send_message(
            chat_id=chat_id,
            text=(
                "⏳ Permintaan diterima dan menunggu persetujuan admin. "
                "Anda belum akan menerima notifikasi trading."
            ),
        )
        if needs_review:
            label = self._subscriber_label(subscriber)
            keyboard = {
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ Approve",
                            "callback_data": f"approve:{chat_id}",
                        },
                        {
                            "text": "❌ Reject",
                            "callback_data": f"reject:{chat_id}",
                        },
                    ]
                ]
            }
            for admin_id in self.admin_chat_ids:
                self.client.send_message(
                    chat_id=admin_id,
                    text=f"🔐 Permintaan akses baru\n{label}\nChat ID: {chat_id}",
                    reply_markup=keyboard,
                )

    def _handle_callback(self, callback: dict[str, Any]) -> None:
        callback_id = str(callback.get("id", ""))
        actor_id = str((callback.get("from") or {}).get("id", ""))
        data = str(callback.get("data", ""))
        if actor_id not in self.admin_chat_ids:
            self.client.answer_callback_query(
                callback_query_id=callback_id,
                text="Anda tidak berwenang memberikan approval.",
                show_alert=True,
            )
            return
        match = _DECISION_PATTERN.fullmatch(data)
        if match is None:
            self.client.answer_callback_query(
                callback_query_id=callback_id,
                text="Permintaan tidak valid.",
                show_alert=True,
            )
            return
        status = "APPROVED" if match.group(1) == "approve" else "REJECTED"
        target_id = match.group(2)
        changed = self._decide(actor_id=actor_id, target_id=target_id, status=status)
        self.client.answer_callback_query(
            callback_query_id=callback_id,
            text="Akses diperbarui." if changed else "Pengguna tidak ditemukan.",
            show_alert=not changed,
        )

    def _admin_command(self, actor_id: str, status: str, target_id: str) -> None:
        if actor_id not in self.admin_chat_ids:
            self.client.send_message(chat_id=actor_id, text="⛔ Perintah khusus admin.")
            return
        if not re.fullmatch(r"-?\d+", target_id):
            command = status.lower()
            self.client.send_message(
                chat_id=actor_id, text=f"Format: /{command} CHAT_ID"
            )
            return
        changed = self._decide(actor_id=actor_id, target_id=target_id, status=status)
        if not changed:
            self.client.send_message(
                chat_id=actor_id, text=f"Pengguna {target_id} tidak ditemukan."
            )

    def _decide(self, *, actor_id: str, target_id: str, status: str) -> bool:
        changed = self.store.set_telegram_subscription_status(
            chat_id=target_id, status=status, decided_by=actor_id
        )
        if not changed:
            return False
        if status == "APPROVED":
            target_text = "✅ Akses disetujui. Notifikasi GOLD.i# sekarang aktif."
            admin_text = f"✅ Chat {target_id} telah di-approve."
        else:
            target_text = "❌ Permintaan akses ditolak. Anda tidak akan menerima notifikasi."
            admin_text = f"❌ Chat {target_id} telah ditolak."
        self.client.send_message(chat_id=target_id, text=target_text)
        self.client.send_message(chat_id=actor_id, text=admin_text)
        return True

    def _send_status(self, chat_id: str) -> None:
        subscriber = self.store.telegram_subscriber(chat_id)
        if subscriber is None:
            text = "Belum terdaftar. Kirim /start untuk meminta akses."
        elif subscriber["status"] == "APPROVED":
            text = "✅ APPROVED — notifikasi aktif."
        elif subscriber["status"] == "PENDING":
            text = "⏳ PENDING — menunggu persetujuan admin."
        else:
            text = "❌ REJECTED — notifikasi tidak aktif. Kirim /start untuk meminta ulang."
        self.client.send_message(chat_id=chat_id, text=text)

    def _unsubscribe(self, chat_id: str) -> None:
        if chat_id in self.admin_chat_ids:
            self.client.send_message(
                chat_id=chat_id, text="Akses admin utama tidak dapat dihentikan lewat /stop."
            )
            return
        changed = self.store.set_telegram_subscription_status(
            chat_id=chat_id, status="REJECTED", decided_by=chat_id
        )
        text = (
            "🔕 Notifikasi dinonaktifkan. Kirim /start jika ingin meminta akses lagi."
            if changed
            else "Belum terdaftar."
        )
        self.client.send_message(chat_id=chat_id, text=text)

    def _send_snapshot(self, chat_id: str) -> None:
        if not self._require_approved(chat_id):
            return
        health = self.store.notification_health()
        latest = self.store.latest_event()
        lines = [
            "📸 SNAPSHOT GOLD.i#",
            f"🕒 {_wib_now()}",
            "",
            "🟢 WORKER TELEGRAM",
            "Aktif — bot berhasil merespons command ini.",
            "",
            "📡 BRIDGE MT5",
            f"• Aktivitas log terakhir: {_format_wib_iso(health['last_log_at'])}",
            f"• Antrean belum terkirim: {health['pending_count']}",
            f"• Event gagal: {health['failed_count']}",
        ]
        if latest is not None:
            lines.extend(
                [
                    "",
                    "📣 EVENT TERAKHIR",
                    f"• Tipe: {_display_event_type(str(latest['event_type']))}",
                    f"• Instrumen: {latest['symbol']} • {latest['side']}",
                    f"• Waktu: {_format_wib_iso(latest['breakout_at'])}",
                ]
            )
        lines.extend(
            [
                "",
                "Gunakan /signal, /watch, /history, atau /health untuk detail.",
            ]
        )
        self.client.send_message(chat_id=chat_id, text="\n".join(lines))

    def _send_event_snapshot(
        self, chat_id: str, *, title: str, event_types: tuple[str, ...]
    ) -> None:
        if not self._require_approved(chat_id):
            return
        event = self.store.latest_event(event_types=event_types)
        if event is None:
            self.client.send_message(
                chat_id=chat_id,
                text=f"{title}\n\nBelum ada data yang tersedia.",
            )
            return
        body = str(event["payload"].get("text", "")).strip()
        self.client.send_message(
            chat_id=chat_id,
            text=(
                f"{title}\n"
                "ℹ️ Ini permintaan snapshot, bukan sinyal baru.\n\n"
                f"{body}"
            ),
        )

    def _send_history(self, chat_id: str) -> None:
        if not self._require_approved(chat_id):
            return
        events = self.store.recent_events(limit=5)
        lines = ["🗂 SNAPSHOT • 5 EVENT TERBARU", ""]
        if not events:
            lines.append("Belum ada event yang tersedia.")
        else:
            for index, event in enumerate(events, start=1):
                lines.extend(
                    [
                        f"{index}. {_display_event_type(str(event['event_type']))}",
                        f"   {event['symbol']} • {event['side']}",
                        f"   {_format_wib_iso(event['breakout_at'])}",
                    ]
                )
        self.client.send_message(chat_id=chat_id, text="\n".join(lines))

    def _send_health(self, chat_id: str) -> None:
        if not self._require_approved(chat_id):
            return
        health = self.store.notification_health()
        status = "🟢 SEHAT" if health["failed_count"] == 0 else "🟠 PERLU DIPERIKSA"
        self.client.send_message(
            chat_id=chat_id,
            text="\n".join(
                [
                    "🩺 HEALTH SNAPSHOT",
                    f"Status: {status}",
                    f"Waktu cek: {_wib_now()}",
                    "",
                    f"• Total event: {health['total_count']}",
                    f"• Antrean: {health['pending_count']}",
                    f"• Gagal: {health['failed_count']}",
                    f"• Log MT5 terakhir: {_format_wib_iso(health['last_log_at'])}",
                    f"• Telegram terkirim terakhir: {_format_wib_iso(health['last_sent_at'])}",
                ]
            ),
        )

    def _require_approved(self, chat_id: str) -> bool:
        subscriber = self.store.telegram_subscriber(chat_id)
        if subscriber is not None and subscriber["status"] == "APPROVED":
            return True
        self.client.send_message(
            chat_id=chat_id,
            text="⛔ Snapshot hanya tersedia untuk subscriber APPROVED. Kirim /status untuk mengecek akses.",
        )
        return False

    def _list_subscribers(self, actor_id: str, status: str) -> None:
        if actor_id not in self.admin_chat_ids:
            self.client.send_message(chat_id=actor_id, text="⛔ Perintah khusus admin.")
            return
        subscribers = self.store.telegram_subscribers(status=status)
        if not subscribers:
            self.client.send_message(chat_id=actor_id, text=f"Tidak ada subscriber {status}.")
            return
        lines = [f"{status} ({len(subscribers)}):"]
        lines.extend(
            f"• {self._subscriber_label(item)} — {item['chat_id']}"
            for item in subscribers[:50]
        )
        if len(subscribers) > 50:
            lines.append(f"… dan {len(subscribers) - 50} lainnya")
        self.client.send_message(chat_id=actor_id, text="\n".join(lines))

    @staticmethod
    def _subscriber_label(subscriber: dict[str, Any]) -> str:
        username = str(subscriber.get("username") or "")
        if username:
            return f"@{username}"
        full_name = " ".join(
            part
            for part in (
                str(subscriber.get("first_name") or ""),
                str(subscriber.get("last_name") or ""),
            )
            if part
        )
        return full_name or "Tanpa nama"


_WIB = timezone(timedelta(hours=7))


def _wib_now() -> str:
    return datetime.now(timezone.utc).astimezone(_WIB).strftime("%d %b %Y • %H:%M WIB")


def _format_wib_iso(value: Any) -> str:
    if not value:
        return "belum tersedia"
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_WIB).strftime("%d %b %Y • %H:%M WIB")


def _display_event_type(value: str) -> str:
    labels = {
        "SNIPER_EARLY_CANDIDATE": "WATCH ONLY",
        "SNIPER_EARLY_PROMOTED": "WATCH PROMOTED",
        "SNIPER_EARLY_CANCELLED": "WATCH CANCELLED",
        "SNIPER_SIGNAL": "ENTRY READY",
        "ENTRY_READY": "ENTRY READY",
    }
    return labels.get(value, value.replace("_", " "))
