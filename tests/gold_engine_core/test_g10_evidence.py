from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import gold_engine_core.g10_evidence as g10_evidence
from gold_engine_core import G10Acceptance, load_named_profile, verify_g10_evidence

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=3))
START = datetime(2026, 8, 21, 9, 0, tzinfo=TZ)


def write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def probe(profile_id: str) -> dict[str, object]:
    profile = load_named_profile(REPOSITORY_ROOT, profile_id)
    is_demo = profile_id == "GOLDI"
    return {
        "account_login_sha256": ("1" if profile_id == "GOLDI" else "2") * 64,
        "account_server": f"{profile_id}-DEMO",
        "account_trade_mode": "demo" if is_demo else "real",
        "access_mode": "demo_execution" if is_demo else "read_only",
        "bars": {name: {"count": 3} for name in ("M1", "M5", "M15", "H1")},
        "captured_at": START.isoformat(),
        "latency_ms": 12.5,
        "orders_sent": 0,
        "order_api_calls": 0,
        "production_real_orders": "DISABLED",
        "profile_fingerprint": profile.fingerprint,
        "profile_id": profile_id,
        "symbol": profile.symbol,
        "terminal_build": 6090,
        "terminal_executable_sha256": "a" * 64,
        "terminal_path_sha256": ("c" if profile_id == "GOLDI" else "d") * 64,
        "tick": {"ask": 4400.2, "bid": 4400.0},
        "validation_profile_id": ("GOLDI_DEMO_VALIDATION" if is_demo else "GOLDM_REAL_READ_ONLY"),
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
        "validation_profile_id": "GOLDI_DEMO_VALIDATION",
    }


def goldm_tester_batch() -> dict[str, object]:
    profile = load_named_profile(REPOSITORY_ROOT, "GOLDM")
    classifications = ("regression", "historical_holdout", "walk_forward_oos")
    return {
        "batch_schema_version": 1,
        "binary_sha256": "b" * 64,
        "execution_environment": "strategy_tester",
        "live_order_api_calls": 0,
        "modeling": "every_tick_based_on_real_ticks",
        "production_real_orders": "DISABLED",
        "profile_fingerprint": profile.fingerprint,
        "profile_id": "GOLDM",
        "runs": [
            {
                "classification": classification,
                "duplicate_count": 0,
                "end": (START + timedelta(days=index + 1)).isoformat(),
                "event_state_parity_pct": 100,
                "max_price_error_ticks": 1,
                "restart_recovery_pass": True,
                "start": (START + timedelta(days=index)).isoformat(),
                "window_id": f"window-{index}",
            }
            for index, classification in enumerate(classifications)
        ],
        "source_commit_sha": "c" * 40,
        "symbol": profile.symbol,
        "validation_profile_id": "GOLDM_REAL_READ_ONLY",
    }


def valid_evidence(root: Path) -> None:
    write(
        root / "prerequisites.json",
        {"ready": True, "production_real_orders": "DISABLED"},
    )
    for profile_id in ("GOLDI", "GOLDM"):
        write(root / f"{profile_id}-probe.json", probe(profile_id))
    write(root / "GOLDI-lifecycle.json", lifecycle("GOLDI"))
    write(root / "GOLDM-tester-batch.json", goldm_tester_batch())
    write(
        root / "concurrency.json",
        {
            "profiles": ["GOLDI", "GOLDM"],
            "access_modes": {
                "GOLDI": "demo_execution",
                "GOLDM": "read_only",
            },
            "live_order_api_calls": 0,
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


def test_current_actual_evidence_is_accepted() -> None:
    current = REPOSITORY_ROOT / "evidence" / "G10-reference-live-validation"
    result = verify_g10_evidence(REPOSITORY_ROOT, current)

    assert result.accepted is True
    assert result.reasons == ()
    assert len(result.evidence_fingerprint or "") == 64


def test_duplicate_account_terminal_and_lifecycle_failures_are_rejected(
    tmp_path: Path,
) -> None:
    valid_evidence(tmp_path)
    goldi_probe = probe("GOLDI")
    goldm_probe = probe("GOLDM")
    goldm_probe["account_login_sha256"] = goldi_probe["account_login_sha256"]
    goldm_probe["terminal_path_sha256"] = goldi_probe["terminal_path_sha256"]
    write(tmp_path / "GOLDM-probe.json", goldm_probe)
    broken = goldm_tester_batch()
    broken["live_order_api_calls"] = 1
    broken_runs = list(broken["runs"])
    broken_runs[0] = {
        **broken_runs[0],
        "duplicate_count": 1,
        "event_state_parity_pct": 99,
    }
    broken["runs"] = broken_runs
    write(tmp_path / "GOLDM-tester-batch.json", broken)

    result = verify_g10_evidence(REPOSITORY_ROOT, tmp_path)

    assert result.accepted is False
    assert "validation profiles reuse one account login" in result.reasons
    assert "validation profiles do not prove distinct terminal paths" in result.reasons
    assert "GOLDM tester batch live_order_api_calls mismatch" in result.reasons
    assert "GOLDM tester run 0 duplicate count is not zero" in result.reasons
    assert "GOLDM tester run 0 event/state parity is not 100" in result.reasons


def test_concurrency_fail_closed(tmp_path: Path) -> None:
    valid_evidence(tmp_path)
    write(
        tmp_path / "concurrency.json",
        {
            "profiles": ["GOLDM", "GOLDI"],
            "access_modes": {"GOLDI": "read_only", "GOLDM": "demo_execution"},
            "live_order_api_calls": 1,
            "overlap_seconds": 0,
            "privacy_bleed_count": 1,
            "production_real_orders": "ENABLED",
            "state_bleed_count": 1,
        },
    )

    result = verify_g10_evidence(REPOSITORY_ROOT, tmp_path)

    assert result.accepted is False
    assert "concurrency profiles mismatch" in result.reasons
    assert "concurrency overlap is not positive" in result.reasons
    assert "concurrency access modes mismatch" in result.reasons
    assert "concurrency live order API count is not zero" in result.reasons
    assert "concurrency bleed count is not zero" in result.reasons


def test_acceptance_result_cannot_claim_pass_without_fingerprint() -> None:
    with pytest.raises(ValueError, match="inconsistent"):
        G10Acceptance(True, (), None)


def test_g10_scalar_validators_reject_ambiguous_values() -> None:
    assert g10_evidence._git_object_id("a" * 40) is True
    assert g10_evidence._git_object_id("b" * 64) is True
    assert g10_evidence._git_object_id("A" * 40) is False
    assert g10_evidence._git_object_id("a" * 39) is False
    assert g10_evidence._sha256("c" * 64) is True
    assert g10_evidence._sha256("C" * 64) is False
    assert g10_evidence._integer_at_least(True, 1) is False
    assert g10_evidence._integer_at_least(0, 1) is False
    assert g10_evidence._integer_at_least(1, 1) is True
    assert g10_evidence._positive_number(True, allow_zero=True) is False
    assert g10_evidence._positive_number(object(), allow_zero=True) is False
    assert g10_evidence._positive_number(0, allow_zero=True) is True
    assert g10_evidence._positive_number(0, allow_zero=False) is False
    assert g10_evidence._timestamp(None) is None
    assert g10_evidence._timestamp("not-a-timestamp") is None
    assert g10_evidence._timestamp("2026-08-22T12:00:00") is None
    assert g10_evidence._timestamp("2026-08-22T12:00:00+07:00") is not None
