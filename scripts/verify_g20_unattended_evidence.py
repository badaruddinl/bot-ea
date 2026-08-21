from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be an ISO timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def _items(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    raise ValueError("evidence collection must be an object, array of objects, or null")


def verify(
    config: dict[str, Any], preboot: dict[str, Any], postboot: dict[str, Any]
) -> dict[str, Any]:
    violations: list[str] = []

    for label, value in (
        ("config", config.get("production_real_orders")),
        ("preboot", preboot.get("production_real_orders")),
        ("postboot", postboot.get("production_real_orders")),
    ):
        if value != "DISABLED":
            violations.append(f"{label} production REAL authority is not disabled")

    preboot_time = _time(preboot.get("boot_time_utc"), "preboot.boot_time_utc")
    postboot_time = _time(postboot.get("boot_time_utc"), "postboot.boot_time_utc")
    if postboot_time <= preboot_time:
        violations.append("Windows boot identity did not advance")

    startup_mode = str(config.get("startup_mode") or "PASSWORD_AT_STARTUP")
    if preboot.get("startup_mode") not in {None, startup_mode}:
        violations.append("preboot startup_mode differs from config")
    if postboot.get("startup_mode") not in {None, startup_mode}:
        violations.append("postboot startup_mode differs from config")

    task = postboot.get("task") or {}
    if startup_mode == "AUTOLOGON_LOCKED_INTERACTIVE":
        if task.get("logon_type") not in {"Interactive", "InteractiveToken"}:
            violations.append("startup task does not use an interactive logon token")
        if task.get("logon_trigger_count") != 1 or task.get("boot_trigger_count") != 0:
            violations.append("startup task does not have exactly one logon trigger")
    else:
        if task.get("logon_type") != "Password":
            violations.append("startup task does not use password-backed logon")
        if task.get("boot_trigger_count") != 1:
            violations.append("startup task does not have exactly one boot trigger")
    if task.get("state") != "Running":
        violations.append("startup task is not running")
    try:
        task_started = _time(task.get("last_run_time_utc"), "task.last_run_time_utc")
        if task_started < postboot_time:
            violations.append("startup task did not start after the new boot")
    except ValueError as exc:
        violations.append(str(exc))

    health = postboot.get("supervisor_health") or {}
    if health.get("production_real_orders") != "DISABLED":
        violations.append("supervisor health does not disable production REAL orders")
    if health.get("startup_mode") not in {None, startup_mode}:
        violations.append("supervisor health startup_mode mismatch")
    if startup_mode == "AUTOLOGON_LOCKED_INTERACTIVE":
        if health.get("interactive_session") is not True or int(health.get("session_id", 0)) <= 0:
            violations.append("supervisor was not proven in an interactive session")
    elif health.get("interactive_session") is not False:
        violations.append("supervisor was not proven in a non-interactive session")
    try:
        health_started = _time(health.get("started_at_utc"), "health.started_at_utc")
        if health_started < postboot_time:
            violations.append("supervisor health predates the new boot")
        if startup_mode == "AUTOLOGON_LOCKED_INTERACTIVE":
            if (health_started - postboot_time).total_seconds() > 180:
                violations.append("interactive supervisor did not start promptly after boot")
        else:
            interactive_raw = postboot.get("interactive_login_observed_at_utc")
            if interactive_raw is not None and health_started >= _time(
                interactive_raw, "interactive login"
            ):
                violations.append("supervisor did not start before interactive login")
    except ValueError as exc:
        violations.append(str(exc))

    configured = {item["profile_id"]: item for item in config.get("terminals", [])}
    health_profiles = {item.get("profile_id"): item for item in _items(health.get("terminals"))}
    process_profiles = {
        item.get("profile_id"): item for item in _items(postboot.get("terminal_processes"))
    }
    new_events = postboot.get("new_events") or {}
    profile_summary: dict[str, Any] = {}
    for profile_id in ("GOLDI", "GOLDM"):
        expected = configured.get(profile_id)
        observed = health_profiles.get(profile_id)
        process = process_profiles.get(profile_id)
        if not expected or not observed or not process:
            violations.append(f"{profile_id} configuration/health/process evidence is incomplete")
            continue
        if observed.get("state") != "RUNNING":
            violations.append(f"{profile_id} terminal is not RUNNING")
        if observed.get("ea_sha256", "").lower() != str(expected["ea_sha256"]).lower():
            violations.append(f"{profile_id} EA hash differs from configured hash")
        if process.get("process_count") != 1:
            violations.append(f"{profile_id} does not have exactly one terminal process")
        if observed.get("pid") not in process.get("pids", []):
            violations.append(f"{profile_id} supervisor PID does not match exact-path process")
        if startup_mode == "AUTOLOGON_LOCKED_INTERACTIVE" and (
            not process.get("session_ids")
            or any(int(session_id) <= 0 for session_id in process["session_ids"])
        ):
            violations.append(f"{profile_id} terminal did not run in an interactive session")

        events = new_events.get(profile_id, [])
        required_types = {"ENGINE_STARTED", "PROFILE_VALIDATED", "ENGINE_HEARTBEAT"}
        seen_types = {event.get("event_type") for event in events}
        missing = sorted(required_types - seen_types)
        if missing:
            violations.append(f"{profile_id} is missing postboot events: {missing}")
        allowed_engine_errors = set(expected.get("allowed_postboot_engine_error_reasons", []))
        if allowed_engine_errors and not (
            profile_id == "GOLDM"
            and int(expected.get("expected_trade_mode", -1)) == 2
            and expected.get("expected_order_authority") == "DISABLED"
            and allowed_engine_errors == {"MANUAL_INTERVENTION_DETECTED"}
        ):
            violations.append(f"{profile_id} has an unsafe ENGINE_ERROR exception policy")
        unexpected_engine_errors = sorted(
            {
                str(event.get("reason") or "")
                for event in events
                if event.get("event_type") == "ENGINE_ERROR"
                and event.get("reason") not in allowed_engine_errors
            }
        )
        if unexpected_engine_errors:
            violations.append(
                f"{profile_id} emitted unexpected ENGINE_ERROR after boot: "
                f"{unexpected_engine_errors}"
            )
        for event in events:
            if event.get("event_type") not in required_types:
                continue
            payload = event.get("payload") or {}
            if event.get("profile_id") != profile_id:
                violations.append(f"{profile_id} event profile mismatch")
            if (
                event.get("profile_fingerprint", "").lower()
                != str(expected["expected_profile_fingerprint"]).lower()
            ):
                violations.append(f"{profile_id} event fingerprint mismatch")
            if event.get("symbol") != expected["expected_symbol"]:
                violations.append(f"{profile_id} event symbol mismatch")
            if int(payload.get("account_login", 0)) != int(expected["expected_account_login"]):
                violations.append(f"{profile_id} event account mismatch")
            if payload.get("account_server") != expected["expected_account_server"]:
                violations.append(f"{profile_id} event server mismatch")
            if int(payload.get("trade_mode", -1)) != int(expected["expected_trade_mode"]):
                violations.append(f"{profile_id} event trade mode mismatch")
            if payload.get("order_authority") != expected["expected_order_authority"]:
                violations.append(f"{profile_id} event order authority mismatch")
            if profile_id == "GOLDM" and payload.get("order_authority") != "DISABLED":
                violations.append("GOLDM REAL event order authority is not disabled")
        profile_summary[profile_id] = {
            "new_event_count": len(events),
            "required_event_types": sorted(required_types),
            "allowed_engine_error_reasons": sorted(allowed_engine_errors),
            "ea_sha256": str(expected["ea_sha256"]).lower(),
        }

    bridge = health.get("bridge") or {}
    bridge_required = bool((config.get("bridge") or {}).get("enabled"))
    if bridge_required and (bridge.get("state") != "RUNNING" or not bridge.get("pid")):
        violations.append("optional delivery bridge was enabled but did not recover")
    roles = _items(postboot.get("python_roles"))
    if any(item.get("role") == "FORBIDDEN_PYTHON_STRATEGY" for item in roles):
        violations.append("a forbidden Python strategy/orchestrator process is running")
    if bridge_required and sum(item.get("role") == "EVENT_BRIDGE" for item in roles) != 1:
        violations.append("bridge process classification is not exactly one")
    bridge_health = postboot.get("bridge_health") or {}
    if bridge_required:
        if bridge_health.get("production_real_orders") != "DISABLED":
            violations.append("bridge health does not disable production REAL orders")
        if bridge_health.get("pid") != bridge.get("pid"):
            violations.append("bridge health PID differs from supervisor bridge PID")
        if int(bridge_health.get("pending_event_count", -1)) != 0:
            violations.append("bridge still has pending engine events")
        if int(bridge_health.get("failed_last_loop", -1)) != 0:
            violations.append("bridge latest delivery loop contains failures")
        latest_states = {
            str(item.get("event_id")): str(item.get("delivery_state"))
            for item in bridge_health.get("latest_events") or []
        }
        for profile_id in ("GOLDI", "GOLDM"):
            for event in new_events.get(profile_id, []):
                expected_state = (
                    "SUPPRESSED" if event.get("event_type") == "ENGINE_HEARTBEAT" else "DELIVERED"
                )
                if (
                    event.get("event_type")
                    in {
                        "ENGINE_STARTED",
                        "PROFILE_VALIDATED",
                        "ENGINE_HEARTBEAT",
                    }
                    and latest_states.get(str(event.get("event_id"))) != expected_state
                ):
                    violations.append(
                        f"bridge state mismatch for postboot event {event.get('event_id')}"
                    )

    for task_evidence in _items(postboot.get("legacy_tasks")):
        if task_evidence.get("enabled") or task_evidence.get("state") == "Running":
            violations.append(f"legacy task remains active: {task_evidence.get('task_name')}")

    if startup_mode == "AUTOLOGON_LOCKED_INTERACTIVE":
        marker = postboot.get("lock_marker") or {}
        if marker.get("production_real_orders") != "DISABLED":
            violations.append("lock marker does not disable production REAL orders")
        if marker.get("lock_requested") is not True or int(marker.get("session_id", 0)) <= 0:
            violations.append("workstation lock was not requested from an interactive session")
        try:
            marker_boot = _time(marker.get("boot_time_utc"), "lock_marker.boot_time_utc")
            marker_time = _time(
                marker.get("lock_requested_at_utc"), "lock_marker.lock_requested_at_utc"
            )
            if marker_boot != postboot_time:
                violations.append("lock marker boot identity differs from postboot identity")
            if marker_time < postboot_time or (marker_time - postboot_time).total_seconds() > 180:
                violations.append("workstation was not locked promptly after automatic sign-in")
        except ValueError as exc:
            violations.append(str(exc))

    return {
        "schema_version": 1,
        "gate": "G20",
        "status": "PASS" if not violations else "FAIL",
        "boot_id_changed": postboot_time > preboot_time,
        "startup_mode": startup_mode,
        "manual_login_required": False if startup_mode == "AUTOLOGON_LOCKED_INTERACTIVE" else None,
        "unattended_before_login": not any("interactive login" in item for item in violations),
        "bridge_recovered": not bridge_required or bridge.get("state") == "RUNNING",
        "profiles": profile_summary,
        "production_real_orders": "DISABLED",
        "violations": violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify G20 unattended cold-boot evidence")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preboot", type=Path, required=True)
    parser.add_argument("--postboot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(_load(args.config), _load(args.preboot), _load(args.postboot))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
