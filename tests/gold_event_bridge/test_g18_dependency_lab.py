from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/run_g18_dependency_lab.py"
SPEC = importlib.util.spec_from_file_location("run_g18_dependency_lab", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def event(profile: str, event_type: str, sequence: int) -> bytes:
    value = {
        "schema_version": 1,
        "event_id": f"G18|{profile}|{sequence}|{event_type}",
        "profile_id": profile,
        "profile_version": "1.0.0",
        "profile_fingerprint": ("a" if profile == "GOLDI" else "b") * 64,
        "event_type": event_type,
        "symbol": "GOLD.i#" if profile == "GOLDI" else "GOLDm#",
        "server_time": 100 + sequence,
        "reason": "TEST",
        "audience": "goldi_approved" if profile == "GOLDI" else "admin_only",
        "payload": {},
    }
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode() + b"\n"


def test_dependency_lab_recovers_backlog_retry_and_duplicate_replay(tmp_path: Path) -> None:
    types = (
        "SETUP_CREATED",
        "ENTRY_READY",
        "ORDER_SUBMITTED",
        "POSITION_OPENED",
        "POSITION_MODIFIED",
        "POSITION_CLOSED",
    )
    goldi = tmp_path / "GOLDI.jsonl"
    goldm = tmp_path / "GOLDM.jsonl"
    goldi.write_bytes(b"".join(event("GOLDI", value, index) for index, value in enumerate(types)))
    goldm.write_bytes(b"".join(event("GOLDM", value, index) for index, value in enumerate(types)))

    report = MODULE.run_lab(goldi, goldm, tmp_path / "lab")

    assert report["status"] == "PASS"
    assert report["db_down_failed_closed"]
    assert report["telegram_down_failed_calls"] == 6
    assert report["telegram_recovery_delivered_calls"] == 6
    assert report["backlog_replay_duplicates"] == 12
    assert report["database_event_count"] == 12
    assert report["spool_unchanged"]
    assert report["production_real_orders"] == "DISABLED"
