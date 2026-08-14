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

    def save_trade_execution(self, record: dict[str, Any]) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO trade_executions (
                    setup_id, signal_outbox_id, execution_mode, status, symbol, side,
                    requested_entry, stop_price, target_price, volume, risk_cash,
                    expected_profit_cash, valid_until, client_tag, order_ticket,
                    deal_ticket, position_ticket, actual_entry, opened_at, closed_at,
                    exit_price, profit_cash, close_reason, closed_by, last_error, updated_at
                ) VALUES (
                    :setup_id, :signal_outbox_id, :execution_mode, :status, :symbol, :side,
                    :requested_entry, :stop_price, :target_price, :volume, :risk_cash,
                    :expected_profit_cash, :valid_until, :client_tag, :order_ticket,
                    :deal_ticket, :position_ticket, :actual_entry, :opened_at, :closed_at,
                    :exit_price, :profit_cash, :close_reason, :closed_by, :last_error, :updated_at
                )
                ON CONFLICT(setup_id) DO UPDATE SET
                    status=excluded.status, volume=excluded.volume, risk_cash=excluded.risk_cash,
                    expected_profit_cash=excluded.expected_profit_cash,
                    order_ticket=COALESCE(excluded.order_ticket, trade_executions.order_ticket),
                    deal_ticket=COALESCE(excluded.deal_ticket, trade_executions.deal_ticket),
                    position_ticket=COALESCE(excluded.position_ticket, trade_executions.position_ticket),
                    actual_entry=COALESCE(excluded.actual_entry, trade_executions.actual_entry),
                    opened_at=COALESCE(excluded.opened_at, trade_executions.opened_at),
                    closed_at=COALESCE(excluded.closed_at, trade_executions.closed_at),
                    exit_price=COALESCE(excluded.exit_price, trade_executions.exit_price),
                    profit_cash=COALESCE(excluded.profit_cash, trade_executions.profit_cash),
                    close_reason=COALESCE(excluded.close_reason, trade_executions.close_reason),
                    closed_by=COALESCE(excluded.closed_by, trade_executions.closed_by),
                    last_error=excluded.last_error, updated_at=excluded.updated_at
                """,
                {**record, "updated_at": now},
            )

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
                WHERE status IN ('FILLED', 'CLOSE_SUBMITTED', 'CLOSE_REJECTED')
                ORDER BY updated_at
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def update_outbox_payload(self, outbox_id: int, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE signal_outbox SET payload_json = ? WHERE id = ? AND sent_at IS NULL",
                (json.dumps(payload, sort_keys=True), int(outbox_id)),
            )

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
