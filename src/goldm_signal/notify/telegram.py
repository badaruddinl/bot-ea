from __future__ import annotations

import json
from typing import Any
from urllib import parse, request

from ..storage.database import SignalStore


class TelegramBotClient:
    """Small Telegram Bot API client with no third-party runtime dependency."""

    def __init__(self, *, bot_token: str, timeout_seconds: float = 10.0) -> None:
        if not bot_token:
            raise ValueError("Telegram bot token is required")
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._timeout_seconds = timeout_seconds

    def get_updates(self, *, offset: int | None = None, timeout: int = 20) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload, timeout_seconds=max(timeout + 5, 10))
        return list(result)

    def send_message(
        self,
        *,
        chat_id: str | int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": str(chat_id), "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return dict(self._call("sendMessage", payload))

    def answer_callback_query(
        self, *, callback_query_id: str, text: str, show_alert: bool = False
    ) -> None:
        self._call(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": show_alert,
            },
        )

    def set_commands(self) -> None:
        self._call(
            "setMyCommands",
            {
                "commands": [
                    {"command": "start", "description": "Minta akses notifikasi"},
                    {"command": "status", "description": "Cek status akses"},
                    {"command": "snapshot", "description": "Ringkasan kondisi bot"},
                    {"command": "signal", "description": "Sinyal entry terakhir"},
                    {"command": "watch", "description": "Kandidat terakhir"},
                    {"command": "history", "description": "5 event terbaru"},
                    {"command": "health", "description": "Kesehatan worker dan antrean"},
                    {"command": "control", "description": "Panel akun, entry, dan risiko (admin)"},
                    {"command": "account", "description": "Akun MT5 aktif (admin)"},
                    {"command": "users", "description": "User penerima notifikasi (admin)"},
                    {"command": "stop", "description": "Berhenti menerima notifikasi"},
                    {"command": "pending", "description": "Daftar permintaan (admin)"},
                ]
            },
        )

    def _call(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        encoded: dict[str, str] = {}
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                encoded[key] = json.dumps(value, separators=(",", ":"))
            elif isinstance(value, bool):
                encoded[key] = "true" if value else "false"
            else:
                encoded[key] = str(value)
        body = parse.urlencode(encoded).encode("utf-8")
        http_request = request.Request(f"{self._base_url}/{method}", data=body, method="POST")
        with request.urlopen(  # noqa: S310
            http_request, timeout=timeout_seconds or self._timeout_seconds
        ) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError(f"Telegram rejected {method}: {result.get('description', 'unknown')}")
        return result.get("result")


class TelegramSender:
    def __init__(self, *, bot_token: str, chat_id: str, timeout_seconds: float = 10.0) -> None:
        if not bot_token or not chat_id:
            raise ValueError("Telegram bot token and chat ID are required")
        self._client = TelegramBotClient(
            bot_token=bot_token, timeout_seconds=timeout_seconds
        )
        self._chat_id = chat_id

    def __call__(self, event: dict[str, Any]) -> None:
        payload = event.get("payload", {})
        text = str(payload.get("text", "")).strip()
        if not text:
            raise ValueError("outbox payload does not contain message text")
        self._client.send_message(chat_id=self._chat_id, text=text)


class ApprovedTelegramSender:
    """Broadcast an outbox event only to currently approved subscribers.

    Per-recipient delivery state prevents a successful recipient from receiving
    the same event again when another recipient temporarily fails.
    """

    def __init__(self, *, store: SignalStore, client: TelegramBotClient) -> None:
        self._store = store
        self._client = client

    def __call__(self, event: dict[str, Any]) -> None:
        payload = event.get("payload", {})
        text = str(payload.get("text", "")).strip()
        if not text:
            raise ValueError("outbox payload does not contain message text")
        outbox_id = int(event["id"])
        chat_ids = self._store.approved_telegram_chat_ids()
        if not chat_ids:
            raise RuntimeError("No approved Telegram subscribers")

        failures = 0
        for chat_id in chat_ids:
            if self._store.telegram_delivery_was_sent(
                outbox_id=outbox_id, chat_id=chat_id
            ):
                continue
            try:
                self._client.send_message(chat_id=chat_id, text=text)
            except Exception as exc:
                self._store.mark_telegram_delivery_failed(
                    outbox_id=outbox_id, chat_id=chat_id, error=str(exc)
                )
                failures += 1
            else:
                self._store.mark_telegram_delivery_sent(
                    outbox_id=outbox_id, chat_id=chat_id
                )
        if failures:
            raise RuntimeError(f"Telegram delivery failed for {failures} approved subscriber(s)")
