from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from gold_engine_core import G10Acceptance, load_named_profile, verify_g10_evidence

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=3))
START = datetime(2026, 8, 21, 9, 0, tzinfo=TZ)


def write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def probe(profile_id: str) -> dict[str, object]:
    profile = load_named_profile(REPOSITORY_ROOT, profile_id)
    return {
        "account_login_sha256": ("1" if profile_id == "GOLDI" else "2") * 64,
        "account_server": f"{profile_id}-DEMO",
        "account_trade_mode": "demo",
        "bars": {name: {"count": 3} for name in ("M1", "M5", "M15", "H1")},
        "captured_at": START.isoformat(),
        "latency_ms": 12.5,
        "orders_sent": 0,
        "production_real_orders": "DISABLED",
        "profile_fingerprint": profile.fingerprint,
        "profile_id": profile_id,
        "symbol": profile.symbol,
        "terminal_build": 6090,
        "terminal_executable_sha256": ("a" if profile_id == "GOLDI" else "b") * 64,
        "tick": {"ask": 4400.2, "bid": 4400.0},
        "validation_profile_id": (
            "GOLDI_DEMO_VALIDATION" if profile_id == "GOLDI" else "GOLDM_DEMO_VALIDATION"
        ),
    }


def lifecycle(profile_id: str) -> dict[str, object]:
    profile = load_named_profile(REPOSITORY_ROOT, profile_id)
    offset = timedelta(minutes=0 if profile_id == "GOLDI" else 1)
    return {
        "close_count": 1,
        "duplicate_count": 0,
        "entry_count": 1,
        "finished_at": (START + timedelta(hours=1) + offset).isoformat(),
        "guarded_started_at": (START + timedelta(minutes=10) + offset).isoformat(),
        "latency_ms_p50": 10.0,
        "latency_ms_p95": 20.0,
        "live_replay_calls": 0,
        "privacy_bleed_count": 0,
        "production_real_orders": "DISABLED",
        "profile_fingerprint": profile.fingerprint,
        "profile_id": profile_id,
        "restart_count": 1,
        "shadow_event_count": 2,
        "shadow_started_at": (START + offset).isoformat(),
        "state_bleed_count": 0,
        "symbol": profile.symbol,
        "validation_profile_id": (
            "GOLDI_DEMO_VALIDATION" if profile_id == "GOLDI" else "GOLDM_DEMO_VALIDATION"
        ),
    }


def valid_evidence(root: Path) -> None:
    write(
        root / "prerequisites.json",
        {"ready": True, "production_real_orders": "DISABLED"},
    )
    for profile_id in ("GOLDI", "GOLDM"):
        write(root / f"{profile_id}-probe.json", probe(profile_id))
        write(root / f"{profile_id}-lifecycle.json", lifecycle(profile_id))
    write(
        root / "concurrency.json",
        {
            "profiles": ["GOLDI", "GOLDM"],
            "overlap_seconds": 300,
            "privacy_bleed_count": 0,
            "production_real_orders": "DISABLED",
            "state_bleed_count": 0,
        },
    )


def test_complete_actual_evidence_is_deterministic_and_accepted(tmp_path: Path) -> None:
    valid_evidence(tmp_path)
    first = verify_g10_evidence(REPOSITORY_ROOT, tmp_path)
    second = verify_g10_evidence(REPOSITORY_ROOT, tmp_path)

    assert first.accepted is True
    assert first.reasons == ()
    assert first.evidence_fingerprint == second.evidence_fingerprint
    assert len(first.evidence_fingerprint or "") == 64
    assert first.to_payload()["production_real_orders"] == "DISABLED"


def test_current_preparation_evidence_cannot_pass_as_actual() -> None:
    current = REPOSITORY_ROOT / "evidence" / "G10-reference-live-validation"
    result = verify_g10_evidence(REPOSITORY_ROOT, current)

    assert result.accepted is False
    assert "prerequisites.ready is not true" in result.reasons
    assert any("GOLDI-probe.json" in reason for reason in result.reasons)
    assert any("GOLDM-lifecycle.json" in reason for reason in result.reasons)


def test_duplicate_account_terminal_and_lifecycle_failures_are_rejected(
    tmp_path: Path,
) -> None:
    valid_evidence(tmp_path)
    goldi_probe = probe("GOLDI")
    goldm_probe = probe("GOLDM")
    goldm_probe["account_login_sha256"] = goldi_probe["account_login_sha256"]
    goldm_probe["terminal_executable_sha256"] = goldi_probe["terminal_executable_sha256"]
    write(tmp_path / "GOLDM-probe.json", goldm_probe)
    broken = lifecycle("GOLDM")
    broken.update(
        entry_count=0,
        duplicate_count=1,
        state_bleed_count=1,
        privacy_bleed_count=1,
        live_replay_calls=1,
        production_real_orders="ENABLED",
    )
    write(tmp_path / "GOLDM-lifecycle.json", broken)

    result = verify_g10_evidence(REPOSITORY_ROOT, tmp_path)

    assert result.accepted is False
    assert "DEMO profiles reuse one account login" in result.reasons
    assert "DEMO profiles do not prove distinct terminal executables" in result.reasons
    assert "GOLDM lifecycle entry_count below 1" in result.reasons
    assert "GOLDM lifecycle duplicate_count is not zero" in result.reasons
    assert "GOLDM lifecycle live_replay_calls is not zero" in result.reasons


def test_concurrency_and_nonoverlap_fail_closed(tmp_path: Path) -> None:
    valid_evidence(tmp_path)
    goldm = lifecycle("GOLDM")
    goldm["guarded_started_at"] = (START + timedelta(hours=2)).isoformat()
    goldm["finished_at"] = (START + timedelta(hours=3)).isoformat()
    write(tmp_path / "GOLDM-lifecycle.json", goldm)
    write(
        tmp_path / "concurrency.json",
        {
            "profiles": ["GOLDM", "GOLDI"],
            "overlap_seconds": 0,
            "privacy_bleed_count": 1,
            "production_real_orders": "ENABLED",
            "state_bleed_count": 1,
        },
    )

    result = verify_g10_evidence(REPOSITORY_ROOT, tmp_path)

    assert result.accepted is False
    assert "guarded DEMO lifecycle windows do not overlap" in result.reasons
    assert "concurrency profiles mismatch" in result.reasons
    assert "concurrency overlap is not positive" in result.reasons
    assert "concurrency bleed count is not zero" in result.reasons


def test_acceptance_result_cannot_claim_pass_without_fingerprint() -> None:
    with pytest.raises(ValueError, match="inconsistent"):
        G10Acceptance(True, (), None)
