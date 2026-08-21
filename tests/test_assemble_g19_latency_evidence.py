from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "assemble_g19_latency_evidence", ROOT / "scripts/assemble_g19_latency_evidence.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _event(profile: str, value: int) -> dict[str, object]:
    return {
        "profile_id": profile,
        "event_type": "POSITION_OPENED",
        "payload": {
            "bar_close_to_detection_ms": value,
            "detection_to_decision_us": 2_000,
            "entry_ready_to_submit_us": 300,
            "submit_to_broker_ack_us": 400,
        },
    }


def test_assembles_profile_and_bridge_latency_without_placeholder_values(tmp_path: Path) -> None:
    resource = tmp_path / "resource.json"
    bridge = tmp_path / "bridge.json"
    goldi = tmp_path / "goldi.jsonl"
    goldm = tmp_path / "goldm.jsonl"
    _write(resource, {"schema_version": 1, "samples": []})
    _write(
        bridge,
        {
            "source": "actual_bridge_capture_sender_no_network",
            "latencies_ms": {
                "event_enqueue_to_db": [5.0],
                "event_enqueue_to_telegram": [7.0],
            },
        },
    )
    goldi.write_text("ignored\n" + json.dumps(_event("GOLDI", 11)) + "\n", encoding="utf-8")
    goldm.write_text(json.dumps(_event("GOLDM", 13)) + "\n", encoding="utf-8")

    result = MODULE.assemble(
        resource_capture=resource,
        bridge_capture=bridge,
        goldi_spool=goldi,
        goldi_offset=1,
        goldm_spool=goldm,
        goldm_offset=0,
    )

    assert result["latencies_ms"]["bar_close_to_detection"] == [11.0, 13.0]
    assert result["latencies_ms"]["detection_to_decision"] == [2.0, 2.0]
    assert result["latencies_ms"]["submit_to_broker_ack"] == [0.4, 0.4]
    assert result["latency_evidence"]["native_profile_sample_counts"] == {
        "GOLDI": 1,
        "GOLDM": 1,
    }
    assert result["latency_evidence"]["telegram_scope"] == "capture_sender_no_internet"
