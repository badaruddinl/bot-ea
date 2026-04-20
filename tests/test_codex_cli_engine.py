from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.codex_cli_engine import CodexCLIEngine  # noqa: E402
from bot_ea.polling_runtime import DecisionAction  # noqa: E402


class CodexCLIEngineTests(unittest.TestCase):
    def test_parse_response(self) -> None:
        response = "\n".join(
            [
                "ACTION=OPEN",
                "SIDE=buy",
                "CONFIDENCE=0.82",
                "STOP_DISTANCE_POINTS=55",
                "REASON=Session breakout still valid.",
            ]
        )
        intent = CodexCLIEngine.parse_response(response)
        self.assertEqual(intent.action, DecisionAction.OPEN)
        self.assertEqual(intent.side, "buy")
        self.assertAlmostEqual(intent.confidence, 0.82)
        self.assertAlmostEqual(intent.stop_distance_points, 55.0)

    @patch("bot_ea.codex_cli_engine.subprocess.run")
    def test_probe_returns_version_output(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=["codex", "--version"],
            returncode=0,
            stdout="codex-cli 0.121.0\n",
            stderr="",
        )
        engine = CodexCLIEngine(executable="codex")

        version = engine.probe()

        self.assertEqual(version, "codex-cli 0.121.0")
        run_mock.assert_called_once()

    @patch("bot_ea.codex_cli_engine.shutil.which")
    @patch("bot_ea.codex_cli_engine.os.name", "nt")
    def test_resolve_executable_prefers_windows_launcher(self, which_mock) -> None:
        which_mock.side_effect = [r"C:\nvm4w\nodejs\codex.cmd", None, None]
        engine = CodexCLIEngine(executable="codex")

        resolved = engine._resolve_executable()

        self.assertEqual(resolved, r"C:\nvm4w\nodejs\codex.cmd")


if __name__ == "__main__":
    unittest.main()
