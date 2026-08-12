from __future__ import annotations

import json
from typing import Any
from urllib import parse, request


class TelegramSender:
    def __init__(self, *, bot_token: str, chat_id: str, timeout_seconds: float = 10.0) -> None:
        if not bot_token or not chat_id:
            raise ValueError("Telegram bot token and chat ID are required")
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id
        self._timeout_seconds = timeout_seconds

    def __call__(self, event: dict[str, Any]) -> None:
        payload = event.get("payload", {})
        text = str(payload.get("text", "")).strip()
        if not text:
            raise ValueError("outbox payload does not contain message text")
        body = parse.urlencode({"chat_id": self._chat_id, "text": text}).encode("utf-8")
        http_request = request.Request(self._url, data=body, method="POST")
        with request.urlopen(http_request, timeout=self._timeout_seconds) as response:  # noqa: S310
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError(f"Telegram rejected message: {result}")
