from __future__ import annotations

import unittest
from typing import Any

from goldm_signal.notify.telegram import TelegramBotClient


class RecordingTelegramBotClient(TelegramBotClient):
    def __init__(self) -> None:
        super().__init__(bot_token="test-token")
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _call(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        del timeout_seconds
        self.calls.append((method, payload))
        return True


class TelegramBotClientTests(unittest.TestCase):
    def test_command_menu_is_public_by_default_and_scoped_for_each_admin(self) -> None:
        client = RecordingTelegramBotClient()

        client.set_commands(admin_chat_ids={"200", "100"})

        self.assertEqual(len(client.calls), 3)
        default_method, default_payload = client.calls[0]
        self.assertEqual(default_method, "setMyCommands")
        self.assertNotIn("scope", default_payload)
        self.assertEqual(
            [item["command"] for item in default_payload["commands"]],
            ["start", "status", "signal", "history", "stop"],
        )
        admin_scopes = [payload["scope"] for _, payload in client.calls[1:]]
        self.assertEqual(
            admin_scopes,
            [
                {"type": "chat", "chat_id": "100"},
                {"type": "chat", "chat_id": "200"},
            ],
        )
        for _, payload in client.calls[1:]:
            commands = {item["command"] for item in payload["commands"]}
            self.assertIn("control", commands)
            self.assertIn("account", commands)
            self.assertIn("pending", commands)


if __name__ == "__main__":
    unittest.main()
