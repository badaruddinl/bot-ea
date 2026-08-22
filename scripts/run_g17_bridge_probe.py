from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from gold_event_bridge import EventBridge, EventStore, RecipientPolicy
from gold_event_bridge.events import EngineEventEnvelope

EXPECTED_TYPES = {
    "SETUP_CREATED",
    "ENTRY_READY",
    "ORDER_SUBMITTED",
    "POSITION_OPENED",
    "POSITION_MODIFIED",
    "POSITION_CLOSED",
}


class ProbeError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_probe(goldi_spool: Path, goldm_spool: Path, database: Path) -> dict[str, Any]:
    sent: list[tuple[str, str]] = []
    store = EventStore(database)
    try:
        goldi_ingest = store.ingest_spool(goldi_spool)
        goldm_ingest = store.ingest_spool(goldm_spool)
        bridge = EventBridge(
            store,
            RecipientPolicy(("g17-admin",), ("g17-approved",)),
            lambda chat_id, message: sent.append((chat_id, message)),
        )
        delivered, failed = bridge.deliver_pending(limit=100)
        rows = tuple(store.connection.execute("SELECT * FROM engine_events ORDER BY event_id"))
        events = [EngineEventEnvelope.from_json_line(str(row["raw_event"])) for row in rows]
        by_profile: dict[str, list[EngineEventEnvelope]] = defaultdict(list)
        for event in events:
            by_profile[event.profile_id].append(event)
        if set(by_profile) != {"GOLDI", "GOLDM"}:
            raise ProbeError("dual-profile event matrix incomplete")
        chains: dict[str, str] = {}
        for profile_id, profile_events in by_profile.items():
            if {event.event_type for event in profile_events} != EXPECTED_TYPES:
                raise ProbeError(f"{profile_id} event lifecycle incomplete")
            prefixes = {
                tuple(event.event_id.split("|", maxsplit=3)[0:3]) for event in profile_events
            }
            # Convert slices to a stable chain string without accepting mixed chains.
            chain_values = {"|".join(parts) for parts in prefixes}
            if len(chain_values) != 1:
                raise ProbeError(f"{profile_id} chain correlation mismatch")
            chain = next(iter(chain_values))
            chain_parts = chain.split("|")
            if (
                len(chain_parts) != 3
                or chain_parts[:2] != ["G17", profile_id]
                or not chain_parts[2].isdigit()
            ):
                raise ProbeError(f"{profile_id} chain identity mismatch")
            chains[profile_id] = chain
            for event in profile_events:
                if event.setup_id and not event.setup_id.startswith(chain):
                    raise ProbeError(f"{profile_id} setup correlation mismatch")
                if event.signal_id and not event.signal_id.startswith(chain):
                    raise ProbeError(f"{profile_id} signal correlation mismatch")
        if failed:
            raise ProbeError("capture sender failed")
        goldm_leak = [item for item in sent if item[0] == "g17-approved" and "GOLDM" in item[1]]
        if goldm_leak:
            raise ProbeError("GOLDM event leaked to approved GOLDI audience")
        states = Counter(str(row["delivery_state"]) for row in rows)
        return {
            "schema_version": 1,
            "status": "PASS",
            "profiles": {
                profile_id: {
                    "chain_id": chains[profile_id],
                    "event_count": len(by_profile[profile_id]),
                    "event_types": sorted(event.event_type for event in by_profile[profile_id]),
                }
                for profile_id in ("GOLDI", "GOLDM")
            },
            "ingest": {
                "GOLDI": {
                    "inserted": goldi_ingest.inserted,
                    "duplicates": goldi_ingest.duplicates,
                    "acknowledged_offset": goldi_ingest.acknowledged_offset,
                },
                "GOLDM": {
                    "inserted": goldm_ingest.inserted,
                    "duplicates": goldm_ingest.duplicates,
                    "acknowledged_offset": goldm_ingest.acknowledged_offset,
                },
            },
            "database_event_count": len(rows),
            "delivery_calls": delivered,
            "delivery_states": dict(sorted(states.items())),
            "goldm_approved_leak_count": len(goldm_leak),
            "telegram_mode": "CAPTURE_SENDER",
            "spool_sha256": {
                "GOLDI": _sha256(goldi_spool),
                "GOLDM": _sha256(goldm_spool),
            },
            "production_real_orders": "DISABLED",
        }
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run G17 spool-to-delivery E2E probe")
    parser.add_argument("--goldi-spool", type=Path, required=True)
    parser.add_argument("--goldm-spool", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_probe(args.goldi_spool, args.goldm_spool, args.database)
    encoded = (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    args.output.with_suffix(".sha256").write_text(
        f"{hashlib.sha256(encoded).hexdigest()}  {args.output.name}\n", encoding="ascii"
    )
    print(encoded.decode().strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
