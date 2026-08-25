from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gold_orchestrator.g20_control import (
    ADMIN_STATE_KEY,
    _admin_chat_ids,
    _persist_admin_chat_ids,
    _resolve_admin_chat_ids,
    main,
)


class G20TelegramControlTests(unittest.TestCase):
    def test_admin_ids_accept_only_positive_private_chat_ids(self) -> None:
        self.assertEqual(_admin_chat_ids("200;100,-999,invalid"), ("100", "200"))

    def test_negative_only_config_uses_trusted_private_state_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_path = Path(raw) / "state.json"
            state_path.write_text(
                json.dumps({ADMIN_STATE_KEY: ["321"]}),
                encoding="utf-8",
            )

            self.assertEqual(
                _resolve_admin_chat_ids("-999", state_path),
                (("321",), "STATE_FALLBACK"),
            )

    def test_invalid_persisted_admin_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_path = Path(raw) / "state.json"
            state_path.write_text(
                json.dumps({ADMIN_STATE_KEY: ["-999"]}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "invalid private chat ID"):
                _resolve_admin_chat_ids("-999", state_path)

    def test_negative_only_config_without_trusted_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with (
                patch.dict(
                    os.environ,
                    {
                        "TELEGRAM_BOT_TOKEN": "test-token",
                        "TELEGRAM_ADMIN_CHAT_IDS": "-999",
                        "TELEGRAM_EXPECTED_BOT_USERNAME": "expected_bot",
                    },
                    clear=True,
                ),
                self.assertRaisesRegex(SystemExit, "no trusted state fallback"),
            ):
                main(
                    [
                        "--state-path",
                        str(root / "state.json"),
                        "--audit-path",
                        str(root / "audit.jsonl"),
                        "--check",
                    ]
                )

    def test_explicit_private_admin_takes_precedence_and_is_persisted_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_path = Path(raw) / "state.json"
            state_path.write_text(
                json.dumps({ADMIN_STATE_KEY: ["321"], "telegram_offset": 7}),
                encoding="utf-8",
            )
            admins, source = _resolve_admin_chat_ids("200,-999", state_path)
            self.assertEqual((admins, source), (("200",), "CONFIG"))

            _persist_admin_chat_ids(state_path, admins)

            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload[ADMIN_STATE_KEY], ["200"])
            self.assertEqual(payload["telegram_offset"], 7)
            self.assertFalse(state_path.with_name(".state.json.admin.tmp").exists())

    def test_check_builds_approval_only_runtime_without_workers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            environment = {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "TELEGRAM_ADMIN_CHAT_IDS": "123",
                "TELEGRAM_EXPECTED_BOT_USERNAME": "expected_bot",
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("gold_orchestrator.g20_control.GlobalOrchestrator") as runtime,
            ):
                self.assertEqual(
                    main(
                        [
                            "--state-path",
                            str(root / "state.json"),
                            "--audit-path",
                            str(root / "audit.jsonl"),
                            "--check",
                        ]
                    ),
                    0,
                )

            config = runtime.call_args.args[0]
            self.assertFalse(config.worker_control_enabled)
            self.assertEqual(config.workers, {})
            self.assertEqual(config.expected_bot_username, "expected_bot")
            runtime.return_value._validate_bot_identity.assert_called_once_with()

    def test_check_builds_runtime_from_trusted_state_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state_path = root / "state.json"
            state_path.write_text(
                json.dumps({ADMIN_STATE_KEY: ["321"]}),
                encoding="utf-8",
            )
            environment = {
                "TELEGRAM_BOT_TOKEN": "test-token",
                "TELEGRAM_ADMIN_CHAT_IDS": "-999",
                "TELEGRAM_EXPECTED_BOT_USERNAME": "expected_bot",
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("gold_orchestrator.g20_control.GlobalOrchestrator") as runtime,
            ):
                self.assertEqual(
                    main(
                        [
                            "--state-path",
                            str(state_path),
                            "--audit-path",
                            str(root / "audit.jsonl"),
                            "--check",
                        ]
                    ),
                    0,
                )

            self.assertEqual(runtime.call_args.args[0].admin_chat_ids, ("321",))

    def test_missing_expected_identity_fails_closed(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_ADMIN_CHAT_IDS": "123"},
                clear=True,
            ),
            self.assertRaisesRegex(SystemExit, "EXPECTED_BOT_USERNAME"),
        ):
            main(["--state-path", "state.json", "--audit-path", "audit.jsonl"])


if __name__ == "__main__":
    unittest.main()
