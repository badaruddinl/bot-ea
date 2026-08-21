from __future__ import annotations

import json
from pathlib import Path

import pytest

from gold_event_bridge import EventBridge, EventStore, RecipientPolicy
from gold_event_bridge.events import EngineEventEnvelope, EventSchemaError

FINGERPRINTS = {"GOLDI": "a" * 64, "GOLDM": "b" * 64}


def event(
    event_id: str,
    *,
    profile: str = "GOLDI",
    event_type: str = "ENTRY_READY",
    audience: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_id": event_id,
        "profile_id": profile,
        "profile_version": "1.0.0",
        "profile_fingerprint": FINGERPRINTS[profile],
        "event_type": event_type,
        "symbol": "GOLD.i#" if profile == "GOLDI" else "GOLDm#",
        "server_time": 1787284800,
        "reason": "M1_CONFIRMATION_READY",
        "audience": audience or ("goldi_approved" if profile == "GOLDI" else "admin_only"),
        "setup_id": f"{profile}:setup:1",
        "signal_id": f"{profile}:signal:1",
        "payload": {"entry": 4400.1, "stop_loss": 4390.1, "take_profit": 4425.1},
    }


def append(spool: Path, *values: dict[str, object], complete: bool = True) -> None:
    data = b"".join(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        for value in values
    )
    if not complete:
        data = data.rstrip(b"\n")
    with spool.open("ab") as handle:
        handle.write(data)


def test_schema_rejects_profile_audience_and_symbol_leakage() -> None:
    wrong_audience = event("goldm:1", profile="GOLDM", audience="goldi_approved")
    with pytest.raises(EventSchemaError, match="admin_only"):
        EngineEventEnvelope.from_json_line(json.dumps(wrong_audience))

    wrong_symbol = event("goldi:1")
    wrong_symbol["symbol"] = "GOLDm#"
    with pytest.raises(EventSchemaError, match="symbol mismatch"):
        EngineEventEnvelope.from_json_line(json.dumps(wrong_symbol))


def test_ingest_is_atomic_at_least_once_and_duplicate_safe(tmp_path: Path) -> None:
    spool = tmp_path / "GOLDI.jsonl"
    store = EventStore(tmp_path / "events.db")
    try:
        append(spool, event("event:1"), event("event:2"))
        first = store.ingest_spool(spool)
        assert (first.inserted, first.duplicates, store.event_count()) == (2, 0, 2)

        with store.connection:
            store.connection.execute("UPDATE spool_offsets SET byte_offset=0")
        replay = store.ingest_spool(spool)
        assert (replay.inserted, replay.duplicates, store.event_count()) == (0, 2, 2)
    finally:
        store.close()


def test_incomplete_tail_is_not_acknowledged_until_newline_arrives(tmp_path: Path) -> None:
    spool = tmp_path / "GOLDI.jsonl"
    store = EventStore(tmp_path / "events.db")
    try:
        append(spool, event("partial:1"), complete=False)
        first = store.ingest_spool(spool)
        assert first.inserted == 0
        assert first.acknowledged_offset == 0

        with spool.open("ab") as handle:
            handle.write(b"\n")
        second = store.ingest_spool(spool)
        assert second.inserted == 1
        assert second.acknowledged_offset == spool.stat().st_size
    finally:
        store.close()


def test_invalid_line_is_durably_rejected_and_acknowledged(tmp_path: Path) -> None:
    spool = tmp_path / "GOLDI.jsonl"
    spool.write_bytes(b"not-json\n")
    store = EventStore(tmp_path / "events.db")
    try:
        result = store.ingest_spool(spool)
        assert result.rejected == 1
        assert result.acknowledged_offset == spool.stat().st_size
        assert store.connection.execute("SELECT COUNT(*) FROM rejected_events").fetchone()[0] == 1
    finally:
        store.close()


def test_routing_is_profile_isolated_and_watch_is_suppressed(tmp_path: Path) -> None:
    spool = tmp_path / "events.jsonl"
    append(
        spool,
        event("goldi:entry"),
        event("goldm:entry", profile="GOLDM"),
        event("goldi:watch", event_type="WATCH_UPDATED", audience="internal"),
    )
    store = EventStore(tmp_path / "events.db")
    sent: list[tuple[str, str]] = []
    bridge = EventBridge(
        store,
        RecipientPolicy(("admin",), ("subscriber",)),
        lambda chat_id, message: sent.append((chat_id, message)),
    )
    try:
        store.ingest_spool(spool)
        delivered, failed = bridge.deliver_pending()
        assert (delivered, failed) == (3, 0)
        assert [chat for chat, message in sent if "GOLDI" in message] == ["admin", "subscriber"]
        assert [chat for chat, message in sent if "GOLDM" in message] == ["admin"]
        watch_state = store.connection.execute(
            "SELECT delivery_state FROM engine_events WHERE event_id='goldi:watch'"
        ).fetchone()[0]
        assert watch_state == "SUPPRESSED"
    finally:
        store.close()


def test_order_and_modify_diagnostics_are_db_only_not_telegram(tmp_path: Path) -> None:
    spool = tmp_path / "events.jsonl"
    append(
        spool,
        event("goldi:order", event_type="ORDER_SUBMITTED", audience="admin_only"),
        event("goldi:modify", event_type="POSITION_MODIFIED", audience="admin_only"),
    )
    store = EventStore(tmp_path / "events.db")
    sent: list[str] = []
    bridge = EventBridge(
        store,
        RecipientPolicy(("admin",), ("subscriber",)),
        lambda _chat_id, message: sent.append(message),
    )
    try:
        store.ingest_spool(spool)
        assert bridge.deliver_pending() == (0, 0)
        assert not sent
        states = {
            row[0]
            for row in store.connection.execute(
                "SELECT delivery_state FROM engine_events ORDER BY event_id"
            )
        }
        assert states == {"SUPPRESSED"}
    finally:
        store.close()


def test_telegram_failure_retries_only_undelivered_recipient(tmp_path: Path) -> None:
    spool = tmp_path / "events.jsonl"
    append(spool, event("retry:1"))
    store = EventStore(tmp_path / "events.db")
    attempts: list[str] = []

    def sender(chat_id: str, _message: str) -> None:
        attempts.append(chat_id)
        if chat_id == "subscriber" and attempts.count(chat_id) == 1:
            raise TimeoutError

    bridge = EventBridge(
        store,
        RecipientPolicy(("admin",), ("subscriber",)),
        sender,
    )
    try:
        store.ingest_spool(spool)
        assert bridge.deliver_pending() == (1, 1)
        assert bridge.deliver_pending() == (1, 0)
        assert attempts == ["admin", "subscriber", "subscriber"]
        state = store.connection.execute(
            "SELECT delivery_state FROM engine_events WHERE event_id='retry:1'"
        ).fetchone()[0]
        assert state == "DELIVERED"
    finally:
        store.close()
