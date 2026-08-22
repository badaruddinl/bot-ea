from __future__ import annotations

import sqlite3
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from os import replace
from pathlib import Path
from uuid import uuid4

from .events import EngineEventEnvelope, EventSchemaError


@dataclass(frozen=True, slots=True)
class IngestResult:
    inserted: int
    duplicates: int
    rejected: int
    acknowledged_offset: int


@dataclass(frozen=True, slots=True)
class SpoolCompactionResult:
    rotated: bool
    original_size: int
    acknowledged_offset: int
    recovered_tail_events: int = 0


@dataclass(frozen=True, slots=True)
class SpoolRecoveryResult:
    files_seen: int
    files_removed: int
    inserted: int
    duplicates: int
    rejected: int


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
        # A bridge-owned rotation may reach the filesystem before its offset
        # reset commits. A newly-created producer spool is smaller than the
        # previous acknowledged file and must start from byte zero.
        if spool.stat().st_size < offset:
            offset = 0
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
            if row is None or offset != int(row[0]):
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

    def compact_ingested_spool(self, spool: Path, *, minimum_bytes: int) -> SpoolCompactionResult:
        """Rotate a fully ingested spool after its events are durable in SQLite.

        The producer opens the spool only for transition writes and closes it
        immediately. On Windows an atomic rename fails while that handle is
        open, so a busy producer is retried on the next bridge cycle. The
        rotated file is ingested again before deletion to capture bytes appended
        between the original ingest and the rename boundary.
        """

        if minimum_bytes <= 0:
            raise ValueError("minimum_bytes must be positive")
        key = str(spool.resolve())
        row = self.connection.execute(
            "SELECT byte_offset FROM spool_offsets WHERE spool_path = ?", (key,)
        ).fetchone()
        offset = int(row[0]) if row else 0
        if not spool.exists():
            return SpoolCompactionResult(False, 0, offset)
        original_size = spool.stat().st_size
        if original_size < minimum_bytes or offset != original_size:
            return SpoolCompactionResult(False, original_size, offset)

        rotated = spool.with_name(f"{spool.name}.bridge-{uuid4().hex}.rotating")
        # Reset first. A crash after this commit can only cause duplicate replay,
        # never skipping bytes in the producer's next spool.
        with self.connection:
            self.connection.execute(
                "UPDATE spool_offsets SET byte_offset=0, updated_at=? WHERE spool_path=?",
                (datetime.now(UTC).isoformat(), key),
            )
        try:
            replace(spool, rotated)
        except (FileNotFoundError, PermissionError):
            with self.connection:
                self.connection.execute(
                    "UPDATE spool_offsets SET byte_offset=?, updated_at=? WHERE spool_path=?",
                    (offset, datetime.now(UTC).isoformat(), key),
                )
            return SpoolCompactionResult(False, original_size, offset)

        rotated_result = self.ingest_spool(rotated)
        rotated_size = rotated.stat().st_size
        if rotated_result.acknowledged_offset != rotated_size:
            # Preserve an unexpected incomplete record for recovery/forensics.
            # On Windows this path is unreachable while a producer handle is
            # open because the preceding rename fails closed.
            return SpoolCompactionResult(
                False,
                original_size,
                offset,
                recovered_tail_events=rotated_result.inserted,
            )

        rotated_key = str(rotated.resolve())
        with self.connection:
            self.connection.execute("DELETE FROM spool_offsets WHERE spool_path=?", (rotated_key,))
        with suppress(FileNotFoundError):
            rotated.unlink()
        return SpoolCompactionResult(
            True,
            original_size,
            0,
            recovered_tail_events=rotated_result.inserted,
        )

    def recover_rotated_spools(self, spool: Path) -> SpoolRecoveryResult:
        """Replay bridge-owned rotation remnants after a process/VM crash."""

        seen = removed = inserted = duplicates = rejected = 0
        pattern = f"{spool.name}.bridge-*.rotating"
        for rotated in sorted(spool.parent.glob(pattern)):
            seen += 1
            result = self.ingest_spool(rotated)
            inserted += result.inserted
            duplicates += result.duplicates
            rejected += result.rejected
            if result.acknowledged_offset != rotated.stat().st_size:
                continue
            with self.connection:
                self.connection.execute(
                    "DELETE FROM spool_offsets WHERE spool_path=?",
                    (str(rotated.resolve()),),
                )
            with suppress(FileNotFoundError):
                rotated.unlink()
            removed += 1
        return SpoolRecoveryResult(seen, removed, inserted, duplicates, rejected)

    def pending_events(self) -> tuple[sqlite3.Row, ...]:
        return tuple(
            self.connection.execute(
                "SELECT * FROM engine_events WHERE delivery_state = 'PENDING' ORDER BY rowid"
            )
        )

    def event_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM engine_events").fetchone()[0])
