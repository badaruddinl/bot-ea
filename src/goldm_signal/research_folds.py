from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from .research_policy import (
    ResearchPurpose,
    StatisticalClassification,
    assert_research_range,
    parse_research_date,
)


_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,95}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ResearchFoldError(RuntimeError):
    """Raised when a mining fold plan is missing, mutable, or not a partition."""


@dataclass(frozen=True, slots=True)
class RegisteredFold:
    name: str
    role: str
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class RegisteredFoldPlan:
    plan_id: str
    registered_at: str
    purpose: ResearchPurpose
    statistical_classification: StatisticalClassification
    start: datetime
    end: datetime
    folds: tuple[RegisteredFold, ...]
    plan_sha256: str
    source_path: Path


def load_registered_fold_plan(
    path: Path,
    *,
    expected_start: datetime,
    expected_end: datetime,
    expected_purpose: ResearchPurpose | str,
    expected_classification: StatisticalClassification | str,
) -> RegisteredFoldPlan:
    canonical = _canonical_file(path)
    try:
        payload = json.loads(canonical.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchFoldError(f"fold plan is not valid UTF-8 JSON: {canonical}") from exc
    required = {
        "schema_version",
        "plan_id",
        "registered_at",
        "purpose",
        "statistical_classification",
        "from_inclusive",
        "to_exclusive",
        "folds",
        "plan_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != required or payload.get(
        "schema_version"
    ) != 1:
        raise ResearchFoldError("fold plan must use schema_version 1 with exact fields")
    supplied_hash = payload["plan_sha256"]
    hash_payload = dict(payload)
    hash_payload.pop("plan_sha256")
    if not isinstance(supplied_hash, str) or not _SHA256.fullmatch(supplied_hash):
        raise ResearchFoldError("fold plan SHA-256 is invalid")
    if _canonical_sha256(hash_payload) != supplied_hash:
        raise ResearchFoldError("fold plan SHA-256 does not match its immutable payload")
    plan_id = payload["plan_id"]
    if not isinstance(plan_id, str) or not _TOKEN.fullmatch(plan_id):
        raise ResearchFoldError("fold plan_id must be a structured token")
    registered_at = _utc_timestamp(payload["registered_at"], "fold registered_at")
    try:
        purpose = ResearchPurpose(payload["purpose"])
        classification = StatisticalClassification(
            payload["statistical_classification"]
        )
        required_purpose = ResearchPurpose(expected_purpose)
        required_classification = StatisticalClassification(expected_classification)
    except (TypeError, ValueError) as exc:
        raise ResearchFoldError("fold purpose/classification is invalid") from exc
    if purpose is not required_purpose or classification is not required_classification:
        raise ResearchFoldError("fold plan purpose/classification does not match the run")
    start = parse_research_date(payload["from_inclusive"], field="fold.from_inclusive")
    end = parse_research_date(payload["to_exclusive"], field="fold.to_exclusive")
    approved = assert_research_range(
        start,
        end,
        purpose=purpose,
        statistical_classification=classification,
        label=f"fold plan/{plan_id}",
    )
    expected_start = _as_utc(expected_start, "expected_start")
    expected_end = _as_utc(expected_end, "expected_end")
    if approved.start != expected_start or approved.end != expected_end:
        raise ResearchFoldError("fold plan range does not exactly match the approved fetch range")
    if not isinstance(payload["folds"], list) or not payload["folds"]:
        raise ResearchFoldError("fold plan must contain explicit non-empty folds")
    folds: list[RegisteredFold] = []
    names: set[str] = set()
    for index, raw in enumerate(payload["folds"]):
        if not isinstance(raw, dict) or set(raw) != {
            "name",
            "role",
            "from_inclusive",
            "to_exclusive",
        }:
            raise ResearchFoldError(f"fold {index} has invalid fields")
        name = raw["name"]
        role = raw["role"]
        if not isinstance(name, str) or not _TOKEN.fullmatch(name) or name in names:
            raise ResearchFoldError(f"fold {index} has an invalid/duplicate name")
        if role not in {"SELECTION", "INTERNAL_VALIDATION"}:
            raise ResearchFoldError(f"fold {name} has an unsupported role")
        fold_start = parse_research_date(
            raw["from_inclusive"], field=f"folds.{name}.from_inclusive"
        )
        fold_end = parse_research_date(
            raw["to_exclusive"], field=f"folds.{name}.to_exclusive"
        )
        if fold_start >= fold_end:
            raise ResearchFoldError(f"fold {name} is empty or reversed")
        folds.append(RegisteredFold(name, role, fold_start, fold_end))
        names.add(name)
    if [fold.name for fold in folds] != [
        "train",
        "validation_1",
        "validation_2",
    ] or [fold.role for fold in folds] != [
        "SELECTION",
        "INTERNAL_VALIDATION",
        "INTERNAL_VALIDATION",
    ]:
        raise ResearchFoldError(
            "candle mining requires registered train/validation_1/validation_2 folds"
        )
    cursor = start
    for fold in folds:
        if fold.start != cursor:
            raise ResearchFoldError("folds must be ordered, contiguous, and gap-free")
        cursor = fold.end
    if cursor != end:
        raise ResearchFoldError("folds do not partition the complete approved range")
    return RegisteredFoldPlan(
        plan_id=plan_id,
        registered_at=registered_at,
        purpose=purpose,
        statistical_classification=classification,
        start=start,
        end=end,
        folds=tuple(folds),
        plan_sha256=supplied_hash,
        source_path=canonical,
    )


def partition_registered_timestamps(
    timestamps: Iterable[datetime],
    plan: RegisteredFoldPlan,
) -> Mapping[str, tuple[bool, ...]]:
    values = tuple(_as_utc(value, "dataset timestamp") for value in timestamps)
    if not values:
        raise ResearchFoldError("mining dataset is empty")
    if any(value < plan.start or value >= plan.end for value in values):
        raise ResearchFoldError("dataset contains rows outside the registered half-open range")
    masks = {
        fold.name: tuple(fold.start <= value < fold.end for value in values)
        for fold in plan.folds
    }
    for name, mask in masks.items():
        if not any(mask):
            raise ResearchFoldError(f"registered fold {name} is empty in the dataset")
    memberships = tuple(
        sum(bool(masks[name][index]) for name in masks) for index in range(len(values))
    )
    if any(count != 1 for count in memberships):
        raise ResearchFoldError("registered fold masks do not partition every dataset row exactly once")
    return masks


def _canonical_file(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or not path.is_file():
        raise ResearchFoldError("fold plan path must be an explicit existing absolute file")
    canonical = path.resolve(strict=True)
    if canonical != path:
        raise ResearchFoldError("fold plan path must be exact and canonical")
    return canonical


def _as_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ResearchFoldError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _utc_timestamp(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ResearchFoldError(f"{label} must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ResearchFoldError(f"{label} is invalid") from exc
    if parsed.tzinfo != timezone.utc:
        raise ResearchFoldError(f"{label} must be UTC")
    return value


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
