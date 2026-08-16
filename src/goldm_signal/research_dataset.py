from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from typing import Iterable

from .research_policy import (
    ResearchPurpose,
    StatisticalClassification,
    assert_research_range,
    load_research_policy,
    parse_research_date,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,95}\Z")
_SYMBOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._#-]{1,62}\Z")
_TICK_COLUMNS = (
    "time_msc",
    "bid",
    "ask",
    "last",
    "volume",
    "flags",
    "volume_real",
)


class ResearchDatasetError(RuntimeError):
    """Raised when a bounded offline dataset cannot be proven safe and immutable."""


@dataclass(frozen=True, slots=True)
class OfflineTick:
    time_msc: int
    bid: float
    ask: float
    last: float
    volume: int
    flags: int
    volume_real: float


@dataclass(frozen=True, slots=True)
class RegisteredTickDataset:
    dataset_id: str
    registered_at: str
    purpose: ResearchPurpose
    statistical_classification: StatisticalClassification
    custom_symbol: str
    source_symbol: str
    warmup_start: datetime
    run_start: datetime
    end: datetime
    row_count: int
    first_time_msc: int
    last_time_msc: int
    dataset_path: Path
    dataset_sha256: str
    manifest_path: Path
    manifest_sha256: str
    source_evidence_path: Path | None
    source_evidence_sha256: str | None
    rows: tuple[OfflineTick, ...]


@dataclass(frozen=True, slots=True)
class DatasetSourceEvidence:
    evidence_id: str
    attested_at: str
    provenance_kind: str
    authority: str
    capture_method: str
    purpose: ResearchPurpose
    statistical_classification: StatisticalClassification
    source_symbol: str
    warmup_start: datetime
    run_start: datetime
    end: datetime
    dataset_path: Path
    dataset_sha256: str
    authority_artifact_path: Path
    authority_artifact_sha256: str
    evidence_path: Path
    evidence_sha256: str


def load_registered_tick_dataset(
    manifest_path: Path,
    *,
    expected_run_start: datetime,
    expected_end: datetime,
    expected_purpose: ResearchPurpose | str,
    expected_classification: StatisticalClassification | str,
    require_exact_run_range: bool = True,
    require_source_evidence: bool = False,
    include_rows: bool = True,
) -> RegisteredTickDataset:
    """Load and fully verify an immutable, half-open, offline tick dataset.

    The CSV is deliberately streamed and checked instead of trusting row bounds
    declared by its manifest. This is intended to run only after the range has
    been authorized; callers must never point it at broker cache/history files.
    """

    canonical_manifest = _canonical_file(manifest_path, "dataset manifest")
    try:
        payload = json.loads(canonical_manifest.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchDatasetError(
            f"dataset manifest is not valid UTF-8 JSON: {canonical_manifest}"
        ) from exc
    required_v1 = {
        "schema_version",
        "dataset_id",
        "registered_at",
        "purpose",
        "statistical_classification",
        "custom_symbol",
        "source_symbol",
        "warmup_from_inclusive",
        "run_from_inclusive",
        "to_exclusive",
        "format",
        "time_semantics",
        "row_count",
        "first_time_msc",
        "last_time_msc",
        "dataset_path",
        "dataset_sha256",
        "manifest_sha256",
    }
    required_v2 = required_v1 | {
        "source_evidence_path",
        "source_evidence_sha256",
    }
    if not isinstance(payload, dict) or payload.get("schema_version") not in (1, 2):
        raise ResearchDatasetError("unsupported dataset manifest schema_version")
    schema_version = payload["schema_version"]
    expected_fields = required_v1 if schema_version == 1 else required_v2
    if set(payload) != expected_fields:
        raise ResearchDatasetError(
            f"dataset manifest must use schema_version {schema_version} with exact fields"
        )
    if require_source_evidence and schema_version != 2:
        raise ResearchDatasetError(
            "production dataset use requires schema_version 2 source evidence"
        )
    supplied_manifest_hash = payload["manifest_sha256"]
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256")
    if not isinstance(supplied_manifest_hash, str) or not _SHA256.fullmatch(
        supplied_manifest_hash
    ):
        raise ResearchDatasetError("dataset manifest SHA-256 is invalid")
    if _canonical_sha256(unsigned) != supplied_manifest_hash:
        raise ResearchDatasetError(
            "dataset manifest SHA-256 does not match its immutable payload"
        )

    dataset_id = payload["dataset_id"]
    if not isinstance(dataset_id, str) or not _TOKEN.fullmatch(dataset_id):
        raise ResearchDatasetError("dataset_id must be a structured token")
    registered_at = _strict_utc_timestamp(payload["registered_at"], "registered_at")
    try:
        purpose = ResearchPurpose(payload["purpose"])
        classification = StatisticalClassification(
            payload["statistical_classification"]
        )
        required_purpose = ResearchPurpose(expected_purpose)
        required_classification = StatisticalClassification(expected_classification)
    except (TypeError, ValueError) as exc:
        raise ResearchDatasetError("dataset purpose/classification is invalid") from exc
    if purpose is not required_purpose or classification is not required_classification:
        raise ResearchDatasetError(
            "dataset purpose/classification does not match the authorized run"
        )

    custom_symbol = payload["custom_symbol"]
    source_symbol = payload["source_symbol"]
    if (
        not isinstance(custom_symbol, str)
        or not _SYMBOL.fullmatch(custom_symbol)
        or not isinstance(source_symbol, str)
        or not _SYMBOL.fullmatch(source_symbol)
    ):
        raise ResearchDatasetError("custom/source symbol is invalid")
    if custom_symbol.casefold() == source_symbol.casefold():
        raise ResearchDatasetError(
            "custom symbol must not reuse the broker source-symbol name"
        )
    if payload["format"] != "MT5_TICKS_CSV_V1" or payload["time_semantics"] != (
        "UTC_HALF_OPEN"
    ):
        raise ResearchDatasetError(
            "dataset must use MT5_TICKS_CSV_V1 with UTC_HALF_OPEN semantics"
        )

    warmup_start = parse_research_date(
        payload["warmup_from_inclusive"], field="warmup_from_inclusive"
    )
    run_start = parse_research_date(
        payload["run_from_inclusive"], field="run_from_inclusive"
    )
    end = parse_research_date(payload["to_exclusive"], field="to_exclusive")
    expected_run_start = _as_utc(expected_run_start, "expected_run_start")
    expected_end = _as_utc(expected_end, "expected_end")
    if require_exact_run_range and (
        run_start != expected_run_start or end != expected_end
    ):
        raise ResearchDatasetError(
            "dataset selection range does not exactly match the authorized run"
        )
    if not require_exact_run_range and (
        run_start > expected_run_start or end < expected_end
    ):
        raise ResearchDatasetError(
            "dataset selection range does not cover the authorized run"
        )
    if warmup_start > run_start:
        raise ResearchDatasetError("dataset warmup begins after the run")
    assert_research_range(
        run_start,
        end,
        purpose=purpose,
        statistical_classification=classification,
        label=f"offline dataset/{dataset_id}",
    )
    policy = load_research_policy()
    quarantine_start = parse_research_date(
        policy["quarantine"]["from"], field="quarantine.from"
    )
    quarantine_end = parse_research_date(
        policy["quarantine"]["to"], field="quarantine.to"
    )
    if warmup_start < quarantine_end and end > quarantine_start:
        raise ResearchDatasetError(
            "offline dataset warmup+run interval intersects protected quarantine"
        )
    if purpose is ResearchPurpose.DEVELOPMENT and run_start == parse_research_date(
        policy["development"]["from"], field="development.from"
    ):
        registered_minimum_warmup = parse_research_date(
            policy["development"].get("warmup_from"),
            field="development.warmup_from",
        )
        if warmup_start > registered_minimum_warmup:
            raise ResearchDatasetError(
                "Development dataset warmup must start no later than the registered "
                f"{registered_minimum_warmup.date()} context boundary"
            )

    dataset_path_value = payload["dataset_path"]
    if not isinstance(dataset_path_value, str):
        raise ResearchDatasetError("dataset_path must be an explicit string")
    dataset_path = _canonical_file(Path(dataset_path_value), "tick dataset")
    if dataset_path == canonical_manifest:
        raise ResearchDatasetError("dataset and manifest paths must be distinct")
    dataset_sha256 = payload["dataset_sha256"]
    if not isinstance(dataset_sha256, str) or not _SHA256.fullmatch(dataset_sha256):
        raise ResearchDatasetError("dataset SHA-256 is invalid")
    observed_dataset_hash = _sha256_file(dataset_path)
    if observed_dataset_hash != dataset_sha256:
        raise ResearchDatasetError("tick dataset SHA-256 does not match its manifest")

    source_evidence: DatasetSourceEvidence | None = None
    if schema_version == 2:
        source_evidence_path_value = payload["source_evidence_path"]
        source_evidence_sha256 = payload["source_evidence_sha256"]
        if not isinstance(source_evidence_path_value, str):
            raise ResearchDatasetError("source_evidence_path must be an explicit string")
        source_evidence_path = _canonical_file(
            Path(source_evidence_path_value), "dataset source evidence"
        )
        if source_evidence_path in (canonical_manifest, dataset_path):
            raise ResearchDatasetError(
                "dataset source evidence must be distinct from dataset and manifest"
            )
        if (
            not isinstance(source_evidence_sha256, str)
            or not _SHA256.fullmatch(source_evidence_sha256)
            or _sha256_file(source_evidence_path) != source_evidence_sha256
        ):
            raise ResearchDatasetError(
                "dataset source evidence SHA-256 does not match its manifest"
            )
        source_evidence = load_dataset_source_evidence(
            source_evidence_path,
            expected_sha256=source_evidence_sha256,
        )
        if (
            source_evidence.dataset_sha256 != dataset_sha256
            or source_evidence.source_symbol != source_symbol
            or source_evidence.purpose is not purpose
            or source_evidence.statistical_classification is not classification
            or source_evidence.warmup_start != warmup_start
            or source_evidence.run_start != run_start
            or source_evidence.end != end
        ):
            raise ResearchDatasetError(
                "dataset source evidence does not exactly match the registered dataset"
            )

    row_count = payload["row_count"]
    first_time_msc = payload["first_time_msc"]
    last_time_msc = payload["last_time_msc"]
    for field_name, value in (
        ("row_count", row_count),
        ("first_time_msc", first_time_msc),
        ("last_time_msc", last_time_msc),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ResearchDatasetError(f"{field_name} must be a non-negative integer")
    if row_count <= 0:
        raise ResearchDatasetError("offline tick dataset must not be empty")
    if first_time_msc > last_time_msc:
        raise ResearchDatasetError("dataset timestamp bounds are reversed")

    if not isinstance(include_rows, bool):
        raise ResearchDatasetError("include_rows must be boolean")
    collected_rows: list[OfflineTick] = []
    observed_count = 0
    observed_first: int | None = None
    observed_last: int | None = None
    warmup_days: set[date] = set()
    latest_warmup_msc = -1
    warmup_msc = _epoch_milliseconds(warmup_start)
    run_msc = _epoch_milliseconds(run_start)
    end_msc = _epoch_milliseconds(end)
    for row in _read_and_validate_ticks(dataset_path):
        observed_count += 1
        if observed_first is None:
            observed_first = row.time_msc
        observed_last = row.time_msc
        if row.time_msc < run_msc:
            warmup_days.add(
                datetime.fromtimestamp(row.time_msc / 1000, tz=timezone.utc).date()
            )
            latest_warmup_msc = max(latest_warmup_msc, row.time_msc)
        if include_rows:
            collected_rows.append(row)
    if _sha256_file(dataset_path) != observed_dataset_hash:
        raise ResearchDatasetError("tick dataset changed while it was being validated")
    if source_evidence is not None and (
        _sha256_file(source_evidence.evidence_path) != source_evidence.evidence_sha256
    ):
        raise ResearchDatasetError(
            "dataset source evidence changed while the dataset was being validated"
        )
    if observed_count != row_count:
        raise ResearchDatasetError(
            f"dataset row_count mismatch: declared {row_count}, observed {observed_count}"
        )
    if observed_first != first_time_msc or observed_last != last_time_msc:
        raise ResearchDatasetError(
            "dataset first/last time_msc do not match the registered bounds"
        )
    if not (warmup_msc <= first_time_msc <= last_time_msc < end_msc):
        raise ResearchDatasetError(
            "dataset rows leave the registered half-open warmup+run interval"
        )
    if last_time_msc < run_msc:
        raise ResearchDatasetError("dataset contains no rows in the authorized run")
    if warmup_start < run_start and first_time_msc >= run_msc:
        raise ResearchDatasetError("declared warmup contains no rows before the run")
    if purpose is ResearchPurpose.DEVELOPMENT and run_start == parse_research_date(
        policy["development"]["from"], field="development.from"
    ):
        if len(warmup_days) < 200:
            raise ResearchDatasetError(
                "Development dataset has fewer than 200 distinct UTC warmup days"
            )
        if latest_warmup_msc < _epoch_milliseconds(run_start - timedelta(days=7)):
            raise ResearchDatasetError(
                "Development dataset warmup does not reach the seven days before evaluation"
            )

    return RegisteredTickDataset(
        dataset_id=dataset_id,
        registered_at=registered_at,
        purpose=purpose,
        statistical_classification=classification,
        custom_symbol=custom_symbol,
        source_symbol=source_symbol,
        warmup_start=warmup_start,
        run_start=run_start,
        end=end,
        row_count=row_count,
        first_time_msc=first_time_msc,
        last_time_msc=last_time_msc,
        dataset_path=dataset_path,
        dataset_sha256=dataset_sha256,
        manifest_path=canonical_manifest,
        manifest_sha256=supplied_manifest_hash,
        source_evidence_path=(
            source_evidence.evidence_path if source_evidence is not None else None
        ),
        source_evidence_sha256=(
            source_evidence.evidence_sha256 if source_evidence is not None else None
        ),
        rows=tuple(collected_rows),
    )


def load_dataset_source_evidence(
    evidence_path: Path,
    *,
    expected_sha256: str,
) -> DatasetSourceEvidence:
    """Verify an independently approved source-attestation artifact.

    ``expected_sha256`` is deliberately mandatory: callers must obtain it from
    an approval channel distinct from the evidence file itself.  This function
    binds that trust root to the exact tick bytes and authority artifact; it
    does not manufacture or self-approve source provenance.
    """

    canonical = _canonical_file(evidence_path, "dataset source evidence")
    if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256):
        raise ResearchDatasetError("expected source evidence SHA-256 is invalid")
    observed_hash = _sha256_file(canonical)
    if observed_hash != expected_sha256:
        raise ResearchDatasetError("dataset source evidence SHA-256 is not approved")
    try:
        payload = json.loads(canonical.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchDatasetError("dataset source evidence is not valid UTF-8 JSON") from exc
    required = {
        "schema_version",
        "status",
        "evidence_id",
        "attested_at",
        "provenance_kind",
        "authority",
        "capture_method",
        "purpose",
        "statistical_classification",
        "source_symbol",
        "warmup_from_inclusive",
        "run_from_inclusive",
        "to_exclusive",
        "dataset_path",
        "dataset_sha256",
        "authority_artifact_path",
        "authority_artifact_sha256",
        "evidence_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ResearchDatasetError("dataset source evidence fields are incomplete")
    if payload["schema_version"] != 1 or payload["status"] != (
        "APPROVED_BOUNDED_OFFLINE_SOURCE"
    ):
        raise ResearchDatasetError("dataset source evidence status/schema is invalid")
    supplied_hash = payload["evidence_sha256"]
    unsigned = dict(payload)
    unsigned.pop("evidence_sha256")
    if (
        not isinstance(supplied_hash, str)
        or not _SHA256.fullmatch(supplied_hash)
        or _canonical_sha256(unsigned) != supplied_hash
    ):
        raise ResearchDatasetError("dataset source evidence self-hash is invalid")
    evidence_id = payload["evidence_id"]
    if not isinstance(evidence_id, str) or not _TOKEN.fullmatch(evidence_id):
        raise ResearchDatasetError("dataset source evidence_id is invalid")
    attested_at = _strict_utc_timestamp(payload["attested_at"], "attested_at")
    provenance_kind = payload["provenance_kind"]
    if provenance_kind not in {"SEALED_OFFLINE_EXPORT", "TRUSTED_EXTERNAL_EXPORT"}:
        raise ResearchDatasetError("dataset source provenance_kind is invalid")
    authority = payload["authority"]
    if not isinstance(authority, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._ /:@-]{2,127}", authority
    ):
        raise ResearchDatasetError("dataset source authority is invalid")
    capture_method = payload["capture_method"]
    if not isinstance(capture_method, str) or not _TOKEN.fullmatch(capture_method):
        raise ResearchDatasetError("dataset source capture_method is invalid")
    try:
        purpose = ResearchPurpose(payload["purpose"])
        classification = StatisticalClassification(
            payload["statistical_classification"]
        )
    except (TypeError, ValueError) as exc:
        raise ResearchDatasetError(
            "dataset source purpose/classification is invalid"
        ) from exc
    source_symbol = payload["source_symbol"]
    if not isinstance(source_symbol, str) or not _SYMBOL.fullmatch(source_symbol):
        raise ResearchDatasetError("dataset source symbol is invalid")
    warmup_start = parse_research_date(
        payload["warmup_from_inclusive"], field="warmup_from_inclusive"
    )
    run_start = parse_research_date(
        payload["run_from_inclusive"], field="run_from_inclusive"
    )
    end = parse_research_date(payload["to_exclusive"], field="to_exclusive")
    if warmup_start > run_start:
        raise ResearchDatasetError("dataset source warmup begins after the run")
    assert_research_range(
        run_start,
        end,
        purpose=purpose,
        statistical_classification=classification,
        label=f"dataset source evidence/{evidence_id}",
    )
    policy = load_research_policy()
    quarantine_start = parse_research_date(
        policy["quarantine"]["from"], field="quarantine.from"
    )
    quarantine_end = parse_research_date(
        policy["quarantine"]["to"], field="quarantine.to"
    )
    if warmup_start < quarantine_end and end > quarantine_start:
        raise ResearchDatasetError(
            "dataset source interval intersects protected quarantine"
        )
    dataset_path_value = payload["dataset_path"]
    authority_path_value = payload["authority_artifact_path"]
    if not isinstance(dataset_path_value, str) or not isinstance(
        authority_path_value, str
    ):
        raise ResearchDatasetError("dataset source paths must be explicit strings")
    source_path = _canonical_file(Path(dataset_path_value), "source tick dataset")
    dataset_sha256 = payload["dataset_sha256"]
    if (
        not isinstance(dataset_sha256, str)
        or not _SHA256.fullmatch(dataset_sha256)
        or _sha256_file(source_path) != dataset_sha256
    ):
        raise ResearchDatasetError("source tick dataset SHA-256 is invalid")
    authority_artifact = _canonical_file(
        Path(authority_path_value), "source authority artifact"
    )
    authority_sha256 = payload["authority_artifact_sha256"]
    if source_path == canonical or authority_artifact in (canonical, source_path):
        raise ResearchDatasetError(
            "source dataset, evidence, and authority artifact must be independent"
        )
    if (
        not isinstance(authority_sha256, str)
        or not _SHA256.fullmatch(authority_sha256)
        or _sha256_file(authority_artifact) != authority_sha256
    ):
        raise ResearchDatasetError("source authority artifact SHA-256 is invalid")
    if _sha256_file(canonical) != observed_hash:
        raise ResearchDatasetError("dataset source evidence changed during validation")
    if _sha256_file(source_path) != dataset_sha256:
        raise ResearchDatasetError("source tick dataset changed during validation")
    if _sha256_file(authority_artifact) != authority_sha256:
        raise ResearchDatasetError("source authority artifact changed during validation")
    return DatasetSourceEvidence(
        evidence_id=evidence_id,
        attested_at=attested_at,
        provenance_kind=provenance_kind,
        authority=authority,
        capture_method=capture_method,
        purpose=purpose,
        statistical_classification=classification,
        source_symbol=source_symbol,
        warmup_start=warmup_start,
        run_start=run_start,
        end=end,
        dataset_path=source_path,
        dataset_sha256=dataset_sha256,
        authority_artifact_path=authority_artifact,
        authority_artifact_sha256=authority_sha256,
        evidence_path=canonical,
        evidence_sha256=observed_hash,
    )


def register_offline_tick_dataset(
    *,
    source_evidence_path: Path,
    expected_source_evidence_sha256: str,
    destination_dataset_path: Path,
    manifest_path: Path,
    dataset_id: str,
    custom_symbol: str,
    registered_at: str | None = None,
) -> RegisteredTickDataset:
    """Copy and register approved tick bytes without accessing MT5 or a broker."""

    source = load_dataset_source_evidence(
        source_evidence_path,
        expected_sha256=expected_source_evidence_sha256,
    )
    if not isinstance(dataset_id, str) or not _TOKEN.fullmatch(dataset_id):
        raise ResearchDatasetError("dataset_id must be a structured token")
    if not isinstance(custom_symbol, str) or not _SYMBOL.fullmatch(custom_symbol):
        raise ResearchDatasetError("custom_symbol is invalid")
    if custom_symbol.casefold() == source.source_symbol.casefold():
        raise ResearchDatasetError(
            "custom symbol must not reuse the broker source-symbol name"
        )
    destination = _new_absolute_file_path(destination_dataset_path, "destination dataset")
    manifest = _new_absolute_file_path(manifest_path, "dataset manifest")
    if len({source.dataset_path, source.evidence_path, destination, manifest}) != 4:
        raise ResearchDatasetError("source, evidence, destination, and manifest must differ")
    timestamp = registered_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    _strict_utc_timestamp(timestamp, "registered_at")
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    created: list[Path] = []
    try:
        digest = hashlib.sha256()
        with source.dataset_path.open("rb") as input_handle, temporary.open("xb") as output:
            for chunk in iter(lambda: input_handle.read(1024 * 1024), b""):
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest() != source.dataset_sha256:
            raise ResearchDatasetError("source tick dataset changed during registration")
        os.link(temporary, destination)
        created.append(destination)
        temporary.unlink()
        row_count = 0
        first_time_msc: int | None = None
        last_time_msc: int | None = None
        for row in _read_and_validate_ticks(destination):
            row_count += 1
            if first_time_msc is None:
                first_time_msc = row.time_msc
            last_time_msc = row.time_msc
        if row_count == 0 or first_time_msc is None or last_time_msc is None:
            raise ResearchDatasetError("offline tick dataset must not be empty")
        payload: dict[str, object] = {
            "schema_version": 2,
            "dataset_id": dataset_id,
            "registered_at": timestamp,
            "purpose": source.purpose.value,
            "statistical_classification": source.statistical_classification.value,
            "custom_symbol": custom_symbol,
            "source_symbol": source.source_symbol,
            "warmup_from_inclusive": source.warmup_start.date().isoformat(),
            "run_from_inclusive": source.run_start.date().isoformat(),
            "to_exclusive": source.end.date().isoformat(),
            "format": "MT5_TICKS_CSV_V1",
            "time_semantics": "UTC_HALF_OPEN",
            "row_count": row_count,
            "first_time_msc": first_time_msc,
            "last_time_msc": last_time_msc,
            "dataset_path": str(destination),
            "dataset_sha256": source.dataset_sha256,
            "source_evidence_path": str(source.evidence_path),
            "source_evidence_sha256": source.evidence_sha256,
        }
        payload["manifest_sha256"] = _canonical_sha256(payload)
        encoded = (
            json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
            + "\n"
        ).encode("utf-8")
        with manifest.open("xb") as handle:
            created.append(manifest)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        return load_registered_tick_dataset(
            manifest,
            expected_run_start=source.run_start,
            expected_end=source.end,
            expected_purpose=source.purpose,
            expected_classification=source.statistical_classification,
            require_source_evidence=True,
        )
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
        raise


def _new_absolute_file_path(path: Path, label: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ResearchDatasetError(f"{label} path must be absolute")
    if path.exists():
        raise ResearchDatasetError(f"{label} must not already exist")
    parent = path.parent
    if not parent.is_dir() or parent.resolve(strict=True) != parent:
        raise ResearchDatasetError(f"{label} parent must be an existing canonical directory")
    return path


def _read_and_validate_ticks(path: Path) -> Iterable[OfflineTick]:
    previous_time: int | None = None
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or tuple(reader.fieldnames) != _TICK_COLUMNS:
                raise ResearchDatasetError(
                    f"tick CSV header must be exactly {','.join(_TICK_COLUMNS)}"
                )
            for line_number, raw in enumerate(reader, start=2):
                if None in raw or any(value is None for value in raw.values()):
                    raise ResearchDatasetError(
                        f"tick CSV line {line_number} has missing/extra columns"
                    )
                try:
                    tick = OfflineTick(
                        time_msc=_strict_integer(raw["time_msc"], "time_msc"),
                        bid=_strict_float(raw["bid"], "bid"),
                        ask=_strict_float(raw["ask"], "ask"),
                        last=_strict_float(raw["last"], "last", allow_zero=True),
                        volume=_strict_integer(raw["volume"], "volume"),
                        flags=_strict_integer(raw["flags"], "flags"),
                        volume_real=_strict_float(
                            raw["volume_real"], "volume_real", allow_zero=True
                        ),
                    )
                except ResearchDatasetError as exc:
                    raise ResearchDatasetError(
                        f"invalid tick CSV line {line_number}: {exc}"
                    ) from exc
                if (
                    tick.time_msc < 0
                    or tick.time_msc > 9_223_372_036_854_775_807
                    or tick.volume < 0
                    # The importer deliberately uses MQL5's signed canonical
                    # integer parser before assigning to MqlTick.volume.
                    or tick.volume > 9_223_372_036_854_775_807
                    or tick.flags < 0
                    or tick.flags > 4_294_967_295
                ):
                    raise ResearchDatasetError(
                        f"invalid tick CSV line {line_number}: integer value is outside MqlTick bounds"
                    )
                if tick.ask < tick.bid:
                    raise ResearchDatasetError(
                        f"invalid tick CSV line {line_number}: ask is below bid"
                    )
                if previous_time is not None and tick.time_msc < previous_time:
                    raise ResearchDatasetError(
                        f"invalid tick CSV line {line_number}: ticks are not time ordered"
                    )
                previous_time = tick.time_msc
                yield tick
    except UnicodeError as exc:
        raise ResearchDatasetError("tick dataset must be UTF-8 CSV") from exc


def _strict_integer(value: str, label: str) -> int:
    if not re.fullmatch(r"0|[1-9][0-9]*", value):
        raise ResearchDatasetError(f"{label} is not a canonical integer")
    return int(value)


def _strict_float(value: str, label: str, *, allow_zero: bool = False) -> float:
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
        raise ResearchDatasetError(f"{label} is not a canonical non-negative number")
    parsed = float(value)
    if not isfinite(parsed) or (parsed < 0 if allow_zero else parsed <= 0):
        comparator = "non-negative" if allow_zero else "positive"
        raise ResearchDatasetError(f"{label} must be finite and {comparator}")
    return parsed


def _canonical_file(path: Path, label: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or not path.is_file():
        raise ResearchDatasetError(f"{label} path must be an existing absolute file")
    canonical = path.resolve(strict=True)
    if canonical != path:
        raise ResearchDatasetError(f"{label} path must be exact and canonical")
    return canonical


def _as_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ResearchDatasetError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _strict_utc_timestamp(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ResearchDatasetError(f"{label} must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ResearchDatasetError(f"{label} is invalid") from exc
    if parsed.tzinfo != timezone.utc:
        raise ResearchDatasetError(f"{label} must be UTC")
    return value


def _epoch_milliseconds(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
