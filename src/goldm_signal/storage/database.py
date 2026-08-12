from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ..strategy.state_machine import SetupRecord, SetupState


_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS setups (
    setup_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    level REAL NOT NULL,
    breakout_at TEXT NOT NULL,
    state TEXT NOT NULL,
    retest_bars_elapsed INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS setup_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_id TEXT NOT NULL REFERENCES setups(setup_id),
    from_state TEXT,
    to_state TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signal_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_id TEXT NOT NULL REFERENCES setups(setup_id),
    event_type TEXT NOT NULL,
    event_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    UNIQUE(setup_id, event_key)
);
"""


class SignalStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def save_setup(self, record: SetupRecord) -> None:
        now = _utc_now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT state FROM setups WHERE setup_id = ?", (record.setup_id,)
            ).fetchone()
            previous = str(existing[0]) if existing else None
            connection.execute(
                """
                INSERT INTO setups (
                    setup_id, symbol, side, level, breakout_at, state,
                    retest_bars_elapsed, reason, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(setup_id) DO UPDATE SET
                    state = excluded.state,
                    retest_bars_elapsed = excluded.retest_bars_elapsed,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (
                    record.setup_id,
                    record.symbol,
                    record.side,
                    record.level,
                    _iso(record.breakout_at),
                    record.state.value,
                    record.retest_bars_elapsed,
                    record.reason,
                    now,
                ),
            )
            if previous != record.state.value:
                connection.execute(
                    """
                    INSERT INTO setup_transitions (setup_id, from_state, to_state, reason, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (record.setup_id, previous, record.state.value, record.reason or "setup created", now),
                )

    def load_setup(self, setup_id: str) -> SetupRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM setups WHERE setup_id = ?", (setup_id,)).fetchone()
        if row is None:
            return None
        return SetupRecord(
            setup_id=str(row["setup_id"]),
            symbol=str(row["symbol"]),
            side=str(row["side"]),
            level=float(row["level"]),
            breakout_at=datetime.fromisoformat(str(row["breakout_at"]).replace("Z", "+00:00")),
            state=SetupState(str(row["state"])),
            retest_bars_elapsed=int(row["retest_bars_elapsed"]),
            reason=str(row["reason"]),
        )

    def enqueue(
        self,
        *,
        setup_id: str,
        event_type: str,
        payload: dict[str, Any],
        event_key: str | None = None,
    ) -> bool:
        dedupe_key = event_key or event_type
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO signal_outbox (setup_id, event_type, event_key, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (setup_id, event_type, dedupe_key, json.dumps(payload, sort_keys=True), _utc_now()),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def pending(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM signal_outbox
                WHERE sent_at IS NULL
                ORDER BY id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]

    def mark_sent(self, outbox_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE signal_outbox
                SET sent_at = ?, attempt_count = attempt_count + 1, last_error = NULL
                WHERE id = ?
                """,
                (_utc_now(), outbox_id),
            )

    def mark_failed(self, outbox_id: int, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE signal_outbox SET attempt_count = attempt_count + 1, last_error = ? WHERE id = ?",
                (error[:1000], outbox_id),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
