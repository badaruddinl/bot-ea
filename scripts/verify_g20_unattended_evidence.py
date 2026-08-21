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


def verify(config: dict[str, Any], preboot: dict[str, Any], postboot: dict[str, Any]) -> dict[str, Any]:
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

    task = postboot.get("task") or {}
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
    if health.get("interactive_session") is not False:
        violations.append("supervisor was not proven in a non-interactive session")
    try:
        health_started = _time(health.get("started_at_utc"), "health.started_at_utc")
        if health_started < postboot_time:
            violations.append("supervisor health predates the new boot")
        interactive_raw = postboot.get("interactive_login_observed_at_utc")
        if interactive_raw is not None and health_started >= _time(interactive_raw, "interactive login"):
            violations.append("supervisor did not start before interactive login")
    except ValueError as exc:
        violations.append(str(exc))

    configured = {item["profile_id"]: item for item in config.get("terminals", [])}
    health_profiles = {item.get("profile_id"): item for item in health.get("terminals", [])}
    process_profiles = {
        item.get("profile_id"): item for item in postboot.get("terminal_processes", [])
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

        events = new_events.get(profile_id, [])
        required_types = {"ENGINE_STARTED", "PROFILE_VALIDATED", "ENGINE_HEARTBEAT"}
        seen_types = {event.get("event_type") for event in events}
        missing = sorted(required_types - seen_types)
        if missing:
            violations.append(f"{profile_id} is missing postboot events: {missing}")
        if any(event.get("event_type") == "ENGINE_ERROR" for event in events):
            violations.append(f"{profile_id} emitted ENGINE_ERROR after boot")
        for event in events:
            if event.get("event_type") not in required_types:
                continue
            payload = event.get("payload") or {}
            if event.get("profile_id") != profile_id:
                violations.append(f"{profile_id} event profile mismatch")
            if event.get("profile_fingerprint", "").lower() != str(
                expected["expected_profile_fingerprint"]
            ).lower():
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
            "ea_sha256": str(expected["ea_sha256"]).lower(),
        }

    bridge = health.get("bridge") or {}
    bridge_required = bool((config.get("bridge") or {}).get("enabled"))
    if bridge_required and (bridge.get("state") != "RUNNING" or not bridge.get("pid")):
        violations.append("optional delivery bridge was enabled but did not recover")
    roles = postboot.get("python_roles") or []
    if any(item.get("role") == "FORBIDDEN_PYTHON_STRATEGY" for item in roles):
        violations.append("a forbidden Python strategy/orchestrator process is running")
    if bridge_required and sum(item.get("role") == "EVENT_BRIDGE" for item in roles) != 1:
        violations.append("bridge process classification is not exactly one")

    for task_evidence in postboot.get("legacy_tasks") or []:
        if task_evidence.get("enabled") or task_evidence.get("state") == "Running":
            violations.append(f"legacy task remains active: {task_evidence.get('task_name')}")

    return {
        "schema_version": 1,
        "gate": "G20",
        "status": "PASS" if not violations else "FAIL",
        "boot_id_changed": postboot_time > preboot_time,
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
