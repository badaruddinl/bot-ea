from __future__ import annotations

import sys
import unittest
from pathlib import Path

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
