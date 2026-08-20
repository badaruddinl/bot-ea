from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from .demo_validation import load_demo_validation_manifest
from .profile import canonical_sha256, load_named_profile


@dataclass(frozen=True, slots=True)
class G10Acceptance:
    accepted: bool
    reasons: tuple[str, ...]
    evidence_fingerprint: str | None

    def __post_init__(self) -> None:
        if self.accepted != (not self.reasons and self.evidence_fingerprint is not None):
            raise ValueError("G10 acceptance result is inconsistent")

    def to_payload(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "evidence_fingerprint": self.evidence_fingerprint,
            "production_real_orders": "DISABLED",
            "reasons": list(self.reasons),
        }


def verify_g10_evidence(repository_root: Path, evidence_root: Path) -> G10Acceptance:
    reasons: list[str] = []
    payloads: dict[str, object] = {}
    prerequisites = _read_optional(evidence_root / "prerequisites.json", reasons)
    if prerequisites is not None:
        payloads["prerequisites"] = prerequisites
        if prerequisites.get("ready") is not True:
            reasons.append("prerequisites.ready is not true")
        if prerequisites.get("production_real_orders") != "DISABLED":
            reasons.append("prerequisites does not prove REAL disabled")

    probes: dict[str, dict[str, object]] = {}
    lifecycles: dict[str, dict[str, object]] = {}
    for profile_id, manifest_name in (
        ("GOLDI", "GOLDI_DEMO.json"),
        ("GOLDM", "GOLDM_DEMO_VALIDATION.json"),
    ):
        production = load_named_profile(repository_root, profile_id)
        validation = load_demo_validation_manifest(
            repository_root / "config" / "validation_profiles" / manifest_name
        )
        probe = _read_optional(evidence_root / f"{profile_id}-probe.json", reasons)
        lifecycle = _read_optional(evidence_root / f"{profile_id}-lifecycle.json", reasons)
        if probe is not None:
            payloads[f"{profile_id}_probe"] = probe
            probes[profile_id] = probe
            _verify_probe(profile_id, production.fingerprint, validation.symbol, probe, reasons)
        if lifecycle is not None:
            payloads[f"{profile_id}_lifecycle"] = lifecycle
            lifecycles[profile_id] = lifecycle
            _verify_lifecycle(
                profile_id,
                validation.validation_profile_id,
                production.fingerprint,
                validation.symbol,
                lifecycle,
                reasons,
            )

    concurrency = _read_optional(evidence_root / "concurrency.json", reasons)
    if concurrency is not None:
        payloads["concurrency"] = concurrency
        _verify_concurrency(concurrency, reasons)

    if set(probes) == {"GOLDI", "GOLDM"}:
        if probes["GOLDI"].get("account_login_sha256") == probes["GOLDM"].get(
            "account_login_sha256"
        ):
            reasons.append("DEMO profiles reuse one account login")
        if probes["GOLDI"].get("terminal_executable_sha256") == probes["GOLDM"].get(
            "terminal_executable_sha256"
        ):
            reasons.append("DEMO profiles do not prove distinct terminal executables")
    if set(lifecycles) == {"GOLDI", "GOLDM"}:
        goldi_start = _timestamp(lifecycles["GOLDI"].get("guarded_started_at"))
        goldi_end = _timestamp(lifecycles["GOLDI"].get("finished_at"))
        goldm_start = _timestamp(lifecycles["GOLDM"].get("guarded_started_at"))
        goldm_end = _timestamp(lifecycles["GOLDM"].get("finished_at"))
        if None not in (goldi_start, goldi_end, goldm_start, goldm_end):
            assert goldi_start is not None and goldi_end is not None
            assert goldm_start is not None and goldm_end is not None
            if min(goldi_end, goldm_end) <= max(goldi_start, goldm_start):
                reasons.append("guarded DEMO lifecycle windows do not overlap")

    unique_reasons = tuple(sorted(set(reasons)))
    fingerprint = None if unique_reasons else str(canonical_sha256(payloads))
    return G10Acceptance(not unique_reasons, unique_reasons, fingerprint)


def _verify_probe(
    profile_id: str,
    fingerprint: str,
    symbol: str,
    probe: dict[str, object],
    reasons: list[str],
) -> None:
    expected = {
        "profile_id": profile_id,
        "profile_fingerprint": fingerprint,
        "symbol": symbol,
        "account_trade_mode": "demo",
        "orders_sent": 0,
        "production_real_orders": "DISABLED",
    }
    for field, value in expected.items():
        if probe.get(field) != value:
            reasons.append(f"{profile_id} probe {field} mismatch")
    for field in ("account_login_sha256", "terminal_executable_sha256"):
        if not _sha256(probe.get(field)):
            reasons.append(f"{profile_id} probe {field} invalid")
    if not _positive_number(probe.get("latency_ms"), allow_zero=True):
        reasons.append(f"{profile_id} probe latency invalid")
    bars = probe.get("bars")
    if not isinstance(bars, dict) or set(bars) != {"M1", "M5", "M15", "H1"}:
        reasons.append(f"{profile_id} probe closed bars incomplete")


def _verify_lifecycle(
    profile_id: str,
    validation_profile_id: str,
    fingerprint: str,
    symbol: str,
    lifecycle: dict[str, object],
    reasons: list[str],
) -> None:
    expected = {
        "profile_id": profile_id,
        "validation_profile_id": validation_profile_id,
        "profile_fingerprint": fingerprint,
        "symbol": symbol,
        "production_real_orders": "DISABLED",
    }
    for field, value in expected.items():
        if lifecycle.get(field) != value:
            reasons.append(f"{profile_id} lifecycle {field} mismatch")
    for field, minimum in {
        "shadow_event_count": 1,
        "entry_count": 1,
        "close_count": 1,
        "restart_count": 1,
    }.items():
        if not _integer_at_least(lifecycle.get(field), minimum):
            reasons.append(f"{profile_id} lifecycle {field} below {minimum}")
    for field in (
        "duplicate_count",
        "state_bleed_count",
        "privacy_bleed_count",
        "live_replay_calls",
    ):
        if lifecycle.get(field) != 0:
            reasons.append(f"{profile_id} lifecycle {field} is not zero")
    for field in ("latency_ms_p50", "latency_ms_p95"):
        if not _positive_number(lifecycle.get(field), allow_zero=True):
            reasons.append(f"{profile_id} lifecycle {field} invalid")
    for field in ("shadow_started_at", "guarded_started_at", "finished_at"):
        if _timestamp(lifecycle.get(field)) is None:
            reasons.append(f"{profile_id} lifecycle {field} invalid")


def _verify_concurrency(value: dict[str, object], reasons: list[str]) -> None:
    if value.get("profiles") != ["GOLDI", "GOLDM"]:
        reasons.append("concurrency profiles mismatch")
    if not _positive_number(value.get("overlap_seconds"), allow_zero=False):
        reasons.append("concurrency overlap is not positive")
    if value.get("production_real_orders") != "DISABLED":
        reasons.append("concurrency does not prove REAL disabled")
    if value.get("state_bleed_count") != 0 or value.get("privacy_bleed_count") != 0:
        reasons.append("concurrency bleed count is not zero")


def _read_optional(path: Path, reasons: list[str]) -> dict[str, object] | None:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        reasons.append(f"missing/invalid {path.name}: {type(exc).__name__}")
        return None
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        reasons.append(f"invalid object {path.name}")
        return None
    return cast(dict[str, object], payload)


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _integer_at_least(value: object, minimum: int) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= minimum


def _positive_number(value: object, *, allow_zero: bool) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return value >= 0 if allow_zero else value > 0


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed
