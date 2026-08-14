from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.database import SignalStore
from .telegram import TelegramBotClient
from .trade_lifecycle import TradeLifecycleConfig


_DECISION_PATTERN = re.compile(r"^(approve|reject):(-?\d+)$")


class TelegramApprovalWorker:
    """Process subscription commands and enforce administrator approval."""

    def __init__(
        self,
        *,
        store: SignalStore,
        client: TelegramBotClient,
        admin_chat_ids: set[str | int],
        account_probe: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        normalized_admins = {str(chat_id) for chat_id in admin_chat_ids if str(chat_id)}
        if not normalized_admins:
            raise ValueError("At least one Telegram administrator chat ID is required")
        self.store = store
        self.client = client
        self.admin_chat_ids = normalized_admins
        self.account_probe = account_probe
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
        elif command in {"/control", "/config"}:
            self._send_control(chat_id)
        elif command == "/account":
            self._send_account(chat_id)
        elif command == "/users":
            self._list_subscribers(chat_id, "APPROVED")
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
                    "/control — kontrol akun, entry, dan risiko (admin)\n"
                    "/account — akun MT5 aktif (admin)\n"
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
        if data.startswith("ctl:"):
            self._handle_control_callback(
                callback_id=callback_id,
                actor_id=actor_id,
                data=data,
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
        if status == "REJECTED" and target_id in self.admin_chat_ids:
            self.client.answer_callback_query(
                callback_query_id=callback_id,
                text="Root admin tidak dapat dicabut dari panel.",
                show_alert=True,
            )
            return
        changed = self._decide(actor_id=actor_id, target_id=target_id, status=status)
        self.client.answer_callback_query(
            callback_query_id=callback_id,
            text="Akses diperbarui." if changed else "Pengguna tidak ditemukan.",
            show_alert=not changed,
        )

    def _send_control(self, actor_id: str) -> None:
        if not self._require_admin(actor_id):
            return
        config = TradeLifecycleConfig.from_sources(self.store)
        self.client.send_message(
            chat_id=actor_id,
            text=self._control_summary(config),
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": "🔄 Refresh", "callback_data": "ctl:refresh"},
                        {"text": "🏦 Akun MT5", "callback_data": "ctl:account"},
                    ],
                    [
                        {"text": "⏸ Matikan Entry", "callback_data": "ctl:mode:off"},
                    ],
                    [
                        {"text": "🧪 Aktif Demo", "callback_data": "ctl:mode:demo"},
                        {"text": "🔴 Aktif Real", "callback_data": "ctl:mode:live"},
                    ],
                    [
                        {"text": "Risk 0.25%", "callback_data": "ctl:risk:025"},
                        {"text": "Risk 0.50%", "callback_data": "ctl:risk:050"},
                        {"text": "Risk 1.00%", "callback_data": "ctl:risk:100"},
                    ],
                    [
                        {"text": "🔗 Kunci Akun Ini", "callback_data": "ctl:bind"},
                        {"text": "👥 Users", "callback_data": "ctl:users"},
                        {"text": "⏳ Pending", "callback_data": "ctl:pending"},
                    ],
                ]
            },
        )

    def _send_account(self, actor_id: str) -> None:
        if not self._require_admin(actor_id):
            return
        account = self._current_account(actor_id)
        if account is None:
            return
        account_type = (
            "REAL"
            if account.get("is_live") is True
            else "DEMO" if account.get("is_live") is False else "UNKNOWN"
        )
        self.client.send_message(
            chat_id=actor_id,
            text="\n".join(
                [
                    "🏦 AKUN MT5 AKTIF",
                    f"• Login: {account.get('login') or '-'}",
                    f"• Server: {account.get('server') or '-'}",
                    f"• Broker: {account.get('broker') or '-'}",
                    f"• Tipe: {account_type}",
                    f"• Trading terminal: {'aktif' if account.get('trade_allowed') else 'tidak aktif'}",
                    "",
                    "Password MT5 tidak pernah dibaca atau disimpan oleh Telegram.",
                ]
            ),
        )

    def _handle_control_callback(
        self, *, callback_id: str, actor_id: str, data: str
    ) -> None:
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        if action == "refresh":
            self._send_control(actor_id)
            self._answer_control(callback_id, "Status diperbarui.")
            return
        if action == "account":
            self._send_account(actor_id)
            self._answer_control(callback_id, "Akun diperiksa.")
            return
        if action == "users":
            self._list_subscribers(actor_id, "APPROVED")
            self._answer_control(callback_id, "Daftar user ditampilkan.")
            return
        if action == "pending":
            self._list_subscribers(actor_id, "PENDING")
            self._answer_control(callback_id, "Daftar pending ditampilkan.")
            return
        if action == "confirm" and len(parts) == 3:
            self._confirm_control_action(callback_id, actor_id, parts[2])
            return
        if action == "cancel" and len(parts) == 3:
            decided = self.store.decide_admin_action(
                token=parts[2], actor_id=actor_id, confirm=False
            )
            status = str((decided or {}).get("status", "NOT_FOUND"))
            self._answer_control(
                callback_id,
                (
                    "Perubahan dibatalkan."
                    if status == "CANCELLED"
                    else f"Pembatalan tidak berlaku: {status}."
                ),
                alert=status != "CANCELLED",
            )
            return
        if action == "mode" and len(parts) == 3:
            mode = parts[2]
            if mode == "off":
                self.store.set_runtime_settings(
                    {
                        "trade.execution_mode": "off",
                        "trade.live_consent": "",
                    },
                    updated_by=actor_id,
                )
                self.client.send_message(
                    chat_id=actor_id,
                    text="⏸ Auto-entry dimatikan. Monitoring dan notifikasi tetap berjalan.",
                )
                self._answer_control(callback_id, "Auto-entry dimatikan.")
                return
            if mode in {"demo", "live"}:
                self._stage_mode_change(callback_id, actor_id, mode)
                return
        if action == "risk" and len(parts) == 3:
            risk_map = {"025": 0.25, "050": 0.5, "100": 1.0}
            if parts[2] in risk_map:
                value = risk_map[parts[2]]
                self._stage_control_action(
                    callback_id=callback_id,
                    actor_id=actor_id,
                    action_type="risk_change",
                    payload={"settings": {"trade.risk_pct": value}},
                    summary=f"Ubah risiko per posisi menjadi {value:.2f}%?",
                )
                return
        if action == "bind":
            account = self._current_account(actor_id)
            if account is None:
                self._answer_control(callback_id, "Akun MT5 tidak tersedia.", alert=True)
                return
            self._stage_control_action(
                callback_id=callback_id,
                actor_id=actor_id,
                action_type="bind_account",
                payload={
                    "account": account,
                    "settings": {
                        "trade.expected_login": str(account.get("login") or ""),
                        "trade.expected_server": str(account.get("server") or ""),
                    },
                },
                summary=(
                    "Kunci eksekusi ke akun aktif ini?\n"
                    f"Login {account.get('login')} • {account.get('server')}"
                ),
            )
            return
        self._answer_control(callback_id, "Perintah kontrol tidak valid.", alert=True)

    def _stage_mode_change(self, callback_id: str, actor_id: str, mode: str) -> None:
        account = self._current_account(actor_id)
        if account is None:
            self._answer_control(callback_id, "Akun MT5 tidak tersedia.", alert=True)
            return
        is_live = account.get("is_live")
        if mode == "demo" and is_live is not False:
            self._answer_control(callback_id, "Terminal bukan akun demo.", alert=True)
            return
        if mode == "live" and is_live is not True:
            self._answer_control(callback_id, "Terminal bukan akun real.", alert=True)
            return
        settings = {
            "trade.execution_mode": mode,
            "trade.expected_login": str(account.get("login") or ""),
            "trade.expected_server": str(account.get("server") or ""),
            "trade.live_consent": "I_UNDERSTAND_LIVE_ORDERS" if mode == "live" else "",
        }
        label = "REAL — ORDER UANG NYATA" if mode == "live" else "DEMO"
        self._stage_control_action(
            callback_id=callback_id,
            actor_id=actor_id,
            action_type="execution_mode",
            payload={"account": account, "settings": settings},
            summary=(
                f"Aktifkan auto-entry {label}?\n"
                f"Login {account.get('login')} • {account.get('server')}\n"
                "Konfirmasi berlaku 2 menit."
            ),
        )

    def _stage_control_action(
        self,
        *,
        callback_id: str,
        actor_id: str,
        action_type: str,
        payload: dict[str, Any],
        summary: str,
    ) -> None:
        token = secrets.token_urlsafe(6)
        self.store.stage_admin_action(
            token=token,
            action_type=action_type,
            payload=payload,
            requested_by=actor_id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
        )
        self.client.send_message(
            chat_id=actor_id,
            text=f"⚠️ KONFIRMASI PERUBAHAN\n\n{summary}",
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": "✅ Konfirmasi", "callback_data": f"ctl:confirm:{token}"},
                        {"text": "❌ Batal", "callback_data": f"ctl:cancel:{token}"},
                    ]
                ]
            },
        )
        self._answer_control(callback_id, "Perlu satu konfirmasi lagi.")

    def _confirm_control_action(self, callback_id: str, actor_id: str, token: str) -> None:
        action = self.store.decide_admin_action(
            token=token, actor_id=actor_id, confirm=True
        )
        if action is None or action.get("status") != "CONFIRMED":
            status = str((action or {}).get("status", "NOT_FOUND"))
            self._answer_control(
                callback_id, f"Konfirmasi tidak berlaku: {status}.", alert=True
            )
            return
        payload = action.get("payload") or {}
        staged_account = payload.get("account")
        if isinstance(staged_account, dict):
            current = self._current_account(actor_id)
            if current is None or any(
                str(current.get(key) or "") != str(staged_account.get(key) or "")
                for key in ("login", "server", "is_live")
            ):
                self._answer_control(
                    callback_id,
                    "Akun berubah sejak approval dibuat; perubahan ditolak.",
                    alert=True,
                )
                return
        settings = payload.get("settings")
        if not isinstance(settings, dict) or not settings:
            self._answer_control(callback_id, "Payload konfigurasi tidak valid.", alert=True)
            return
        self.store.set_runtime_settings(settings, updated_by=actor_id)
        self.client.send_message(
            chat_id=actor_id,
            text="✅ Konfigurasi diterapkan dan aktif pada siklus worker berikutnya.",
        )
        self._answer_control(callback_id, "Konfigurasi diterapkan.")

    def _current_account(self, actor_id: str) -> dict[str, Any] | None:
        if self.account_probe is None:
            self.client.send_message(
                chat_id=actor_id,
                text="⛔ Probe akun MT5 belum tersedia pada worker ini.",
            )
            return None
        try:
            return dict(self.account_probe())
        except Exception as exc:
            self.client.send_message(
                chat_id=actor_id,
                text=f"⛔ Gagal membaca akun MT5: {str(exc)[:300]}",
            )
            return None

    @staticmethod
    def _control_summary(config: TradeLifecycleConfig) -> str:
        mode = {"off": "OFF", "demo": "DEMO", "live": "REAL"}.get(
            config.execution_mode, "UNKNOWN"
        )
        return "\n".join(
            [
                "🎛 CONTROL PANEL GOLDM",
                f"• Auto-entry: {mode}",
                f"• Akun terkunci: {config.expected_login or '-'} / {config.expected_server or '-'}",
                f"• Risiko/posisi: {config.risk_pct:.2f}%",
                f"• Maks open risk: {config.max_total_open_risk_pct:.2f}%",
                f"• Daily loss limit: {config.daily_loss_limit_pct:.2f}%",
                f"• TTL sinyal: {config.signal_ttl_minutes} menit",
                "",
                "Viewer APPROVED hanya melihat notifikasi. Tombol entry/config hanya menerima root admin chat ID.",
            ]
        )

    def _answer_control(self, callback_id: str, text: str, *, alert: bool = False) -> None:
        self.client.answer_callback_query(
            callback_query_id=callback_id,
            text=text,
            show_alert=alert,
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
        if status == "REJECTED" and target_id in self.admin_chat_ids:
            self.client.send_message(
                chat_id=actor_id,
                text="⛔ Root admin tidak dapat dicabut dari panel runtime.",
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

    def _require_admin(self, actor_id: str) -> bool:
        if actor_id in self.admin_chat_ids:
            return True
        self.client.send_message(chat_id=actor_id, text="⛔ Perintah khusus root admin.")
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
        keyboard: list[list[dict[str, str]]] = []
        for item in subscribers[:50]:
            target_id = str(item["chat_id"])
            label = self._subscriber_label(item)
            if status == "PENDING":
                keyboard.append(
                    [
                        {
                            "text": f"✅ {label}",
                            "callback_data": f"approve:{target_id}",
                        },
                        {
                            "text": f"❌ {label}",
                            "callback_data": f"reject:{target_id}",
                        },
                    ]
                )
            elif status == "APPROVED" and target_id not in self.admin_chat_ids:
                keyboard.append(
                    [
                        {
                            "text": f"🚫 Cabut {label}",
                            "callback_data": f"reject:{target_id}",
                        }
                    ]
                )
        self.client.send_message(
            chat_id=actor_id,
            text="\n".join(lines),
            reply_markup={"inline_keyboard": keyboard} if keyboard else None,
        )

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
