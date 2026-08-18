from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .engine import RevisedDecision, RevisedState


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(type(value).__name__)


def _json(value: object) -> str:
    if is_dataclass(value):
        value = asdict(value)
    return json.dumps(value, default=_json_default, sort_keys=True, separators=(",", ":"))


class RevisedStore:
    """Dedicated shadow store; never opens the production signal database."""

    def __init__(self, path: str | Path, *, audit_path: str | Path | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_path = Path(audit_path) if audit_path else self.path.with_suffix(".jsonl")
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS revised_setups (
                    setup_id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    state TEXT NOT NULL,
                    observation_only INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS revised_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    setup_id TEXT NOT NULL REFERENCES revised_setups(setup_id),
                    event_key TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_revised_events_delivery
                    ON revised_events(delivered_at, event_type);
                CREATE TABLE IF NOT EXISTS revised_positions (
                    setup_id TEXT PRIMARY KEY REFERENCES revised_setups(setup_id),
                    side TEXT NOT NULL,
                    entry REAL NOT NULL,
                    stop REAL NOT NULL,
                    target REAL NOT NULL,
                    first_obstacle REAL,
                    first_obstacle_r REAL,
                    opened_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    closed_at TEXT,
                    exit_price REAL,
                    close_reason TEXT,
                    mfe REAL NOT NULL DEFAULT 0,
                    mae REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS revised_health (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observed_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

    def record_decision(self, decision: RevisedDecision) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        setup_id = self._setup_id(decision)
        event_type = f"REVISED_{decision.state.value}"
        event_key = f"{setup_id}:{event_type}"
        payload = asdict(decision)
        connection = self._connect()
        inserted = False
        try:
            connection.execute(
                """
                INSERT INTO revised_setups(
                    setup_id, strategy_id, strategy_version, symbol, side, state,
                    observation_only, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(setup_id) DO UPDATE SET
                    state=excluded.state,
                    observation_only=excluded.observation_only,
                    updated_at=excluded.updated_at
                """,
                (
                    setup_id,
                    decision.strategy_id,
                    decision.strategy_version,
                    decision.symbol,
                    decision.side.value,
                    decision.state.value,
                    int(decision.observation_only),
                    now,
                    now,
                ),
            )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO revised_events(
                    setup_id, event_key, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (setup_id, event_key, event_type, _json(payload), now),
            )
            inserted = cursor.rowcount == 1
            if decision.state is RevisedState.ENTRY_READY and decision.action.value == "ENTER" and decision.entry is not None and decision.stop is not None and decision.target is not None:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO revised_positions(
                        setup_id, side, entry, stop, target, first_obstacle,
                        first_obstacle_r, opened_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
                    """,
                    (
                        setup_id,
                        decision.side.value,
                        decision.entry,
                        decision.stop,
                        decision.target,
                        decision.first_obstacle,
                        decision.first_obstacle_r,
                        now,
                    ),
                )
            connection.commit()
        finally:
            connection.close()
        if inserted:
            self._append_audit({"event": event_type, "event_key": event_key, "payload": payload})
        return inserted

    def record_outcome(
        self,
        *,
        setup_id: str,
        status: str,
        close_reason: str,
        exit_price: float | None,
        mfe: float,
        mae: float,
        closed_at: datetime | None = None,
    ) -> None:
        now = closed_at or datetime.now(timezone.utc)
        payload = {
            "setup_id": setup_id,
            "status": status,
            "close_reason": close_reason,
            "exit_price": exit_price,
            "mfe": mfe,
            "mae": mae,
            "closed_at": now,
        }
        event_key = f"{setup_id}:REVISED_OUTCOME"
        connection = self._connect()
        try:
            connection.execute(
                """
                UPDATE revised_positions
                SET status=?, closed_at=?, exit_price=?, close_reason=?, mfe=?, mae=?
                WHERE setup_id=? AND status='OPEN'
                """,
                (status, now.isoformat(), exit_price, close_reason, mfe, mae, setup_id),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO revised_events(
                    setup_id, event_key, event_type, payload_json, created_at
                ) VALUES (?, ?, 'REVISED_OUTCOME', ?, ?)
                """,
                (setup_id, event_key, _json(payload), now.isoformat()),
            )
            connection.commit()
        finally:
            connection.close()
        self._append_audit({"event": "REVISED_OUTCOME", "event_key": event_key, "payload": payload})

    def record_health(self, status: str, detail: str) -> None:
        observed = datetime.now(timezone.utc)
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO revised_health(observed_at, status, detail) VALUES (?, ?, ?)",
                (observed.isoformat(), status, detail[:2000]),
            )
            connection.commit()
        finally:
            connection.close()
        self._append_audit({"event": "REVISED_HEALTH", "status": status, "detail": detail, "observed_at": observed})

    def pending_notifications(self, *, limit: int = 20) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT id, setup_id, event_type, payload_json, created_at
                FROM revised_events
                WHERE delivered_at IS NULL
                  AND event_type IN ('REVISED_ENTRY_READY', 'REVISED_OUTCOME', 'REVISED_HEALTH')
                ORDER BY id ASC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def mark_delivered(self, event_id: int) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "UPDATE revised_events SET delivered_at=? WHERE id=? AND delivered_at IS NULL",
                (datetime.now(timezone.utc).isoformat(), event_id),
            )
            connection.commit()
        finally:
            connection.close()

    def open_positions(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            return [dict(row) for row in connection.execute("SELECT * FROM revised_positions WHERE status='OPEN'").fetchall()]
        finally:
            connection.close()

    def update_position_marks(self, setup_id: str, *, mfe: float, mae: float) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "UPDATE revised_positions SET mfe=MAX(mfe, ?), mae=MIN(mae, ?) WHERE setup_id=? AND status='OPEN'",
                (mfe, mae, setup_id),
            )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _setup_id(decision: RevisedDecision) -> str:
        level = f"{decision.first_obstacle:.2f}" if decision.first_obstacle is not None else "NONE"
        return f"{decision.strategy_id}-{decision.symbol}-{decision.side.value}-{level}-{decision.time:%Y%m%dT%H%M}"

    def _append_audit(self, record: Mapping[str, Any]) -> None:
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(_json(record) + "\n")
