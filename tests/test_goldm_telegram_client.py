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
        if method == "getMe":
            return {"id": 1, "username": "new_gold_notify_bot"}
        return True


class TelegramBotClientTests(unittest.TestCase):
    def test_get_me_returns_authenticated_bot_identity(self) -> None:
        client = RecordingTelegramBotClient()

        identity = client.get_me()

        self.assertEqual(identity["username"], "new_gold_notify_bot")
        self.assertEqual(client.calls, [("getMe", {})])

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

    def test_inline_message_can_be_replaced_and_buttons_removed(self) -> None:
        client = RecordingTelegramBotClient()

        client.edit_message_text(
            chat_id="123",
            message_id=77,
            text="Status diperbarui",
            reply_markup={"inline_keyboard": []},
        )
        client.edit_message_reply_markup(chat_id="123", message_id=78)

        self.assertEqual(client.calls[0][0], "editMessageText")
        self.assertEqual(client.calls[0][1]["message_id"], 77)
        self.assertEqual(
            client.calls[0][1]["reply_markup"],
            {"inline_keyboard": []},
        )
        self.assertEqual(client.calls[1][0], "editMessageReplyMarkup")
        self.assertEqual(
            client.calls[1][1]["reply_markup"],
            {"inline_keyboard": []},
        )

    def test_command_scope_accepts_negative_group_chat_id(self) -> None:
        client = RecordingTelegramBotClient()

        client.replace_commands(
            commands=({"command": "stop", "description": "Stop"},),
            chat_ids={"-5299542070"},
            include_default=False,
        )

        self.assertEqual(client.calls[0][0], "setMyCommands")
        self.assertEqual(
            client.calls[0][1]["scope"],
            {"type": "chat", "chat_id": "-5299542070"},
        )


if __name__ == "__main__":
    unittest.main()
