from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from goldm_signal.research_dataset import (
    ResearchDatasetError,
    load_dataset_source_evidence,
    load_registered_tick_dataset,
    register_offline_tick_dataset,
)
from goldm_signal.research_policy import (
    ResearchPurpose,
    StatisticalClassification,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _time_msc(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp() * 1000)


class GoldMResearchDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.dataset_path = self.root / "goldm-dev-d1-ticks.csv"
        self.manifest_path = self.root / "goldm-dev-d1-dataset.json"
        self.source_evidence_path = self.root / "goldm-dev-d1-source.json"
        self.authority_artifact_path = self.root / "approved-export-receipt.txt"
        self.authority_artifact_path.write_text(
            "independently-approved bounded offline export\n", encoding="utf-8"
        )
        warmup_start = datetime(2021, 1, 1, 12, tzinfo=timezone.utc)
        evaluation_start = datetime(2022, 2, 28, tzinfo=timezone.utc)
        warmup_days = (evaluation_start.date() - warmup_start.date()).days
        self.times = tuple(
            int((warmup_start + timedelta(days=index)).timestamp() * 1000)
            for index in range(warmup_days)
        ) + (
            _time_msc("2022-02-28T00:00:00+00:00"),
            _time_msc("2022-06-27T23:59:59+00:00"),
        )
        self._write_ticks(self.times)

    def _write_ticks(self, times: tuple[int, ...]) -> None:
        lines = ["time_msc,bid,ask,last,volume,flags,volume_real"]
        lines.extend(
            f"{value},1999.90,2000.10,0,1,6,1.0" for value in times
        )
        self.dataset_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _payload(self) -> dict[str, object]:
        source_evidence_sha256 = self._write_source_evidence()
        payload: dict[str, object] = {
            "schema_version": 2,
            "dataset_id": "goldm-dev-d1-ticks-v1",
            "registered_at": "2026-08-15T00:00:00Z",
            "purpose": "Development",
            "statistical_classification": "DEVELOPMENT_SELECTION",
            "custom_symbol": "GOLD_i_DEV_D1",
            "source_symbol": "GOLD.i#",
            "warmup_from_inclusive": "2021-01-01",
            "run_from_inclusive": "2022-02-28",
            "to_exclusive": "2022-06-28",
            "format": "MT5_TICKS_CSV_V1",
            "time_semantics": "UTC_HALF_OPEN",
            "row_count": len(self.times),
            "first_time_msc": self.times[0],
            "last_time_msc": self.times[-1],
            "dataset_path": str(self.dataset_path),
            "dataset_sha256": _sha256(self.dataset_path),
            "source_evidence_path": str(self.source_evidence_path),
            "source_evidence_sha256": source_evidence_sha256,
        }
        payload["manifest_sha256"] = _canonical_sha256(payload)
        return payload

    def _write_source_evidence(self) -> str:
        payload: dict[str, object] = {
            "schema_version": 1,
            "status": "APPROVED_BOUNDED_OFFLINE_SOURCE",
            "evidence_id": "approved-goldm-dev-d1-source",
            "attested_at": "2026-08-15T00:00:00Z",
            "provenance_kind": "TRUSTED_EXTERNAL_EXPORT",
            "authority": "GoldM test authority",
            "capture_method": "EXACT_BOUNDED_TICK_EXPORT",
            "purpose": "Development",
            "statistical_classification": "DEVELOPMENT_SELECTION",
            "source_symbol": "GOLD.i#",
            "warmup_from_inclusive": "2021-01-01",
            "run_from_inclusive": "2022-02-28",
            "to_exclusive": "2022-06-28",
            "dataset_path": str(self.dataset_path),
            "dataset_sha256": _sha256(self.dataset_path),
            "authority_artifact_path": str(self.authority_artifact_path),
            "authority_artifact_sha256": _sha256(self.authority_artifact_path),
        }
        payload["evidence_sha256"] = _canonical_sha256(payload)
        self.source_evidence_path.write_text(
            json.dumps(payload, sort_keys=True), encoding="utf-8"
        )
        return _sha256(self.source_evidence_path)

    def _write_manifest(self, payload: dict[str, object] | None = None) -> None:
        self.manifest_path.write_text(
            json.dumps(self._payload() if payload is None else payload, sort_keys=True),
            encoding="utf-8",
        )

    def _load(self):
        return load_registered_tick_dataset(
            self.manifest_path,
            expected_run_start=datetime(2022, 2, 28, tzinfo=timezone.utc),
            expected_end=datetime(2022, 6, 28, tzinfo=timezone.utc),
            expected_purpose=ResearchPurpose.DEVELOPMENT,
            expected_classification=(
                StatisticalClassification.DEVELOPMENT_SELECTION
            ),
        )

    def _rehash(self, payload: dict[str, object]) -> None:
        payload["manifest_sha256"] = _canonical_sha256(
            {key: value for key, value in payload.items() if key != "manifest_sha256"}
        )

    def test_registered_csv_is_hash_and_range_bound(self) -> None:
        self._write_manifest()
        dataset = self._load()
        self.assertEqual(dataset.custom_symbol, "GOLD_i_DEV_D1")
        self.assertEqual(dataset.source_symbol, "GOLD.i#")
        self.assertEqual(dataset.row_count, len(self.times))
        self.assertEqual(tuple(row.time_msc for row in dataset.rows), self.times)
        self.assertEqual(dataset.source_evidence_path, self.source_evidence_path)

        metadata_only = load_registered_tick_dataset(
            self.manifest_path,
            expected_run_start=datetime(2022, 2, 28, tzinfo=timezone.utc),
            expected_end=datetime(2022, 6, 28, tzinfo=timezone.utc),
            expected_purpose=ResearchPurpose.DEVELOPMENT,
            expected_classification=StatisticalClassification.DEVELOPMENT_SELECTION,
            include_rows=False,
        )
        self.assertEqual(metadata_only.row_count, len(self.times))
        self.assertEqual(metadata_only.rows, ())

    def test_legacy_manifest_is_read_only_and_rejected_for_production(self) -> None:
        payload = self._payload()
        payload["schema_version"] = 1
        payload.pop("source_evidence_path")
        payload.pop("source_evidence_sha256")
        self._rehash(payload)
        self._write_manifest(payload)
        legacy = self._load()
        self.assertIsNone(legacy.source_evidence_path)
        with self.assertRaisesRegex(ResearchDatasetError, "schema_version 2"):
            load_registered_tick_dataset(
                self.manifest_path,
                expected_run_start=datetime(2022, 2, 28, tzinfo=timezone.utc),
                expected_end=datetime(2022, 6, 28, tzinfo=timezone.utc),
                expected_purpose=ResearchPurpose.DEVELOPMENT,
                expected_classification=(
                    StatisticalClassification.DEVELOPMENT_SELECTION
                ),
                require_source_evidence=True,
            )

    def test_source_evidence_and_external_authority_are_hash_bound(self) -> None:
        self._write_manifest()
        approved_hash = _sha256(self.source_evidence_path)
        evidence = load_dataset_source_evidence(
            self.source_evidence_path, expected_sha256=approved_hash
        )
        self.assertEqual(evidence.dataset_sha256, _sha256(self.dataset_path))

        self.authority_artifact_path.write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(ResearchDatasetError, "authority artifact SHA-256"):
            self._load()

    def test_registration_copies_exact_bytes_and_never_overwrites(self) -> None:
        approved_hash = self._write_source_evidence()
        destination = self.root / "registered-ticks.csv"
        manifest = self.root / "registered-dataset.json"
        registered = register_offline_tick_dataset(
            source_evidence_path=self.source_evidence_path,
            expected_source_evidence_sha256=approved_hash,
            destination_dataset_path=destination,
            manifest_path=manifest,
            dataset_id="registered-goldm-dev-d1",
            custom_symbol="GOLD_i_DEV_D1",
            registered_at="2026-08-15T01:00:00Z",
        )
        self.assertEqual(destination.read_bytes(), self.dataset_path.read_bytes())
        self.assertEqual(registered.source_evidence_sha256, approved_hash)
        with self.assertRaisesRegex(ResearchDatasetError, "must not already exist"):
            register_offline_tick_dataset(
                source_evidence_path=self.source_evidence_path,
                expected_source_evidence_sha256=approved_hash,
                destination_dataset_path=destination,
                manifest_path=self.root / "second-manifest.json",
                dataset_id="registered-goldm-dev-d2",
                custom_symbol="GOLD_i_DEV_D2",
            )

    def test_registration_script_has_no_mt5_or_network_reader(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "register-goldm-research-dataset.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("MetaTrader5", source)
        self.assertNotIn("copy_ticks", source.casefold())
        self.assertNotIn("copy_rates", source.casefold())
        self.assertNotIn("requests", source)

    def test_failed_registration_leaves_no_partial_outputs(self) -> None:
        self.dataset_path.write_text(
            "time_msc,bid,ask,last,volume,flags,volume_real\n"
            "1640995200000,2000.10,1999.90,0,1,6,1\n",
            encoding="utf-8",
        )
        approved_hash = self._write_source_evidence()
        destination = self.root / "rejected-ticks.csv"
        manifest = self.root / "rejected-dataset.json"
        with self.assertRaisesRegex(ResearchDatasetError, "ask is below bid"):
            register_offline_tick_dataset(
                source_evidence_path=self.source_evidence_path,
                expected_source_evidence_sha256=approved_hash,
                destination_dataset_path=destination,
                manifest_path=manifest,
                dataset_id="rejected-goldm-dev-d1",
                custom_symbol="GOLD_i_DEV_D1",
            )
        self.assertFalse(destination.exists())
        self.assertFalse(manifest.exists())
        self.assertEqual(list(self.root.glob(".*.tmp")), [])

    def test_dataset_or_manifest_tampering_is_rejected(self) -> None:
        self._write_manifest()
        self.dataset_path.write_text(
            self.dataset_path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ResearchDatasetError, "dataset SHA-256"):
            self._load()

        self._write_ticks(self.times)
        payload = self._payload()
        payload["row_count"] = 4
        self._write_manifest(payload)
        with self.assertRaisesRegex(ResearchDatasetError, "manifest SHA-256"):
            self._load()

    def test_sorted_rows_and_registered_bounds_are_verified_from_csv(self) -> None:
        unsorted = (self.times[1], self.times[0], *self.times[2:])
        self._write_ticks(unsorted)
        payload = self._payload()
        payload["dataset_sha256"] = _sha256(self.dataset_path)
        payload["first_time_msc"] = self.times[1]
        self._rehash(payload)
        self._write_manifest(payload)
        with self.assertRaisesRegex(ResearchDatasetError, "not time ordered"):
            self._load()

        self._write_ticks(self.times)
        payload = self._payload()
        payload["last_time_msc"] = self.times[-1] - 1
        self._rehash(payload)
        self._write_manifest(payload)
        with self.assertRaisesRegex(ResearchDatasetError, "registered bounds"):
            self._load()

    def test_source_symbol_reuse_and_quarantine_overlap_fail_closed(self) -> None:
        payload = self._payload()
        payload["custom_symbol"] = "GOLD.i#"
        self._rehash(payload)
        self._write_manifest(payload)
        with self.assertRaisesRegex(ResearchDatasetError, "must not reuse"):
            self._load()

        payload = self._payload()
        payload.update(
            {
                "warmup_from_inclusive": "2026-02-27",
                "run_from_inclusive": "2026-03-01",
                "to_exclusive": "2026-06-01",
            }
        )
        self._rehash(payload)
        self._write_manifest(payload)
        with self.assertRaisesRegex(ValueError, "protected quarantine"):
            load_registered_tick_dataset(
                self.manifest_path,
                expected_run_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
                expected_end=datetime(2026, 6, 1, tzinfo=timezone.utc),
                expected_purpose=ResearchPurpose.DEVELOPMENT,
                expected_classification=(
                    StatisticalClassification.DEVELOPMENT_SELECTION
                ),
            )

    def test_empty_warmup_and_rows_outside_half_open_end_are_rejected(self) -> None:
        no_warmup = (self.times[-2], self.times[-1])
        self._write_ticks(no_warmup)
        payload = self._payload()
        payload.update(
            {
                "row_count": 2,
                "first_time_msc": no_warmup[0],
                "last_time_msc": no_warmup[-1],
                "dataset_sha256": _sha256(self.dataset_path),
            }
        )
        self._rehash(payload)
        self._write_manifest(payload)
        with self.assertRaisesRegex(ResearchDatasetError, "warmup contains no rows"):
            self._load()

        outside = (self.times[0], self.times[1], _time_msc("2022-06-28T00:00:00+00:00"))
        self._write_ticks(outside)
        payload = self._payload()
        payload.update(
            {
                "row_count": len(outside),
                "first_time_msc": outside[0],
                "last_time_msc": outside[-1],
                "dataset_sha256": _sha256(self.dataset_path),
            }
        )
        self._rehash(payload)
        self._write_manifest(payload)
        with self.assertRaisesRegex(ResearchDatasetError, "half-open"):
            self._load()


if __name__ == "__main__":
    unittest.main()
