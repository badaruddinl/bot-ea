from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from goldm_signal.research_policy import (  # noqa: E402
    ResearchPurpose,
    StatisticalClassification,
    assert_research_range,
    inclusive_api_end,
    load_research_policy,
    parse_research_date,
)


class GoldMResearchPolicyTests(unittest.TestCase):
    def test_authorized_boundaries_are_half_open(self) -> None:
        development = assert_research_range(
            "2022-02-28",
            "2024-02-28",
            purpose=ResearchPurpose.DEVELOPMENT,
        )
        validation = assert_research_range(
            "2024-02-28",
            "2026-02-28",
            purpose=ResearchPurpose.VALIDATION,
        )
        after_quarantine = assert_research_range(
            "2026-07-01",
            "2026-07-02",
            purpose=ResearchPurpose.DIAGNOSTIC,
        )
        blind = assert_research_range(
            "2026-08-19",
            "2026-08-20",
            purpose=ResearchPurpose.BLIND_OOS,
        )

        self.assertEqual(development.end, validation.start)
        self.assertEqual(validation.end.date().isoformat(), "2026-02-28")
        self.assertEqual(after_quarantine.start.date().isoformat(), "2026-07-01")
        self.assertEqual(blind.start.date().isoformat(), "2026-08-19")
        self.assertIs(
            development.statistical_classification,
            StatisticalClassification.DEVELOPMENT_SELECTION,
        )
        self.assertIs(
            validation.statistical_classification,
            StatisticalClassification.LOCKED_LEGACY_VALIDATION,
        )
        self.assertIs(
            after_quarantine.statistical_classification,
            StatisticalClassification.DIAGNOSTIC_ONLY,
        )
        self.assertIs(
            blind.statistical_classification,
            StatisticalClassification.BLIND_OOS,
        )

    def test_every_quarantine_overlap_shape_is_rejected(self) -> None:
        ranges = (
            ("2026-02-27", "2026-03-01"),
            ("2026-03-01", "2026-04-01"),
            ("2026-06-30", "2026-07-02"),
            ("2026-02-01", "2026-08-01"),
        )
        for start, end in ranges:
            with self.subTest(start=start, end=end):
                with self.assertRaisesRegex(ValueError, "protected quarantine"):
                    assert_research_range(start, end, purpose="Diagnostic")

    def test_invalid_ranges_dates_and_purposes_fail_closed(self) -> None:
        for start, end in (("2024-01-01", "2024-01-01"), ("2024-02-01", "2024-01-01")):
            with self.subTest(start=start, end=end):
                with self.assertRaisesRegex(ValueError, "from_date must be earlier"):
                    assert_research_range(start, end)

        for value in ("2024.01.01", "20240101", "2024-1-1", "not-a-date"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
                    parse_research_date(value, field="test_date")

        with self.assertRaisesRegex(ValueError, "invalid research purpose"):
            assert_research_range("2024-01-01", "2024-01-02", purpose="Selection")
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            assert_research_range(datetime(2024, 1, 1), datetime(2024, 1, 2))

    def test_labeled_ranges_cannot_escape_their_authorized_periods(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside"):
            assert_research_range(
                "2024-02-27",
                "2024-03-01",
                purpose=ResearchPurpose.VALIDATION,
            )
        with self.assertRaisesRegex(ValueError, "already exposed"):
            assert_research_range(
                "2026-08-11",
                "2026-08-13",
                purpose=ResearchPurpose.BLIND_OOS,
            )
        for start, end in (
            ("2022-02-28", "2022-03-01"),
            ("2024-02-28", "2024-03-01"),
            ("2026-08-18", "2026-08-20"),
        ):
            with self.subTest(start=start, end=end):
                with self.assertRaisesRegex(ValueError, "known-exposure"):
                    assert_research_range(start, end, purpose=ResearchPurpose.DIAGNOSTIC)

    def test_purpose_and_statistical_classification_cannot_disagree(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "requires statistical classification LOCKED_LEGACY_VALIDATION",
        ):
            assert_research_range(
                "2024-02-28",
                "2024-03-01",
                purpose=ResearchPurpose.VALIDATION,
                statistical_classification=(
                    StatisticalClassification.BLIND_OOS
                ),
            )

    def test_inclusive_mt5_api_endpoint_never_reaches_exclusive_boundary(self) -> None:
        exclusive_end = datetime(2026, 2, 28, tzinfo=timezone.utc)
        api_end = inclusive_api_end(exclusive_end)
        self.assertLess(api_end, exclusive_end)
        self.assertEqual(api_end.date().isoformat(), "2026-02-27")
        self.assertEqual(api_end.tzinfo, timezone.utc)

    def test_policy_is_single_source_for_python_and_powershell_guards(self) -> None:
        policy = load_research_policy()
        self.assertEqual(policy["quarantine"]["from"], "2026-02-28")
        self.assertEqual(policy["quarantine"]["to"], "2026-07-01")

        powershell_guard = (REPO_ROOT / "scripts" / "goldm-research-guard.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("config\\goldm-research-policy.json", powershell_guard)
        self.assertIn("LOCKED_LEGACY_VALIDATION", powershell_guard)
        self.assertIn("known-exposure", powershell_guard)

    def test_every_terminal_research_runner_guards_before_process_start(self) -> None:
        runner_names = (
            "run-mt5-goldm-backtests.ps1",
            "run-mt5-goldm-deposit-matrix.ps1",
            "run-mt5-goldm-sniper-backtests.ps1",
            "tune-mt5-goldm-scalper.ps1",
            "tune-mt5-goldm-walkforward.ps1",
        )
        for name in runner_names:
            with self.subTest(name=name):
                source = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
                self.assertIn("goldm-research-guard.ps1", source)
                self.assertLess(
                    source.index("Assert-GoldMResearchRange"),
                    source.index("Start-Process"),
                )
                if name == "run-mt5-goldm-sniper-backtests.ps1":
                    self.assertIn("BacktestStatisticalClassification", source)
                    self.assertIn("OosStatisticalClassification", source)

    def test_repository_contains_no_static_executable_mt5_tester_ini(self) -> None:
        config_root = REPO_ROOT / "mt5" / "tester_configs"
        executable = tuple(config_root.glob("*.ini"))
        self.assertEqual(
            executable,
            (),
            "static MT5 tester INI files bypass immutable run registration",
        )
        readme = (config_root / "README.md").read_text(encoding="utf-8")
        self.assertIn("protected quarantine", readme)
        self.assertIn("run-goldm-research-safe.py", readme)

    def test_candle_miner_has_no_direct_broker_history_path(self) -> None:
        source = (REPO_ROOT / "scripts" / "mine-goldm-candle-patterns.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("--dataset-manifest", source)
        self.assertIn("load_registered_tick_dataset", source)
        self.assertNotIn("import MetaTrader5", source)
        self.assertNotIn("copy_rates_range", source)
        self.assertNotIn("copy_ticks_range", source)
        self.assertNotIn("--terminal", source)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell required")
    def test_powershell_guard_rejects_quarantine_from_shared_policy(self) -> None:
        guard = REPO_ROOT / "scripts" / "goldm-research-guard.ps1"
        command = (
            f". '{guard}'; "
            "Assert-GoldMResearchRange -FromDate '2026.02.28' -ToDate '2026.03.01' "
            "-Purpose Diagnostic -StatisticalClassification DIAGNOSTIC_ONLY "
            "-Label 'unit-test'"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("protected quarantine", result.stderr + result.stdout)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell required")
    def test_powershell_guard_rejects_diagnostic_bypass_and_bad_classification(self) -> None:
        guard = REPO_ROOT / "scripts" / "goldm-research-guard.ps1"
        commands = (
            (
                f". '{guard}'; "
                "Assert-GoldMResearchRange -FromDate '2024.02.28' "
                "-ToDate '2024.03.01' -Purpose Diagnostic "
                "-StatisticalClassification DIAGNOSTIC_ONLY -Label 'unit-test'",
                "known-exposure",
            ),
            (
                f". '{guard}'; "
                "Assert-GoldMResearchRange -FromDate '2024.02.28' "
                "-ToDate '2024.03.01' -Purpose Validation "
                "-StatisticalClassification BLIND_OOS -Label 'unit-test'",
                "LOCKED_LEGACY_VALIDATION",
            ),
            (
                f". '{guard}'; "
                "Assert-GoldMResearchRange -FromDate '2024.02.28' "
                "-ToDate '2024.03.01' -Purpose Validation -Label 'unit-test'",
                "statistical classification is required",
            ),
        )
        for command, expected in commands:
            with self.subTest(expected=expected):
                result = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        command,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
