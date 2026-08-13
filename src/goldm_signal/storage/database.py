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
CREATE TABLE IF NOT EXISTS telegram_subscribers (
    chat_id TEXT PRIMARY KEY,
    username TEXT NOT NULL DEFAULT '',
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED')),
    requested_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_telegram_subscribers_status
    ON telegram_subscribers(status);
CREATE TABLE IF NOT EXISTS telegram_bot_state (
    state_key TEXT PRIMARY KEY,
    state_value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mt5_log_cursors (
    log_path TEXT PRIMARY KEY,
    byte_offset INTEGER NOT NULL DEFAULT 0,
    encoding TEXT NOT NULL DEFAULT 'utf-8',
    fragment TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS telegram_deliveries (
    outbox_id INTEGER NOT NULL REFERENCES signal_outbox(id) ON DELETE CASCADE,
    chat_id TEXT NOT NULL REFERENCES telegram_subscribers(chat_id),
    sent_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    PRIMARY KEY(outbox_id, chat_id)
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

    def latest_event(
        self, *, event_types: tuple[str, ...] | None = None
    ) -> dict[str, Any] | None:
        query = """
            SELECT signal_outbox.*, setups.symbol, setups.side, setups.level,
                   setups.breakout_at, setups.state
            FROM signal_outbox
            JOIN setups ON setups.setup_id = signal_outbox.setup_id
        """
        parameters: tuple[str, ...] = ()
        if event_types:
            placeholders = ", ".join("?" for _ in event_types)
            query += f" WHERE signal_outbox.event_type IN ({placeholders})"
            parameters = event_types
        query += " ORDER BY signal_outbox.id DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        return _outbox_row(row) if row is not None else None

    def recent_events(self, *, limit: int = 5) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 20))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT signal_outbox.*, setups.symbol, setups.side, setups.level,
                       setups.breakout_at, setups.state
                FROM signal_outbox
                JOIN setups ON setups.setup_id = signal_outbox.setup_id
                ORDER BY signal_outbox.id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [_outbox_row(row) for row in rows]

    def notification_health(self) -> dict[str, Any]:
        with self._connect() as connection:
            outbox = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_count,
                    SUM(CASE WHEN sent_at IS NULL THEN 1 ELSE 0 END) AS pending_count,
                    SUM(CASE WHEN last_error IS NOT NULL THEN 1 ELSE 0 END) AS failed_count,
                    MAX(created_at) AS last_event_at,
                    MAX(sent_at) AS last_sent_at
                FROM signal_outbox
                """
            ).fetchone()
            cursor = connection.execute(
                "SELECT MAX(updated_at) AS last_log_at FROM mt5_log_cursors"
            ).fetchone()
        assert outbox is not None and cursor is not None
        return {
            "total_count": int(outbox["total_count"] or 0),
            "pending_count": int(outbox["pending_count"] or 0),
            "failed_count": int(outbox["failed_count"] or 0),
            "last_event_at": outbox["last_event_at"],
            "last_sent_at": outbox["last_sent_at"],
            "last_log_at": cursor["last_log_at"],
        }

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

    def request_telegram_subscription(
        self,
        *,
        chat_id: str | int,
        username: str = "",
        first_name: str = "",
        last_name: str = "",
    ) -> tuple[dict[str, Any], bool]:
        """Create a pending request or reopen a previously rejected request.

        The boolean result is true only when an administrator needs a new
        approval notification. Repeated ``/start`` messages from an already
        pending or approved chat are idempotent.
        """

        normalized_id = str(chat_id)
        now = _utc_now()
        needs_review = False
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT status FROM telegram_subscribers WHERE chat_id = ?", (normalized_id,)
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO telegram_subscribers (
                        chat_id, username, first_name, last_name, status, requested_at
                    ) VALUES (?, ?, ?, ?, 'PENDING', ?)
                    """,
                    (normalized_id, username, first_name, last_name, now),
                )
                needs_review = True
            elif str(existing["status"]) == "REJECTED":
                connection.execute(
                    """
                    UPDATE telegram_subscribers
                    SET username = ?, first_name = ?, last_name = ?, status = 'PENDING',
                        requested_at = ?, decided_at = NULL, decided_by = NULL
                    WHERE chat_id = ?
                    """,
                    (username, first_name, last_name, now, normalized_id),
                )
                needs_review = True
            else:
                connection.execute(
                    """
                    UPDATE telegram_subscribers
                    SET username = ?, first_name = ?, last_name = ?
                    WHERE chat_id = ?
                    """,
                    (username, first_name, last_name, normalized_id),
                )
            row = connection.execute(
                "SELECT * FROM telegram_subscribers WHERE chat_id = ?", (normalized_id,)
            ).fetchone()
        assert row is not None
        return dict(row), needs_review

    def ensure_telegram_admin(self, chat_id: str | int) -> None:
        normalized_id = str(chat_id)
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO telegram_subscribers (
                    chat_id, status, requested_at, decided_at, decided_by
                ) VALUES (?, 'APPROVED', ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    status = 'APPROVED', decided_at = excluded.decided_at,
                    decided_by = excluded.decided_by
                """,
                (normalized_id, now, now, normalized_id),
            )

    def set_telegram_subscription_status(
        self, *, chat_id: str | int, status: str, decided_by: str | int
    ) -> bool:
        normalized_status = status.upper()
        if normalized_status not in {"APPROVED", "REJECTED"}:
            raise ValueError("Telegram subscription status must be APPROVED or REJECTED")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE telegram_subscribers
                SET status = ?, decided_at = ?, decided_by = ?
                WHERE chat_id = ?
                """,
                (normalized_status, _utc_now(), str(decided_by), str(chat_id)),
            )
        return cursor.rowcount > 0

    def telegram_subscriber(self, chat_id: str | int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM telegram_subscribers WHERE chat_id = ?", (str(chat_id),)
            ).fetchone()
        return dict(row) if row is not None else None

    def telegram_subscribers(self, *, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM telegram_subscribers"
        parameters: tuple[str, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            parameters = (status.upper(),)
        query += " ORDER BY requested_at, chat_id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def approved_telegram_chat_ids(self) -> list[str]:
        return [
            str(row["chat_id"]) for row in self.telegram_subscribers(status="APPROVED")
        ]

    def telegram_update_offset(self) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_value FROM telegram_bot_state WHERE state_key = 'update_offset'"
            ).fetchone()
        return int(row["state_value"]) if row is not None else None

    def set_telegram_update_offset(self, offset: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO telegram_bot_state (state_key, state_value)
                VALUES ('update_offset', ?)
                ON CONFLICT(state_key) DO UPDATE SET state_value = excluded.state_value
                """,
                (str(offset),),
            )

    def mt5_log_cursor(self, log_path: str | Path) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM mt5_log_cursors WHERE log_path = ?", (str(log_path),)
            ).fetchone()
        return dict(row) if row is not None else None

    def set_mt5_log_cursor(
        self,
        *,
        log_path: str | Path,
        byte_offset: int,
        encoding: str,
        fragment: str = "",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO mt5_log_cursors (
                    log_path, byte_offset, encoding, fragment, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(log_path) DO UPDATE SET
                    byte_offset = excluded.byte_offset,
                    encoding = excluded.encoding,
                    fragment = excluded.fragment,
                    updated_at = excluded.updated_at
                """,
                (str(log_path), int(byte_offset), encoding, fragment, _utc_now()),
            )

    def telegram_delivery_was_sent(self, *, outbox_id: int, chat_id: str | int) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT sent_at FROM telegram_deliveries
                WHERE outbox_id = ? AND chat_id = ?
                """,
                (outbox_id, str(chat_id)),
            ).fetchone()
        return row is not None and row["sent_at"] is not None

    def mark_telegram_delivery_sent(self, *, outbox_id: int, chat_id: str | int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO telegram_deliveries (
                    outbox_id, chat_id, sent_at, attempt_count, last_error
                ) VALUES (?, ?, ?, 1, NULL)
                ON CONFLICT(outbox_id, chat_id) DO UPDATE SET
                    sent_at = excluded.sent_at,
                    attempt_count = telegram_deliveries.attempt_count + 1,
                    last_error = NULL
                """,
                (outbox_id, str(chat_id), _utc_now()),
            )

    def mark_telegram_delivery_failed(
        self, *, outbox_id: int, chat_id: str | int, error: str
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO telegram_deliveries (
                    outbox_id, chat_id, attempt_count, last_error
                ) VALUES (?, ?, 1, ?)
                ON CONFLICT(outbox_id, chat_id) DO UPDATE SET
                    attempt_count = telegram_deliveries.attempt_count + 1,
                    last_error = excluded.last_error
                """,
                (outbox_id, str(chat_id), error[:1000]),
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


def _outbox_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["payload"] = json.loads(str(row["payload_json"]))
    return result
