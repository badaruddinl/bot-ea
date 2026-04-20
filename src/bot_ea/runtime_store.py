from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    status TEXT NOT NULL,
    symbol TEXT,
    timeframe TEXT,
    trading_style TEXT,
    allocation_mode TEXT,
    allocation_value REAL,
    stop_reason TEXT,
    config_json TEXT
);

CREATE TABLE IF NOT EXISTS polling_cycles (
    cycle_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    polled_at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cycle_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT,
    bid REAL,
    ask REAL,
    spread_points REAL,
    equity REAL,
    free_margin REAL,
    session_state TEXT,
    news_state TEXT,
    payload_json TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(run_id),
    FOREIGN KEY(cycle_id) REFERENCES polling_cycles(cycle_id)
);

CREATE TABLE IF NOT EXISTS ai_decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cycle_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    side TEXT,
    confidence REAL,
    reason TEXT,
    payload_json TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(run_id),
    FOREIGN KEY(cycle_id) REFERENCES polling_cycles(cycle_id)
);

CREATE TABLE IF NOT EXISTS risk_guard_events (
    guard_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cycle_id INTEGER NOT NULL,
    allowed INTEGER NOT NULL,
    mode TEXT,
    rejection_reason TEXT,
    normalized_volume REAL,
    risk_cash_budget REAL,
    payload_json TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(run_id),
    FOREIGN KEY(cycle_id) REFERENCES polling_cycles(cycle_id)
);

CREATE TABLE IF NOT EXISTS execution_events (
    execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cycle_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    symbol TEXT,
    side TEXT,
    volume REAL,
    price REAL,
    retcode TEXT,
    detail TEXT,
    payload_json TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(run_id),
    FOREIGN KEY(cycle_id) REFERENCES polling_cycles(cycle_id)
);

CREATE TABLE IF NOT EXISTS position_events (
    position_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cycle_id INTEGER NOT NULL,
    broker_position_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT,
    volume REAL,
    status TEXT NOT NULL,
    entry_price REAL,
    stop_loss REAL,
    take_profit REAL,
    payload_json TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(run_id),
    FOREIGN KEY(cycle_id) REFERENCES polling_cycles(cycle_id)
);

CREATE TABLE IF NOT EXISTS stop_events (
    stop_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cycle_id INTEGER,
    stop_code TEXT NOT NULL,
    severity TEXT NOT NULL,
    detail TEXT NOT NULL,
    payload_json TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(run_id),
    FOREIGN KEY(cycle_id) REFERENCES polling_cycles(cycle_id)
);

CREATE TABLE IF NOT EXISTS runtime_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cycle_id INTEGER,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(run_id),
    FOREIGN KEY(cycle_id) REFERENCES polling_cycles(cycle_id)
);

CREATE INDEX IF NOT EXISTS idx_polling_cycles_run_time ON polling_cycles(run_id, polled_at);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_run_cycle ON market_snapshots(run_id, cycle_id);
CREATE INDEX IF NOT EXISTS idx_ai_decisions_run_cycle ON ai_decisions(run_id, cycle_id);
CREATE INDEX IF NOT EXISTS idx_execution_events_run_cycle ON execution_events(run_id, cycle_id);
CREATE INDEX IF NOT EXISTS idx_stop_events_run_cycle ON stop_events(run_id, cycle_id);
"""


class RuntimeStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.session() as connection:
            connection.executescript(SCHEMA_SQL)

    def start_run(
        self,
        *,
        run_id: str,
        started_at: str,
        status: str,
        symbol: str | None = None,
        timeframe: str | None = None,
        trading_style: str | None = None,
        allocation_mode: str | None = None,
        allocation_value: float | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, started_at, status, symbol, timeframe, trading_style,
                    allocation_mode, allocation_value, config_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    started_at,
                    status,
                    symbol,
                    timeframe,
                    trading_style,
                    allocation_mode,
                    allocation_value,
                    self._dump(config),
                ),
            )

    def update_run_status(self, run_id: str, *, status: str, stop_reason: str | None = None) -> None:
        with self.session() as connection:
            connection.execute(
                "UPDATE runs SET status = ?, stop_reason = ? WHERE run_id = ?",
                (status, stop_reason, run_id),
            )

    def start_cycle(self, *, run_id: str, polled_at: str, status: str, detail: str | None = None) -> int:
        with self.session() as connection:
            cursor = connection.execute(
                "INSERT INTO polling_cycles (run_id, polled_at, status, detail) VALUES (?, ?, ?, ?)",
                (run_id, polled_at, status, detail),
            )
            return int(cursor.lastrowid)

    def record_market_snapshot(
        self,
        *,
        run_id: str,
        cycle_id: int,
        symbol: str,
        timeframe: str | None,
        bid: float | None,
        ask: float | None,
        spread_points: float | None,
        equity: float | None,
        free_margin: float | None,
        session_state: str | None,
        news_state: str | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._insert(
            """
            INSERT INTO market_snapshots (
                run_id, cycle_id, symbol, timeframe, bid, ask, spread_points,
                equity, free_margin, session_state, news_state, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                cycle_id,
                symbol,
                timeframe,
                bid,
                ask,
                spread_points,
                equity,
                free_margin,
                session_state,
                news_state,
                self._dump(payload),
            ),
        )

    def record_ai_decision(
        self,
        *,
        run_id: str,
        cycle_id: int,
        action: str,
        side: str | None,
        confidence: float | None,
        reason: str | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._insert(
            """
            INSERT INTO ai_decisions (run_id, cycle_id, action, side, confidence, reason, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, cycle_id, action, side, confidence, reason, self._dump(payload)),
        )

    def record_risk_guard(
        self,
        *,
        run_id: str,
        cycle_id: int,
        allowed: bool,
        mode: str | None,
        rejection_reason: str | None,
        normalized_volume: float | None,
        risk_cash_budget: float | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._insert(
            """
            INSERT INTO risk_guard_events (
                run_id, cycle_id, allowed, mode, rejection_reason, normalized_volume, risk_cash_budget, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                cycle_id,
                1 if allowed else 0,
                mode,
                rejection_reason,
                normalized_volume,
                risk_cash_budget,
                self._dump(payload),
            ),
        )

    def record_execution_event(
        self,
        *,
        run_id: str,
        cycle_id: int,
        event_type: str,
        status: str,
        symbol: str | None,
        side: str | None,
        volume: float | None,
        price: float | None,
        retcode: str | None,
        detail: str | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._insert(
            """
            INSERT INTO execution_events (
                run_id, cycle_id, event_type, status, symbol, side, volume, price, retcode, detail, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                cycle_id,
                event_type,
                status,
                symbol,
                side,
                volume,
                price,
                retcode,
                detail,
                self._dump(payload),
            ),
        )

    def record_stop_event(
        self,
        *,
        run_id: str,
        cycle_id: int | None,
        stop_code: str,
        severity: str,
        detail: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._insert(
            """
            INSERT INTO stop_events (run_id, cycle_id, stop_code, severity, detail, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, cycle_id, stop_code, severity, detail, self._dump(payload)),
        )

    def record_log(
        self,
        *,
        run_id: str,
        cycle_id: int | None,
        level: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._insert(
            "INSERT INTO runtime_logs (run_id, cycle_id, level, message, payload_json) VALUES (?, ?, ?, ?, ?)",
            (run_id, cycle_id, level, message, self._dump(payload)),
        )

    def fetch_counts(self) -> dict[str, int]:
        tables = (
            "runs",
            "polling_cycles",
            "market_snapshots",
            "ai_decisions",
            "risk_guard_events",
            "execution_events",
            "stop_events",
            "runtime_logs",
        )
        counts: dict[str, int] = {}
        with self.session() as connection:
            for table in tables:
                counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return counts

    def _insert(self, sql: str, params: tuple[Any, ...]) -> None:
        with self.session() as connection:
            connection.execute(sql, params)

    @staticmethod
    def _dump(payload: dict[str, Any] | None) -> str | None:
        if payload is None:
            return None
        return json.dumps(payload, sort_keys=True)
