from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any


DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "goldm-research-policy.json"
)


class ResearchPurpose(StrEnum):
    DEVELOPMENT = "Development"
    VALIDATION = "Validation"
    DIAGNOSTIC = "Diagnostic"
    BLIND_OOS = "BlindOos"


class StatisticalClassification(StrEnum):
    DEVELOPMENT_SELECTION = "DEVELOPMENT_SELECTION"
    LOCKED_LEGACY_VALIDATION = "LOCKED_LEGACY_VALIDATION"
    DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
    BLIND_OOS = "BLIND_OOS"


_PURPOSE_CLASSIFICATION = {
    ResearchPurpose.DEVELOPMENT: StatisticalClassification.DEVELOPMENT_SELECTION,
    ResearchPurpose.VALIDATION: StatisticalClassification.LOCKED_LEGACY_VALIDATION,
    ResearchPurpose.DIAGNOSTIC: StatisticalClassification.DIAGNOSTIC_ONLY,
    ResearchPurpose.BLIND_OOS: StatisticalClassification.BLIND_OOS,
}


@dataclass(frozen=True)
class ResearchRange:
    start: datetime
    end: datetime
    purpose: ResearchPurpose
    statistical_classification: StatisticalClassification
    label: str


def _parse_policy_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date string")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD; received {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must use YYYY-MM-DD; received {value!r}")
    return parsed


@lru_cache(maxsize=4)
def load_research_policy(path: str | Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy_path = Path(path).resolve()
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != 1:
        raise ValueError(f"unsupported research policy schema: {policy_path}")
    if policy.get("range_semantics") != "half-open [from, to)":
        raise ValueError(f"unsupported research range semantics: {policy_path}")
    for section in ("development", "validation", "quarantine", "known_exposure"):
        values = policy.get(section)
        if not isinstance(values, dict):
            raise ValueError(f"research policy is missing section {section!r}")
        section_from = _parse_policy_date(values.get("from"), f"{section}.from")
        section_to = _parse_policy_date(values.get("to"), f"{section}.to")
        if section_from >= section_to:
            raise ValueError(f"research policy section {section!r} is not increasing")
    return policy


def parse_research_date(value: str, *, field: str) -> datetime:
    parsed = _parse_policy_date(value, field)
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)


def _coerce_utc(value: str | date | datetime, *, field: str) -> datetime:
    if isinstance(value, str):
        return parse_research_date(value, field=field)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} datetime must be timezone-aware")
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    raise TypeError(f"{field} must be a date, timezone-aware datetime, or YYYY-MM-DD string")


def assert_research_range(
    start: str | date | datetime,
    end: str | date | datetime,
    *,
    purpose: ResearchPurpose | str = ResearchPurpose.DIAGNOSTIC,
    statistical_classification: StatisticalClassification | str | None = None,
    label: str = "research run",
    policy_path: str | Path = DEFAULT_POLICY_PATH,
) -> ResearchRange:
    start_utc = _coerce_utc(start, field="from_date")
    end_utc = _coerce_utc(end, field="to_date")
    if start_utc >= end_utc:
        raise ValueError(
            f"{label} has an invalid half-open range [{start_utc.isoformat()}, "
            f"{end_utc.isoformat()}): from_date must be earlier than to_date"
        )
    try:
        resolved_purpose = ResearchPurpose(purpose)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ResearchPurpose)
        raise ValueError(f"invalid research purpose {purpose!r}; expected one of {allowed}") from exc
    expected_classification = _PURPOSE_CLASSIFICATION[resolved_purpose]
    if statistical_classification is not None:
        try:
            resolved_classification = StatisticalClassification(
                statistical_classification
            )
        except ValueError as exc:
            allowed = ", ".join(item.value for item in StatisticalClassification)
            raise ValueError(
                "invalid statistical classification "
                f"{statistical_classification!r}; expected one of {allowed}"
            ) from exc
        if resolved_classification is not expected_classification:
            raise ValueError(
                f"{label} purpose {resolved_purpose.value} requires "
                f"statistical classification {expected_classification.value}"
            )

    policy = load_research_policy(policy_path)

    def boundary(section: str, key: str) -> datetime:
        return parse_research_date(policy[section][key], field=f"{section}.{key}")

    quarantine_from = boundary("quarantine", "from")
    quarantine_to = boundary("quarantine", "to")
    if start_utc < quarantine_to and end_utc > quarantine_from:
        raise ValueError(
            f"{label} range [{start_utc.isoformat()}, {end_utc.isoformat()}) intersects "
            f"the protected quarantine [{quarantine_from.date()}, {quarantine_to.date()}); "
            "no data read, backtest, tuning, selection, validation, or OOS run is permitted"
        )

    if resolved_purpose is ResearchPurpose.DEVELOPMENT:
        allowed_from = boundary("development", "from")
        allowed_to = boundary("development", "to")
        if start_utc < allowed_from or end_utc > allowed_to:
            raise ValueError(
                f"{label} is labeled Development but falls outside "
                f"[{allowed_from.date()}, {allowed_to.date()})"
            )
    elif resolved_purpose is ResearchPurpose.VALIDATION:
        allowed_from = boundary("validation", "from")
        allowed_to = boundary("validation", "to")
        if start_utc < allowed_from or end_utc > allowed_to:
            raise ValueError(
                f"{label} is labeled Validation but falls outside "
                f"[{allowed_from.date()}, {allowed_to.date()})"
            )
    elif resolved_purpose is ResearchPurpose.BLIND_OOS:
        first_unexposed = boundary("known_exposure", "to")
        if start_utc < first_unexposed:
            raise ValueError(
                f"{label} is labeled BlindOos but starts before {first_unexposed.date()}; "
                "earlier data is already exposed and may only be used diagnostically"
            )
    elif resolved_purpose is ResearchPurpose.DIAGNOSTIC:
        allowed_from = boundary("known_exposure", "from")
        allowed_to = boundary("known_exposure", "to")
        if start_utc < allowed_from or end_utc > allowed_to:
            raise ValueError(
                f"{label} is labeled Diagnostic but falls outside known-exposure "
                f"[{allowed_from.date()}, {allowed_to.date()})"
            )

    return ResearchRange(
        start_utc,
        end_utc,
        resolved_purpose,
        expected_classification,
        label,
    )


def inclusive_api_end(exclusive_end: datetime) -> datetime:
    """Translate a half-open end into an endpoint safe for inclusive MT5 APIs."""
    if exclusive_end.tzinfo is None or exclusive_end.utcoffset() is None:
        raise ValueError("exclusive_end datetime must be timezone-aware")
    return exclusive_end.astimezone(timezone.utc) - timedelta(microseconds=1)
