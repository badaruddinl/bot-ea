from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/run_g17_bridge_probe.py"
SPEC = importlib.util.spec_from_file_location("run_g17_bridge_probe", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def line(profile: str, event_type: str, sequence: int) -> bytes:
    chain = f"G17|{profile}|100"
    payload = {
        "schema_version": 1,
        "event_id": f"{chain}|{event_type}|{event_type}|TEST",
        "profile_id": profile,
        "profile_version": "1.0.0",
        "profile_fingerprint": ("a" if profile == "GOLDI" else "b") * 64,
        "event_type": event_type,
        "symbol": "GOLD.i#" if profile == "GOLDI" else "GOLDm#",
        "server_time": 100 + sequence,
        "reason": "TEST",
        "audience": "goldi_approved" if profile == "GOLDI" else "admin_only",
        "setup_id": f"{chain}|SETUP",
        "signal_id": f"{chain}|SIGNAL",
        "order_id": "2",
        "position_id": "2",
        "payload": {},
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode() + b"\n"


def test_probe_correlates_dual_profile_spool_db_and_delivery(tmp_path: Path) -> None:
    goldi = tmp_path / "GOLDI.jsonl"
    goldm = tmp_path / "GOLDM.jsonl"
    event_types = sorted(MODULE.EXPECTED_TYPES)
    goldi.write_bytes(
        b"".join(line("GOLDI", value, index) for index, value in enumerate(event_types))
    )
    goldm.write_bytes(
        b"".join(line("GOLDM", value, index) for index, value in enumerate(event_types))
    )

    report = MODULE.run_probe(goldi, goldm, tmp_path / "events.db")

    assert report["status"] == "PASS"
    assert report["database_event_count"] == 12
    assert report["profiles"]["GOLDI"]["event_count"] == 6
    assert report["profiles"]["GOLDM"]["event_count"] == 6
    assert report["goldm_approved_leak_count"] == 0
    assert report["delivery_calls"] == 9
    assert report["production_real_orders"] == "DISABLED"
