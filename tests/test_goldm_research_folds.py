from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from goldm_signal.research_folds import (
    ResearchFoldError,
    load_registered_fold_plan,
    partition_registered_timestamps,
)
from goldm_signal.research_policy import (
    ResearchPurpose,
    StatisticalClassification,
)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class GoldMResearchFoldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / "registered-fold-plan.json"

    def _payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": 1,
            "plan_id": "goldm-dev-d1-folds-v1",
            "registered_at": "2026-08-15T00:00:00Z",
            "purpose": "Development",
            "statistical_classification": "DEVELOPMENT_SELECTION",
            "from_inclusive": "2022-02-28",
            "to_exclusive": "2022-06-28",
            "folds": [
                {
                    "name": "train",
                    "role": "SELECTION",
                    "from_inclusive": "2022-02-28",
                    "to_exclusive": "2022-04-01",
                },
                {
                    "name": "validation_1",
                    "role": "INTERNAL_VALIDATION",
                    "from_inclusive": "2022-04-01",
                    "to_exclusive": "2022-05-01",
                },
                {
                    "name": "validation_2",
                    "role": "INTERNAL_VALIDATION",
                    "from_inclusive": "2022-05-01",
                    "to_exclusive": "2022-06-28",
                },
            ],
        }
        payload["plan_sha256"] = _canonical_sha256(payload)
        return payload

    def _write(self, payload: dict[str, object] | None = None) -> Path:
        selected = self._payload() if payload is None else payload
        self.path.write_text(json.dumps(selected, sort_keys=True), encoding="utf-8")
        return self.path

    def _load(self):
        return load_registered_fold_plan(
            self.path,
            expected_start=datetime(2022, 2, 28, tzinfo=timezone.utc),
            expected_end=datetime(2022, 6, 28, tzinfo=timezone.utc),
            expected_purpose=ResearchPurpose.DEVELOPMENT,
            expected_classification=(
                StatisticalClassification.DEVELOPMENT_SELECTION
            ),
        )

    def test_registered_folds_partition_every_row_once(self) -> None:
        self._write()
        plan = self._load()
        masks = partition_registered_timestamps(
            (
                datetime(2022, 3, 1, tzinfo=timezone.utc),
                datetime(2022, 4, 15, tzinfo=timezone.utc),
                datetime(2022, 6, 1, tzinfo=timezone.utc),
            ),
            plan,
        )
        self.assertEqual(tuple(masks), ("train", "validation_1", "validation_2"))
        self.assertEqual(masks["train"], (True, False, False))
        self.assertEqual(masks["validation_1"], (False, True, False))
        self.assertEqual(masks["validation_2"], (False, False, True))

    def test_digest_tampering_is_rejected(self) -> None:
        payload = self._payload()
        payload["to_exclusive"] = "2022-06-27"
        self._write(payload)
        with self.assertRaisesRegex(ResearchFoldError, "SHA-256"):
            self._load()

    def test_gap_overlap_and_empty_fold_are_rejected(self) -> None:
        for replacement in ("2022-04-02", "2022-03-31", "2022-04-01"):
            with self.subTest(replacement=replacement):
                payload = self._payload()
                folds = payload["folds"]
                assert isinstance(folds, list)
                second = folds[1]
                assert isinstance(second, dict)
                second["from_inclusive"] = replacement
                if replacement == "2022-04-01":
                    second["to_exclusive"] = replacement
                payload["plan_sha256"] = _canonical_sha256(
                    {key: value for key, value in payload.items() if key != "plan_sha256"}
                )
                self._write(payload)
                with self.assertRaises(ResearchFoldError):
                    self._load()

    def test_quarantine_fold_plan_is_rejected_by_policy(self) -> None:
        payload = self._payload()
        payload["from_inclusive"] = "2026-03-01"
        payload["to_exclusive"] = "2026-06-01"
        folds = payload["folds"]
        assert isinstance(folds, list)
        boundaries = (
            ("2026-03-01", "2026-04-01"),
            ("2026-04-01", "2026-05-01"),
            ("2026-05-01", "2026-06-01"),
        )
        for fold, (start, end) in zip(folds, boundaries, strict=True):
            assert isinstance(fold, dict)
            fold["from_inclusive"] = start
            fold["to_exclusive"] = end
        payload["plan_sha256"] = _canonical_sha256(
            {key: value for key, value in payload.items() if key != "plan_sha256"}
        )
        self._write(payload)
        with self.assertRaisesRegex(ValueError, "protected quarantine"):
            load_registered_fold_plan(
                self.path,
                expected_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
                expected_end=datetime(2026, 6, 1, tzinfo=timezone.utc),
                expected_purpose=ResearchPurpose.DEVELOPMENT,
                expected_classification=(
                    StatisticalClassification.DEVELOPMENT_SELECTION
                ),
            )

    def test_empty_outside_or_missing_fold_rows_fail_closed(self) -> None:
        self._write()
        plan = self._load()
        with self.assertRaisesRegex(ResearchFoldError, "empty"):
            partition_registered_timestamps((), plan)
        with self.assertRaisesRegex(ResearchFoldError, "outside"):
            partition_registered_timestamps(
                (datetime(2022, 6, 28, tzinfo=timezone.utc),), plan
            )
        with self.assertRaisesRegex(ResearchFoldError, "validation_1"):
            partition_registered_timestamps(
                (
                    datetime(2022, 3, 1, tzinfo=timezone.utc),
                    datetime(2022, 6, 1, tzinfo=timezone.utc),
                ),
                plan,
            )


if __name__ == "__main__":
    unittest.main()
