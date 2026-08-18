from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class RevisedAdminNotifier:
    """One-way Telegram sender; it never polls Telegram updates."""

    def __init__(
        self,
        *,
        bot_token: str | None = None,
        chat_ids: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.bot_token = (bot_token or os.environ.get("GOLDM_REVISED_TELEGRAM_BOT_TOKEN", "")).strip()
        raw_ids = chat_ids if chat_ids is not None else os.environ.get("GOLDM_REVISED_TELEGRAM_ADMIN_CHAT_IDS", "")
        self.chat_ids = tuple(item.strip() for item in raw_ids.split(",") if item.strip())
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.chat_ids)

    def send(self, text: str) -> int:
        if not self.configured:
            raise RuntimeError("REVISED Telegram admin sender is not configured")
        if not text.strip():
            raise ValueError("Telegram text is required")
        sent = 0
        endpoint = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        for chat_id in self.chat_ids:
            body = urlencode({"chat_id": chat_id, "text": text[:4000]}).encode("utf-8")
            request = Request(endpoint, data=body, method="POST")
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
            if not payload.get("ok"):
                raise RuntimeError(f"Telegram sendMessage rejected admin delivery: {payload}")
            sent += 1
        return sent

    @staticmethod
    def format_event(event_type: str, payload: dict[str, object]) -> str:
        if event_type == "REVISED_HEALTH":
            return f"🛡️ GOLDM_REVISED HEALTH\n• Status: {payload.get('status')}\n• Detail: {payload.get('detail')}"
        if event_type == "REVISED_OUTCOME":
            return (
                "📊 GOLDM_REVISED OUTCOME\n"
                f"• Setup: {payload.get('setup_id')}\n"
                f"• Result: {payload.get('status')}\n"
                f"• Reason: {payload.get('close_reason')}\n"
                f"• MFE/MAE: {payload.get('mfe')} / {payload.get('mae')}"
            )
        return (
            "🧪 GOLDM_REVISED ENTRY READY\n"
            f"• Setup: {payload.get('setup_id')}\n"
            f"• Side: {payload.get('side')}\n"
            f"• Entry/SL/TP: {payload.get('entry')} / {payload.get('stop')} / {payload.get('target')}\n"
            f"• Obstacle: {payload.get('first_obstacle')} ({payload.get('first_obstacle_r')}R)\n"
            f"• Mode: {payload.get('mode')}\n"
            f"• Touch/rejection/acceptance: {payload.get('touch_count')}/{payload.get('rejection_count')}/{payload.get('acceptance_count')}"
        )
