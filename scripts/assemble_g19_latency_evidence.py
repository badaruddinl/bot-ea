from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

NATIVE_FIELDS = {
    "bar_close_to_detection_ms": ("bar_close_to_detection", 1.0),
    "detection_to_decision_us": ("detection_to_decision", 0.001),
    "entry_ready_to_submit_us": ("entry_ready_to_submit", 0.001),
    "submit_to_broker_ack_us": ("submit_to_broker_ack", 0.001),
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _position_latencies(path: Path, offset: int, profile_id: str) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {target: [] for target, _factor in NATIVE_FIELDS.values()}
    lines = path.read_text(encoding="utf-8").splitlines()
    for raw in lines[offset:]:
        event = json.loads(raw)
        if event.get("profile_id") != profile_id or event.get("event_type") != "POSITION_OPENED":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise ValueError(f"{profile_id} POSITION_OPENED payload must be an object")
        for source, (target, factor) in NATIVE_FIELDS.items():
            value = payload.get(source)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{profile_id} POSITION_OPENED missing non-negative {source}")
            result[target].append(float(value) * factor)
    if not result["submit_to_broker_ack"]:
        raise ValueError(f"{profile_id} produced no POSITION_OPENED latency samples")
    return result


def assemble(
    *,
    resource_capture: Path,
    bridge_capture: Path,
    goldi_spool: Path,
    goldi_offset: int,
    goldm_spool: Path,
    goldm_offset: int,
) -> dict[str, Any]:
    result = _read_json(resource_capture)
    bridge = _read_json(bridge_capture)
    combined: dict[str, list[float]] = {target: [] for target, _ in NATIVE_FIELDS.values()}
    counts: dict[str, int] = {}
    for profile_id, spool, offset in (
        ("GOLDI", goldi_spool, goldi_offset),
        ("GOLDM", goldm_spool, goldm_offset),
    ):
        values = _position_latencies(spool, offset, profile_id)
        counts[profile_id] = len(values["submit_to_broker_ack"])
        for name, samples in values.items():
            combined[name].extend(samples)

    bridge_latencies = bridge.get("latencies_ms")
    if not isinstance(bridge_latencies, dict):
        raise ValueError("bridge capture is missing latencies_ms")
    for name in ("event_enqueue_to_db", "event_enqueue_to_telegram"):
        bridge_samples = bridge_latencies.get(name)
        if not isinstance(bridge_samples, list) or not bridge_samples:
            raise ValueError(f"bridge capture is missing {name}")
        combined[name] = [float(value) for value in bridge_samples]

    result["latencies_ms"] = combined
    result["latency_evidence"] = {
        "native_source": "actual_mql5_strategy_tester_position_opened",
        "native_profile_sample_counts": counts,
        "bridge_source": bridge.get("source"),
        "telegram_scope": "capture_sender_no_internet",
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble actual G19 latency evidence")
    parser.add_argument("--resource-capture", type=Path, required=True)
    parser.add_argument("--bridge-capture", type=Path, required=True)
    parser.add_argument("--goldi-spool", type=Path, required=True)
    parser.add_argument("--goldi-offset", type=int, required=True)
    parser.add_argument("--goldm-spool", type=Path, required=True)
    parser.add_argument("--goldm-offset", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.goldi_offset < 0 or args.goldm_offset < 0:
        parser.error("spool offsets must be non-negative")
    result = assemble(
        resource_capture=args.resource_capture,
        bridge_capture=args.bridge_capture,
        goldi_spool=args.goldi_spool,
        goldi_offset=args.goldi_offset,
        goldm_spool=args.goldm_spool,
        goldm_offset=args.goldm_offset,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
