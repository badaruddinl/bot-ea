from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, cast

from .profile import canonical_json

CorpusDomain = Literal["revised", "bear", "execution"]
_DOMAINS = frozenset({"revised", "bear", "execution"})
_PROFILE_IDS = frozenset({"GOLDI", "GOLDM"})
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class CorpusError(ValueError):
    """Raised when a current-behavior corpus is invalid or non-causal."""


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CorpusError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CorpusError(f"{field} must be a non-empty string")
    return value


def _sha256(value: object, field: str) -> str:
    result = _string(value, field)
    if not _SHA256_PATTERN.fullmatch(result):
        raise CorpusError(f"{field} must be a lowercase SHA-256")
    return result


def _timestamp(value: object, field: str) -> datetime:
    text = _string(value, field)
    try:
        result = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CorpusError(f"{field} must be ISO-8601") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise CorpusError(f"{field} must include an explicit UTC offset")
    return result


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CorpusError(f"{field} must be null or a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise CorpusError(f"{field} is not a decimal") from exc
    if not result.is_finite():
        raise CorpusError(f"{field} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class StateTransition:
    available_at: datetime
    from_state: str
    to_state: str

    @classmethod
    def from_payload(cls, payload: object, field: str) -> StateTransition:
        data = _mapping(payload, field)
        expected = {"available_at", "from", "to"}
        if set(data) != expected:
            raise CorpusError(f"{field} keys must be {sorted(expected)}")
        return cls(
            available_at=_timestamp(data["available_at"], f"{field}.available_at"),
            from_state=_string(data["from"], f"{field}.from"),
            to_state=_string(data["to"], f"{field}.to"),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "available_at": self.available_at.isoformat(),
            "from": self.from_state,
            "to": self.to_state,
        }


@dataclass(frozen=True, slots=True)
class PlannedGeometry:
    entry: Decimal | None
    stop: Decimal | None
    target: Decimal | None
    invalidation: Decimal | None

    @classmethod
    def from_payload(cls, payload: object) -> PlannedGeometry:
        data = _mapping(payload, "planned_geometry")
        expected = {"entry", "invalidation", "stop", "target"}
        if set(data) != expected:
            raise CorpusError(f"planned_geometry keys must be {sorted(expected)}")
        return cls(
            entry=_optional_decimal(data["entry"], "planned_geometry.entry"),
            stop=_optional_decimal(data["stop"], "planned_geometry.stop"),
            target=_optional_decimal(data["target"], "planned_geometry.target"),
            invalidation=_optional_decimal(data["invalidation"], "planned_geometry.invalidation"),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "entry": None if self.entry is None else str(self.entry),
            "invalidation": None if self.invalidation is None else str(self.invalidation),
            "stop": None if self.stop is None else str(self.stop),
            "target": None if self.target is None else str(self.target),
        }


@dataclass(frozen=True, slots=True)
class BehaviorRecord:
    schema_version: int
    profile_id: str
    profile_fingerprint: str
    scenario_id: str
    domain: CorpusDomain
    input_fingerprint: str
    available_at: datetime
    setup_id: str
    state_transitions: tuple[StateTransition, ...]
    decision: str
    planned_geometry: PlannedGeometry
    reason: str
    execution_outcome: str
    source_ref: str
    source_sha256: str
    closed_bars_only: bool

    @classmethod
    def from_payload(cls, payload: object) -> BehaviorRecord:
        data = _mapping(payload, "record")
        expected = {
            "available_at",
            "closed_bars_only",
            "decision",
            "domain",
            "execution_outcome",
            "input_fingerprint",
            "planned_geometry",
            "profile_fingerprint",
            "profile_id",
            "reason",
            "scenario_id",
            "schema_version",
            "setup_id",
            "source_ref",
            "source_sha256",
            "state_transitions",
        }
        if set(data) != expected:
            raise CorpusError(f"record keys must be {sorted(expected)}")
        profile_id = _string(data["profile_id"], "profile_id")
        if profile_id not in _PROFILE_IDS:
            raise CorpusError(f"unsupported profile_id: {profile_id!r}")
        domain_value = data["domain"]
        if domain_value not in _DOMAINS:
            raise CorpusError(f"unsupported domain: {domain_value!r}")
        schema_version = data["schema_version"]
        if isinstance(schema_version, bool) or schema_version != 1:
            raise CorpusError("schema_version must equal 1")
        transitions_payload = data["state_transitions"]
        if not isinstance(transitions_payload, list) or not transitions_payload:
            raise CorpusError("state_transitions must be a non-empty array")
        closed_bars_only = data["closed_bars_only"]
        if not isinstance(closed_bars_only, bool):
            raise CorpusError("closed_bars_only must be boolean")
        record = cls(
            schema_version=1,
            profile_id=profile_id,
            profile_fingerprint=_sha256(data["profile_fingerprint"], "profile_fingerprint"),
            scenario_id=_string(data["scenario_id"], "scenario_id"),
            domain=cast(CorpusDomain, domain_value),
            input_fingerprint=_sha256(data["input_fingerprint"], "input_fingerprint"),
            available_at=_timestamp(data["available_at"], "available_at"),
            setup_id=_string(data["setup_id"], "setup_id"),
            state_transitions=tuple(
                StateTransition.from_payload(item, f"state_transitions[{index}]")
                for index, item in enumerate(transitions_payload)
            ),
            decision=_string(data["decision"], "decision"),
            planned_geometry=PlannedGeometry.from_payload(data["planned_geometry"]),
            reason=_string(data["reason"], "reason"),
            execution_outcome=_string(data["execution_outcome"], "execution_outcome"),
            source_ref=_string(data["source_ref"], "source_ref"),
            source_sha256=_sha256(data["source_sha256"], "source_sha256"),
            closed_bars_only=closed_bars_only,
        )
        record._validate_causality()
        return record

    def _validate_causality(self) -> None:
        if not self.setup_id.startswith(f"{self.profile_id}:"):
            raise CorpusError("setup_id must be profile-namespaced")
        if not self.scenario_id.startswith(f"{self.domain}."):
            raise CorpusError("scenario_id must start with its domain")
        if any(item.available_at > self.available_at for item in self.state_transitions):
            raise CorpusError("state transition uses information after available_at")
        if self.domain in {"revised", "bear"} and not self.closed_bars_only:
            raise CorpusError("strategy corpus must use closed bars only")

    def to_payload(self) -> dict[str, object]:
        return {
            "available_at": self.available_at.isoformat(),
            "closed_bars_only": self.closed_bars_only,
            "decision": self.decision,
            "domain": self.domain,
            "execution_outcome": self.execution_outcome,
            "input_fingerprint": self.input_fingerprint,
            "planned_geometry": self.planned_geometry.to_payload(),
            "profile_fingerprint": self.profile_fingerprint,
            "profile_id": self.profile_id,
            "reason": self.reason,
            "scenario_id": self.scenario_id,
            "schema_version": self.schema_version,
            "setup_id": self.setup_id,
            "source_ref": self.source_ref,
            "source_sha256": self.source_sha256,
            "state_transitions": [item.to_payload() for item in self.state_transitions],
        }


def corpus_bytes(records: tuple[BehaviorRecord, ...]) -> bytes:
    return b"".join(canonical_json(record.to_payload()) + b"\n" for record in records)


def write_corpus(path: Path, records: tuple[BehaviorRecord, ...]) -> str:
    if not records:
        raise CorpusError("cannot write an empty corpus")
    profile_ids = {record.profile_id for record in records}
    if len(profile_ids) != 1:
        raise CorpusError("a corpus file cannot mix profiles")
    scenario_ids = tuple(record.scenario_id for record in records)
    if len(set(scenario_ids)) != len(scenario_ids):
        raise CorpusError("scenario_id must be unique within a profile corpus")
    payload = corpus_bytes(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    path.with_suffix(".sha256").write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return digest


def load_corpus(path: Path) -> tuple[BehaviorRecord, ...]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CorpusError(f"cannot read corpus: {path}") from exc
    records: list[BehaviorRecord] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line:
            raise CorpusError(f"blank line at corpus line {line_number}")
        try:
            payload: object = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CorpusError(f"invalid JSON at corpus line {line_number}") from exc
        record = BehaviorRecord.from_payload(payload)
        if canonical_json(record.to_payload()) != line:
            raise CorpusError(f"non-canonical JSON at corpus line {line_number}")
        records.append(record)
    result = tuple(records)
    if not result:
        raise CorpusError("corpus is empty")
    if corpus_bytes(result) != raw:
        raise CorpusError("corpus must end with exactly one newline")
    profile_ids = {record.profile_id for record in result}
    if len(profile_ids) != 1:
        raise CorpusError("corpus mixes profiles")
    scenario_ids = tuple(record.scenario_id for record in result)
    if len(set(scenario_ids)) != len(scenario_ids):
        raise CorpusError("corpus contains duplicate scenario_id")
    checksum_path = path.with_suffix(".sha256")
    try:
        fields = checksum_path.read_text(encoding="ascii").strip().split()
    except OSError as exc:
        raise CorpusError(f"cannot read corpus checksum: {checksum_path}") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if len(fields) != 2 or fields[1] != path.name or fields[0] != digest:
        raise CorpusError("corpus checksum mismatch")
    return result
