from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .events import EngineEventEnvelope, EventSchemaError


@dataclass(frozen=True, slots=True)
class IngestResult:
    inserted: int
    duplicates: int
    rejected: int
    acknowledged_offset: int


class EventStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self._migrate()

    def close(self) -> None:
        self.connection.close()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS engine_events (
                event_id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                server_time TEXT NOT NULL,
                audience TEXT NOT NULL,
                raw_event TEXT NOT NULL,
                delivery_state TEXT NOT NULL DEFAULT 'PENDING',
                inserted_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS spool_offsets (
                spool_path TEXT PRIMARY KEY,
                byte_offset INTEGER NOT NULL CHECK(byte_offset >= 0),
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rejected_events (
                spool_path TEXT NOT NULL,
                byte_offset INTEGER NOT NULL,
                raw_line BLOB NOT NULL,
                reason TEXT NOT NULL,
                rejected_at TEXT NOT NULL,
                PRIMARY KEY(spool_path, byte_offset)
            );
            CREATE TABLE IF NOT EXISTS deliveries (
                event_id TEXT NOT NULL REFERENCES engine_events(event_id),
                chat_id TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'PENDING',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                delivered_at TEXT,
                PRIMARY KEY(event_id, chat_id)
            );
            """
        )
        self.connection.commit()

    def ingest_spool(self, spool: Path) -> IngestResult:
        key = str(spool.resolve())
        row = self.connection.execute(
            "SELECT byte_offset FROM spool_offsets WHERE spool_path = ?", (key,)
        ).fetchone()
        offset = int(row[0]) if row else 0
        if not spool.exists():
            return IngestResult(0, 0, 0, offset)
        inserted = duplicates = rejected = 0
        with spool.open("rb") as handle, self.connection:
            handle.seek(offset)
            while True:
                line_offset = handle.tell()
                line = handle.readline()
                if not line:
                    break
                if not line.endswith(b"\n"):
                    handle.seek(line_offset)
                    break
                acknowledged = handle.tell()
                try:
                    event = EngineEventEnvelope.from_json_line(line)
                except EventSchemaError as exc:
                    self.connection.execute(
                        """
                        INSERT OR IGNORE INTO rejected_events
                            (spool_path, byte_offset, raw_line, reason, rejected_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (key, line_offset, line, str(exc), datetime.now(UTC).isoformat()),
                    )
                    rejected += 1
                else:
                    cursor = self.connection.execute(
                        """
                        INSERT OR IGNORE INTO engine_events
                            (event_id, profile_id, event_type, server_time, audience,
                             raw_event, inserted_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event.event_id,
                            event.profile_id,
                            event.event_type,
                            event.server_time.isoformat(),
                            event.audience,
                            event.canonical_json(),
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                    if cursor.rowcount:
                        inserted += 1
                    else:
                        duplicates += 1
                offset = acknowledged
            self.connection.execute(
                """
                INSERT INTO spool_offsets(spool_path, byte_offset, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(spool_path) DO UPDATE SET
                    byte_offset=excluded.byte_offset,
                    updated_at=excluded.updated_at
                """,
                (key, offset, datetime.now(UTC).isoformat()),
            )
        return IngestResult(inserted, duplicates, rejected, offset)

    def pending_events(self) -> tuple[sqlite3.Row, ...]:
        return tuple(
            self.connection.execute(
                "SELECT * FROM engine_events WHERE delivery_state = 'PENDING' ORDER BY rowid"
            )
        )

    def event_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM engine_events").fetchone()[0])
