from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from goldm_signal.directional_research import (
    Bar,
    Candidate,
    DirectionalResearchError,
    Features,
    load_candidate_plan,
    load_registered_bar_dataset,
    simulate_candidate,
)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GoldIDirectionalResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def _source_fixture(self, *, run_from: str = "2022-02-28", to: str = "2022-06-28"):
        archive = self.root / "source.zip"
        archive.write_bytes(b"immutable-source")
        bars = self.root / "bars.csv"
        bars.write_text(
            "Local time,Open,High,Low,Close,Volume\n"
            "31.12.2020 19:00:00.000 GMT-0500,100,101,99,100,1\n"
            "27.02.2022 19:00:00.000 GMT-0500,101,102,100,101,1\n"
            "27.06.2022 19:55:00.000 GMT-0400,102,103,101,102,1\n",
            encoding="utf-8",
        )
        payload: dict[str, object] = {
            "schema_version": 1,
            "dataset_id": "goldi-test-bars-v1",
            "registered_at": "2026-08-17T08:00:00Z",
            "purpose": "Development",
            "statistical_classification": "DEVELOPMENT_SELECTION",
            "source_repository": "https://example.test/source",
            "source_commit": "a" * 40,
            "archive_path": archive.name,
            "archive_sha256": _file_sha256(archive),
            "source_symbol": "XAUUSD",
            "target_symbol": "GOLD.i#",
            "format": "EPSOFT_XAUUSD_BID_M5_V1",
            "time_semantics": "SOURCE_ROW_EXPLICIT_GMT_OFFSET_TO_UTC_HALF_OPEN",
            "bar_model_classification": "EXPLORATORY_BAR_MODEL_NOT_MT5_TICKS",
            "warmup_from_inclusive": "2021-01-01",
            "run_from_inclusive": run_from,
            "to_exclusive": to,
            "files": [{"path": bars.name, "sha256": _file_sha256(bars)}],
            "cost_model": {
                "round_trip_quote": 0.3,
                "same_bar_collision": "STOP_FIRST_CONSERVATIVE",
            },
        }
        payload["manifest_sha256"] = _canonical_sha256(payload)
        manifest = self.root / "dataset.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        return manifest, bars, payload

    def test_registered_dataset_honors_row_dst_offset_and_hashes(self) -> None:
        manifest, bars, _ = self._source_fixture()
        dataset = load_registered_bar_dataset(manifest)
        self.assertEqual(dataset.target_symbol, "GOLD.i#")
        self.assertEqual(dataset.bars[-1].time.hour, 23)
        bars.write_text(bars.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(DirectionalResearchError, "SHA-256 mismatch"):
            load_registered_bar_dataset(manifest)

    def test_protected_period_is_rejected_before_any_research(self) -> None:
        manifest, _, payload = self._source_fixture()
        payload["run_from_inclusive"] = "2026-03-01"
        payload["to_exclusive"] = "2026-04-01"
        payload["manifest_sha256"] = _canonical_sha256(
            {key: value for key, value in payload.items() if key != "manifest_sha256"}
        )
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "protected quarantine"):
            load_registered_bar_dataset(manifest)

    def test_same_bar_stop_and_target_collision_is_stop_first(self) -> None:
        start = datetime(2022, 3, 1, tzinfo=timezone.utc)
        bars = [
            Bar(start + timedelta(minutes=5 * index), 100, 100, 100, 100)
            for index in range(60)
        ]
        bars[52] = Bar(bars[52].time, 100, 102, 99, 101)
        bars[53] = Bar(bars[53].time, 101, 106, 98, 101)
        values = tuple(1.0 for _ in bars)
        features = Features(
            ema_fast=tuple(101.0 for _ in bars),
            ema_slow=tuple(99.0 for _ in bars),
            atr=values,
            atr_slow=tuple(2.0 for _ in bars),
            rsi=tuple(60.0 for _ in bars),
        )
        candidate = Candidate(
            candidate_id="BULL_SQUEEZE_TEST",
            side="BULL",
            family="SQUEEZE_EXPANSION",
            pattern="NONE",
            session_start_utc=0,
            session_end_utc=24,
            structure_lookback=3,
            stop_atr=1.0,
            target_r=2.0,
            max_hold_bars=5,
            rsi_minimum=50.0,
            rsi_maximum=70.0,
            squeeze_ratio=0.75,
        )
        trades = simulate_candidate(
            bars,
            features,
            candidate,
            start=start,
            end=start + timedelta(days=1),
            round_trip_quote=0.3,
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].exit_reason, "STOP_FIRST_COLLISION")
        self.assertLess(trades[0].net_r, -1.0)

    def test_registered_plan_has_independent_budget_per_side(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        plan = load_candidate_plan(
            (repository / "config" / "goldi-directional-candidates-v1.json").resolve()
        )
        bull = [candidate for candidate in plan.candidates if candidate.side == "BULL"]
        bear = [candidate for candidate in plan.candidates if candidate.side == "BEAR"]
        self.assertEqual(len(bull), 6)
        self.assertEqual(len(bear), 6)
        self.assertTrue(all(candidate.candidate_id.startswith("BULL_") for candidate in bull))
        self.assertTrue(all(candidate.candidate_id.startswith("BEAR_") for candidate in bear))
        self.assertEqual(len(plan.tweaks), 7)


if __name__ == "__main__":
    unittest.main()
