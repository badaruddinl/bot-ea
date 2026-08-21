from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_g20_unattended_evidence", ROOT / "scripts/verify_g20_unattended_evidence.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _terminal(profile_id: str) -> dict[str, object]:
    goldi = profile_id == "GOLDI"
    return {
        "profile_id": profile_id,
        "terminal_path": f"C:/{profile_id}/terminal64.exe",
        "ea_binary_path": f"C:/{profile_id}/{profile_id}.ex5",
        "ea_sha256": ("a" if goldi else "b") * 64,
        "expected_account_login": 108098316 if goldi else 391425346,
        "expected_account_server": "XMGlobal-MT5 5" if goldi else "XMGlobal-MT5 14",
        "expected_profile_fingerprint": ("c" if goldi else "d") * 64,
        "expected_symbol": "GOLD.i#" if goldi else "GOLDm#",
        "expected_trade_mode": 0 if goldi else 2,
        "expected_order_authority": "ENABLED" if goldi else "DISABLED",
    }


def _event(profile: dict[str, object], event_type: str) -> dict[str, object]:
    return {
        "event_id": f"{profile['profile_id']}:{event_type}",
        "profile_id": profile["profile_id"],
        "profile_fingerprint": profile["expected_profile_fingerprint"],
        "symbol": profile["expected_symbol"],
        "event_type": event_type,
        "payload": {
            "account_login": profile["expected_account_login"],
            "account_server": profile["expected_account_server"],
            "trade_mode": profile["expected_trade_mode"],
            "order_authority": profile["expected_order_authority"],
        },
    }


def _evidence() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    goldi = _terminal("GOLDI")
    goldm = _terminal("GOLDM")
    config: dict[str, object] = {
        "production_real_orders": "DISABLED",
        "terminals": [goldi, goldm],
        "bridge": {"enabled": True},
    }
    preboot: dict[str, object] = {
        "production_real_orders": "DISABLED",
        "boot_time_utc": "2026-08-21T09:00:00+00:00",
    }
    postboot: dict[str, object] = {
        "production_real_orders": "DISABLED",
        "boot_time_utc": "2026-08-21T10:00:00+00:00",
        "interactive_login_observed_at_utc": "2026-08-21T10:05:00+00:00",
        "task": {
            "logon_type": "Password",
            "boot_trigger_count": 1,
            "state": "Running",
            "last_run_time_utc": "2026-08-21T10:00:30+00:00",
        },
        "supervisor_health": {
            "production_real_orders": "DISABLED",
            "interactive_session": False,
            "started_at_utc": "2026-08-21T10:00:31+00:00",
            "bridge": {"state": "RUNNING", "pid": 30},
            "terminals": [
                {
                    "profile_id": "GOLDI",
                    "state": "RUNNING",
                    "pid": 10,
                    "ea_sha256": goldi["ea_sha256"],
                },
                {
                    "profile_id": "GOLDM",
                    "state": "RUNNING",
                    "pid": 20,
                    "ea_sha256": goldm["ea_sha256"],
                },
            ],
        },
        "terminal_processes": [
            {"profile_id": "GOLDI", "process_count": 1, "pids": [10]},
            {"profile_id": "GOLDM", "process_count": 1, "pids": [20]},
        ],
        "python_roles": [{"pid": 30, "role": "EVENT_BRIDGE"}],
        "legacy_tasks": [{"task_name": "old", "enabled": False, "state": "Disabled"}],
        "new_events": {
            profile["profile_id"]: [
                _event(profile, "ENGINE_STARTED"),
                _event(profile, "PROFILE_VALIDATED"),
                _event(profile, "ENGINE_HEARTBEAT"),
            ]
            for profile in (goldi, goldm)
        },
    }
    postboot["bridge_health"] = {
        "pid": 30,
        "production_real_orders": "DISABLED",
        "pending_event_count": 0,
        "failed_last_loop": 0,
        "latest_events": [
            {
                "event_id": event["event_id"],
                "delivery_state": (
                    "SUPPRESSED" if event["event_type"] == "ENGINE_HEARTBEAT" else "DELIVERED"
                ),
            }
            for profile_events in postboot["new_events"].values()
            for event in profile_events
        ],
    }
    return config, preboot, postboot


def test_strict_unattended_cold_boot_evidence_passes() -> None:
    report = MODULE.verify(*_evidence())

    assert report["status"] == "PASS"
    assert report["boot_id_changed"] is True
    assert report["unattended_before_login"] is True
    assert report["bridge_recovered"] is True


def test_single_python_role_object_is_normalized() -> None:
    config, preboot, postboot = copy.deepcopy(_evidence())
    postboot["python_roles"] = postboot["python_roles"][0]

    assert MODULE.verify(config, preboot, postboot)["status"] == "PASS"


def _autologon_evidence() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    config, preboot, postboot = copy.deepcopy(_evidence())
    config["startup_mode"] = "AUTOLOGON_LOCKED_INTERACTIVE"
    preboot["startup_mode"] = "AUTOLOGON_LOCKED_INTERACTIVE"
    postboot["startup_mode"] = "AUTOLOGON_LOCKED_INTERACTIVE"
    postboot["task"].update(
        {
            "logon_type": "Interactive",
            "boot_trigger_count": 0,
            "logon_trigger_count": 1,
        }
    )
    postboot["supervisor_health"].update(
        {
            "interactive_session": True,
            "session_id": 1,
            "startup_mode": "AUTOLOGON_LOCKED_INTERACTIVE",
        }
    )
    for process in postboot["terminal_processes"]:
        process["session_ids"] = [1]
    postboot["lock_marker"] = {
        "boot_time_utc": postboot["boot_time_utc"],
        "lock_requested_at_utc": "2026-08-21T10:00:40+00:00",
        "lock_requested": True,
        "session_id": 1,
        "production_real_orders": "DISABLED",
    }
    return config, preboot, postboot


def test_autologon_locked_interactive_evidence_passes() -> None:
    report = MODULE.verify(*_autologon_evidence())

    assert report["status"] == "PASS"
    assert report["startup_mode"] == "AUTOLOGON_LOCKED_INTERACTIVE"
    assert report["manual_login_required"] is False


@pytest.mark.parametrize("mutation", ["session_zero", "lock_missing", "late_lock"])
def test_autologon_safety_mutations_fail(mutation: str) -> None:
    config, preboot, postboot = copy.deepcopy(_autologon_evidence())
    if mutation == "session_zero":
        postboot["terminal_processes"][0]["session_ids"] = [0]
    elif mutation == "lock_missing":
        postboot["lock_marker"]["lock_requested"] = False
    else:
        postboot["lock_marker"]["lock_requested_at_utc"] = "2026-08-21T10:04:00+00:00"

    assert MODULE.verify(config, preboot, postboot)["status"] == "FAIL"


@pytest.mark.parametrize(
    "mutation",
    ["missing_heartbeat", "authority_enabled", "after_login", "forbidden_python", "legacy_task"],
)
def test_strict_mutations_fail(mutation: str) -> None:
    config, preboot, postboot = copy.deepcopy(_evidence())
    if mutation == "missing_heartbeat":
        postboot["new_events"]["GOLDM"] = postboot["new_events"]["GOLDM"][:-1]
    elif mutation == "authority_enabled":
        postboot["new_events"]["GOLDM"][0]["payload"]["order_authority"] = "ENABLED"
    elif mutation == "after_login":
        postboot["interactive_login_observed_at_utc"] = "2026-08-21T10:00:20+00:00"
    elif mutation == "forbidden_python":
        postboot["python_roles"].append({"pid": 99, "role": "FORBIDDEN_PYTHON_STRATEGY"})
    else:
        postboot["legacy_tasks"][0]["enabled"] = True

    report = MODULE.verify(config, preboot, postboot)

    assert report["status"] == "FAIL"
    assert report["violations"]
