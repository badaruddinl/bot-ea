from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from gold_event_bridge import (  # noqa: E402
    EngineEventEnvelope,
    EventBridge,
    EventStore,
    RecipientPolicy,
)


@dataclass(slots=True)
class TimestampSender:
    observed: list[int] = field(default_factory=list)

    def __call__(self, _chat_id: str, _message: str) -> None:
        self.observed.append(perf_counter_ns())


def event(index: int) -> EngineEventEnvelope:
    value = {
        "schema_version": 1,
        "event_id": f"G19|GOLDI|LATENCY|{index}",
        "profile_id": "GOLDI",
        "profile_version": "1.1.0",
        "profile_fingerprint": "7af1d75e1be54ba4505b32cedcf53f4317dea0a90a2a0636510884d0d408c5b5",
        "event_type": "ENGINE_ERROR",
        "symbol": "GOLD.i#",
        "server_time": int(datetime.now(UTC).timestamp()),
        "reason": "G19_LATENCY_PROBE",
        "audience": "admin_only",
        "setup_id": "",
        "signal_id": "",
        "order_id": "",
        "position_id": "",
        "payload": {},
    }
    return EngineEventEnvelope.from_json_line(json.dumps(value))


def run(output: Path, workspace: Path, iterations: int) -> dict[str, object]:
    if iterations < 20:
        raise ValueError("iterations must be at least 20")
    workspace.mkdir(parents=True, exist_ok=True)
    spool = workspace / "GOLDI-latency.jsonl"
    database = workspace / "latency.db"
    spool.write_bytes(b"")
    store = EventStore(database)
    enqueue_to_db: list[float] = []
    enqueue_to_sender: list[float] = []
    try:
        for index in range(iterations):
            envelope = event(index)
            enqueued_at = perf_counter_ns()
            with spool.open("ab") as handle:
                handle.write(envelope.canonical_json().encode() + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            ingest = store.ingest_spool(spool)
            stored_at = perf_counter_ns()
            sender = TimestampSender()
            bridge = EventBridge(
                store,
                RecipientPolicy(("1",), ()),
                sender,
            )
            delivered, failed = bridge.deliver_pending(limit=1)
            if ingest.inserted != 1 or delivered != 1 or failed or len(sender.observed) != 1:
                raise RuntimeError("bridge latency probe did not complete exactly one event")
            enqueue_to_db.append((stored_at - enqueued_at) / 1_000_000.0)
            enqueue_to_sender.append((sender.observed[0] - enqueued_at) / 1_000_000.0)
    finally:
        store.close()

    result: dict[str, object] = {
        "schema_version": 1,
        "iterations": iterations,
        "source": "actual_bridge_capture_sender_no_network",
        "latencies_ms": {
            "event_enqueue_to_db": enqueue_to_db,
            "event_enqueue_to_telegram": enqueue_to_sender,
        },
        "production_real_orders": "DISABLED",
    }
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure actual G19 bridge latency")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.output, args.workspace, args.iterations),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
