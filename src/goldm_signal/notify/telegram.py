from __future__ import annotations

import json
from typing import Any
from urllib import parse, request

from ..config import NotificationSideFilter
from ..storage.database import SignalStore

_DIRECTIONAL_STRATEGY_EVENTS = frozenset(
    {
        "SNIPER_EARLY_CANDIDATE",
        "SNIPER_EARLY_PROMOTED",
        "SNIPER_EARLY_CANCELLED",
        "SNIPER_SIGNAL",
        "SNIPER_OUTCOME",
    }
)


PUBLIC_BOT_COMMANDS: tuple[dict[str, str], ...] = (
    {"command": "start", "description": "Request GOLD.i notification access"},
    {"command": "status", "description": "Check access status"},
    {"command": "signal", "description": "Latest GOLD.i signal"},
    {"command": "history", "description": "Latest 5 GOLD.i events"},
    {"command": "stop", "description": "Stop receiving notifications"},
)

ADMIN_BOT_COMMANDS: tuple[dict[str, str], ...] = (
    *PUBLIC_BOT_COMMANDS,
    {"command": "snapshot", "description": "Bot condition summary"},
    {"command": "watch", "description": "Latest candidate"},
    {"command": "health", "description": "Worker and queue health"},
    {"command": "control", "description": "Account, entry, and risk panel"},
    {"command": "account", "description": "Active MT5 account"},
    {"command": "users", "description": "Notification recipients"},
    {"command": "pending", "description": "Pending access requests"},
)

PUBLIC_BOT_COMMAND_NAMES = frozenset(f"/{item['command']}" for item in PUBLIC_BOT_COMMANDS)


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

    def get_me(self) -> dict[str, Any]:
        """Return the authenticated bot identity without exposing its token."""
        return dict(self._call("getMe", {}))

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

    def set_commands(self, *, admin_chat_ids: set[str | int]) -> None:
        """Publish a minimal default menu and a richer menu per admin chat."""
        normalized_admins = normalize_admin_user_ids(admin_chat_ids, require_nonempty=False)
        self.replace_commands(
            commands=PUBLIC_BOT_COMMANDS,
            chat_ids=(),
        )
        self.replace_commands(
            commands=ADMIN_BOT_COMMANDS,
            chat_ids=tuple(sorted(normalized_admins, key=int)),
            include_default=False,
        )

    def edit_message_reply_markup(
        self,
        *,
        chat_id: str | int,
        message_id: int,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        self._call(
            "editMessageReplyMarkup",
            {
                "chat_id": str(chat_id),
                "message_id": int(message_id),
                "reply_markup": reply_markup or {"inline_keyboard": []},
            },
        )

    def edit_message_text(
        self,
        *,
        chat_id: str | int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": str(chat_id),
            "message_id": int(message_id),
            "text": text,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        self._call("editMessageText", payload)

    def replace_commands(
        self,
        *,
        commands: tuple[dict[str, str], ...],
        chat_ids: set[str | int] | tuple[str, ...] = (),
        include_default: bool = True,
    ) -> None:
        """Replace Telegram command menus for the default and selected chats."""
        normalized_commands = [
            {
                "command": str(item["command"]).strip().lstrip("/"),
                "description": str(item["description"]).strip(),
            }
            for item in commands
        ]
        if not normalized_commands or any(
            not item["command"] or not item["description"] for item in normalized_commands
        ):
            raise ValueError("Telegram command menu cannot be empty")
        if include_default:
            self._call(
                "setMyCommands",
                {"commands": normalized_commands},
            )
        normalized_chat_ids: set[str] = set()
        for raw_chat_id in chat_ids:
            text = str(raw_chat_id).strip()
            digits = text[1:] if text.startswith("-") else text
            if not text.isascii() or not digits.isdecimal() or int(text) == 0:
                raise ValueError("Telegram command-scope chat IDs must be non-zero integers")
            normalized_chat_ids.add(str(int(text)))
        for chat_id in sorted(normalized_chat_ids, key=int):
            self._call(
                "setMyCommands",
                {
                    "commands": normalized_commands,
                    "scope": {"type": "chat", "chat_id": chat_id},
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
        with request.urlopen(
            http_request, timeout=timeout_seconds or self._timeout_seconds
        ) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError(
                f"Telegram rejected {method}: {result.get('description', 'unknown')}"
            )
        return result.get("result")


class TelegramSender:
    def __init__(self, *, bot_token: str, chat_id: str, timeout_seconds: float = 10.0) -> None:
        if not bot_token or not chat_id:
            raise ValueError("Telegram bot token and chat ID are required")
        self._client = TelegramBotClient(bot_token=bot_token, timeout_seconds=timeout_seconds)
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

    def __init__(
        self,
        *,
        store: SignalStore,
        client: TelegramBotClient,
        admin_chat_ids: set[str | int] | None = None,
    ) -> None:
        self._store = store
        self._client = client
        self._admin_chat_ids = normalize_admin_user_ids(
            admin_chat_ids or set(), require_nonempty=False
        )

    def __call__(self, event: dict[str, Any]) -> None:
        payload = event.get("payload", {})
        text = str(payload.get("text", "")).strip()
        if not text:
            raise ValueError("outbox payload does not contain message text")
        outbox_id = int(event["id"])
        admin_only = telegram_event_is_admin_only(payload)
        if (
            not admin_only
            and str(event.get("event_type") or "").upper() in _DIRECTIONAL_STRATEGY_EVENTS
        ):
            settings = self._store.runtime_settings(prefix="trade.")
            raw_profile = settings.get(
                "trade.notification_side_filter", NotificationSideFilter.ALL.value
            )
            if "trade.notification_direction_profile" in settings:
                raw_profile = "INVALID_LEGACY_DIRECTION_PROFILE"
            try:
                profile = NotificationSideFilter.parse(raw_profile)
            except ValueError:
                self._send_invalid_direction_warning(
                    event=event,
                    raw_profile=raw_profile,
                )
                return
            fields = payload.get("fields")
            field_side = fields.get("side") if isinstance(fields, dict) else None
            side = str(event.get("side") or payload.get("side") or field_side or "").lower()
            if side not in {"buy", "sell"}:
                self._send_invalid_direction_warning(
                    event=event,
                    raw_profile=raw_profile,
                    detail="event does not contain a valid BUY/SELL side",
                )
                return
            if not profile.allows(side):
                # Display-only suppression: persistence, execution candidates,
                # and all POSITION_* safety/broker events remain intact.
                return
        chat_ids = (
            sorted(self._admin_chat_ids) if admin_only else self._store.approved_telegram_chat_ids()
        )
        if not chat_ids:
            audience = "root administrators" if admin_only else "approved Telegram subscribers"
            raise RuntimeError(f"No eligible {audience}")

        failures = 0
        for chat_id in chat_ids:
            if self._store.telegram_delivery_was_sent(outbox_id=outbox_id, chat_id=chat_id):
                continue
            try:
                self._client.send_message(chat_id=chat_id, text=text)
            except Exception as exc:
                self._store.mark_telegram_delivery_failed(
                    outbox_id=outbox_id, chat_id=chat_id, error=str(exc)
                )
                failures += 1
            else:
                self._store.mark_telegram_delivery_sent(outbox_id=outbox_id, chat_id=chat_id)
        if failures:
            raise RuntimeError(f"Telegram delivery failed for {failures} approved subscriber(s)")

    def _send_invalid_direction_warning(
        self,
        *,
        event: dict[str, Any],
        raw_profile: object,
        detail: str = "runtime notification side filter is invalid",
    ) -> None:
        if not self._admin_chat_ids:
            raise RuntimeError(
                "Directional notification suppressed but no root administrator is configured"
            )
        outbox_id = int(event["id"])
        warning = "\n".join(
            [
                "🚨 STRATEGY NOTIFICATION BLOCKED — FAIL-CLOSED",
                f"• Event: {event.get('event_type') or '-'} / {event.get('side') or '-'}",
                f"• Notification side filter: {raw_profile!s}",
                f"• Reason: {detail}",
                "The signal remains stored; execution and broker POSITION_* alerts are not filtered.",
            ]
        )
        failures = 0
        for chat_id in sorted(self._admin_chat_ids):
            if self._store.telegram_delivery_was_sent(outbox_id=outbox_id, chat_id=chat_id):
                continue
            try:
                self._client.send_message(chat_id=chat_id, text=warning)
            except Exception as exc:
                self._store.mark_telegram_delivery_failed(
                    outbox_id=outbox_id, chat_id=chat_id, error=str(exc)
                )
                failures += 1
            else:
                self._store.mark_telegram_delivery_sent(outbox_id=outbox_id, chat_id=chat_id)
        if failures:
            raise RuntimeError(
                f"Telegram fail-closed warning failed for {failures} root administrator(s)"
            )


def telegram_event_is_admin_only(payload: dict[str, Any]) -> bool:
    """Only an explicitly approved DEMO event may reach non-admin viewers."""

    audience = str(payload.get("audience", "")).strip().lower()
    account_scope = str(payload.get("account_scope", "")).strip().lower()
    if (
        str(payload.get("source") or "").strip().lower() == "mt5_expert_log"
        and payload.get("event_account_binding_verified") is not True
    ):
        return True
    return not (account_scope == "demo" and audience == "approved")


def normalize_admin_user_ids(values: set[str | int], *, require_nonempty: bool = True) -> set[str]:
    """Validate Telegram administrators as positive private user identifiers."""

    normalized: set[str] = set()
    for raw_value in values:
        value = str(raw_value).strip()
        if not value.isascii() or not value.isdecimal() or int(value) <= 0:
            raise ValueError("Telegram administrator IDs must be positive private user IDs")
        normalized.add(str(int(value)))
    if require_nonempty and not normalized:
        raise ValueError("At least one Telegram administrator user ID is required")
    return normalized
