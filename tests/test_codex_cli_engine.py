from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.codex_cli_engine import CodexCLIEngine, CodexContractError, CodexTimeoutError  # noqa: E402
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

    def test_parse_response_supports_single_line_contract(self) -> None:
        response = "ACTION=NO_TRADE SYMBOL=NONE SIDE=NONE CONFIDENCE=0 REASON=INSUFFICIENT_DATA"

        intent = CodexCLIEngine.parse_response(response)

        self.assertEqual(intent.action, DecisionAction.NO_TRADE)
        self.assertIsNone(intent.side)
        self.assertEqual(intent.confidence, 0.0)
        self.assertIsNone(intent.stop_distance_points)
        self.assertEqual(intent.reason, "INSUFFICIENT_DATA")

    def test_parse_response_allows_missing_stop_distance_points(self) -> None:
        response = "\n".join(
            [
                "ACTION=NO_TRADE",
                "SIDE=none",
                "CONFIDENCE=0.15",
                "REASON=waiting for confirmation",
            ]
        )

        intent = CodexCLIEngine.parse_response(response)

        self.assertEqual(intent.action, DecisionAction.NO_TRADE)
        self.assertIsNone(intent.stop_distance_points)

    def test_parse_response_allows_empty_stop_distance_points(self) -> None:
        response = "\n".join(
            [
                "ACTION=OPEN",
                "SIDE=buy",
                "CONFIDENCE=0.67",
                "STOP_DISTANCE_POINTS=",
                "REASON=breakout continuation",
            ]
        )

        intent = CodexCLIEngine.parse_response(response)

        self.assertEqual(intent.action, DecisionAction.OPEN)
        self.assertIsNone(intent.stop_distance_points)

    def test_parse_response_rejects_invalid_action(self) -> None:
        response = "\n".join(
            [
                "ACTION=WAIT",
                "SIDE=none",
                "CONFIDENCE=0.2",
                "REASON=invalid action",
            ]
        )

        with self.assertRaisesRegex(CodexContractError, "invalid ACTION"):
            CodexCLIEngine.parse_response(response)

    def test_parse_response_rejects_invalid_confidence(self) -> None:
        response = "\n".join(
            [
                "ACTION=NO_TRADE",
                "SIDE=none",
                "CONFIDENCE=high",
                "REASON=invalid confidence",
            ]
        )

        with self.assertRaisesRegex(CodexContractError, "invalid CONFIDENCE"):
            CodexCLIEngine.parse_response(response)

    def test_parse_response_rejects_invalid_stop_distance_points(self) -> None:
        response = "\n".join(
            [
                "ACTION=OPEN",
                "SIDE=buy",
                "CONFIDENCE=0.8",
                "STOP_DISTANCE_POINTS=abc",
                "REASON=invalid stop",
            ]
        )

        with self.assertRaisesRegex(CodexContractError, "invalid STOP_DISTANCE_POINTS"):
            CodexCLIEngine.parse_response(response)

    def test_parse_response_rejects_non_contract_output(self) -> None:
        with self.assertRaisesRegex(CodexContractError, "missing required keys"):
            CodexCLIEngine.parse_response("Please provide the exact lines to output.")

    def test_parse_response_accepts_single_line_no_trade_contract(self) -> None:
        response = "ACTION=NO_TRADE SYMBOL=NONE SIDE=NONE CONFIDENCE=0 REASON=INSUFFICIENT_DATA"
        intent = CodexCLIEngine.parse_response(response)
        self.assertEqual(intent.action, DecisionAction.NO_TRADE)
        self.assertIsNone(intent.side)
        self.assertEqual(intent.confidence, 0.0)
        self.assertEqual(intent.reason, "INSUFFICIENT_DATA")
        self.assertIsNone(intent.stop_distance_points)

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

    @patch("bot_ea.codex_cli_engine.subprocess.run")
    def test_probe_wraps_timeout_cleanly(self, run_mock) -> None:
        run_mock.side_effect = subprocess.TimeoutExpired(cmd=["codex", "--version"], timeout=60)
        engine = CodexCLIEngine(executable="codex", timeout_seconds=60)

        with self.assertRaisesRegex(RuntimeError, "codex --version timed out after 60 seconds"):
            engine.probe()

    @patch("bot_ea.codex_cli_engine.subprocess.run")
    def test_decide_wraps_timeout_cleanly(self, run_mock) -> None:
        from bot_ea.models import AccountSnapshot, CapitalAllocation, CapitalAllocationMode, RiskPolicy, SymbolSnapshot, TradingStyle
        from bot_ea.polling_runtime import RuntimeSnapshot

        run_mock.side_effect = subprocess.TimeoutExpired(cmd=["codex", "exec"], timeout=60)
        engine = CodexCLIEngine(executable="codex", timeout_seconds=60)
        snapshot = RuntimeSnapshot(
            symbol="EURUSD",
            timeframe="M5",
            bid=1.1,
            ask=1.1002,
            spread_points=2.0,
            account=AccountSnapshot(equity=1000.0, balance=1000.0, free_margin=900.0, margin_level=500.0),
            symbol_snapshot=SymbolSnapshot(
                name="EURUSD",
                instrument_class="forex_major",
                risk_weight=1.0,
                point=0.0001,
                tick_size=0.0001,
                tick_value=1.0,
                volume_min=0.01,
                volume_max=10.0,
                volume_step=0.01,
                spread_points=2.0,
                stops_level_points=10.0,
                freeze_level_points=0.0,
            ),
            risk_policy=RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0),
            trading_style=TradingStyle.INTRADAY,
            stop_distance_points=50.0,
            capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.FIXED_CASH, value=250.0),
        )

        with self.assertRaisesRegex(CodexTimeoutError, "codex exec timed out after 60 seconds"):
            engine.decide(snapshot)

    @patch("bot_ea.codex_cli_engine.shutil.which")
    @patch("bot_ea.codex_cli_engine.os.name", "nt")
    def test_resolve_executable_prefers_windows_launcher(self, which_mock) -> None:
        which_mock.side_effect = [r"C:\nvm4w\nodejs\codex.cmd", None, None]
        engine = CodexCLIEngine(executable="codex")

        resolved = engine._resolve_executable()

        self.assertEqual(resolved, r"C:\nvm4w\nodejs\codex.cmd")


if __name__ == "__main__":
    unittest.main()
