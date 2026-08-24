from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gold_orchestrator.g20_control import _admin_chat_ids, main


class G20TelegramControlTests(unittest.TestCase):
    def test_admin_ids_accept_only_positive_private_chat_ids(self) -> None:
        self.assertEqual(_admin_chat_ids("200;100,-999,invalid"), ("100", "200"))

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
