from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from gold_event_bridge import EventBridge, EventStore, RecipientPolicy


class DependencyLabError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_lab(goldi_spool: Path, goldm_spool: Path, workspace: Path) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    before = {"GOLDI": _sha256(goldi_spool), "GOLDM": _sha256(goldm_spool)}

    blocked_db = workspace / "database-unavailable"
    blocked_db.mkdir(exist_ok=True)
    db_failure = False
    try:
        EventStore(blocked_db)
    except sqlite3.Error:
        db_failure = True
    if not db_failure:
        raise DependencyLabError("DB-down injection did not fail")
    if before != {"GOLDI": _sha256(goldi_spool), "GOLDM": _sha256(goldm_spool)}:
        raise DependencyLabError("dependency failure mutated the EA spools")

    store = EventStore(workspace / "recovered.db")
    try:
        goldi = store.ingest_spool(goldi_spool)
        goldm = store.ingest_spool(goldm_spool)
        if goldi.inserted != 6 or goldm.inserted != 6 or store.event_count() != 12:
            raise DependencyLabError("bridge recovery did not ingest the full backlog")

        def telegram_down(_chat_id: str, _message: str) -> None:
            raise TimeoutError

        failing = EventBridge(
            store,
            RecipientPolicy(("g18-admin",), ("g18-approved",)),
            telegram_down,
        )
        first_delivered, first_failed = failing.deliver_pending(limit=100)
        if first_delivered != 0 or first_failed != 9:
            raise DependencyLabError("Telegram-down retry matrix is incorrect")
        recovered_calls: list[tuple[str, str]] = []
        recovered = EventBridge(
            store,
            RecipientPolicy(("g18-admin",), ("g18-approved",)),
            lambda chat_id, message: recovered_calls.append((chat_id, message)),
        )
        second_delivered, second_failed = recovered.deliver_pending(limit=100)
        if second_delivered != 9 or second_failed != 0:
            raise DependencyLabError("Telegram recovery did not drain retry state")

        with store.connection:
            store.connection.execute("UPDATE spool_offsets SET byte_offset=0")
        replay_goldi = store.ingest_spool(goldi_spool)
        replay_goldm = store.ingest_spool(goldm_spool)
        duplicates = replay_goldi.duplicates + replay_goldm.duplicates
        if duplicates != 12 or store.event_count() != 12:
            raise DependencyLabError("backlog replay created duplicate DB rows")
        states = {
            str(row[0]): int(row[1])
            for row in store.connection.execute(
                "SELECT delivery_state, COUNT(*) FROM engine_events GROUP BY delivery_state"
            )
        }
        if states != {"DELIVERED": 6, "SUPPRESSED": 6}:
            raise DependencyLabError(f"unexpected final delivery states: {states}")
        after = {"GOLDI": _sha256(goldi_spool), "GOLDM": _sha256(goldm_spool)}
        return {
            "schema_version": 1,
            "status": "PASS",
            "bridge_down_backlog_events": 12,
            "db_down_failed_closed": db_failure,
            "telegram_down_failed_calls": first_failed,
            "telegram_recovery_delivered_calls": second_delivered,
            "backlog_replay_duplicates": duplicates,
            "database_event_count": store.event_count(),
            "delivery_states": states,
            "spool_unchanged": before == after,
            "spool_sha256": after,
            "production_real_orders": "DISABLED",
        }
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run G18 dependency failure lab")
    parser.add_argument("--goldi-spool", type=Path, required=True)
    parser.add_argument("--goldm-spool", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_lab(args.goldi_spool, args.goldm_spool, args.workspace)
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
