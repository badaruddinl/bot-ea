from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from ..strategy.state_machine import SetupRecord, SetupState


_TELEGRAM_POLL_READINESS_KEY = "telegram_poll_readiness_v1"
_TELEGRAM_POLL_READINESS_SCHEMA_VERSION = 3
_LOWER_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_LOWER_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_LOWER_HEX_32 = re.compile(r"^[0-9a-f]{32}$")


def telegram_poll_db_identity(path: str | Path) -> str:
    """Return the canonical, non-secret digest used to bind poll readiness.

    The identity deliberately depends on the resolved database path rather than
    mutable file metadata. Writer and deployment-side reader therefore agree
    across SQLite WAL/checkpoint activity while a database moved to a different
    path fails closed.
    """

    canonical_path = os.path.normcase(
        os.path.normpath(str(Path(path).expanduser().resolve(strict=False)))
    )
    payload = f"goldm-telegram-poll-db-v1\0{canonical_path}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class Mt5SetupIdentityError(ValueError):
    """A replayed MT5 setup id conflicts with its immutable stored identity."""


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
    file_identity TEXT NOT NULL DEFAULT '',
    anchor_offset INTEGER NOT NULL DEFAULT 0,
    anchor_sha256 TEXT NOT NULL DEFAULT '',
    raw_tail_b64 TEXT NOT NULL DEFAULT '',
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
CREATE TABLE IF NOT EXISTS trade_executions (
    setup_id TEXT PRIMARY KEY REFERENCES setups(setup_id),
    signal_outbox_id INTEGER NOT NULL UNIQUE REFERENCES signal_outbox(id),
    execution_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    requested_entry REAL NOT NULL,
    stop_price REAL NOT NULL,
    target_price REAL NOT NULL,
    volume REAL NOT NULL DEFAULT 0,
    risk_cash REAL NOT NULL DEFAULT 0,
    expected_profit_cash REAL NOT NULL DEFAULT 0,
    valid_until TEXT,
    client_tag TEXT NOT NULL DEFAULT '',
    order_ticket INTEGER,
    deal_ticket INTEGER,
    position_ticket INTEGER,
    actual_entry REAL,
    opened_at TEXT,
    closed_at TEXT,
    exit_price REAL,
    profit_cash REAL,
    close_reason TEXT,
    closed_by TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trade_executions_status
    ON trade_executions(status);
CREATE TABLE IF NOT EXISTS trade_event_receipts (
    outbox_id INTEGER PRIMARY KEY REFERENCES signal_outbox(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    result TEXT NOT NULL,
    processed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_settings (
    setting_key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS telegram_admin_actions (
    action_token TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'CONFIRMED', 'CANCELLED', 'EXPIRED')),
    requested_by TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_telegram_admin_actions_status
    ON telegram_admin_actions(status, expires_at);
"""

_SCHEMA_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL
)
"""

_POSITION_ACTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS position_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    setup_id TEXT,
    position_ticket INTEGER,
    position_identifier INTEGER,
    action_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK(status IN ('PENDING', 'SUBMITTED', 'CONFIRMED', 'FAILED', 'UNKNOWN')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    management_policy TEXT NOT NULL DEFAULT '',
    account_login TEXT NOT NULL DEFAULT '',
    account_server TEXT NOT NULL DEFAULT '',
    account_scope TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    lease_owner TEXT,
    lease_acquired_at TEXT,
    lease_expires_at TEXT,
    broker_order_ticket INTEGER,
    broker_deal_ticket INTEGER,
    broker_position_ticket INTEGER,
    broker_retcode INTEGER,
    broker_reference TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    last_attempt_at TEXT,
    submitted_at TEXT,
    confirmed_at TEXT,
    failed_at TEXT,
    unknown_at TEXT,
    projection_attempt_count INTEGER NOT NULL DEFAULT 0
        CHECK(projection_attempt_count >= 0),
    projection_lease_owner TEXT,
    projection_lease_acquired_at TEXT,
    projection_lease_expires_at TEXT,
    projected_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_position_actions_claim
    ON position_actions(status, lease_expires_at, created_at, id);
CREATE INDEX IF NOT EXISTS idx_position_actions_setup
    ON position_actions(setup_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_position_actions_position
    ON position_actions(position_ticket, created_at, id);
CREATE INDEX IF NOT EXISTS idx_position_actions_identifier
    ON position_actions(position_identifier, created_at, id);
"""

_POSITION_ACTIONS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_position_actions_claim
    ON position_actions(status, lease_expires_at, created_at, id);
CREATE INDEX IF NOT EXISTS idx_position_actions_setup
    ON position_actions(setup_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_position_actions_position
    ON position_actions(position_ticket, created_at, id);
CREATE INDEX IF NOT EXISTS idx_position_actions_identifier
    ON position_actions(position_identifier, created_at, id);
"""

_POSITION_ACTION_STATUSES = frozenset(
    {"PENDING", "SUBMITTED", "CONFIRMED", "FAILED", "UNKNOWN"}
)

_PENDING_OPEN_EXECUTION_STATUSES = frozenset(
    {
        "OPEN_PENDING",
        "OPEN_SUBMITTED",
        "PLACED",
        "OPEN_UNKNOWN",
        "UNKNOWN",
        "PARTIAL",
        "UNPROTECTED",
    }
)
_TERMINAL_OPEN_EXECUTION_STATUSES = frozenset(
    {
        "CANCELLED",
        "READY_MANUAL",
        "RISK_REJECTED",
        "EXPIRED",
        "DIRECTION_REJECTED",
        "PRECHECK_REJECTED",
        "GUARD_REJECTED",
        "REJECTED",
    }
)
_EXECUTION_STATUS_RANK = {
    "PLANNING": 10,
    "OPEN_PENDING": 20,
    "OPEN_SUBMITTED": 30,
    "PLACED": 30,
    "PARTIAL": 35,
    "OPEN_UNKNOWN": 40,
    "UNKNOWN": 40,
    "UNPROTECTED": 45,
    "FILLED": 50,
    "CLOSE_REJECTED": 60,
    "CLOSE_SUBMITTED": 70,
    "CLOSE_UNKNOWN": 80,
    "CANCELLED": 100,
    "CLOSED": 100,
}
_TERMINAL_SIGNAL_EVENT_TYPES = frozenset(
    {"SNIPER_OUTCOME", "SNIPER_EARLY_CANCELLED"}
)
_MILESTONE_COLUMNS = {
    "R1": ("r1_reached_at", "r1_protection_status"),
    "R2": ("r2_reached_at", "r2_protection_status"),
    "R3": ("r3_reached_at", "r3_close_status"),
}


def _migration_baseline(connection: sqlite3.Connection) -> None:
    _execute_script(connection, _SCHEMA)


def _migration_position_action_ledger(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "trade_executions",
        {
            "strategy_id": "TEXT NOT NULL DEFAULT ''",
            "strategy_version": "TEXT NOT NULL DEFAULT ''",
            "direction_profile": "TEXT NOT NULL DEFAULT ''",
            "execution_profile": "TEXT NOT NULL DEFAULT ''",
            "magic": "INTEGER",
            "position_identifier": "INTEGER",
            "initial_volume": "REAL",
            "remaining_volume": "REAL",
            "initial_stop_price": "REAL",
            "current_stop_price": "REAL",
            "initial_take_profit_price": "REAL",
            "current_take_profit_price": "REAL",
            "initial_risk_distance": "REAL",
            "management_policy": "TEXT NOT NULL DEFAULT ''",
            "management_policy_version": "TEXT NOT NULL DEFAULT ''",
            "management_policy_json": "TEXT NOT NULL DEFAULT '{}'",
            "account_login": "TEXT NOT NULL DEFAULT ''",
            "account_server": "TEXT NOT NULL DEFAULT ''",
            "account_scope": "TEXT NOT NULL DEFAULT ''",
            "account_margin_mode": "TEXT",
            "highest_observed_r": "REAL",
            "r1_reached_at": "TEXT",
            "r2_reached_at": "TEXT",
            "r3_reached_at": "TEXT",
            "r1_protection_status": "TEXT",
            "r2_protection_status": "TEXT",
            "r3_close_status": "TEXT",
            "last_broker_sync_at": "TEXT",
            "max_holding_minutes": "INTEGER",
        },
    )
    _execute_script(connection, _POSITION_ACTIONS_SCHEMA)


def _migration_open_action_targets(connection: sqlite3.Connection) -> None:
    columns = {
        str(row["name"]): row
        for row in connection.execute("PRAGMA table_info(position_actions)").fetchall()
    }
    if not columns:
        raise RuntimeError("Cannot migrate missing table: position_actions")
    ticket_is_required = bool(int(columns["position_ticket"]["notnull"] or 0))
    identifier_is_missing = "position_identifier" not in columns
    if ticket_is_required or identifier_is_missing:
        invalid_target = connection.execute(
            """
            SELECT id, action_type, position_ticket FROM position_actions
            WHERE (UPPER(action_type) = 'OPEN' AND position_ticket NOT IN (0))
               OR (UPPER(action_type) <> 'OPEN' AND position_ticket <= 0)
            LIMIT 1
            """
        ).fetchone()
        if invalid_target is not None:
            raise RuntimeError(
                "Legacy position action has an unsafe target: "
                f"id={invalid_target['id']} type={invalid_target['action_type']} "
                f"ticket={invalid_target['position_ticket']}"
            )
        connection.execute("ALTER TABLE position_actions RENAME TO position_actions_v2_legacy")
        _execute_script(connection, _POSITION_ACTIONS_SCHEMA)
        position_identifier = "position_identifier" if not identifier_is_missing else "NULL"
        connection.execute(
            f"""
            INSERT INTO position_actions (
                id, idempotency_key, setup_id, position_ticket, position_identifier,
                action_type, status, payload_json, management_policy, account_login,
                account_server, account_scope, attempt_count, lease_owner,
                lease_acquired_at, lease_expires_at, broker_order_ticket,
                broker_deal_ticket, broker_position_ticket, broker_retcode,
                broker_reference, last_error, created_at, last_attempt_at,
                submitted_at, confirmed_at, failed_at, unknown_at, updated_at
            )
            SELECT
                id, idempotency_key, setup_id,
                CASE WHEN UPPER(action_type) = 'OPEN' AND position_ticket = 0
                     THEN NULL ELSE position_ticket END,
                {position_identifier},
                action_type, status, payload_json, management_policy, account_login,
                account_server, account_scope, attempt_count, lease_owner,
                lease_acquired_at, lease_expires_at, broker_order_ticket,
                broker_deal_ticket, broker_position_ticket, broker_retcode,
                broker_reference, last_error, created_at, last_attempt_at,
                submitted_at, confirmed_at, failed_at, unknown_at, updated_at
            FROM position_actions_v2_legacy
            """
        )
        connection.execute("DROP TABLE position_actions_v2_legacy")
    _execute_script(connection, _POSITION_ACTIONS_INDEXES)
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_executions_account_position
        ON trade_executions(account_login, account_server, position_identifier)
        WHERE position_identifier IS NOT NULL
          AND account_login <> '' AND account_server <> ''
        """
    )


def _migration_position_action_projection(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "position_actions",
        {
            "projection_attempt_count": (
                "INTEGER NOT NULL DEFAULT 0 CHECK(projection_attempt_count >= 0)"
            ),
            "projection_lease_owner": "TEXT",
            "projection_lease_acquired_at": "TEXT",
            "projection_lease_expires_at": "TEXT",
            "projected_at": "TEXT",
        },
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_position_actions_projection
        ON position_actions(projected_at, projection_lease_expires_at, id)
        WHERE status IN ('CONFIRMED', 'FAILED', 'UNKNOWN')
        """
    )


def _migration_execution_broker_snapshots(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "trade_executions",
        {
            "initial_take_profit_price": "REAL",
            "current_take_profit_price": "REAL",
            "max_holding_minutes": "INTEGER",
        },
    )


def _migration_terminal_open_fence(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "trade_executions",
        {
            "deferred_close_reason": "TEXT",
            "deferred_close_terminal_outbox_id": "INTEGER",
            "deferred_close_requested_at": "TEXT",
            "cancelled_at": "TEXT",
            "cancelled_by_terminal_outbox_id": "INTEGER",
        },
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_trade_executions_deferred_close
        ON trade_executions(deferred_close_terminal_outbox_id, status)
        WHERE deferred_close_terminal_outbox_id IS NOT NULL
        """
    )


def _migration_execution_account_margin_mode(
    connection: sqlite3.Connection,
) -> None:
    _ensure_columns(
        connection,
        "trade_executions",
        {"account_margin_mode": "TEXT"},
    )


def _migration_mt5_log_cursor_continuity(
    connection: sqlite3.Connection,
) -> None:
    """Add replacement/truncate continuity evidence to persisted log cursors."""

    _ensure_columns(
        connection,
        "mt5_log_cursors",
        {
            "file_identity": "TEXT NOT NULL DEFAULT ''",
            "anchor_offset": "INTEGER NOT NULL DEFAULT 0",
            "anchor_sha256": "TEXT NOT NULL DEFAULT ''",
            "raw_tail_b64": "TEXT NOT NULL DEFAULT ''",
        },
    )


def _migration_entry_side_policy(connection: sqlite3.Connection) -> None:
    """Separate immutable engine lineage from runtime entry-side authority."""

    _ensure_columns(
        connection,
        "trade_executions",
        {
            "entry_side_policy": "TEXT NOT NULL DEFAULT 'LEGACY_UNSPECIFIED'",
        },
    )


_MIGRATIONS: tuple[tuple[int, str, Callable[[sqlite3.Connection], None]], ...] = (
    (1, "baseline", _migration_baseline),
    (2, "position_action_ledger", _migration_position_action_ledger),
    (3, "open_action_targets", _migration_open_action_targets),
    (4, "position_action_projection", _migration_position_action_projection),
    (5, "execution_broker_snapshots", _migration_execution_broker_snapshots),
    (6, "terminal_open_fence", _migration_terminal_open_fence),
    (7, "execution_account_margin_mode", _migration_execution_account_margin_mode),
    (8, "mt5_log_cursor_continuity", _migration_mt5_log_cursor_continuity),
    (9, "entry_side_policy", _migration_entry_side_policy),
)


class SignalStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            _enable_wal(connection)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(_SCHEMA_MIGRATIONS_TABLE)
            applied_rows = connection.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            ).fetchall()
            applied = {int(row["version"]): str(row["name"]) for row in applied_rows}
            latest_known = _MIGRATIONS[-1][0]
            if applied and max(applied) > latest_known:
                raise RuntimeError(
                    "Signal database schema is newer than this application "
                    f"(database={max(applied)}, supported={latest_known})"
                )
            for version, name, migrate in _MIGRATIONS:
                recorded_name = applied.get(version)
                if recorded_name is not None:
                    if recorded_name != name:
                        raise RuntimeError(
                            f"Signal database migration {version} is recorded as "
                            f"{recorded_name!r}, expected {name!r}"
                        )
                    continue
                migrate(connection)
                connection.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, _utc_now()),
                )
                connection.execute(f"PRAGMA user_version = {version}")

    def schema_version(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(version) AS version FROM schema_migrations"
            ).fetchone()
        return int(row["version"] or 0) if row is not None else 0

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

    def ingest_mt5_event(
        self,
        *,
        record: SetupRecord,
        event_type: str,
        event_key: str,
        payload: dict[str, Any],
    ) -> bool:
        """Atomically persist one MT5 event without regressing setup state.

        Cursor continuity resets intentionally replay already-consumed bytes.
        The outbox key makes those replays idempotent, while the monotonic state
        rule prevents an old SIGNAL/EARLY line from reopening a CLOSED setup.
        """

        normalized_event_type = str(event_type or "").strip()
        normalized_event_key = str(event_key or "").strip()
        if not normalized_event_type or not normalized_event_key:
            raise ValueError("MT5 event type and key must not be empty")
        payload_json = json.dumps(payload, sort_keys=True, allow_nan=False)
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                """
                SELECT 1 FROM signal_outbox
                WHERE setup_id = ? AND event_key = ?
                """,
                (record.setup_id, normalized_event_key),
            ).fetchone()
            if duplicate is not None:
                return False

            existing = connection.execute(
                "SELECT * FROM setups WHERE setup_id = ?", (record.setup_id,)
            ).fetchone()
            previous: str | None = None
            effective_state = record.state
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO setups (
                        setup_id, symbol, side, level, breakout_at, state,
                        retest_bars_elapsed, reason, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.setup_id,
                        record.symbol,
                        record.side,
                        record.level,
                        _iso(record.breakout_at),
                        effective_state.value,
                        record.retest_bars_elapsed,
                        record.reason,
                        now,
                    ),
                )
            else:
                _validate_mt5_setup_identity(existing, record)
                previous = str(existing["state"])
                effective_state = _monotonic_mt5_setup_state(
                    SetupState(previous), record.state
                )
                if effective_state.value != previous:
                    connection.execute(
                        """
                        UPDATE setups
                        SET state = ?, retest_bars_elapsed = ?, reason = ?, updated_at = ?
                        WHERE setup_id = ? AND state = ?
                        """,
                        (
                            effective_state.value,
                            max(
                                int(existing["retest_bars_elapsed"] or 0),
                                int(record.retest_bars_elapsed),
                            ),
                            record.reason,
                            now,
                            record.setup_id,
                            previous,
                        ),
                    )

            if previous != effective_state.value:
                connection.execute(
                    """
                    INSERT INTO setup_transitions (
                        setup_id, from_state, to_state, reason, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        record.setup_id,
                        previous,
                        effective_state.value,
                        record.reason or "MT5 event ingested",
                        now,
                    ),
                )
            connection.execute(
                """
                INSERT INTO signal_outbox (
                    setup_id, event_type, event_key, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record.setup_id,
                    normalized_event_type,
                    normalized_event_key,
                    payload_json,
                    now,
                ),
            )
        return True

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
        self,
        *,
        event_types: tuple[str, ...] | None = None,
        include_admin_only: bool = True,
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
        query += " ORDER BY signal_outbox.id DESC"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        for row in rows:
            event = _outbox_row(row)
            if include_admin_only or not _event_is_admin_only(event):
                return event
        return None

    def recent_events(
        self, *, limit: int = 5, include_admin_only: bool = True
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 20))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT signal_outbox.*, setups.symbol, setups.side, setups.level,
                       setups.breakout_at, setups.state
                FROM signal_outbox
                JOIN setups ON setups.setup_id = signal_outbox.setup_id
                ORDER BY signal_outbox.id DESC
                """,
            ).fetchall()
        events = [_outbox_row(row) for row in rows]
        if not include_admin_only:
            events = [event for event in events if not _event_is_admin_only(event)]
        return events[:safe_limit]

    def execution_candidates(self, *, event_type: str = "SNIPER_SIGNAL", limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if event_type == "SNIPER_SIGNAL":
                rows = connection.execute(
                    """
                    SELECT signal_outbox.*, setups.symbol, setups.side, setups.level,
                           setups.breakout_at, setups.state
                    FROM signal_outbox
                    JOIN setups ON setups.setup_id = signal_outbox.setup_id
                    LEFT JOIN trade_executions ON trade_executions.signal_outbox_id = signal_outbox.id
                    WHERE signal_outbox.event_type = ? AND trade_executions.signal_outbox_id IS NULL
                    ORDER BY signal_outbox.id LIMIT ?
                    """,
                    (event_type, max(1, int(limit))),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT signal_outbox.*, setups.symbol, setups.side, setups.level,
                           setups.breakout_at, setups.state
                    FROM signal_outbox
                    JOIN setups ON setups.setup_id = signal_outbox.setup_id
                    LEFT JOIN trade_event_receipts ON trade_event_receipts.outbox_id = signal_outbox.id
                    WHERE signal_outbox.event_type = ? AND trade_event_receipts.outbox_id IS NULL
                    ORDER BY signal_outbox.id LIMIT ?
                    """,
                    (event_type, max(1, int(limit))),
                ).fetchall()
        return [_outbox_row(row) for row in rows]

    def create_open_execution_intent(
        self,
        record: dict[str, Any],
        *,
        action_idempotency_key: str,
        action_payload: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        """Atomically persist a pending OPEN execution and its broker-action fence."""

        values, immutable_action = _prepare_open_execution_intent(
            record,
            action_idempotency_key=action_idempotency_key,
            action_payload=action_payload,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            execution_row, action_row, created = _create_or_replay_open_intent(
                connection, values, immutable_action
            )
        return dict(execution_row), _position_action_row(action_row), created

    def create_open_execution_intent_if_setup_current(
        self,
        record: dict[str, Any],
        *,
        action_idempotency_key: str,
        action_payload: dict[str, Any] | None = None,
        expected_setup_state: str | SetupState = SetupState.ACTIVE_SIGNAL,
        expected_signal_outbox_id: int,
    ) -> tuple[
        dict[str, Any] | None,
        dict[str, Any] | None,
        bool,
        str,
    ]:
        """Create an OPEN fence only while its exact signal is still current.

        The setup-state and terminal-event checks share the same ``BEGIN
        IMMEDIATE`` transaction as the execution/action insert.  A stale signal
        therefore returns an explicit disposition without leaving either row.
        """

        values, immutable_action = _prepare_open_execution_intent(
            record,
            action_idempotency_key=action_idempotency_key,
            action_payload=action_payload,
        )
        signal_id = _optional_positive_int(
            expected_signal_outbox_id, "expected_signal_outbox_id"
        )
        assert signal_id is not None
        if int(values["signal_outbox_id"]) != signal_id:
            raise ValueError(
                "Expected signal outbox id does not match the OPEN execution intent"
            )
        expected_state = (
            expected_setup_state.value
            if isinstance(expected_setup_state, SetupState)
            else str(expected_setup_state or "").strip().upper()
        )
        if not expected_state:
            raise ValueError("Expected setup state must not be empty")
        try:
            SetupState(expected_state)
        except ValueError as exc:
            raise ValueError(f"Unsupported expected setup state: {expected_state}") from exc
        setup_id = str(values["setup_id"])

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            signal = connection.execute(
                """
                SELECT id, setup_id, event_type FROM signal_outbox WHERE id = ?
                """,
                (signal_id,),
            ).fetchone()
            if signal is None:
                raise RuntimeError("Expected signal outbox row does not exist")
            if (
                str(signal["setup_id"]) != setup_id
                or str(signal["event_type"]).upper() != "SNIPER_SIGNAL"
            ):
                raise ValueError(
                    "Expected signal outbox row does not identify this setup's SNIPER_SIGNAL"
                )
            setup = connection.execute(
                "SELECT state FROM setups WHERE setup_id = ?", (setup_id,)
            ).fetchone()
            if setup is None:
                raise RuntimeError("OPEN execution intent requires an existing setup")
            terminal = connection.execute(
                """
                SELECT id, event_type FROM signal_outbox
                WHERE setup_id = ?
                  AND event_type IN ('SNIPER_OUTCOME', 'SNIPER_EARLY_CANCELLED')
                ORDER BY id DESC LIMIT 1
                """,
                (setup_id,),
            ).fetchone()
            if terminal is not None:
                return None, None, False, "TERMINAL_EVENT"
            if str(setup["state"]).strip().upper() != expected_state:
                return None, None, False, "STALE_SETUP"
            execution_row, action_row, created = _create_or_replay_open_intent(
                connection, values, immutable_action
            )
        return (
            dict(execution_row),
            _position_action_row(action_row),
            created,
            "CREATED" if created else "REPLAY",
        )

    def save_trade_execution(self, record: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _write_trade_execution(connection, record, upsert=True)

    def trade_execution(self, setup_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM trade_executions WHERE setup_id = ?", (setup_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def active_trade_executions(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM trade_executions
                WHERE status IN (
                    'OPEN_PENDING', 'OPEN_SUBMITTED', 'PLACED',
                    'OPEN_UNKNOWN', 'UNKNOWN', 'PARTIAL', 'UNPROTECTED',
                    'FILLED', 'CLOSE_SUBMITTED', 'CLOSE_UNKNOWN', 'CLOSE_REJECTED'
                )
                ORDER BY updated_at
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def confirm_trade_position(
        self,
        setup_id: str,
        *,
        action_idempotency_key: str,
        position_ticket: int,
        position_identifier: int,
        symbol: str,
        side: str,
        comment: str,
        actual_entry: float,
        opened_at: datetime | str,
        initial_volume: float,
        initial_stop_price: float,
        current_stop_price: float,
        magic: int,
        strategy_id: str,
        strategy_version: str,
        direction_profile: str,
        entry_side_policy: str = "LEGACY_UNSPECIFIED",
        execution_profile: str,
        management_policy: str,
        management_policy_version: str,
        management_policy_json: Any,
        account_login: str | int,
        account_server: str,
        account_scope: str,
        account_margin_mode: str,
        last_broker_sync_at: datetime | str | None = None,
        initial_take_profit_price: float | None = None,
        current_take_profit_price: float | None = None,
    ) -> dict[str, Any]:
        """Bind one exact broker position to a pending OPEN exactly once.

        An exact replay after commit is idempotent. Any different position,
        account, strategy, or policy snapshot fails closed. The associated OPEN
        (or emergency initial-protection) action is confirmed in the same SQLite
        transaction as the execution transition to FILLED.
        """

        normalized = _confirmed_position_values(
            position_ticket=position_ticket,
            position_identifier=position_identifier,
            symbol=symbol,
            side=side,
            comment=comment,
            actual_entry=actual_entry,
            opened_at=opened_at,
            initial_volume=initial_volume,
            initial_stop_price=initial_stop_price,
            current_stop_price=current_stop_price,
            magic=magic,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            direction_profile=direction_profile,
            entry_side_policy=entry_side_policy,
            execution_profile=execution_profile,
            management_policy=management_policy,
            management_policy_version=management_policy_version,
            management_policy_json=management_policy_json,
            account_login=account_login,
            account_server=account_server,
            account_scope=account_scope,
            account_margin_mode=account_margin_mode,
            last_broker_sync_at=last_broker_sync_at,
            initial_take_profit_price=initial_take_profit_price,
            current_take_profit_price=current_take_profit_price,
        )
        action_key = action_idempotency_key.strip()
        if not action_key:
            raise ValueError("Position confirmation requires an action idempotency key")
        now = _utc_now()
        allowed_pending = tuple(sorted(_PENDING_OPEN_EXECUTION_STATUSES))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = connection.execute(
                "SELECT * FROM trade_executions WHERE setup_id = ?", (str(setup_id),)
            ).fetchone()
            action = connection.execute(
                "SELECT * FROM position_actions WHERE idempotency_key = ?", (action_key,)
            ).fetchone()
            if execution is None or action is None:
                raise RuntimeError("Position confirmation requires both execution and action rows")
            _validate_position_confirmation_context(execution, action, normalized)
            primary_action_type = str(action["action_type"] or "").strip().upper()
            if primary_action_type not in {"OPEN", "SET_INITIAL_PROTECTION"}:
                raise RuntimeError(
                    "Position confirmation requires OPEN or SET_INITIAL_PROTECTION action"
                )
            open_actions = connection.execute(
                """
                SELECT * FROM position_actions
                WHERE setup_id = ? AND UPPER(action_type) = 'OPEN'
                ORDER BY id
                """,
                (str(setup_id),),
            ).fetchall()
            if primary_action_type == "OPEN" and not any(
                int(row["id"]) == int(action["id"]) for row in open_actions
            ):
                raise RuntimeError("Primary OPEN action is missing from its setup fence set")
            if primary_action_type == "SET_INITIAL_PROTECTION" and not open_actions:
                raise RuntimeError(
                    "Protected-position confirmation requires its original OPEN action fence"
                )
            for open_action in open_actions:
                _validate_position_confirmation_context(
                    execution, open_action, normalized
                )
                _validate_open_action_confirmation_payload(execution, open_action)
                if str(open_action["status"]).upper() not in {
                    "SUBMITTED",
                    "UNKNOWN",
                    "CONFIRMED",
                }:
                    raise RuntimeError(
                        "Protected-position confirmation found an OPEN fence outside "
                        "SUBMITTED/UNKNOWN/CONFIRMED"
                    )

            if str(execution["status"]) == "FILLED":
                _assert_confirmed_position_replay(execution, normalized)
                if str(action["status"]).upper() not in {
                    "SUBMITTED",
                    "UNKNOWN",
                    "CONFIRMED",
                }:
                    raise RuntimeError(
                        "FILLED execution has an invalid confirmation action state"
                    )
                _confirm_position_action_fences(
                    connection,
                    (action, *open_actions),
                    normalized,
                    confirmed_at=now,
                )
                refreshed = connection.execute(
                    "SELECT * FROM trade_executions WHERE setup_id = ?",
                    (str(setup_id),),
                ).fetchone()
                assert refreshed is not None
                return dict(refreshed)
            if str(execution["status"]) not in allowed_pending:
                raise RuntimeError(
                    f"Cannot confirm position from execution status {execution['status']!r}"
                )
            bound_unprotected = (
                str(execution["status"]) == "UNPROTECTED"
                and execution["position_identifier"] is not None
            )
            if bound_unprotected:
                _assert_unprotected_position_binding_replay(execution, normalized)
            elif execution["position_identifier"] is not None:
                raise RuntimeError("Pending execution is already bound to a position identifier")
            expected_action_type = (
                "SET_INITIAL_PROTECTION"
                if str(execution["status"]) == "UNPROTECTED"
                else "OPEN"
            )
            if primary_action_type != expected_action_type:
                raise RuntimeError(
                    f"Execution status {execution['status']} requires {expected_action_type} action"
                )
            if str(action["status"]).upper() not in {
                "SUBMITTED",
                "UNKNOWN",
                "CONFIRMED",
            }:
                raise RuntimeError(
                    "Position confirmation action must be SUBMITTED, UNKNOWN, or an "
                    f"exact CONFIRMED crash replay, got {action['status']!r}"
                )

            placeholders = ", ".join("?" for _ in allowed_pending)
            identifier_guard = (
                "position_identifier = ?" if bound_unprotected else "position_identifier IS NULL"
            )
            guard_parameters: tuple[Any, ...] = (
                (normalized["position_identifier"],) if bound_unprotected else ()
            )
            cursor = connection.execute(
                f"""
                UPDATE trade_executions
                SET status = 'FILLED', position_ticket = ?, position_identifier = ?,
                    actual_entry = ?, opened_at = ?, volume = ?, initial_volume = ?,
                    remaining_volume = ?, initial_stop_price = ?, current_stop_price = ?,
                    initial_take_profit_price = ?, current_take_profit_price = ?,
                    initial_risk_distance = ?, last_broker_sync_at = ?,
                    last_error = NULL, updated_at = ?
                WHERE setup_id = ? AND {identifier_guard}
                  AND status IN ({placeholders})
                """,
                (
                    normalized["position_ticket"],
                    normalized["position_identifier"],
                    normalized["actual_entry"],
                    normalized["opened_at"],
                    normalized["initial_volume"],
                    normalized["initial_volume"],
                    normalized["initial_volume"],
                    normalized["initial_stop_price"],
                    normalized["current_stop_price"],
                    normalized["initial_take_profit_price"],
                    normalized["current_take_profit_price"],
                    normalized["initial_risk_distance"],
                    normalized["last_broker_sync_at"],
                    now,
                    str(setup_id),
                    *guard_parameters,
                    *allowed_pending,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Concurrent position confirmation lost its atomic guard")
            _confirm_position_action_fences(
                connection,
                (action, *open_actions),
                normalized,
                confirmed_at=now,
            )
            confirmed = connection.execute(
                "SELECT * FROM trade_executions WHERE setup_id = ?", (str(setup_id),)
            ).fetchone()
        assert confirmed is not None
        return dict(confirmed)

    def update_trade_execution_management(
        self,
        setup_id: str,
        *,
        remaining_volume: float | None = None,
        current_stop_price: float | None = None,
        current_take_profit_price: float | None = None,
        highest_observed_r: float | None = None,
        r1_reached_at: datetime | str | None = None,
        r2_reached_at: datetime | str | None = None,
        r3_reached_at: datetime | str | None = None,
        r1_protection_status: str | None = None,
        r2_protection_status: str | None = None,
        r3_close_status: str | None = None,
        last_broker_sync_at: datetime | str | None = None,
    ) -> bool:
        """Patch only mutable position-management state.

        Identity, strategy, account, initial-risk, and management-policy
        snapshots remain immutable after the trade execution is inserted.
        Milestone timestamps retain their first observed value, while the
        highest observed R multiple can only increase.
        """

        assignments: list[str] = []
        parameters: list[Any] = []
        if remaining_volume is not None:
            normalized_volume = _required_finite_float(remaining_volume, "remaining_volume")
            if normalized_volume < 0:
                raise ValueError("remaining_volume must not be negative")
            assignments.append("remaining_volume = ?")
            parameters.append(normalized_volume)
        if current_stop_price is not None:
            normalized_stop = _required_finite_float(current_stop_price, "current_stop_price")
            if normalized_stop <= 0:
                raise ValueError("current_stop_price must be positive")
            assignments.append("current_stop_price = ?")
            parameters.append(normalized_stop)
        if current_take_profit_price is not None:
            normalized_take_profit = _required_finite_float(
                current_take_profit_price, "current_take_profit_price"
            )
            if normalized_take_profit < 0:
                raise ValueError("current_take_profit_price must not be negative")
            assignments.append("current_take_profit_price = ?")
            parameters.append(normalized_take_profit)
        if highest_observed_r is not None:
            normalized_r = _required_finite_float(highest_observed_r, "highest_observed_r")
            assignments.append(
                "highest_observed_r = CASE "
                "WHEN highest_observed_r IS NULL OR highest_observed_r < ? THEN ? "
                "ELSE highest_observed_r END"
            )
            parameters.extend((normalized_r, normalized_r))
        for column, value in (
            ("r1_reached_at", r1_reached_at),
            ("r2_reached_at", r2_reached_at),
            ("r3_reached_at", r3_reached_at),
        ):
            if value is not None:
                assignments.append(f"{column} = COALESCE({column}, ?)")
                parameters.append(_optional_timestamp(value))
        for column, value in (
            ("r1_protection_status", r1_protection_status),
            ("r2_protection_status", r2_protection_status),
            ("r3_close_status", r3_close_status),
        ):
            if value is not None:
                normalized_status = value.strip().upper()
                if not normalized_status:
                    raise ValueError(f"{column} must not be empty")
                assignments.append(f"{column} = ?")
                parameters.append(normalized_status)
        if last_broker_sync_at is not None:
            assignments.append("last_broker_sync_at = ?")
            parameters.append(_optional_timestamp(last_broker_sync_at))
        if not assignments:
            raise ValueError("At least one mutable management field is required")
        assignments.append("updated_at = ?")
        parameters.extend((_utc_now(), str(setup_id)))
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE trade_executions SET {', '.join(assignments)} WHERE setup_id = ?",
                tuple(parameters),
            )
        return cursor.rowcount == 1

    def record_position_observation_with_milestone_alerts(
        self,
        setup_id: str,
        *,
        remaining_volume: float,
        current_stop_price: float,
        current_take_profit_price: float,
        highest_observed_r: float,
        last_broker_sync_at: datetime | str,
        reached_at: datetime | str,
        milestone_payloads: dict[str, dict[str, Any]],
    ) -> int:
        """Atomically persist a broker observation and every new R-touch alert.

        The milestone timestamp is the durable alert latch. Keeping its outbox
        insert in the same transaction prevents a crash from permanently
        suppressing an R1/R2/R3 notification after the latch was advanced.
        Existing outbox rows replay idempotently through their stable event key.
        """

        normalized_volume = _required_finite_float(
            remaining_volume, "remaining_volume"
        )
        normalized_stop = _required_finite_float(
            current_stop_price, "current_stop_price"
        )
        normalized_take_profit = _required_finite_float(
            current_take_profit_price, "current_take_profit_price"
        )
        normalized_r = _required_finite_float(
            highest_observed_r, "highest_observed_r"
        )
        if normalized_volume <= 0:
            raise ValueError("remaining_volume must be positive for an active position")
        if normalized_stop <= 0:
            raise ValueError("current_stop_price must be positive")
        if normalized_take_profit < 0:
            raise ValueError("current_take_profit_price must not be negative")
        observed_at = _optional_timestamp(reached_at)
        synced_at = _optional_timestamp(last_broker_sync_at)
        if observed_at is None or synced_at is None:
            raise ValueError("position observation timestamps are required")

        normalized_payloads: dict[str, str] = {}
        for raw_milestone, payload in milestone_payloads.items():
            milestone = _normalize_management_milestone(raw_milestone)
            if milestone not in _MILESTONE_COLUMNS:
                raise ValueError("Milestone alerts support only R1, R2, and R3")
            if milestone in normalized_payloads:
                raise ValueError(f"Duplicate milestone alert: {milestone}")
            normalized_payloads[milestone] = json.dumps(
                dict(payload), sort_keys=True, allow_nan=False
            )

        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = connection.execute(
                "SELECT * FROM trade_executions WHERE setup_id = ?", (str(setup_id),)
            ).fetchone()
            if execution is None:
                raise RuntimeError("Cannot observe a missing trade execution")
            if str(execution["status"]) != "FILLED":
                raise RuntimeError(
                    "Milestone observation requires an active FILLED execution"
                )
            identifier = _optional_positive_int(
                execution["position_identifier"], "position_identifier"
            )
            if identifier is None:
                raise RuntimeError(
                    "Milestone observation requires a stable position identifier"
                )

            assignments = [
                "remaining_volume = ?",
                "current_stop_price = ?",
                "current_take_profit_price = ?",
                "highest_observed_r = CASE "
                "WHEN highest_observed_r IS NULL OR highest_observed_r < ? THEN ? "
                "ELSE highest_observed_r END",
                "last_broker_sync_at = ?",
            ]
            parameters: list[Any] = [
                normalized_volume,
                normalized_stop,
                normalized_take_profit,
                normalized_r,
                normalized_r,
                synced_at,
            ]
            for milestone in normalized_payloads:
                reached_column = _MILESTONE_COLUMNS[milestone][0]
                assignments.append(f"{reached_column} = COALESCE({reached_column}, ?)")
                parameters.append(observed_at)
            assignments.append("updated_at = ?")
            parameters.extend((now, str(setup_id)))
            cursor = connection.execute(
                f"UPDATE trade_executions SET {', '.join(assignments)} "
                "WHERE setup_id = ? AND status = 'FILLED'",
                tuple(parameters),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Position observation lost its FILLED status guard")

            inserted = 0
            for milestone, payload_json in normalized_payloads.items():
                event_type = f"POSITION_{milestone}_TOUCHED"
                event_key = f"{event_type}:{identifier}"
                outbox = connection.execute(
                    """
                    INSERT INTO signal_outbox (
                        setup_id, event_type, event_key, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(setup_id, event_key) DO NOTHING
                    """,
                    (str(setup_id), event_type, event_key, payload_json, now),
                )
                inserted += int(outbox.rowcount == 1)
        return inserted

    def sync_trade_position_binding(
        self,
        setup_id: str,
        *,
        position_ticket: int,
        position_identifier: int,
        symbol: str,
        side: str,
        comment: str,
        remaining_volume: float,
        current_stop_price: float,
        magic: int,
        account_login: str | int,
        account_server: str,
        account_scope: str,
        last_broker_sync_at: datetime | str | None = None,
        current_take_profit_price: float | None = None,
        protection_degraded: bool = False,
    ) -> dict[str, Any]:
        """Refresh mutable broker state using the stable position identity.

        MetaTrader position tickets may change across broker-side lifecycle
        operations. The position identifier, frozen account, magic, symbol,
        side, and client tag remain authoritative and must all match before the
        current ticket or broker-observed volume/stop can be updated.
        """

        normalized = _position_binding_values(
            position_ticket=position_ticket,
            position_identifier=position_identifier,
            symbol=symbol,
            side=side,
            comment=comment,
            remaining_volume=remaining_volume,
            current_stop_price=current_stop_price,
            magic=magic,
            account_login=account_login,
            account_server=account_server,
            account_scope=account_scope,
            last_broker_sync_at=last_broker_sync_at,
            current_take_profit_price=current_take_profit_price,
        )
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = connection.execute(
                "SELECT * FROM trade_executions WHERE setup_id = ?", (str(setup_id),)
            ).fetchone()
            if execution is None:
                raise RuntimeError("Cannot synchronize a missing trade execution")
            _validate_position_binding_context(execution, normalized)
            if str(execution["status"]) not in {
                "FILLED",
                "UNPROTECTED",
                "CLOSE_REJECTED",
                "CLOSE_SUBMITTED",
                "CLOSE_UNKNOWN",
            }:
                raise RuntimeError(
                    f"Cannot synchronize position from execution status {execution['status']!r}"
                )
            next_status = str(execution["status"])
            if (
                next_status == "FILLED"
                and (
                    normalized["current_stop_price"] == 0
                    or bool(protection_degraded)
                )
            ):
                next_status = "UNPROTECTED"
            cursor = connection.execute(
                """
                UPDATE trade_executions
                SET status = ?, position_ticket = ?, remaining_volume = ?,
                    current_stop_price = ?,
                    current_take_profit_price = COALESCE(?, current_take_profit_price),
                    last_broker_sync_at = ?, updated_at = ?
                WHERE setup_id = ? AND position_identifier = ?
                  AND account_login = ? AND account_server = ? AND magic = ?
                """,
                (
                    next_status,
                    normalized["position_ticket"],
                    normalized["remaining_volume"],
                    normalized["current_stop_price"],
                    normalized["current_take_profit_price"],
                    normalized["last_broker_sync_at"],
                    now,
                    str(setup_id),
                    normalized["position_identifier"],
                    normalized["account_login"],
                    normalized["account_server"],
                    normalized["magic"],
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Position synchronization lost its stable-identity guard")
            refreshed = connection.execute(
                "SELECT * FROM trade_executions WHERE setup_id = ?", (str(setup_id),)
            ).fetchone()
        assert refreshed is not None
        return dict(refreshed)

    def bind_unprotected_trade_position(
        self,
        setup_id: str,
        *,
        position_ticket: int,
        position_identifier: int,
        symbol: str,
        side: str,
        comment: str,
        actual_entry: float,
        opened_at: datetime | str,
        volume: float,
        current_stop_price: float,
        current_take_profit_price: float,
        magic: int,
        account_login: str | int,
        account_server: str,
        account_scope: str,
        last_broker_sync_at: datetime | str,
    ) -> dict[str, Any]:
        """Freeze an exact broker position even while initial protection is absent."""

        ticket = _optional_positive_int(position_ticket, "position_ticket")
        identifier = _optional_positive_int(
            position_identifier, "position_identifier"
        )
        normalized_magic = _optional_positive_int(magic, "magic")
        assert ticket is not None and identifier is not None and normalized_magic is not None
        entry = _required_finite_float(actual_entry, "actual_entry")
        normalized_volume = _required_finite_float(volume, "volume")
        stop = _required_finite_float(current_stop_price, "current_stop_price")
        take_profit = _required_finite_float(
            current_take_profit_price, "current_take_profit_price"
        )
        opened = _optional_timestamp(opened_at)
        synced = _optional_timestamp(last_broker_sync_at)
        normalized_side = str(side or "").strip().lower()
        login = str(account_login or "").strip()
        server = str(account_server or "").strip()
        scope = str(account_scope or "").strip().lower()
        if entry <= 0 or normalized_volume <= 0:
            raise ValueError("Unprotected position entry and volume must be positive")
        if stop < 0 or take_profit < 0:
            raise ValueError("Unprotected position SL/TP must not be negative")
        if opened is None or synced is None:
            raise ValueError("Unprotected position timestamps are required")
        if normalized_side not in {"buy", "sell"}:
            raise ValueError("Unprotected position side must be BUY or SELL")
        if scope not in {"demo", "live"} or not login or not server:
            raise ValueError("Unprotected position requires a frozen account binding")

        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = connection.execute(
                "SELECT * FROM trade_executions WHERE setup_id = ?", (str(setup_id),)
            ).fetchone()
            if execution is None:
                raise RuntimeError("Cannot bind a missing trade execution")
            if str(execution["status"]) not in _PENDING_OPEN_EXECUTION_STATUSES:
                raise RuntimeError(
                    "Unprotected binding requires an active pending/UNPROTECTED execution"
                )
            expected = {
                "symbol": str(symbol),
                "side": normalized_side,
                "magic": normalized_magic,
                "account_login": login,
                "account_server": server,
                "account_scope": scope,
            }
            for field, value in expected.items():
                stored = execution[field]
                if field in {"side", "account_scope"}:
                    matches = str(stored or "").strip().lower() == str(value).lower()
                elif field == "magic":
                    matches = int(stored or 0) == int(value)
                else:
                    matches = str(stored or "") == str(value)
                if not matches:
                    raise ValueError(
                        f"Unprotected position {field} does not match frozen execution"
                    )
            if str(execution["client_tag"] or "") not in str(comment or ""):
                raise ValueError(
                    "Unprotected position comment does not contain frozen client tag"
                )
            existing_identifier = _optional_positive_int(
                execution["position_identifier"], "position_identifier"
            )
            if existing_identifier is not None and existing_identifier != identifier:
                raise ValueError(
                    "Unprotected position stable identifier changed on replay"
                )
            stored_entry = _optional_float(execution["actual_entry"])
            if stored_entry is not None and not math.isclose(
                stored_entry, entry, rel_tol=1e-12, abs_tol=1e-9
            ):
                raise ValueError(
                    "Unprotected position immutable actual_entry changed on replay"
                )
            stored_initial_volume = _optional_float(execution["initial_volume"])
            if (
                stored_initial_volume is not None
                and normalized_volume > stored_initial_volume + 1e-9
            ):
                raise ValueError(
                    "Unprotected position remaining volume exceeds frozen initial volume"
                )
            if execution["opened_at"] is not None and str(execution["opened_at"]) != opened:
                raise ValueError("Unprotected position opened_at changed on replay")

            cursor = connection.execute(
                """
                UPDATE trade_executions
                SET status = 'UNPROTECTED', position_ticket = ?,
                    position_identifier = ?, actual_entry = COALESCE(actual_entry, ?),
                    opened_at = COALESCE(opened_at, ?),
                    volume = CASE WHEN initial_volume IS NULL THEN ? ELSE volume END,
                    initial_volume = COALESCE(initial_volume, ?), remaining_volume = ?,
                    current_stop_price = ?, current_take_profit_price = ?,
                    last_broker_sync_at = ?, last_error = ?, updated_at = ?
                WHERE setup_id = ? AND status IN (
                    'OPEN_PENDING', 'OPEN_SUBMITTED', 'PLACED', 'OPEN_UNKNOWN',
                    'UNKNOWN', 'PARTIAL', 'UNPROTECTED'
                ) AND (position_identifier IS NULL OR position_identifier = ?)
                """,
                (
                    ticket,
                    identifier,
                    entry,
                    opened,
                    normalized_volume,
                    normalized_volume,
                    normalized_volume,
                    stop,
                    take_profit,
                    synced,
                    "broker position exists without complete initial protection",
                    now,
                    str(setup_id),
                    identifier,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Unprotected position binding lost its status guard")
            refreshed = connection.execute(
                "SELECT * FROM trade_executions WHERE setup_id = ?", (str(setup_id),)
            ).fetchone()
        assert refreshed is not None
        return dict(refreshed)

    def stage_position_management_action(
        self,
        setup_id: str,
        *,
        action_idempotency_key: str,
        action_type: str,
        milestone: str | None = None,
        reached_milestones: tuple[str, ...] | list[str] = (),
        reached_at: datetime | str | None = None,
        current_r: float | None = None,
        payload: dict[str, Any] | None = None,
        repair: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        """Atomically latch R observations and persist one broker action intent.

        ``repair=True`` is the explicit exception that can reopen an R1/R2
        protection slot after a previously CONFIRMED stop is observed weaker at
        the broker. It remains a new, independently idempotent ledger action.
        """

        normalized_key = str(action_idempotency_key or "").strip()
        normalized_type = str(action_type or "").strip().upper()
        normalized_milestone = _normalize_management_milestone(milestone)
        reached = _normalize_reached_milestones(reached_milestones)
        if normalized_milestone in _MILESTONE_COLUMNS:
            reached = tuple(dict.fromkeys((*reached, normalized_milestone)))
        if not normalized_key or not normalized_type:
            raise ValueError("Management action requires idempotency key and action type")
        observed_at = _optional_timestamp(reached_at) or _utc_now()
        normalized_r = (
            None
            if current_r is None
            else _required_finite_float(current_r, "current_r")
        )
        if reached and normalized_r is None:
            raise ValueError("Reached management milestones require current_r")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = connection.execute(
                "SELECT * FROM trade_executions WHERE setup_id = ?", (str(setup_id),)
            ).fetchone()
            if execution is None:
                raise RuntimeError("Cannot stage management for a missing execution")
            action_payload = dict(payload or {})
            _validate_manageable_execution(
                execution,
                action_type=normalized_type,
                payload=action_payload,
            )
            if action_payload.get("repair_filled") is True:
                _validate_filled_protection_repair_lineage(connection, execution)
            required_payload: dict[str, Any] = {
                "position_identifier": int(execution["position_identifier"]),
            }
            if normalized_milestone is not None:
                required_payload["milestone"] = normalized_milestone
            if repair:
                if normalized_milestone not in {"R1", "R2"}:
                    raise ValueError("Protection repair is supported only for R1 or R2")
                required_payload["repair"] = True
            for field, expected in required_payload.items():
                if field in action_payload and action_payload[field] != expected:
                    raise ValueError(
                        f"Management action payload {field} does not match execution"
                    )
                action_payload[field] = expected
            immutable_action = {
                "idempotency_key": normalized_key,
                "setup_id": str(setup_id),
                "position_ticket": _optional_positive_int(
                    execution["position_ticket"], "position_ticket"
                ),
                "position_identifier": _optional_positive_int(
                    execution["position_identifier"], "position_identifier"
                ),
                "action_type": normalized_type,
                "payload_json": json.dumps(
                    action_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                "management_policy": str(execution["management_policy"]),
                "account_login": str(execution["account_login"]),
                "account_server": str(execution["account_server"]),
                "account_scope": str(execution["account_scope"]).lower(),
            }
            existing_action = connection.execute(
                "SELECT * FROM position_actions WHERE idempotency_key = ?",
                (normalized_key,),
            ).fetchone()
            if existing_action is not None:
                _assert_position_action_replay(existing_action, immutable_action)
                _validate_action_execution_binding(execution, existing_action)
                _assert_management_projection(
                    execution, existing_action, normalized_milestone
                )
                return (
                    dict(execution),
                    _position_action_row(existing_action),
                    False,
                )

            _assert_management_slot_available(
                execution, normalized_milestone, repair=bool(repair)
            )
            assignments, parameters = _management_observation_update(
                reached=reached,
                observed_at=observed_at,
                current_r=normalized_r,
                milestone=normalized_milestone,
                action_status="PENDING",
            )
            assignments.append("updated_at = ?")
            staged_status = str(execution["status"])
            parameters.extend((_utc_now(), str(setup_id), staged_status))
            cursor = connection.execute(
                f"UPDATE trade_executions SET {', '.join(assignments)} "
                "WHERE setup_id = ? AND status = ?",
                tuple(parameters),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Management staging lost its execution-status guard")
            action_row = _insert_position_action(
                connection, immutable_action, now=observed_at
            )
            refreshed = connection.execute(
                "SELECT * FROM trade_executions WHERE setup_id = ?", (str(setup_id),)
            ).fetchone()
        assert refreshed is not None
        return dict(refreshed), _position_action_row(action_row), True

    def finalize_position_management_action(
        self,
        idempotency_key: str,
        *,
        setup_id: str,
        outcome: str,
        milestone: str | None = None,
        remaining_volume: float | None = None,
        current_stop_price: float | None = None,
        current_take_profit_price: float | None = None,
        last_broker_sync_at: datetime | str | None = None,
        broker_order_ticket: int | None = None,
        broker_deal_ticket: int | None = None,
        broker_position_ticket: int | None = None,
        broker_retcode: int | None = None,
        broker_reference: str | None = None,
        error: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Commit a management broker outcome and its projected R state together."""

        normalized_key = str(idempotency_key or "").strip()
        normalized_outcome = str(outcome or "").strip().upper()
        normalized_milestone = _normalize_management_milestone(milestone)
        if not normalized_key:
            raise ValueError("Management action idempotency key must not be empty")
        if normalized_outcome not in {"CONFIRMED", "FAILED", "UNKNOWN"}:
            raise ValueError("Management action outcome must be CONFIRMED, FAILED, or UNKNOWN")
        normalized_error = str(error or "").strip()[:1000] or None
        if normalized_outcome in {"FAILED", "UNKNOWN"} and normalized_error is None:
            raise ValueError(f"Management action {normalized_outcome} requires an error")
        normalized_remaining = (
            None
            if remaining_volume is None
            else _required_finite_float(remaining_volume, "remaining_volume")
        )
        if normalized_remaining is not None and normalized_remaining < 0:
            raise ValueError("remaining_volume must not be negative")
        normalized_stop = (
            None
            if current_stop_price is None
            else _required_finite_float(current_stop_price, "current_stop_price")
        )
        if normalized_stop is not None and normalized_stop < 0:
            raise ValueError("current_stop_price must not be negative")
        normalized_take_profit = (
            None
            if current_take_profit_price is None
            else _required_finite_float(
                current_take_profit_price, "current_take_profit_price"
            )
        )
        if normalized_take_profit is not None and normalized_take_profit < 0:
            raise ValueError("current_take_profit_price must not be negative")
        normalized_sync = (
            _optional_timestamp(last_broker_sync_at)
            if last_broker_sync_at is not None
            else None
        )
        broker_values = {
            "broker_order_ticket": _optional_positive_int(
                broker_order_ticket, "broker_order_ticket"
            ),
            "broker_deal_ticket": _optional_positive_int(
                broker_deal_ticket, "broker_deal_ticket"
            ),
            "broker_position_ticket": _optional_positive_int(
                broker_position_ticket, "broker_position_ticket"
            ),
            "broker_retcode": _optional_int(broker_retcode),
            "broker_reference": str(broker_reference or "").strip()[:1000] or None,
        }
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = connection.execute(
                "SELECT * FROM trade_executions WHERE setup_id = ?", (str(setup_id),)
            ).fetchone()
            action = connection.execute(
                "SELECT * FROM position_actions WHERE idempotency_key = ?",
                (normalized_key,),
            ).fetchone()
            if execution is None or action is None:
                raise RuntimeError("Management finalization requires execution and action rows")
            _validate_action_execution_binding(execution, action)
            _validate_execution_take_profit(execution, normalized_take_profit)
            stored_milestone = _management_action_milestone(action)
            if normalized_milestone is None:
                normalized_milestone = stored_milestone
            elif normalized_milestone != stored_milestone:
                raise ValueError("Management action milestone does not match its payload")
            _assert_management_projection(execution, action, normalized_milestone)
            _validate_management_outcome_transition(
                current=str(action["status"]), requested=normalized_outcome
            )
            _validate_broker_audit_replay(action, broker_values)
            if (
                str(action["status"]) == normalized_outcome
                and normalized_outcome in {"FAILED", "UNKNOWN"}
                and str(action["last_error"] or "") != str(normalized_error or "")
            ):
                raise ValueError("Management action outcome replay changes its error audit")
            if normalized_remaining is not None:
                initial_volume = _optional_float(execution["initial_volume"])
                current_remaining = _optional_float(execution["remaining_volume"])
                if initial_volume is not None and normalized_remaining > initial_volume + 1e-9:
                    raise ValueError("remaining_volume exceeds frozen initial volume")
                if (
                    current_remaining is not None
                    and normalized_remaining > current_remaining + 1e-9
                ):
                    raise ValueError("remaining_volume must not increase")
            timestamp_column = {
                "CONFIRMED": "confirmed_at",
                "FAILED": "failed_at",
                "UNKNOWN": "unknown_at",
            }[normalized_outcome]
            cursor = connection.execute(
                f"""
                UPDATE position_actions
                SET status = ?,
                    projected_at = CASE WHEN status = ? THEN projected_at ELSE NULL END,
                    projection_lease_owner = CASE
                        WHEN status = ? THEN projection_lease_owner ELSE NULL END,
                    projection_lease_acquired_at = CASE
                        WHEN status = ? THEN projection_lease_acquired_at ELSE NULL END,
                    projection_lease_expires_at = CASE
                        WHEN status = ? THEN projection_lease_expires_at ELSE NULL END,
                    broker_order_ticket = COALESCE(broker_order_ticket, ?),
                    broker_deal_ticket = COALESCE(broker_deal_ticket, ?),
                    broker_position_ticket = COALESCE(broker_position_ticket, ?),
                    broker_retcode = COALESCE(broker_retcode, ?),
                    broker_reference = COALESCE(broker_reference, ?),
                    last_error = ?, {timestamp_column} = COALESCE({timestamp_column}, ?),
                    lease_owner = NULL, lease_acquired_at = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    normalized_outcome,
                    normalized_outcome,
                    normalized_outcome,
                    normalized_outcome,
                    normalized_outcome,
                    broker_values["broker_order_ticket"],
                    broker_values["broker_deal_ticket"],
                    broker_values["broker_position_ticket"],
                    broker_values["broker_retcode"],
                    broker_values["broker_reference"],
                    None if normalized_outcome == "CONFIRMED" else normalized_error,
                    now,
                    now,
                    int(action["id"]),
                    str(action["status"]),
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Management action finalization lost its status guard")
            execution_assignments: list[str] = []
            execution_parameters: list[Any] = []
            action_payload = json.loads(str(action["payload_json"] or "{}"))
            is_filled_protection_repair = bool(
                str(action["action_type"]).upper() == "SET_INITIAL_PROTECTION"
                and action_payload.get("repair_filled") is True
            )
            if (
                str(action["action_type"]).upper() == "CLOSE_FULL"
                and str(execution["status"]) != "CLOSED"
            ):
                close_status = {
                    "CONFIRMED": "CLOSE_SUBMITTED",
                    "FAILED": "CLOSE_REJECTED",
                    "UNKNOWN": "CLOSE_UNKNOWN",
                }[normalized_outcome]
                execution_assignments.append("status = ?")
                execution_parameters.append(close_status)
            elif is_filled_protection_repair:
                execution_assignments.append("status = ?")
                execution_parameters.append(
                    "FILLED" if normalized_outcome == "CONFIRMED" else "UNPROTECTED"
                )
            if normalized_milestone in _MILESTONE_COLUMNS:
                status_column = _MILESTONE_COLUMNS[normalized_milestone][1]
                execution_assignments.append(f"{status_column} = ?")
                execution_parameters.append(normalized_outcome)
            if normalized_remaining is not None:
                execution_assignments.append("remaining_volume = ?")
                execution_parameters.append(normalized_remaining)
            if normalized_stop is not None:
                execution_assignments.append("current_stop_price = ?")
                execution_parameters.append(normalized_stop)
            if normalized_take_profit is not None:
                execution_assignments.append("current_take_profit_price = ?")
                execution_parameters.append(normalized_take_profit)
            if normalized_sync is not None:
                execution_assignments.append("last_broker_sync_at = ?")
                execution_parameters.append(normalized_sync)
            execution_assignments.append("updated_at = ?")
            execution_parameters.extend((now, str(setup_id)))
            cursor = connection.execute(
                f"UPDATE trade_executions SET {', '.join(execution_assignments)} "
                "WHERE setup_id = ? AND position_identifier = ?",
                (*execution_parameters, int(execution["position_identifier"])),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Management projection lost its stable-identity guard")
            refreshed_execution = connection.execute(
                "SELECT * FROM trade_executions WHERE setup_id = ?", (str(setup_id),)
            ).fetchone()
            refreshed_action = connection.execute(
                "SELECT * FROM position_actions WHERE id = ?", (int(action["id"]),)
            ).fetchone()
        assert refreshed_execution is not None and refreshed_action is not None
        return dict(refreshed_execution), _position_action_row(refreshed_action)

    def create_position_action(
        self,
        *,
        idempotency_key: str,
        action_type: str,
        position_ticket: int | None = None,
        position_identifier: int | None = None,
        payload: dict[str, Any] | None = None,
        setup_id: str | None = None,
        management_policy: str = "",
        account_login: str | int = "",
        account_server: str = "",
        account_scope: str = "",
        created_at: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Persist one immutable broker action intent.

        Retrying the exact same idempotency key and intent returns the original
        row with ``created=False``. Reusing a key for a different intent is an
        error instead of silently operating on the wrong broker action.
        """

        normalized_key = idempotency_key.strip()
        normalized_type = action_type.strip().upper()
        normalized_ticket = _optional_positive_int(position_ticket, "position_ticket")
        normalized_identifier = _optional_positive_int(
            position_identifier, "position_identifier"
        )
        if not normalized_key:
            raise ValueError("Position action idempotency_key must not be empty")
        if not normalized_type:
            raise ValueError("Position action action_type must not be empty")
        if normalized_type == "OPEN":
            if normalized_ticket is not None or normalized_identifier is not None:
                raise ValueError("OPEN position action must not have a position target")
        elif normalized_ticket is None and normalized_identifier is None:
            raise ValueError(
                "Position mutation action requires a positive ticket or stable identifier"
            )
        payload_json = json.dumps(
            payload or {}, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        now = _iso(created_at) if created_at is not None else _utc_now()
        immutable = {
            "idempotency_key": normalized_key,
            "setup_id": str(setup_id).strip() if setup_id is not None else None,
            "position_ticket": normalized_ticket,
            "position_identifier": normalized_identifier,
            "action_type": normalized_type,
            "payload_json": payload_json,
            "management_policy": str(management_policy or "").strip(),
            "account_login": str(account_login or "").strip(),
            "account_server": str(account_server or "").strip(),
            "account_scope": str(account_scope or "").strip().lower(),
        }
        with self._connect() as connection:
            try:
                row = _insert_position_action(connection, immutable, now=now)
                created = True
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM position_actions WHERE idempotency_key = ?",
                    (normalized_key,),
                ).fetchone()
                if row is None:
                    raise
                try:
                    _assert_position_action_replay(row, immutable)
                except ValueError as exc:
                    raise ValueError(
                        "Position action idempotency key already belongs to a different intent"
                    ) from exc
                created = False
        assert row is not None
        return _position_action_row(row), created

    def position_action(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM position_actions WHERE idempotency_key = ?",
                (idempotency_key.strip(),),
            ).fetchone()
        return _position_action_row(row) if row is not None else None

    def position_actions(
        self,
        *,
        status: str | None = None,
        setup_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if status is not None:
            normalized_status = status.strip().upper()
            if normalized_status not in _POSITION_ACTION_STATUSES:
                raise ValueError(f"Unsupported position action status: {status}")
            clauses.append("status = ?")
            parameters.append(normalized_status)
        if setup_id is not None:
            clauses.append("setup_id = ?")
            parameters.append(str(setup_id))
        query = "SELECT * FROM position_actions"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at, id LIMIT ?"
        parameters.append(max(1, min(int(limit), 1000)))
        with self._connect() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [_position_action_row(row) for row in rows]

    def claim_position_action_projection(
        self,
        *,
        lease_owner: str,
        statuses: tuple[str, ...] | list[str] = ("CONFIRMED", "FAILED", "UNKNOWN"),
        exclude_action_ids: tuple[int, ...] | list[int] = (),
        lease_seconds: float = 30.0,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Claim the oldest unprojected broker outcome without history starvation."""

        normalized_owner = str(lease_owner or "").strip()
        if not normalized_owner:
            raise ValueError("Projection lease_owner must not be empty")
        if lease_seconds <= 0:
            raise ValueError("Projection lease_seconds must be positive")
        normalized_statuses = _normalize_projection_statuses(statuses)
        excluded_ids = tuple(
            dict.fromkeys(
                _optional_positive_int(value, "exclude_action_id")
                for value in exclude_action_ids
            )
        )
        if any(value is None for value in excluded_ids):
            raise ValueError("Projection exclusion IDs must be positive integers")
        claimed_at = now or datetime.now(timezone.utc)
        claimed_at_text = _iso(claimed_at)
        expires_at_text = _iso(claimed_at + timedelta(seconds=float(lease_seconds)))
        placeholders = ", ".join("?" for _ in normalized_statuses)
        exclusion_sql = ""
        exclusion_parameters: tuple[Any, ...] = ()
        if excluded_ids:
            exclusion_sql = (
                " AND id NOT IN (" + ", ".join("?" for _ in excluded_ids) + ")"
            )
            exclusion_parameters = tuple(int(value) for value in excluded_ids)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            candidate = connection.execute(
                f"""
                SELECT id FROM position_actions
                WHERE status IN ({placeholders}) AND projected_at IS NULL
                  AND (
                      projection_lease_expires_at IS NULL
                      OR projection_lease_expires_at <= ?
                  )
                  {exclusion_sql}
                ORDER BY id
                LIMIT 1
                """,
                (*normalized_statuses, claimed_at_text, *exclusion_parameters),
            ).fetchone()
            if candidate is None:
                return None
            cursor = connection.execute(
                f"""
                UPDATE position_actions
                SET projection_lease_owner = ?, projection_lease_acquired_at = ?,
                    projection_lease_expires_at = ?,
                    projection_attempt_count = projection_attempt_count + 1,
                    updated_at = ?
                WHERE id = ? AND status IN ({placeholders}) AND projected_at IS NULL
                  AND (
                      projection_lease_expires_at IS NULL
                      OR projection_lease_expires_at <= ?
                  )
                """,
                (
                    normalized_owner,
                    claimed_at_text,
                    expires_at_text,
                    claimed_at_text,
                    int(candidate["id"]),
                    *normalized_statuses,
                    claimed_at_text,
                ),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT * FROM position_actions WHERE id = ?", (int(candidate["id"]),)
            ).fetchone()
        assert row is not None
        return _position_action_row(row)

    def mark_position_action_projected(
        self,
        idempotency_key: str,
        *,
        lease_owner: str,
        projected_at: datetime | str | None = None,
    ) -> bool:
        """Complete a claimed projection; exact replay after commit is successful."""

        normalized_key = str(idempotency_key or "").strip()
        normalized_owner = str(lease_owner or "").strip()
        if not normalized_key or not normalized_owner:
            raise ValueError("Projection completion requires idempotency key and lease owner")
        completed_at = _optional_timestamp(projected_at) or _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM position_actions WHERE idempotency_key = ?",
                (normalized_key,),
            ).fetchone()
            if row is None:
                return False
            if row["projected_at"] is not None:
                return True
            cursor = connection.execute(
                """
                UPDATE position_actions
                SET projected_at = ?, projection_lease_owner = NULL,
                    projection_lease_acquired_at = NULL,
                    projection_lease_expires_at = NULL, updated_at = ?
                WHERE id = ? AND projected_at IS NULL
                  AND projection_lease_owner = ?
                  AND status IN ('CONFIRMED', 'FAILED', 'UNKNOWN')
                """,
                (completed_at, completed_at, int(row["id"]), normalized_owner),
            )
        return cursor.rowcount == 1

    def release_position_action_projection(
        self,
        *,
        idempotency_key: str,
        lease_owner: str,
        retry_seconds: float = 0.0,
        now: datetime | None = None,
    ) -> bool:
        delay = float(retry_seconds)
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("Projection retry_seconds must be finite and non-negative")
        released_at = now or datetime.now(timezone.utc)
        retry_at = (
            _iso(released_at + timedelta(seconds=delay)) if delay > 0 else None
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE position_actions
                SET projection_lease_owner = NULL,
                    projection_lease_acquired_at = NULL,
                    projection_lease_expires_at = ?, updated_at = ?
                WHERE idempotency_key = ? AND projected_at IS NULL
                  AND projection_lease_owner = ?
                """,
                (
                    retry_at,
                    _iso(released_at),
                    idempotency_key.strip(),
                    lease_owner.strip(),
                ),
            )
        return cursor.rowcount == 1

    def claim_position_action(
        self,
        *,
        lease_owner: str,
        lease_seconds: float = 30.0,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Atomically claim the oldest available pending action.

        ``BEGIN IMMEDIATE`` serializes competing claimers before either can
        select a row. An abandoned PENDING claim becomes eligible after its
        lease expires; SUBMITTED and UNKNOWN actions are never auto-retried.
        """

        normalized_owner = lease_owner.strip()
        if not normalized_owner:
            raise ValueError("Position action lease_owner must not be empty")
        if lease_seconds <= 0:
            raise ValueError("Position action lease_seconds must be positive")
        claimed_at = now or datetime.now(timezone.utc)
        claimed_at_text = _iso(claimed_at)
        expires_at_text = _iso(claimed_at + timedelta(seconds=float(lease_seconds)))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            candidate = connection.execute(
                """
                SELECT id FROM position_actions
                WHERE status = 'PENDING'
                  AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                ORDER BY created_at, id
                LIMIT 1
                """,
                (claimed_at_text,),
            ).fetchone()
            if candidate is None:
                return None
            cursor = connection.execute(
                """
                UPDATE position_actions
                SET lease_owner = ?, lease_acquired_at = ?, lease_expires_at = ?,
                    attempt_count = attempt_count + 1, last_attempt_at = ?, updated_at = ?
                WHERE id = ? AND status = 'PENDING'
                  AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                """,
                (
                    normalized_owner,
                    claimed_at_text,
                    expires_at_text,
                    claimed_at_text,
                    claimed_at_text,
                    int(candidate["id"]),
                    claimed_at_text,
                ),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT * FROM position_actions WHERE id = ?", (int(candidate["id"]),)
            ).fetchone()
        assert row is not None
        return _position_action_row(row)

    def defer_pending_position_action(
        self,
        *,
        idempotency_key: str,
        lease_owner: str,
        retry_seconds: float,
        now: datetime | None = None,
    ) -> bool:
        """Release a PENDING fence with a durable not-before retry time."""

        delay = float(retry_seconds)
        if not math.isfinite(delay) or delay <= 0:
            raise ValueError("Pending-action retry_seconds must be finite and positive")
        released_at = now or datetime.now(timezone.utc)
        retry_at = _iso(released_at + timedelta(seconds=delay))
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE position_actions
                SET lease_owner = NULL, lease_acquired_at = NULL,
                    lease_expires_at = ?, updated_at = ?
                WHERE idempotency_key = ? AND status = 'PENDING'
                  AND lease_owner = ?
                """,
                (
                    retry_at,
                    _iso(released_at),
                    str(idempotency_key).strip(),
                    str(lease_owner).strip(),
                ),
            )
        return cursor.rowcount == 1

    def release_position_action_claim(self, *, idempotency_key: str, lease_owner: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE position_actions
                SET lease_owner = NULL, lease_acquired_at = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE idempotency_key = ? AND status = 'PENDING' AND lease_owner = ?
                """,
                (_utc_now(), idempotency_key.strip(), lease_owner.strip()),
            )
        return cursor.rowcount == 1

    def retry_position_action(self, idempotency_key: str) -> bool:
        """Explicitly requeue a FAILED mutation without resetting attempt audit.

        OPEN fences are generation-bound and cannot be resurrected after a
        terminal event or failed submission through this generic retry path.
        """

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE position_actions
                SET status = 'PENDING', lease_owner = NULL, lease_acquired_at = NULL,
                    lease_expires_at = NULL, last_error = NULL,
                    projected_at = NULL, projection_lease_owner = NULL,
                    projection_lease_acquired_at = NULL,
                    projection_lease_expires_at = NULL, updated_at = ?
                WHERE idempotency_key = ? AND status = 'FAILED'
                  AND UPPER(action_type) <> 'OPEN'
                """,
                (_utc_now(), idempotency_key.strip()),
            )
        return cursor.rowcount == 1

    def mark_position_action_submitted(
        self,
        idempotency_key: str,
        *,
        lease_owner: str | None = None,
        broker_order_ticket: int | None = None,
        broker_deal_ticket: int | None = None,
        broker_position_ticket: int | None = None,
        broker_retcode: int | None = None,
        broker_reference: str | None = None,
    ) -> bool:
        """Fence the action from re-claim before performing the broker mutation.

        A worker should persist SUBMITTED immediately before the external side
        effect, then reconcile the broker response to CONFIRMED, FAILED, or
        UNKNOWN. This deliberately favors a recoverable reconciliation over an
        automatic duplicate position mutation after a process crash.
        """

        return self._transition_position_action(
            idempotency_key,
            status="SUBMITTED",
            allowed_from=("PENDING", "SUBMITTED"),
            lease_owner=lease_owner,
            broker_order_ticket=broker_order_ticket,
            broker_deal_ticket=broker_deal_ticket,
            broker_position_ticket=broker_position_ticket,
            broker_retcode=broker_retcode,
            broker_reference=broker_reference,
        )

    def mark_position_action_confirmed(
        self,
        idempotency_key: str,
        *,
        lease_owner: str | None = None,
        broker_order_ticket: int | None = None,
        broker_deal_ticket: int | None = None,
        broker_position_ticket: int | None = None,
        broker_retcode: int | None = None,
        broker_reference: str | None = None,
    ) -> bool:
        return self._transition_position_action(
            idempotency_key,
            status="CONFIRMED",
            allowed_from=("PENDING", "SUBMITTED", "CONFIRMED", "FAILED", "UNKNOWN"),
            lease_owner=lease_owner,
            broker_order_ticket=broker_order_ticket,
            broker_deal_ticket=broker_deal_ticket,
            broker_position_ticket=broker_position_ticket,
            broker_retcode=broker_retcode,
            broker_reference=broker_reference,
        )

    def mark_position_action_failed(
        self,
        idempotency_key: str,
        error: str,
        *,
        lease_owner: str | None = None,
        broker_retcode: int | None = None,
        broker_reference: str | None = None,
    ) -> bool:
        return self._transition_position_action(
            idempotency_key,
            status="FAILED",
            allowed_from=("PENDING", "SUBMITTED", "FAILED", "UNKNOWN"),
            lease_owner=lease_owner,
            broker_retcode=broker_retcode,
            broker_reference=broker_reference,
            error=error,
        )

    def mark_position_action_unknown(
        self,
        idempotency_key: str,
        error: str,
        *,
        lease_owner: str | None = None,
        broker_retcode: int | None = None,
        broker_reference: str | None = None,
    ) -> bool:
        return self._transition_position_action(
            idempotency_key,
            status="UNKNOWN",
            allowed_from=("PENDING", "SUBMITTED", "FAILED", "UNKNOWN"),
            lease_owner=lease_owner,
            broker_retcode=broker_retcode,
            broker_reference=broker_reference,
            error=error,
        )

    def _transition_position_action(
        self,
        idempotency_key: str,
        *,
        status: str,
        allowed_from: tuple[str, ...],
        lease_owner: str | None = None,
        broker_order_ticket: int | None = None,
        broker_deal_ticket: int | None = None,
        broker_position_ticket: int | None = None,
        broker_retcode: int | None = None,
        broker_reference: str | None = None,
        error: str | None = None,
    ) -> bool:
        if status not in _POSITION_ACTION_STATUSES:
            raise ValueError(f"Unsupported position action status: {status}")
        if status in {"FAILED", "UNKNOWN"} and not str(error or "").strip():
            raise ValueError(f"Position action {status} requires a non-empty error")
        timestamp_column = {
            "SUBMITTED": "submitted_at",
            "CONFIRMED": "confirmed_at",
            "FAILED": "failed_at",
            "UNKNOWN": "unknown_at",
        }[status]
        placeholders = ", ".join("?" for _ in allowed_from)
        owner_clause = (
            " AND lease_owner IS NULL"
            if lease_owner is None
            else " AND lease_owner = ?"
        )
        now = _utc_now()
        parameters: list[Any] = [
            status,
            status,
            status,
            status,
            status,
            broker_order_ticket,
            broker_deal_ticket,
            broker_position_ticket,
            broker_retcode,
            broker_reference[:1000] if broker_reference else None,
            str(error).strip()[:1000] if error else None,
            now,
            now,
            idempotency_key.strip(),
            *allowed_from,
        ]
        if lease_owner is not None:
            parameters.append(lease_owner.strip())
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE position_actions
                SET status = ?,
                    projected_at = CASE WHEN status = ? THEN projected_at ELSE NULL END,
                    projection_lease_owner = CASE
                        WHEN status = ? THEN projection_lease_owner ELSE NULL END,
                    projection_lease_acquired_at = CASE
                        WHEN status = ? THEN projection_lease_acquired_at ELSE NULL END,
                    projection_lease_expires_at = CASE
                        WHEN status = ? THEN projection_lease_expires_at ELSE NULL END,
                    broker_order_ticket = COALESCE(?, broker_order_ticket),
                    broker_deal_ticket = COALESCE(?, broker_deal_ticket),
                    broker_position_ticket = COALESCE(?, broker_position_ticket),
                    broker_retcode = COALESCE(?, broker_retcode),
                    broker_reference = COALESCE(?, broker_reference),
                    last_error = ?,
                    {timestamp_column} = COALESCE({timestamp_column}, ?),
                    lease_owner = NULL, lease_acquired_at = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE idempotency_key = ? AND status IN ({placeholders}){owner_clause}
                """,
                tuple(parameters),
            )
        return cursor.rowcount == 1

    def update_outbox_payload(self, outbox_id: int, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE signal_outbox SET payload_json = ? WHERE id = ? AND sent_at IS NULL",
                (json.dumps(payload, sort_keys=True), int(outbox_id)),
            )

    def cancel_pending_open_for_terminal_event(
        self,
        setup_id: str,
        *,
        terminal_outbox_id: int,
        reason: str,
    ) -> dict[str, Any]:
        """Atomically consume a terminal signal event and fence its OPEN.

        A broker action that is still PENDING can be cancelled truthfully.  A
        SUBMITTED/UNKNOWN (or already confirmed) OPEN is never relabelled as
        cancelled; instead the first terminal request is durably latched for
        close-after-reconciliation.
        """

        normalized_setup = str(setup_id or "").strip()
        terminal_id = _optional_positive_int(
            terminal_outbox_id, "terminal_outbox_id"
        )
        normalized_reason = str(reason or "").strip()[:500]
        if not normalized_setup:
            raise ValueError("Terminal OPEN cancellation requires setup_id")
        if terminal_id is None:
            raise ValueError("Terminal OPEN cancellation requires terminal_outbox_id")
        if not normalized_reason:
            raise ValueError("Terminal OPEN cancellation requires a reason")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            terminal = connection.execute(
                """
                SELECT id, setup_id, event_type FROM signal_outbox WHERE id = ?
                """,
                (terminal_id,),
            ).fetchone()
            if terminal is None:
                raise RuntimeError("Terminal outbox row does not exist")
            event_type = str(terminal["event_type"] or "").strip().upper()
            if str(terminal["setup_id"]) != normalized_setup:
                raise ValueError("Terminal outbox row belongs to a different setup")
            if event_type not in _TERMINAL_SIGNAL_EVENT_TYPES:
                raise ValueError(
                    f"Outbox event {event_type!r} is not a terminal signal event"
                )

            receipt = connection.execute(
                "SELECT * FROM trade_event_receipts WHERE outbox_id = ?",
                (terminal_id,),
            ).fetchone()
            if receipt is not None:
                if str(receipt["event_type"]).strip().upper() != event_type:
                    raise RuntimeError("Terminal event receipt type does not match its outbox row")
                recorded = _decode_terminal_open_receipt(str(receipt["result"] or ""))
                if recorded is not None:
                    if (
                        recorded.get("setup_id") != normalized_setup
                        or int(recorded.get("terminal_outbox_id") or 0) != terminal_id
                        or recorded.get("reason") != normalized_reason
                    ):
                        raise ValueError(
                            "Terminal OPEN cancellation replay changes immutable receipt data"
                        )
                    disposition = str(recorded["disposition"])
                else:
                    disposition = "ALREADY_PROCESSED"
                return _terminal_open_snapshot(
                    connection,
                    normalized_setup,
                    disposition=disposition,
                )

            execution = connection.execute(
                "SELECT * FROM trade_executions WHERE setup_id = ?",
                (normalized_setup,),
            ).fetchone()
            open_actions = connection.execute(
                """
                SELECT * FROM position_actions
                WHERE setup_id = ? AND UPPER(action_type) = 'OPEN'
                ORDER BY id
                """,
                (normalized_setup,),
            ).fetchall()
            if len(open_actions) > 1:
                raise RuntimeError(
                    "Multiple OPEN action fences exist for one setup; refusing ambiguous cancellation"
                )
            action = open_actions[0] if open_actions else None
            if execution is None and action is not None:
                raise RuntimeError(
                    "OPEN action exists without its execution; refusing terminal receipt"
                )

            now = _utc_now()
            execution_status = (
                str(execution["status"] or "").strip().upper()
                if execution is not None
                else ""
            )
            action_status = (
                str(action["status"] or "").strip().upper()
                if action is not None
                else ""
            )
            if (
                execution is not None
                and execution_status == "OPEN_PENDING"
                and action is not None
                and action_status == "PENDING"
            ):
                cursor = connection.execute(
                    """
                    UPDATE trade_executions
                    SET status = 'CANCELLED', cancelled_at = ?,
                        cancelled_by_terminal_outbox_id = ?, close_reason = ?,
                        closed_by = 'TERMINAL_EVENT', last_error = ?, updated_at = ?
                    WHERE setup_id = ? AND status = 'OPEN_PENDING'
                      AND position_identifier IS NULL
                    """,
                    (
                        now,
                        terminal_id,
                        normalized_reason,
                        normalized_reason,
                        now,
                        normalized_setup,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Pending OPEN cancellation lost its execution guard")
                cursor = connection.execute(
                    """
                    UPDATE position_actions
                    SET status = 'FAILED', last_error = ?, failed_at = COALESCE(failed_at, ?),
                        lease_owner = NULL, lease_acquired_at = NULL,
                        lease_expires_at = NULL, projected_at = NULL,
                        projection_lease_owner = NULL,
                        projection_lease_acquired_at = NULL,
                        projection_lease_expires_at = NULL, updated_at = ?
                    WHERE id = ? AND status = 'PENDING'
                    """,
                    (
                        f"{event_type} #{terminal_id}: {normalized_reason}"[:1000],
                        now,
                        now,
                        int(action["id"]),
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Pending OPEN cancellation lost its action guard")
                disposition = "CANCELLED"
            elif execution is None:
                disposition = "NO_EXECUTION"
            elif execution_status in {*_TERMINAL_OPEN_EXECUTION_STATUSES, "CLOSED"} or (
                action is not None and action_status == "FAILED"
            ):
                if action is not None and action_status == "PENDING":
                    cursor = connection.execute(
                        """
                        UPDATE position_actions
                        SET status = 'FAILED', last_error = ?,
                            failed_at = COALESCE(failed_at, ?),
                            lease_owner = NULL, lease_acquired_at = NULL,
                            lease_expires_at = NULL, projected_at = NULL,
                            projection_lease_owner = NULL,
                            projection_lease_acquired_at = NULL,
                            projection_lease_expires_at = NULL, updated_at = ?
                        WHERE id = ? AND status = 'PENDING'
                        """,
                        (
                            f"{event_type} #{terminal_id}: {normalized_reason}"[:1000],
                            now,
                            now,
                            int(action["id"]),
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError(
                            "Terminal execution lost its pending-action failure guard"
                        )
                disposition = "ALREADY_TERMINAL"
            else:
                if execution_status == "OPEN_PENDING" and action is None:
                    raise RuntimeError(
                        "OPEN_PENDING execution has no OPEN action fence; refusing terminal receipt"
                    )
                if action is not None and action_status == "PENDING":
                    raise RuntimeError(
                        "Execution advanced while its OPEN action is still PENDING"
                    )
                if action is not None and action_status not in {
                    "SUBMITTED",
                    "UNKNOWN",
                    "CONFIRMED",
                }:
                    raise RuntimeError(
                        f"Unsupported OPEN action state for terminal event: {action_status!r}"
                    )
                existing_reason = execution["deferred_close_reason"]
                existing_terminal_id = execution["deferred_close_terminal_outbox_id"]
                if existing_reason is None and existing_terminal_id is None:
                    cursor = connection.execute(
                        """
                        UPDATE trade_executions
                        SET deferred_close_reason = ?,
                            deferred_close_terminal_outbox_id = ?,
                            deferred_close_requested_at = ?, updated_at = ?
                        WHERE setup_id = ?
                          AND deferred_close_reason IS NULL
                          AND deferred_close_terminal_outbox_id IS NULL
                          AND status NOT IN ('CANCELLED', 'CLOSED')
                        """,
                        (
                            normalized_reason,
                            terminal_id,
                            now,
                            now,
                            normalized_setup,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError("Deferred close latch lost its atomic guard")
                elif existing_reason is None or existing_terminal_id is None:
                    raise RuntimeError("Deferred close latch is partially populated")
                elif int(existing_terminal_id) == terminal_id and str(
                    existing_reason
                ) != normalized_reason:
                    raise ValueError(
                        "Terminal event replay changes immutable deferred-close reason"
                    )
                disposition = "DEFERRED_CLOSE"

            snapshot = _terminal_open_snapshot(
                connection, normalized_setup, disposition=disposition
            )
            receipt_result = json.dumps(
                {
                    "kind": "OPEN_TERMINAL_V1",
                    "setup_id": normalized_setup,
                    "terminal_outbox_id": terminal_id,
                    "event_type": event_type,
                    "reason": normalized_reason,
                    "disposition": disposition,
                    "deferred_close_reason": snapshot["deferred_close_reason"],
                },
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            cursor = connection.execute(
                """
                INSERT INTO trade_event_receipts (outbox_id, event_type, result, processed_at)
                VALUES (?, ?, ?, ?)
                """,
                (terminal_id, event_type, receipt_result, now),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Terminal event receipt lost its atomic insert")
            return snapshot

    def mark_trade_event_processed(self, *, outbox_id: int, event_type: str, result: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO trade_event_receipts (outbox_id, event_type, result, processed_at)
                VALUES (?, ?, ?, ?)
                """,
                (int(outbox_id), event_type, result[:1000], _utc_now()),
            )

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
            bridge_row = connection.execute(
                "SELECT state_value FROM telegram_bot_state "
                "WHERE state_key = 'mt5_bridge_health'"
            ).fetchone()
        assert outbox is not None and cursor is not None
        bridge_health: dict[str, Any] = {}
        if bridge_row is not None:
            try:
                decoded = json.loads(str(bridge_row["state_value"]))
                if isinstance(decoded, dict):
                    bridge_health = decoded
            except (TypeError, ValueError):
                bridge_health = {"state_error": "invalid persisted bridge health"}
        bridge_health.pop("session_fingerprint", None)
        return {
            "total_count": int(outbox["total_count"] or 0),
            "pending_count": int(outbox["pending_count"] or 0),
            "failed_count": int(outbox["failed_count"] or 0),
            "last_event_at": outbox["last_event_at"],
            "last_sent_at": outbox["last_sent_at"],
            "last_log_at": cursor["last_log_at"],
            "bridge": bridge_health,
        }

    def record_mt5_bridge_health(
        self,
        *,
        session_fingerprint: str | None,
        files_discovered: int,
        tracked_cursors: int,
        matched_events: int,
        mismatched_events: int,
        provider_failures: int,
        last_session_observation: str | None = None,
        last_account_context_result: str | None = None,
        observed_at: datetime | None = None,
    ) -> None:
        """Persist bridge liveness without ever storing the EA session nonce."""

        now = _iso(observed_at or datetime.now(timezone.utc))
        fingerprint = str(session_fingerprint or "").strip()
        if fingerprint and (
            len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise ValueError("session_fingerprint must be a SHA-256 lowercase hex digest")
        counters = {
            "files_discovered": max(0, int(files_discovered)),
            "tracked_cursors": max(0, int(tracked_cursors)),
            "matched_events": max(0, int(matched_events)),
            "mismatched_events": max(0, int(mismatched_events)),
            "provider_failures": max(0, int(provider_failures)),
        }
        session_observation = str(last_session_observation or "").strip().lower()
        if not session_observation:
            if counters["mismatched_events"]:
                session_observation = "mismatch"
            elif counters["matched_events"]:
                session_observation = "match"
        if session_observation not in {"", "match", "mismatch"}:
            raise ValueError("last_session_observation must be match or mismatch")
        account_result = str(last_account_context_result or "").strip().lower()
        if not account_result:
            if counters["provider_failures"]:
                account_result = "failure"
            elif counters["matched_events"]:
                account_result = "ok"
        if account_result not in {"", "ok", "failure"}:
            raise ValueError("last_account_context_result must be ok or failure")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state_value FROM telegram_bot_state "
                "WHERE state_key = 'mt5_bridge_health'"
            ).fetchone()
            previous: dict[str, Any] = {}
            if row is not None:
                try:
                    decoded = json.loads(str(row["state_value"]))
                    if isinstance(decoded, dict):
                        previous = decoded
                except (TypeError, ValueError):
                    previous = {}
            if str(previous.get("session_fingerprint") or "") != fingerprint:
                for stale_key in (
                    "last_session_match_at",
                    "last_session_mismatch_at",
                    "last_provider_failure_at",
                    "last_session_observation",
                    "last_account_context_result",
                ):
                    previous.pop(stale_key, None)
            state = {
                **previous,
                **counters,
                "required_session_configured": bool(fingerprint),
                "session_fingerprint": fingerprint,
                "last_scan_at": now,
            }
            if counters["matched_events"]:
                state["last_session_match_at"] = now
            if counters["mismatched_events"]:
                state["last_session_mismatch_at"] = now
            if counters["provider_failures"]:
                state["last_provider_failure_at"] = now
            if session_observation:
                state["last_session_observation"] = session_observation
            if account_result:
                state["last_account_context_result"] = account_result
            connection.execute(
                """
                INSERT INTO telegram_bot_state (state_key, state_value)
                VALUES ('mt5_bridge_health', ?)
                ON CONFLICT(state_key) DO UPDATE SET state_value = excluded.state_value
                """,
                (json.dumps(state, sort_keys=True, separators=(",", ":")),),
            )

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

    def start_telegram_poll_readiness(
        self,
        *,
        release_id: str,
        session_sha256: str,
        db_identity: str,
        deployment_nonce_sha256: str,
        release_manifest_sha256: str,
        runtime_config_sha256: str,
        production_config_sha256: str,
        worker_instance_id: str,
        worker_started_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Reset durable readiness for a newly started Telegram poll worker."""

        normalized_release = _required_lower_hex(
            release_id, length=40, field="release_id"
        )
        normalized_session = _required_lower_hex(
            session_sha256, length=64, field="session_sha256"
        )
        normalized_database = _required_lower_hex(
            db_identity, length=64, field="db_identity"
        )
        normalized_deployment_nonce = _required_lower_hex(
            deployment_nonce_sha256,
            length=64,
            field="deployment_nonce_sha256",
        )
        normalized_release_manifest = _required_lower_hex(
            release_manifest_sha256,
            length=64,
            field="release_manifest_sha256",
        )
        normalized_runtime_config = _required_lower_hex(
            runtime_config_sha256,
            length=64,
            field="runtime_config_sha256",
        )
        normalized_production_config = _required_lower_hex(
            production_config_sha256,
            length=64,
            field="production_config_sha256",
        )
        current_database = telegram_poll_db_identity(self.path)
        if normalized_database != current_database:
            raise ValueError("db_identity does not match the current database path")
        normalized_worker = _required_lower_hex(
            worker_instance_id, length=32, field="worker_instance_id"
        )
        started_at = _aware_utc(worker_started_at or datetime.now(timezone.utc))
        state: dict[str, Any] = {
            "schema_version": _TELEGRAM_POLL_READINESS_SCHEMA_VERSION,
            "release_id": normalized_release,
            "session_sha256": normalized_session,
            "db_identity": normalized_database,
            "deployment_nonce_sha256": normalized_deployment_nonce,
            "release_manifest_sha256": normalized_release_manifest,
            "runtime_config_sha256": normalized_runtime_config,
            "production_config_sha256": normalized_production_config,
            "worker_instance_id": normalized_worker,
            "worker_started_at": _iso(started_at),
            "last_attempt_at": None,
            "last_success_at": None,
            "last_failure_at": None,
            "last_result": "not_polled",
            "last_error_kind": None,
            "attempt_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "conflict_count": 0,
        }
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO telegram_bot_state (state_key, state_value)
                VALUES (?, ?)
                ON CONFLICT(state_key) DO UPDATE SET state_value = excluded.state_value
                """,
                (
                    _TELEGRAM_POLL_READINESS_KEY,
                    json.dumps(state, sort_keys=True, separators=(",", ":")),
                ),
            )
        return dict(state)

    def record_telegram_poll_success(
        self,
        *,
        worker_instance_id: str,
        observed_at: datetime | None = None,
    ) -> bool:
        """Record a valid getUpdates response, including an empty result."""

        return self._record_telegram_poll_result(
            worker_instance_id=worker_instance_id,
            result="success",
            error_kind=None,
            observed_at=observed_at,
        )

    def record_telegram_poll_failure(
        self,
        *,
        worker_instance_id: str,
        error_kind: str,
        observed_at: datetime | None = None,
    ) -> bool:
        """Record a failed getUpdates attempt without persisting exception text."""

        normalized_kind = str(error_kind or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{1,64}", normalized_kind):
            raise ValueError("error_kind must be a short lowercase identifier")
        return self._record_telegram_poll_result(
            worker_instance_id=worker_instance_id,
            result="failure",
            error_kind=normalized_kind,
            observed_at=observed_at,
        )

    def _record_telegram_poll_result(
        self,
        *,
        worker_instance_id: str,
        result: str,
        error_kind: str | None,
        observed_at: datetime | None,
    ) -> bool:
        normalized_worker = _required_lower_hex(
            worker_instance_id, length=32, field="worker_instance_id"
        )
        observed = _aware_utc(observed_at or datetime.now(timezone.utc))
        observed_text = _iso(observed)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state_value FROM telegram_bot_state WHERE state_key = ?",
                (_TELEGRAM_POLL_READINESS_KEY,),
            ).fetchone()
            state = _decode_telegram_poll_readiness(row)
            if (
                state is None
                or state.get("schema_version")
                != _TELEGRAM_POLL_READINESS_SCHEMA_VERSION
                or state.get("worker_instance_id") != normalized_worker
            ):
                return False
            started_at = _parse_persisted_utc(state.get("worker_started_at"))
            previous_attempt = _parse_persisted_utc(state.get("last_attempt_at"))
            if (
                started_at is None
                or observed < started_at
                or (previous_attempt is not None and observed < previous_attempt)
            ):
                return False
            state["last_attempt_at"] = observed_text
            state["last_result"] = result
            state["attempt_count"] = max(0, _safe_int(state.get("attempt_count"))) + 1
            if result == "success":
                state["last_success_at"] = observed_text
                state["last_error_kind"] = None
                state["success_count"] = (
                    max(0, _safe_int(state.get("success_count"))) + 1
                )
            else:
                state["last_failure_at"] = observed_text
                state["last_error_kind"] = error_kind
                state["failure_count"] = (
                    max(0, _safe_int(state.get("failure_count"))) + 1
                )
                if error_kind == "telegram_conflict":
                    state["conflict_count"] = (
                        max(0, _safe_int(state.get("conflict_count"))) + 1
                    )
            connection.execute(
                "UPDATE telegram_bot_state SET state_value = ? WHERE state_key = ?",
                (
                    json.dumps(state, sort_keys=True, separators=(",", ":")),
                    _TELEGRAM_POLL_READINESS_KEY,
                ),
            )
        return True

    def telegram_poll_readiness(
        self,
        *,
        expected_release_id: str,
        expected_session_sha256: str,
        expected_db_identity: str,
        expected_deployment_nonce_sha256: str,
        expected_release_manifest_sha256: str,
        expected_runtime_config_sha256: str,
        expected_production_config_sha256: str,
        not_before: datetime,
        max_age_seconds: float,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Read readiness evidence and reject stale or mismatched identities."""

        expected_release = _required_lower_hex(
            expected_release_id, length=40, field="expected_release_id"
        )
        expected_session = _required_lower_hex(
            expected_session_sha256,
            length=64,
            field="expected_session_sha256",
        )
        expected_database = _required_lower_hex(
            expected_db_identity, length=64, field="expected_db_identity"
        )
        expected_deployment_nonce = _required_lower_hex(
            expected_deployment_nonce_sha256,
            length=64,
            field="expected_deployment_nonce_sha256",
        )
        expected_release_manifest = _required_lower_hex(
            expected_release_manifest_sha256,
            length=64,
            field="expected_release_manifest_sha256",
        )
        expected_runtime_config = _required_lower_hex(
            expected_runtime_config_sha256,
            length=64,
            field="expected_runtime_config_sha256",
        )
        expected_production_config = _required_lower_hex(
            expected_production_config_sha256,
            length=64,
            field="expected_production_config_sha256",
        )
        try:
            freshness_seconds = float(max_age_seconds)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("max_age_seconds must be finite and positive") from exc
        if not math.isfinite(freshness_seconds) or freshness_seconds <= 0:
            raise ValueError("max_age_seconds must be finite and positive")
        lower_bound = _aware_utc(not_before)
        observed_now = _aware_utc(now or datetime.now(timezone.utc))
        if expected_database != telegram_poll_db_identity(self.path):
            return _telegram_poll_readiness_result(
                ready=False, reason="database_path_mismatch", evidence=None
            )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_value FROM telegram_bot_state WHERE state_key = ?",
                (_TELEGRAM_POLL_READINESS_KEY,),
            ).fetchone()
        state = _decode_telegram_poll_readiness(row)
        if state is None:
            return _telegram_poll_readiness_result(
                ready=False, reason="missing_or_invalid_evidence", evidence=None
            )
        evidence = _public_telegram_poll_evidence(state)
        if state.get("schema_version") != _TELEGRAM_POLL_READINESS_SCHEMA_VERSION:
            return _telegram_poll_readiness_result(
                ready=False, reason="unsupported_evidence_schema", evidence=evidence
            )
        if state.get("release_id") != expected_release:
            return _telegram_poll_readiness_result(
                ready=False, reason="release_mismatch", evidence=evidence
            )
        if state.get("session_sha256") != expected_session:
            return _telegram_poll_readiness_result(
                ready=False, reason="session_mismatch", evidence=evidence
            )
        if state.get("db_identity") != expected_database:
            return _telegram_poll_readiness_result(
                ready=False, reason="database_mismatch", evidence=evidence
            )
        if state.get("deployment_nonce_sha256") != expected_deployment_nonce:
            return _telegram_poll_readiness_result(
                ready=False, reason="deployment_nonce_mismatch", evidence=evidence
            )
        if state.get("release_manifest_sha256") != expected_release_manifest:
            return _telegram_poll_readiness_result(
                ready=False, reason="release_manifest_mismatch", evidence=evidence
            )
        if state.get("runtime_config_sha256") != expected_runtime_config:
            return _telegram_poll_readiness_result(
                ready=False, reason="runtime_config_mismatch", evidence=evidence
            )
        if state.get("production_config_sha256") != expected_production_config:
            return _telegram_poll_readiness_result(
                ready=False, reason="production_config_mismatch", evidence=evidence
            )
        if not _LOWER_HEX_32.fullmatch(str(state.get("worker_instance_id") or "")):
            return _telegram_poll_readiness_result(
                ready=False, reason="invalid_worker_identity", evidence=evidence
            )
        started_at = _parse_persisted_utc(state.get("worker_started_at"))
        attempted_at = _parse_persisted_utc(state.get("last_attempt_at"))
        succeeded_at = _parse_persisted_utc(state.get("last_success_at"))
        failed_at = _parse_persisted_utc(state.get("last_failure_at"))
        for field, parsed in (
            ("worker_started_at", started_at),
            ("last_attempt_at", attempted_at),
            ("last_success_at", succeeded_at),
            ("last_failure_at", failed_at),
        ):
            raw_value = state.get(field)
            if raw_value is not None and parsed is None:
                return _telegram_poll_readiness_result(
                    ready=False, reason="invalid_evidence_timestamp", evidence=evidence
                )
        if started_at is None:
            return _telegram_poll_readiness_result(
                ready=False, reason="invalid_worker_start", evidence=evidence
            )
        if started_at < lower_bound:
            return _telegram_poll_readiness_result(
                ready=False, reason="worker_started_before_window", evidence=evidence
            )
        if succeeded_at is None or attempted_at is None:
            return _telegram_poll_readiness_result(
                ready=False, reason="no_successful_poll", evidence=evidence
            )
        if succeeded_at < lower_bound:
            return _telegram_poll_readiness_result(
                ready=False, reason="success_before_window", evidence=evidence
            )
        if started_at > succeeded_at or succeeded_at > attempted_at:
            return _telegram_poll_readiness_result(
                ready=False, reason="invalid_evidence_order", evidence=evidence
            )
        if state.get("last_result") != "success":
            return _telegram_poll_readiness_result(
                ready=False, reason="latest_poll_failed", evidence=evidence
            )
        attempt_count = _safe_int(state.get("attempt_count"))
        success_count = _safe_int(state.get("success_count"))
        failure_count = _safe_int(state.get("failure_count"))
        conflict_count = _safe_int(state.get("conflict_count"))
        if conflict_count > 0:
            return _telegram_poll_readiness_result(
                ready=False,
                reason="telegram_conflict_observed",
                evidence=evidence,
            )
        if (
            attempt_count < 1
            or success_count < 1
            or failure_count < 0
            or conflict_count < 0
            or conflict_count > failure_count
            or attempt_count != success_count + failure_count
            or (failure_count > 0 and failed_at is None)
            or state.get("last_error_kind") is not None
        ):
            return _telegram_poll_readiness_result(
                ready=False, reason="invalid_evidence_counters", evidence=evidence
            )
        if failed_at is not None and failed_at > succeeded_at:
            return _telegram_poll_readiness_result(
                ready=False, reason="failure_after_success", evidence=evidence
            )
        if started_at > observed_now or attempted_at > observed_now:
            return _telegram_poll_readiness_result(
                ready=False, reason="future_evidence", evidence=evidence
            )
        if (observed_now - succeeded_at).total_seconds() > freshness_seconds:
            return _telegram_poll_readiness_result(
                ready=False, reason="stale_success", evidence=evidence
            )
        return _telegram_poll_readiness_result(
            ready=True, reason="ready", evidence=evidence
        )

    def runtime_settings(self, *, prefix: str | None = None) -> dict[str, Any]:
        query = "SELECT setting_key, value_json FROM runtime_settings"
        parameters: tuple[Any, ...] = ()
        if prefix is not None:
            query += " WHERE setting_key LIKE ?"
            parameters = (f"{prefix}%",)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return {str(row["setting_key"]): json.loads(str(row["value_json"])) for row in rows}

    def set_runtime_settings(self, values: dict[str, Any], *, updated_by: str | int) -> None:
        if not values:
            return
        now = _utc_now()
        rows = [
            (str(key), json.dumps(value, separators=(",", ":")), str(updated_by), now)
            for key, value in values.items()
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO runtime_settings (setting_key, value_json, updated_by, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                rows,
            )

    def stage_admin_action(
        self,
        *,
        token: str,
        action_type: str,
        payload: dict[str, Any],
        requested_by: str | int,
        expires_at: datetime,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO telegram_admin_actions (
                    action_token, action_type, payload_json, status,
                    requested_by, requested_at, expires_at
                ) VALUES (?, ?, ?, 'PENDING', ?, ?, ?)
                """,
                (
                    token,
                    action_type,
                    json.dumps(payload, separators=(",", ":")),
                    str(requested_by),
                    _utc_now(),
                    _iso(expires_at),
                ),
            )

    def decide_admin_action(
        self,
        *,
        token: str,
        actor_id: str | int,
        confirm: bool,
    ) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM telegram_admin_actions WHERE action_token = ?",
                (token,),
            ).fetchone()
            if row is None or str(row["requested_by"]) != str(actor_id):
                return None
            result = dict(row)
            if str(row["status"]) != "PENDING":
                return result
            expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
            if expires_at <= now:
                status = "EXPIRED"
            else:
                status = "CONFIRMED" if confirm else "CANCELLED"
            connection.execute(
                """
                UPDATE telegram_admin_actions
                SET status = ?, decided_at = ?
                WHERE action_token = ? AND status = 'PENDING'
                """,
                (status, _utc_now(), token),
            )
            result["status"] = status
            result["payload"] = json.loads(str(row["payload_json"]))
            return result

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
        file_identity: str = "",
        anchor_offset: int = 0,
        anchor_sha256: str = "",
        raw_tail_b64: str = "",
    ) -> None:
        normalized_offset = int(byte_offset)
        normalized_anchor_offset = int(anchor_offset)
        normalized_anchor_sha256 = str(anchor_sha256 or "").strip().lower()
        if normalized_offset < 0:
            raise ValueError("MT5 log cursor byte_offset must not be negative")
        if not 0 <= normalized_anchor_offset <= normalized_offset:
            raise ValueError(
                "MT5 log cursor anchor_offset must be between zero and byte_offset"
            )
        if normalized_anchor_sha256 and re.fullmatch(
            r"[0-9a-f]{64}", normalized_anchor_sha256
        ) is None:
            raise ValueError("MT5 log cursor anchor_sha256 must be a SHA-256 hex digest")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO mt5_log_cursors (
                    log_path, byte_offset, encoding, fragment, file_identity,
                    anchor_offset, anchor_sha256, raw_tail_b64, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(log_path) DO UPDATE SET
                    byte_offset = excluded.byte_offset,
                    encoding = excluded.encoding,
                    fragment = excluded.fragment,
                    file_identity = excluded.file_identity,
                    anchor_offset = excluded.anchor_offset,
                    anchor_sha256 = excluded.anchor_sha256,
                    raw_tail_b64 = excluded.raw_tail_b64,
                    updated_at = excluded.updated_at
                """,
                (
                    str(log_path),
                    normalized_offset,
                    encoding,
                    fragment,
                    str(file_identity or ""),
                    normalized_anchor_offset,
                    normalized_anchor_sha256,
                    str(raw_tail_b64 or ""),
                    _utc_now(),
                ),
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
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()


def _write_trade_execution(
    connection: sqlite3.Connection,
    record: dict[str, Any],
    *,
    upsert: bool,
) -> None:
    values = _trade_execution_values(record)
    existing = None
    if upsert:
        existing = connection.execute(
            "SELECT * FROM trade_executions WHERE setup_id = ?",
            (str(values["setup_id"]),),
        ).fetchone()
    statement = """
        INSERT INTO trade_executions (
            setup_id, signal_outbox_id, execution_mode, status, symbol, side,
            requested_entry, stop_price, target_price, volume, risk_cash,
            expected_profit_cash, valid_until, client_tag, order_ticket,
            deal_ticket, position_ticket, actual_entry, opened_at, closed_at,
            exit_price, profit_cash, close_reason, closed_by, last_error,
            strategy_id, strategy_version, direction_profile, entry_side_policy,
            execution_profile,
            magic, position_identifier, initial_volume, remaining_volume,
            initial_stop_price, current_stop_price, initial_take_profit_price,
            current_take_profit_price, initial_risk_distance,
            management_policy, management_policy_version, management_policy_json,
            account_login, account_server, account_scope, account_margin_mode,
            highest_observed_r,
            r1_reached_at, r2_reached_at, r3_reached_at,
            r1_protection_status, r2_protection_status, r3_close_status,
            last_broker_sync_at, max_holding_minutes, updated_at
        ) VALUES (
            :setup_id, :signal_outbox_id, :execution_mode, :status, :symbol, :side,
            :requested_entry, :stop_price, :target_price, :volume, :risk_cash,
            :expected_profit_cash, :valid_until, :client_tag, :order_ticket,
            :deal_ticket, :position_ticket, :actual_entry, :opened_at, :closed_at,
            :exit_price, :profit_cash, :close_reason, :closed_by, :last_error,
            :strategy_id, :strategy_version, :direction_profile, :entry_side_policy,
            :execution_profile,
            :magic, :position_identifier, :initial_volume, :remaining_volume,
            :initial_stop_price, :current_stop_price, :initial_take_profit_price,
            :current_take_profit_price, :initial_risk_distance,
            :management_policy, :management_policy_version, :management_policy_json,
            :account_login, :account_server, :account_scope, :account_margin_mode,
            :highest_observed_r,
            :r1_reached_at, :r2_reached_at, :r3_reached_at,
            :r1_protection_status, :r2_protection_status, :r3_close_status,
            :last_broker_sync_at, :max_holding_minutes, :updated_at
        )
    """
    if existing is None:
        connection.execute(statement, values)
        return

    _validate_trade_execution_identity(existing, values)
    resolved_status, accepted = _resolve_trade_execution_status(
        str(existing["status"]), str(values["status"])
    )
    update_values: dict[str, Any] = {
        "setup_id": str(values["setup_id"]),
        "status": resolved_status,
        "volume": existing["volume"],
        "risk_cash": existing["risk_cash"],
        "expected_profit_cash": existing["expected_profit_cash"],
        "order_ticket": existing["order_ticket"],
        "deal_ticket": existing["deal_ticket"],
        "position_ticket": existing["position_ticket"],
        "actual_entry": existing["actual_entry"],
        "opened_at": existing["opened_at"],
        "closed_at": existing["closed_at"],
        "exit_price": existing["exit_price"],
        "profit_cash": existing["profit_cash"],
        "close_reason": existing["close_reason"],
        "closed_by": existing["closed_by"],
        "last_error": existing["last_error"],
        "updated_at": existing["updated_at"],
    }
    existing_rank = _EXECUTION_STATUS_RANK.get(str(existing["status"]).upper(), -1)
    if accepted:
        closed_replay = (
            str(existing["status"]).upper() == "CLOSED"
            and str(values["status"]).upper() == "CLOSED"
        )
        update_values["order_ticket"] = existing["order_ticket"] or values["order_ticket"]
        update_values["deal_ticket"] = existing["deal_ticket"] or values["deal_ticket"]
        if existing["position_identifier"] is None:
            update_values["position_ticket"] = (
                existing["position_ticket"] or values["position_ticket"]
            )
            update_values["actual_entry"] = (
                existing["actual_entry"]
                if existing["actual_entry"] is not None
                else values["actual_entry"]
            )
            update_values["opened_at"] = existing["opened_at"] or values["opened_at"]
        if (
            existing["initial_volume"] is None
            and existing_rank < _EXECUTION_STATUS_RANK["FILLED"]
        ):
            update_values["volume"] = values["volume"]
            update_values["risk_cash"] = values["risk_cash"]
            update_values["expected_profit_cash"] = values["expected_profit_cash"]
        if not closed_replay:
            update_values["last_error"] = values["last_error"]
            update_values["updated_at"] = values["updated_at"]
        for field in ("close_reason", "closed_by"):
            if existing[field] is None and values[field] is not None:
                update_values[field] = values[field]
        if str(values["status"]).upper() == "CLOSED":
            for field in (
                "closed_at",
                "exit_price",
                "profit_cash",
                "close_reason",
                "closed_by",
            ):
                if values[field] is not None and (
                    not closed_replay or existing[field] is None
                ):
                    update_values[field] = values[field]

    connection.execute(
        """
        UPDATE trade_executions
        SET status = :status, volume = :volume, risk_cash = :risk_cash,
            expected_profit_cash = :expected_profit_cash,
            order_ticket = :order_ticket, deal_ticket = :deal_ticket,
            position_ticket = :position_ticket, actual_entry = :actual_entry,
            opened_at = :opened_at, closed_at = :closed_at,
            exit_price = :exit_price, profit_cash = :profit_cash,
            close_reason = :close_reason, closed_by = :closed_by,
            last_error = :last_error, updated_at = :updated_at
        WHERE setup_id = :setup_id
        """,
        update_values,
    )


def _prepare_open_execution_intent(
    record: dict[str, Any],
    *,
    action_idempotency_key: str,
    action_payload: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    values = _trade_execution_values(record)
    _validate_open_execution_intent(values)
    payload = dict(action_payload or {})
    required_payload = {
        "signal_outbox_id": int(values["signal_outbox_id"]),
        "client_tag": str(values["client_tag"]),
        "symbol": str(values["symbol"]),
        "side": str(values["side"]).lower(),
    }
    for key, expected in required_payload.items():
        if key in payload and payload[key] != expected:
            raise ValueError(f"OPEN action payload {key} does not match execution intent")
        payload[key] = expected
    normalized_key = str(action_idempotency_key or "").strip()
    if not normalized_key:
        raise ValueError("OPEN action idempotency key must not be empty")
    immutable_action = {
        "idempotency_key": normalized_key,
        "setup_id": str(values["setup_id"]),
        "position_ticket": None,
        "position_identifier": None,
        "action_type": "OPEN",
        "payload_json": json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ),
        "management_policy": str(values["management_policy"]),
        "account_login": str(values["account_login"]),
        "account_server": str(values["account_server"]),
        "account_scope": str(values["account_scope"]).lower(),
    }
    return values, immutable_action


def _create_or_replay_open_intent(
    connection: sqlite3.Connection,
    values: dict[str, Any],
    immutable_action: dict[str, Any],
) -> tuple[sqlite3.Row, sqlite3.Row, bool]:
    execution_row = connection.execute(
        "SELECT * FROM trade_executions WHERE setup_id = ?",
        (str(values["setup_id"]),),
    ).fetchone()
    action_row = connection.execute(
        "SELECT * FROM position_actions WHERE idempotency_key = ?",
        (str(immutable_action["idempotency_key"]),),
    ).fetchone()
    if (execution_row is None) != (action_row is None):
        raise RuntimeError(
            "OPEN execution/action atomicity invariant is broken; refusing partial replay"
        )
    if execution_row is not None and action_row is not None:
        _assert_open_execution_replay(execution_row, values)
        _assert_position_action_replay(action_row, immutable_action)
        return execution_row, action_row, False

    _write_trade_execution(connection, values, upsert=False)
    action_row = _insert_position_action(
        connection, immutable_action, now=str(values["updated_at"])
    )
    execution_row = connection.execute(
        "SELECT * FROM trade_executions WHERE setup_id = ?",
        (str(values["setup_id"]),),
    ).fetchone()
    assert execution_row is not None
    return execution_row, action_row, True


def _validate_trade_execution_identity(
    existing: sqlite3.Row,
    requested: dict[str, Any],
) -> None:
    for field in ("signal_outbox_id", "execution_mode", "symbol", "client_tag"):
        if existing[field] != requested[field]:
            raise ValueError(f"Trade execution identity mismatch for immutable {field}")
    if str(existing["side"]).strip().lower() != str(requested["side"]).strip().lower():
        raise ValueError("Trade execution identity mismatch for immutable side")
    for field in ("requested_entry", "stop_price", "target_price"):
        if not math.isclose(
            float(existing[field]), float(requested[field]), rel_tol=1e-12, abs_tol=1e-9
        ):
            raise ValueError(f"Trade execution identity mismatch for immutable {field}")


def _resolve_trade_execution_status(current: str, requested: str) -> tuple[str, bool]:
    """Return a monotonic lifecycle status and whether the write was accepted."""

    current_status = str(current or "").strip().upper()
    requested_status = str(requested or "").strip().upper()
    if not requested_status:
        raise ValueError("Trade execution status must not be empty")
    if current_status == requested_status:
        return current_status, True
    if current_status == "CLOSED" or current_status in _TERMINAL_OPEN_EXECUTION_STATUSES:
        return current_status, False
    if requested_status == "CLOSED":
        current_rank = _EXECUTION_STATUS_RANK.get(current_status, -1)
        if current_rank >= _EXECUTION_STATUS_RANK["FILLED"]:
            return requested_status, True
        return current_status, False
    if requested_status == "CANCELLED":
        if current_status in {"PLANNING", "OPEN_PENDING"}:
            return requested_status, True
        return current_status, False
    if requested_status in _TERMINAL_OPEN_EXECUTION_STATUSES:
        if current_status in {"PLANNING", "OPEN_PENDING", "OPEN_SUBMITTED"}:
            return requested_status, True
        return current_status, False
    current_rank = _EXECUTION_STATUS_RANK.get(current_status)
    requested_rank = _EXECUTION_STATUS_RANK.get(requested_status)
    if current_rank is None or requested_rank is None or requested_rank < current_rank:
        return current_status, False
    return requested_status, True


def _insert_position_action(
    connection: sqlite3.Connection,
    immutable: dict[str, Any],
    *,
    now: str,
) -> sqlite3.Row:
    cursor = connection.execute(
        """
        INSERT INTO position_actions (
            idempotency_key, setup_id, position_ticket, position_identifier, action_type,
            payload_json, management_policy, account_login,
            account_server, account_scope, created_at, updated_at
        ) VALUES (
            :idempotency_key, :setup_id, :position_ticket, :position_identifier, :action_type,
            :payload_json, :management_policy, :account_login,
            :account_server, :account_scope, :created_at, :updated_at
        )
        """,
        {**immutable, "created_at": now, "updated_at": now},
    )
    row = connection.execute(
        "SELECT * FROM position_actions WHERE id = ?", (int(cursor.lastrowid),)
    ).fetchone()
    assert row is not None
    return row


def _trade_execution_values(record: dict[str, Any]) -> dict[str, Any]:
    return {
        **record,
        "valid_until": _optional_timestamp(record.get("valid_until")),
        "opened_at": _optional_timestamp(record.get("opened_at")),
        "closed_at": _optional_timestamp(record.get("closed_at")),
        "strategy_id": str(record.get("strategy_id") or ""),
        "strategy_version": str(record.get("strategy_version") or ""),
        "direction_profile": str(record.get("direction_profile") or ""),
        "entry_side_policy": str(
            record.get("entry_side_policy") or "LEGACY_UNSPECIFIED"
        ),
        "execution_profile": str(record.get("execution_profile") or ""),
        "magic": _optional_int(record.get("magic")),
        "position_identifier": _optional_int(record.get("position_identifier")),
        "initial_volume": _optional_float(record.get("initial_volume")),
        "remaining_volume": _optional_float(record.get("remaining_volume")),
        "initial_stop_price": _optional_float(record.get("initial_stop_price")),
        "current_stop_price": _optional_float(record.get("current_stop_price")),
        "initial_take_profit_price": _optional_float(
            record.get("initial_take_profit_price")
        ),
        "current_take_profit_price": _optional_float(
            record.get("current_take_profit_price")
        ),
        "initial_risk_distance": _optional_float(record.get("initial_risk_distance")),
        "management_policy": str(record.get("management_policy") or ""),
        "management_policy_version": str(record.get("management_policy_version") or ""),
        "management_policy_json": _json_text(record.get("management_policy_json")),
        "account_login": str(record.get("account_login") or ""),
        "account_server": str(record.get("account_server") or ""),
        "account_scope": str(record.get("account_scope") or ""),
        "account_margin_mode": _optional_account_margin_mode(
            record.get("account_margin_mode")
        ),
        "highest_observed_r": _optional_float(record.get("highest_observed_r")),
        "r1_reached_at": _optional_timestamp(record.get("r1_reached_at")),
        "r2_reached_at": _optional_timestamp(record.get("r2_reached_at")),
        "r3_reached_at": _optional_timestamp(record.get("r3_reached_at")),
        "r1_protection_status": _optional_text(record.get("r1_protection_status")),
        "r2_protection_status": _optional_text(record.get("r2_protection_status")),
        "r3_close_status": _optional_text(record.get("r3_close_status")),
        "last_broker_sync_at": _optional_timestamp(record.get("last_broker_sync_at")),
        "max_holding_minutes": _optional_positive_int(
            record.get("max_holding_minutes"), "max_holding_minutes"
        ),
        "updated_at": _utc_now(),
    }


_OPEN_INTENT_IMMUTABLE_FIELDS = (
    "setup_id",
    "signal_outbox_id",
    "execution_mode",
    "symbol",
    "side",
    "requested_entry",
    "stop_price",
    "target_price",
    "volume",
    "risk_cash",
    "expected_profit_cash",
    "valid_until",
    "client_tag",
    "strategy_id",
    "strategy_version",
    "direction_profile",
    "entry_side_policy",
    "execution_profile",
    "magic",
    "management_policy",
    "management_policy_version",
    "management_policy_json",
    "account_login",
    "account_server",
    "account_scope",
    "account_margin_mode",
    "max_holding_minutes",
)


def _validate_open_execution_intent(values: dict[str, Any]) -> None:
    if str(values.get("status") or "").upper() != "OPEN_PENDING":
        raise ValueError("Atomic OPEN execution intent must start in OPEN_PENDING")
    for field in (
        "position_ticket",
        "position_identifier",
        "actual_entry",
        "opened_at",
        "initial_volume",
        "remaining_volume",
        "initial_stop_price",
        "current_stop_price",
        "initial_take_profit_price",
        "current_take_profit_price",
        "initial_risk_distance",
    ):
        if values.get(field) is not None:
            raise ValueError(f"OPEN_PENDING execution must not pre-populate {field}")
    for field in (
        "setup_id",
        "client_tag",
        "strategy_id",
        "strategy_version",
        "direction_profile",
        "entry_side_policy",
        "execution_profile",
        "management_policy",
        "management_policy_version",
        "account_login",
        "account_server",
        "account_scope",
    ):
        if not str(values.get(field) or "").strip():
            raise ValueError(f"OPEN_PENDING execution requires immutable {field}")
    if _optional_positive_int(values.get("magic"), "magic") is None:
        raise ValueError("OPEN_PENDING execution requires magic")
    if values.get("account_margin_mode") is None:
        raise ValueError("OPEN_PENDING execution requires account_margin_mode")
    if int(values.get("signal_outbox_id") or 0) <= 0:
        raise ValueError("OPEN_PENDING execution requires signal_outbox_id")
    volume = _required_finite_float(values.get("volume"), "volume")
    if volume <= 0:
        raise ValueError("OPEN_PENDING execution volume must be positive")
    entry = _required_finite_float(values.get("requested_entry"), "requested_entry")
    stop = _required_finite_float(values.get("stop_price"), "stop_price")
    side = str(values.get("side") or "").strip().lower()
    if side == "buy" and not 0 < stop < entry:
        raise ValueError("OPEN_PENDING BUY stop must be below entry")
    if side == "sell" and not stop > entry > 0:
        raise ValueError("OPEN_PENDING SELL stop must be above entry")
    if side not in {"buy", "sell"}:
        raise ValueError("OPEN_PENDING execution side must be BUY or SELL")
    execution_mode = str(values.get("execution_mode") or "").strip().lower()
    account_scope = str(values.get("account_scope") or "").strip().lower()
    if execution_mode not in {"demo", "live"} or account_scope != execution_mode:
        raise ValueError("OPEN_PENDING execution/account scope must be matching demo or live")


def _assert_open_execution_replay(
    existing: sqlite3.Row,
    expected: dict[str, Any],
) -> None:
    for field in _OPEN_INTENT_IMMUTABLE_FIELDS:
        if existing[field] != expected[field]:
            raise ValueError(f"OPEN execution replay mismatch for immutable {field}")


def _assert_position_action_replay(
    existing: sqlite3.Row,
    expected: dict[str, Any],
) -> None:
    for field, value in expected.items():
        if (
            field == "position_ticket"
            and existing["position_identifier"] is not None
            and expected.get("position_identifier") is not None
            and int(existing["position_identifier"])
            == int(expected["position_identifier"])
        ):
            continue
        if (
            str(expected.get("action_type")) == "OPEN"
            and field in {"position_ticket", "position_identifier"}
            and value is None
            and str(existing["status"]) == "CONFIRMED"
        ):
            continue
        if existing[field] != value:
            raise ValueError(f"Position action replay mismatch for immutable {field}")


def _confirmed_position_values(**raw: Any) -> dict[str, Any]:
    position_ticket = _optional_positive_int(raw.get("position_ticket"), "position_ticket")
    position_identifier = _optional_positive_int(
        raw.get("position_identifier"), "position_identifier"
    )
    assert position_ticket is not None and position_identifier is not None
    actual_entry = _required_finite_float(raw.get("actual_entry"), "actual_entry")
    initial_volume = _required_finite_float(raw.get("initial_volume"), "initial_volume")
    initial_stop = _required_finite_float(
        raw.get("initial_stop_price"), "initial_stop_price"
    )
    current_stop = _required_finite_float(
        raw.get("current_stop_price"), "current_stop_price"
    )
    if actual_entry <= 0 or initial_volume <= 0 or initial_stop <= 0 or current_stop <= 0:
        raise ValueError("Confirmed position prices and volume must be positive")
    side = str(raw.get("side") or "").strip().lower()
    if side == "buy" and initial_stop >= actual_entry:
        raise ValueError("Confirmed BUY initial stop must be below actual entry")
    if side == "sell" and initial_stop <= actual_entry:
        raise ValueError("Confirmed SELL initial stop must be above actual entry")
    if side not in {"buy", "sell"}:
        raise ValueError("Confirmed position side must be BUY or SELL")
    if not math.isclose(initial_stop, current_stop, rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError("Initial confirmation requires current stop to equal initial stop")
    initial_take_profit = _optional_float(raw.get("initial_take_profit_price"))
    current_take_profit = _optional_float(raw.get("current_take_profit_price"))
    if (initial_take_profit is None) != (current_take_profit is None):
        raise ValueError("Initial and current take-profit must be supplied together")
    if initial_take_profit is not None:
        if initial_take_profit <= 0 or current_take_profit is None:
            raise ValueError("Confirmed take-profit prices must be positive")
        if side == "buy" and initial_take_profit <= actual_entry:
            raise ValueError("Confirmed BUY take-profit must be above actual entry")
        if side == "sell" and initial_take_profit >= actual_entry:
            raise ValueError("Confirmed SELL take-profit must be below actual entry")
        if not math.isclose(
            initial_take_profit,
            current_take_profit,
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "Initial confirmation requires current take-profit to equal initial take-profit"
            )
    opened_at = _optional_timestamp(raw.get("opened_at"))
    if opened_at is None:
        raise ValueError("Confirmed position requires opened_at")
    last_sync = _optional_timestamp(raw.get("last_broker_sync_at")) or _utc_now()
    normalized = {
        "position_ticket": position_ticket,
        "position_identifier": position_identifier,
        "symbol": str(raw.get("symbol") or "").strip(),
        "side": side,
        "comment": str(raw.get("comment") or ""),
        "actual_entry": actual_entry,
        "opened_at": opened_at,
        "initial_volume": initial_volume,
        "initial_stop_price": initial_stop,
        "current_stop_price": current_stop,
        "initial_take_profit_price": initial_take_profit,
        "current_take_profit_price": current_take_profit,
        "initial_risk_distance": abs(actual_entry - initial_stop),
        "magic": _optional_positive_int(raw.get("magic"), "magic"),
        "strategy_id": str(raw.get("strategy_id") or "").strip(),
        "strategy_version": str(raw.get("strategy_version") or "").strip(),
        "direction_profile": str(raw.get("direction_profile") or "").strip(),
        "entry_side_policy": str(
            raw.get("entry_side_policy") or "LEGACY_UNSPECIFIED"
        ).strip(),
        "execution_profile": str(raw.get("execution_profile") or "").strip(),
        "management_policy": str(raw.get("management_policy") or "").strip(),
        "management_policy_version": str(
            raw.get("management_policy_version") or ""
        ).strip(),
        "management_policy_json": _json_text(raw.get("management_policy_json")),
        "account_login": str(raw.get("account_login") or "").strip(),
        "account_server": str(raw.get("account_server") or "").strip(),
        "account_scope": str(raw.get("account_scope") or "").strip().lower(),
        "account_margin_mode": _optional_account_margin_mode(
            raw.get("account_margin_mode")
        ),
        "last_broker_sync_at": last_sync,
    }
    for field in (
        "symbol",
        "strategy_id",
        "strategy_version",
        "direction_profile",
        "entry_side_policy",
        "execution_profile",
        "management_policy",
        "management_policy_version",
        "account_login",
        "account_server",
        "account_margin_mode",
        "account_scope",
    ):
        if not normalized[field]:
            raise ValueError(f"Confirmed position requires {field}")
    if normalized["account_scope"] not in {"demo", "live"}:
        raise ValueError("Confirmed position account_scope must be demo or live")
    if normalized["magic"] is None:
        raise ValueError("Confirmed position requires magic")
    return normalized


def _validate_position_confirmation_context(
    execution: sqlite3.Row,
    action: sqlite3.Row,
    confirmed: dict[str, Any],
) -> None:
    if str(action["setup_id"] or "") != str(execution["setup_id"]):
        raise RuntimeError("Position action belongs to a different execution")
    if str(execution["symbol"]) != confirmed["symbol"]:
        raise ValueError("Broker position symbol does not match execution")
    if str(execution["side"]).strip().lower() != confirmed["side"]:
        raise ValueError("Broker position side does not match execution")
    client_tag = str(execution["client_tag"] or "")
    if not client_tag or client_tag not in confirmed["comment"]:
        raise ValueError("Broker position comment does not contain the execution client tag")
    for field in (
        "magic",
        "strategy_id",
        "strategy_version",
        "direction_profile",
        "entry_side_policy",
        "execution_profile",
        "management_policy",
        "management_policy_version",
        "management_policy_json",
        "account_login",
        "account_server",
        "account_margin_mode",
    ):
        if execution[field] != confirmed[field]:
            raise ValueError(f"Broker confirmation mismatch for immutable {field}")
    if str(execution["account_scope"]).strip().lower() != confirmed["account_scope"]:
        raise ValueError("Broker confirmation mismatch for immutable account_scope")
    for field in ("management_policy", "account_login", "account_server"):
        if str(action[field]) != confirmed[field]:
            raise ValueError(f"Position action mismatch for immutable {field}")
    if str(action["account_scope"]).strip().lower() != confirmed["account_scope"]:
        raise ValueError("Position action mismatch for immutable account_scope")
    target_identifier = action["position_identifier"]
    target_ticket = action["position_ticket"]
    if target_identifier is not None:
        if int(target_identifier) != int(confirmed["position_identifier"]):
            raise ValueError("Position action targets a different stable identifier")
    elif target_ticket is not None and int(target_ticket) != int(confirmed["position_ticket"]):
        raise ValueError("Position action targets a different position ticket")
    broker_position_ticket = action["broker_position_ticket"]
    if (
        target_identifier is None
        and broker_position_ticket is not None
        and int(broker_position_ticket) != int(confirmed["position_ticket"])
    ):
        raise ValueError("Position action broker ticket does not match confirmation")


def _validate_open_action_confirmation_payload(
    execution: sqlite3.Row,
    action: sqlite3.Row,
) -> None:
    try:
        payload = json.loads(str(action["payload_json"] or "{}"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("OPEN action payload is not valid JSON") from exc
    expected = {
        "signal_outbox_id": int(execution["signal_outbox_id"]),
        "client_tag": str(execution["client_tag"]),
        "symbol": str(execution["symbol"]),
        "side": str(execution["side"]).strip().lower(),
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ValueError(
                f"OPEN action payload {field} does not match confirmed execution"
            )


def _confirm_position_action_fences(
    connection: sqlite3.Connection,
    actions: tuple[sqlite3.Row, ...],
    confirmed: dict[str, Any],
    *,
    confirmed_at: str,
) -> None:
    unique_actions = {int(action["id"]): action for action in actions}
    for action in unique_actions.values():
        status = str(action["status"] or "").strip().upper()
        if status == "CONFIRMED":
            if action["position_identifier"] is None or int(
                action["position_identifier"]
            ) != int(confirmed["position_identifier"]):
                raise ValueError(
                    "Confirmed action stable identifier does not match position"
                )
            continue
        if status not in {"SUBMITTED", "UNKNOWN"}:
            raise RuntimeError(
                f"Position action fence cannot confirm from status {status!r}"
            )
        cursor = connection.execute(
            """
            UPDATE position_actions
            SET status = 'CONFIRMED',
                position_ticket = COALESCE(position_ticket, ?),
                position_identifier = COALESCE(position_identifier, ?),
                broker_position_ticket = COALESCE(broker_position_ticket, ?),
                confirmed_at = COALESCE(confirmed_at, ?), last_error = NULL,
                lease_owner = NULL, lease_acquired_at = NULL,
                lease_expires_at = NULL, projected_at = NULL,
                projection_lease_owner = NULL,
                projection_lease_acquired_at = NULL,
                projection_lease_expires_at = NULL, updated_at = ?
            WHERE id = ? AND status IN ('SUBMITTED', 'UNKNOWN')
            """,
            (
                confirmed["position_ticket"],
                confirmed["position_identifier"],
                confirmed["position_ticket"],
                confirmed_at,
                confirmed_at,
                int(action["id"]),
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Concurrent action-fence confirmation lost its guard")


def _assert_confirmed_position_replay(
    existing: sqlite3.Row,
    confirmed: dict[str, Any],
) -> None:
    exact_fields = (
        "position_identifier",
        "opened_at",
        "magic",
        "strategy_id",
        "strategy_version",
        "direction_profile",
        "entry_side_policy",
        "execution_profile",
        "management_policy",
        "management_policy_version",
        "management_policy_json",
        "account_login",
        "account_server",
        "account_margin_mode",
    )
    for field in exact_fields:
        if existing[field] != confirmed[field]:
            raise ValueError(f"Confirmed position replay mismatch for immutable {field}")
    if str(existing["account_scope"]).strip().lower() != confirmed["account_scope"]:
        raise ValueError("Confirmed position replay mismatch for immutable account_scope")
    for field in (
        "actual_entry",
        "initial_volume",
        "initial_stop_price",
        "initial_risk_distance",
    ):
        if not math.isclose(
            float(existing[field]), float(confirmed[field]), rel_tol=1e-12, abs_tol=1e-9
        ):
            raise ValueError(f"Confirmed position replay mismatch for immutable {field}")
    expected_take_profit = confirmed["initial_take_profit_price"]
    existing_take_profit = existing["initial_take_profit_price"]
    if (expected_take_profit is None) != (existing_take_profit is None):
        raise ValueError(
            "Confirmed position replay mismatch for immutable initial_take_profit_price"
        )
    if expected_take_profit is not None and not math.isclose(
        float(existing_take_profit),
        float(expected_take_profit),
        rel_tol=1e-12,
        abs_tol=1e-9,
    ):
        raise ValueError(
            "Confirmed position replay mismatch for immutable initial_take_profit_price"
        )


def _assert_unprotected_position_binding_replay(
    existing: sqlite3.Row,
    confirmed: dict[str, Any],
) -> None:
    if int(existing["position_identifier"] or 0) != int(
        confirmed["position_identifier"]
    ):
        raise ValueError("Unprotected binding stable identifier changed at confirmation")
    if str(existing["opened_at"] or "") != str(confirmed["opened_at"]):
        raise ValueError("Unprotected binding opened_at changed at confirmation")
    for field in ("actual_entry", "initial_volume"):
        stored = _optional_float(existing[field])
        if stored is None or not math.isclose(
            stored,
            float(confirmed[field]),
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            raise ValueError(
                f"Unprotected binding immutable {field} changed at confirmation"
            )


def _position_binding_values(**raw: Any) -> dict[str, Any]:
    position_ticket = _optional_positive_int(raw.get("position_ticket"), "position_ticket")
    position_identifier = _optional_positive_int(
        raw.get("position_identifier"), "position_identifier"
    )
    magic = _optional_positive_int(raw.get("magic"), "magic")
    assert position_ticket is not None and position_identifier is not None and magic is not None
    remaining_volume = _required_finite_float(
        raw.get("remaining_volume"), "remaining_volume"
    )
    current_stop_price = _required_finite_float(
        raw.get("current_stop_price"), "current_stop_price"
    )
    current_take_profit_price = _optional_float(raw.get("current_take_profit_price"))
    if remaining_volume <= 0:
        raise ValueError("Open broker position remaining_volume must be positive")
    if current_stop_price < 0:
        raise ValueError("current_stop_price must not be negative")
    if current_take_profit_price is not None and current_take_profit_price < 0:
        raise ValueError("current_take_profit_price must not be negative")
    side = str(raw.get("side") or "").strip().lower()
    account_scope = str(raw.get("account_scope") or "").strip().lower()
    normalized = {
        "position_ticket": position_ticket,
        "position_identifier": position_identifier,
        "symbol": str(raw.get("symbol") or "").strip(),
        "side": side,
        "comment": str(raw.get("comment") or ""),
        "remaining_volume": remaining_volume,
        "current_stop_price": current_stop_price,
        "current_take_profit_price": current_take_profit_price,
        "magic": magic,
        "account_login": str(raw.get("account_login") or "").strip(),
        "account_server": str(raw.get("account_server") or "").strip(),
        "account_scope": account_scope,
        "last_broker_sync_at": _optional_timestamp(raw.get("last_broker_sync_at"))
        or _utc_now(),
    }
    if side not in {"buy", "sell"}:
        raise ValueError("Broker position side must be BUY or SELL")
    if account_scope not in {"demo", "live"}:
        raise ValueError("Broker position account_scope must be demo or live")
    for field in ("symbol", "account_login", "account_server"):
        if not normalized[field]:
            raise ValueError(f"Broker position requires {field}")
    return normalized


def _validate_position_binding_context(
    execution: sqlite3.Row,
    observed: dict[str, Any],
) -> None:
    if execution["position_identifier"] is None:
        raise RuntimeError("Execution has no frozen stable position identifier")
    if int(execution["position_identifier"]) != int(observed["position_identifier"]):
        raise ValueError("Broker position stable identifier does not match execution")
    if str(execution["symbol"]) != observed["symbol"]:
        raise ValueError("Broker position symbol does not match execution")
    if str(execution["side"]).strip().lower() != observed["side"]:
        raise ValueError("Broker position side does not match execution")
    if int(execution["magic"] or 0) != int(observed["magic"]):
        raise ValueError("Broker position magic does not match execution")
    client_tag = str(execution["client_tag"] or "")
    if not client_tag or client_tag not in observed["comment"]:
        raise ValueError("Broker position comment does not contain the execution client tag")
    for field in ("account_login", "account_server"):
        if str(execution[field]) != observed[field]:
            raise ValueError(f"Broker position {field} does not match execution")
    if str(execution["account_scope"]).strip().lower() != observed["account_scope"]:
        raise ValueError("Broker position account_scope does not match execution")
    initial_volume = _optional_float(execution["initial_volume"])
    current_volume = _optional_float(execution["remaining_volume"])
    if initial_volume is None or initial_volume <= 0:
        raise RuntimeError("Execution has no frozen initial volume")
    if observed["remaining_volume"] > initial_volume + 1e-9:
        raise ValueError("Broker remaining volume exceeds frozen initial volume")
    if current_volume is not None and observed["remaining_volume"] > current_volume + 1e-9:
        raise ValueError("Broker remaining volume must not increase")
    current_take_profit = observed["current_take_profit_price"]
    actual_entry = _optional_float(execution["actual_entry"])
    if current_take_profit not in {None, 0}:
        if actual_entry is None or actual_entry <= 0:
            raise RuntimeError("Execution has no frozen actual entry")
        side = str(execution["side"]).strip().lower()
        if side == "buy" and current_take_profit <= actual_entry:
            raise ValueError("Broker BUY take-profit must be above actual entry")
        if side == "sell" and current_take_profit >= actual_entry:
            raise ValueError("Broker SELL take-profit must be below actual entry")


def _validate_execution_take_profit(
    execution: sqlite3.Row,
    current_take_profit: float | None,
) -> None:
    if current_take_profit in {None, 0}:
        return
    actual_entry = _optional_float(execution["actual_entry"])
    if actual_entry is None or actual_entry <= 0:
        raise RuntimeError("Execution has no frozen actual entry")
    side = str(execution["side"]).strip().lower()
    if side == "buy" and current_take_profit <= actual_entry:
        raise ValueError("Broker BUY take-profit must be above actual entry")
    if side == "sell" and current_take_profit >= actual_entry:
        raise ValueError("Broker SELL take-profit must be below actual entry")


_MT5_SETUP_STATE_RANK = {
    SetupState.SCANNING: 0,
    SetupState.LEVEL_APPROACH: 5,
    SetupState.BREAKOUT_DETECTED: 10,
    SetupState.WAITING_RETEST: 15,
    SetupState.RETEST_VALID: 20,
    SetupState.WAITING_M5_TRIGGER: 25,
    SetupState.EARLY_CANDIDATE: 30,
    SetupState.CONFIRMED_A_PLUS: 40,
    SetupState.TELEGRAM_SENT: 45,
    SetupState.ACTIVE_SIGNAL: 50,
    SetupState.EXPIRED: 80,
    SetupState.CANCELLED: 80,
    SetupState.MANUALLY_ENTERED: 80,
    SetupState.MISSED: 80,
    SetupState.CLOSED: 100,
}
_MT5_TERMINAL_SETUP_STATES = frozenset(
    {
        SetupState.EXPIRED,
        SetupState.CANCELLED,
        SetupState.MANUALLY_ENTERED,
        SetupState.MISSED,
        SetupState.CLOSED,
    }
)


def _monotonic_mt5_setup_state(
    current: SetupState,
    incoming: SetupState,
) -> SetupState:
    if current is SetupState.CLOSED or current == incoming:
        return current
    if incoming is SetupState.CLOSED:
        return incoming
    if current in _MT5_TERMINAL_SETUP_STATES:
        return current
    if incoming in _MT5_TERMINAL_SETUP_STATES:
        return incoming
    return (
        incoming
        if _MT5_SETUP_STATE_RANK[incoming] > _MT5_SETUP_STATE_RANK[current]
        else current
    )


def _validate_mt5_setup_identity(
    existing: sqlite3.Row,
    record: SetupRecord,
) -> None:
    if str(existing["symbol"]) != str(record.symbol):
        raise Mt5SetupIdentityError("MT5 setup replay changes symbol")
    if str(existing["side"]).upper() != str(record.side).upper():
        raise Mt5SetupIdentityError("MT5 setup replay changes side")
    if not math.isclose(
        float(existing["level"]), float(record.level), rel_tol=1e-12, abs_tol=1e-9
    ):
        raise Mt5SetupIdentityError("MT5 setup replay changes level")
    existing_breakout = datetime.fromisoformat(
        str(existing["breakout_at"]).replace("Z", "+00:00")
    )
    incoming_breakout = record.breakout_at
    if incoming_breakout.tzinfo is None:
        incoming_breakout = incoming_breakout.replace(tzinfo=timezone.utc)
    if existing_breakout.tzinfo is None:
        existing_breakout = existing_breakout.replace(tzinfo=timezone.utc)
    if existing_breakout.astimezone(timezone.utc) != incoming_breakout.astimezone(
        timezone.utc
    ):
        raise Mt5SetupIdentityError("MT5 setup replay changes breakout_at")


def _normalize_management_milestone(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    normalized = str(value).strip().upper()
    if normalized not in {*_MILESTONE_COLUMNS, "MODEL"}:
        raise ValueError("Management milestone must be R1, R2, R3, MODEL, or None")
    return normalized


def _normalize_projection_statuses(
    values: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(str(value or "").strip().upper() for value in values)
    )
    allowed = {"CONFIRMED", "FAILED", "UNKNOWN"}
    if not normalized or any(value not in allowed for value in normalized):
        raise ValueError(
            "Projection statuses must be a non-empty subset of CONFIRMED, FAILED, UNKNOWN"
        )
    return normalized


def _normalize_reached_milestones(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        milestone = _normalize_management_milestone(value)
        if milestone not in _MILESTONE_COLUMNS:
            raise ValueError("Only R1, R2, and R3 can be latched as reached milestones")
        if milestone not in normalized:
            normalized.append(milestone)
    return tuple(normalized)


def _validate_manageable_execution(
    execution: sqlite3.Row,
    *,
    action_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    status = str(execution["status"])
    normalized_type = str(action_type).upper()
    unprotected_action_allowed = status == "UNPROTECTED" and (
        normalized_type == "CLOSE_FULL"
        or (
            normalized_type == "SET_INITIAL_PROTECTION"
            and (payload or {}).get("repair_filled") is True
        )
    )
    if status != "FILLED" and not unprotected_action_allowed:
        raise RuntimeError(
            "Management action requires FILLED execution; UNPROTECTED permits "
            "only full close or an explicit post-fill protection repair, got "
            f"{execution['status']!r}/{normalized_type!r}"
        )
    if _optional_positive_int(execution["position_identifier"], "position_identifier") is None:
        raise RuntimeError("Management action requires stable position identifier")
    if _optional_positive_int(execution["magic"], "magic") is None:
        raise RuntimeError("Management action requires frozen magic")
    for field in (
        "client_tag",
        "management_policy",
        "account_login",
        "account_server",
        "account_scope",
    ):
        if not str(execution[field] or "").strip():
            raise RuntimeError(f"Management action requires frozen {field}")


def _validate_filled_protection_repair_lineage(
    connection: sqlite3.Connection,
    execution: sqlite3.Row,
) -> None:
    """Prove UNPROTECTED is a post-fill degradation, not an unfilled OPEN."""

    for field in (
        "actual_entry",
        "initial_volume",
        "initial_stop_price",
        "initial_take_profit_price",
        "initial_risk_distance",
    ):
        value = _optional_float(execution[field])
        if value is None or value <= 0:
            raise RuntimeError(
                "Post-fill protection repair requires a positive frozen "
                f"{field} snapshot"
            )
    identifier = _optional_positive_int(
        execution["position_identifier"], "position_identifier"
    )
    confirmed_fence = connection.execute(
        """
        SELECT id FROM position_actions
        WHERE setup_id = ? AND position_identifier = ? AND status = 'CONFIRMED'
          AND UPPER(action_type) IN ('OPEN', 'SET_INITIAL_PROTECTION')
        ORDER BY id
        LIMIT 1
        """,
        (str(execution["setup_id"]), identifier),
    ).fetchone()
    if confirmed_fence is None:
        raise RuntimeError(
            "Post-fill protection repair requires a confirmed OPEN/protection fence"
        )


def _validate_action_execution_binding(
    execution: sqlite3.Row,
    action: sqlite3.Row,
) -> None:
    if str(action["setup_id"] or "") != str(execution["setup_id"]):
        raise RuntimeError("Position action belongs to a different execution")
    execution_identifier = _optional_positive_int(
        execution["position_identifier"], "position_identifier"
    )
    action_identifier = _optional_positive_int(
        action["position_identifier"], "position_identifier"
    )
    if execution_identifier is None or action_identifier != execution_identifier:
        raise ValueError("Position action stable identifier does not match execution")
    for field in ("management_policy", "account_login", "account_server"):
        if str(action[field]) != str(execution[field]):
            raise ValueError(f"Position action {field} does not match execution")
    if str(action["account_scope"]).strip().lower() != str(
        execution["account_scope"]
    ).strip().lower():
        raise ValueError("Position action account_scope does not match execution")


def _assert_management_projection(
    execution: sqlite3.Row,
    action: sqlite3.Row,
    milestone: str | None,
) -> None:
    if milestone not in _MILESTONE_COLUMNS:
        return
    reached_column, status_column = _MILESTONE_COLUMNS[milestone]
    if execution[reached_column] is None:
        raise RuntimeError("Management action exists without its reached milestone latch")
    projected = str(execution[status_column] or "").upper()
    action_status = str(action["status"] or "").upper()
    acceptable = {action_status}
    if action_status in {"SUBMITTED", "UNKNOWN"}:
        acceptable.add("PENDING")
    if projected not in acceptable:
        raise RuntimeError(
            "Management action/execution status projection invariant is broken"
        )


def _assert_management_slot_available(
    execution: sqlite3.Row,
    milestone: str | None,
    *,
    repair: bool,
) -> None:
    if milestone not in _MILESTONE_COLUMNS:
        if repair:
            raise ValueError("Management repair requires an R1 or R2 milestone")
        return
    status_column = _MILESTONE_COLUMNS[milestone][1]
    current = str(execution[status_column] or "").strip().upper()
    if repair:
        if milestone not in {"R1", "R2"} or current != "CONFIRMED":
            raise RuntimeError(
                f"Management repair requires CONFIRMED {milestone} protection"
            )
        return
    if current:
        raise RuntimeError(f"Management milestone {milestone} already has an action state")


def _management_observation_update(
    *,
    reached: tuple[str, ...],
    observed_at: str,
    current_r: float | None,
    milestone: str | None,
    action_status: str,
) -> tuple[list[str], list[Any]]:
    assignments: list[str] = []
    parameters: list[Any] = []
    if current_r is not None:
        assignments.append(
            "highest_observed_r = CASE "
            "WHEN highest_observed_r IS NULL OR highest_observed_r < ? THEN ? "
            "ELSE highest_observed_r END"
        )
        parameters.extend((current_r, current_r))
    for reached_milestone in reached:
        reached_column = _MILESTONE_COLUMNS[reached_milestone][0]
        assignments.append(f"{reached_column} = COALESCE({reached_column}, ?)")
        parameters.append(observed_at)
    if milestone in _MILESTONE_COLUMNS:
        status_column = _MILESTONE_COLUMNS[milestone][1]
        assignments.append(f"{status_column} = ?")
        parameters.append(action_status)
    return assignments, parameters


def _management_action_milestone(action: sqlite3.Row) -> str | None:
    payload = json.loads(str(action["payload_json"] or "{}"))
    return _normalize_management_milestone(payload.get("milestone"))


def _validate_management_outcome_transition(*, current: str, requested: str) -> None:
    current_status = str(current or "").strip().upper()
    allowed = {
        "CONFIRMED": {"SUBMITTED", "UNKNOWN", "FAILED", "CONFIRMED"},
        "FAILED": {"PENDING", "SUBMITTED", "UNKNOWN", "FAILED"},
        "UNKNOWN": {"SUBMITTED", "UNKNOWN"},
    }[requested]
    if current_status not in allowed:
        raise RuntimeError(
            f"Cannot finalize management action {current_status!r} as {requested}"
        )


def _validate_broker_audit_replay(
    action: sqlite3.Row,
    broker_values: dict[str, Any],
) -> None:
    for field, value in broker_values.items():
        if value is not None and action[field] is not None and action[field] != value:
            raise ValueError(f"Management action replay changes broker audit field {field}")


def _required_lower_hex(value: Any, *, length: int, field: str) -> str:
    normalized = str(value or "").strip()
    pattern = {
        32: _LOWER_HEX_32,
        40: _LOWER_HEX_40,
        64: _LOWER_HEX_64,
    }.get(length)
    if pattern is None or not pattern.fullmatch(normalized):
        raise ValueError(f"{field} must be exactly {length} lowercase hex characters")
    return normalized


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("timestamp must be a datetime")
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc)


def _parse_persisted_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def _decode_telegram_poll_readiness(
    row: sqlite3.Row | None,
) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        decoded = json.loads(str(row["state_value"]))
    except (KeyError, TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _public_telegram_poll_evidence(state: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = (
        "schema_version",
        "release_id",
        "session_sha256",
        "db_identity",
        "deployment_nonce_sha256",
        "release_manifest_sha256",
        "runtime_config_sha256",
        "production_config_sha256",
        "worker_instance_id",
        "worker_started_at",
        "last_attempt_at",
        "last_success_at",
        "last_failure_at",
        "last_result",
        "last_error_kind",
        "attempt_count",
        "success_count",
        "failure_count",
        "conflict_count",
    )
    return {field: state.get(field) for field in allowed_fields}


def _telegram_poll_readiness_result(
    *, ready: bool, reason: str, evidence: dict[str, Any] | None
) -> dict[str, Any]:
    return {"ready": bool(ready), "reason": reason, "evidence": evidence}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _outbox_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["payload"] = json.loads(str(row["payload_json"]))
    return result


def _position_action_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["payload"] = json.loads(str(row["payload_json"]))
    return result


def _decode_terminal_open_receipt(value: str) -> dict[str, Any] | None:
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(decoded, dict) or decoded.get("kind") != "OPEN_TERMINAL_V1":
        return None
    return decoded


def _terminal_open_snapshot(
    connection: sqlite3.Connection,
    setup_id: str,
    *,
    disposition: str,
) -> dict[str, Any]:
    execution = connection.execute(
        "SELECT * FROM trade_executions WHERE setup_id = ?", (str(setup_id),)
    ).fetchone()
    actions = connection.execute(
        """
        SELECT * FROM position_actions
        WHERE setup_id = ? AND UPPER(action_type) = 'OPEN'
        ORDER BY id
        """,
        (str(setup_id),),
    ).fetchall()
    if len(actions) > 1:
        raise RuntimeError("Multiple OPEN action fences exist for one setup")
    action = actions[0] if actions else None
    execution_result = dict(execution) if execution is not None else None
    return {
        "disposition": str(disposition),
        "execution": execution_result,
        "action": _position_action_row(action) if action is not None else None,
        "deferred_close_reason": (
            execution_result.get("deferred_close_reason")
            if execution_result is not None
            else None
        ),
    }


def _enable_wal(connection: sqlite3.Connection) -> None:
    """Prefer WAL for concurrent readers, retaining SQLite's safe fallback."""

    try:
        connection.execute("PRAGMA journal_mode = WAL").fetchone()
    except sqlite3.OperationalError as exc:
        # Read-only filesystems and a concurrently locked legacy database may
        # legitimately reject a journal-mode change. busy_timeout still gives
        # those databases bounded lock coordination using their existing mode.
        message = str(exc).lower()
        if "readonly" not in message and "locked" not in message:
            raise


def _execute_script(connection: sqlite3.Connection, script: str) -> None:
    """Execute a SQL script without sqlite3.executescript's implicit COMMIT."""

    buffer = ""
    for line in script.splitlines():
        buffer += line + "\n"
        if not sqlite3.complete_statement(buffer):
            continue
        statement = buffer.strip()
        if statement:
            connection.execute(statement)
        buffer = ""
    if buffer.strip():
        raise RuntimeError("Incomplete SQL migration statement")


def _ensure_columns(
    connection: sqlite3.Connection, table: str, columns: dict[str, str]
) -> None:
    existing = {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if not existing:
        raise RuntimeError(f"Cannot migrate missing table: {table}")
    for name, declaration in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def _optional_int(value: Any) -> int | None:
    return None if value is None or value == "" else int(value)


def _optional_positive_int(value: Any, field: str) -> int | None:
    normalized = _optional_int(value)
    if normalized is not None and normalized <= 0:
        raise ValueError(f"{field} must be positive")
    return normalized


def _required_finite_float(value: Any, field: str) -> float:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field} must be finite")
    return normalized


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return _required_finite_float(value, "numeric value")


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_account_margin_mode(value: Any) -> str | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    canonical = normalized.upper()
    if canonical not in {"HEDGING", "NETTING", "EXCHANGE", "UNKNOWN"}:
        raise ValueError(
            "account_margin_mode must be HEDGING, NETTING, EXCHANGE, or UNKNOWN"
        )
    return canonical


def _optional_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _iso(value)
    text = str(value).strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return _iso(parsed)


def _json_text(value: Any) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "{}"
        parsed = json.loads(text)
    else:
        parsed = value
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _event_is_admin_only(event: dict[str, Any]) -> bool:
    payload = event.get("payload") or {}
    audience = str(payload.get("audience", "")).strip().lower()
    account_scope = str(payload.get("account_scope", "")).strip().lower()
    return not (account_scope == "demo" and audience == "approved")
