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
    attempt_id TEXT,
    event_type TEXT NOT NULL,
    phase TEXT,
    status TEXT NOT NULL,
    symbol TEXT,
    side TEXT,
    volume REAL,
    price REAL,
    quoted_price REAL,
    executed_price REAL,
    slippage_points REAL,
    fill_latency_ms REAL,
    order_ticket TEXT,
    deal_ticket TEXT,
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
    exit_price REAL,
    stop_loss REAL,
    take_profit REAL,
    opened_at TEXT,
    closed_at TEXT,
    realized_pnl_cash REAL,
    commission_cash REAL,
    swap_cash REAL,
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
            self._ensure_columns(connection, "execution_events", {
                "attempt_id": "TEXT",
                "phase": "TEXT",
                "quoted_price": "REAL",
                "executed_price": "REAL",
                "slippage_points": "REAL",
                "fill_latency_ms": "REAL",
                "order_ticket": "TEXT",
                "deal_ticket": "TEXT",
            })
            self._ensure_columns(connection, "position_events", {
                "exit_price": "REAL",
                "opened_at": "TEXT",
                "closed_at": "TEXT",
                "realized_pnl_cash": "REAL",
                "commission_cash": "REAL",
                "swap_cash": "REAL",
            })

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
        attempt_id: str | None = None,
        event_type: str,
        phase: str | None = None,
        status: str,
        symbol: str | None,
        side: str | None,
        volume: float | None,
        price: float | None,
        quoted_price: float | None = None,
        executed_price: float | None = None,
        slippage_points: float | None = None,
        fill_latency_ms: float | None = None,
        order_ticket: str | None = None,
        deal_ticket: str | None = None,
        retcode: str | None = None,
        detail: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._insert(
            """
            INSERT INTO execution_events (
                run_id, cycle_id, attempt_id, event_type, phase, status, symbol, side, volume, price, quoted_price, executed_price, slippage_points, fill_latency_ms, order_ticket, deal_ticket, retcode, detail, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                cycle_id,
                attempt_id,
                event_type,
                phase,
                status,
                symbol,
                side,
                volume,
                price,
                quoted_price,
                executed_price,
                slippage_points,
                fill_latency_ms,
                order_ticket,
                deal_ticket,
                retcode,
                detail,
                self._dump(payload),
            ),
        )

    def record_position_event(
        self,
        *,
        run_id: str,
        cycle_id: int,
        broker_position_id: str | None,
        symbol: str,
        side: str | None,
        volume: float | None,
        status: str,
        entry_price: float | None,
        exit_price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        opened_at: str | None = None,
        closed_at: str | None = None,
        realized_pnl_cash: float | None = None,
        commission_cash: float | None = None,
        swap_cash: float | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._insert(
            """
            INSERT INTO position_events (
                run_id, cycle_id, broker_position_id, symbol, side, volume, status, entry_price, exit_price, stop_loss, take_profit, opened_at, closed_at, realized_pnl_cash, commission_cash, swap_cash, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                cycle_id,
                broker_position_id,
                symbol,
                side,
                volume,
                status,
                entry_price,
                exit_price,
                stop_loss,
                take_profit,
                opened_at,
                closed_at,
                realized_pnl_cash,
                commission_cash,
                swap_cash,
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
            "position_events",
            "stop_events",
            "runtime_logs",
        )
        counts: dict[str, int] = {}
        with self.session() as connection:
            for table in tables:
                counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return counts

    def fetch_recent_execution_events(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.session() as connection:
            rows = connection.execute(
                """
                SELECT
                    ee.execution_id,
                    ee.run_id,
                    ee.cycle_id,
                    ee.attempt_id,
                    pc.polled_at,
                    ee.event_type,
                    ee.phase,
                    ee.status,
                    ee.symbol,
                    ee.side,
                    ee.volume,
                    ee.price,
                    ee.quoted_price,
                    ee.executed_price,
                    ee.slippage_points,
                    ee.fill_latency_ms,
                    ee.order_ticket,
                    ee.deal_ticket,
                    ee.retcode,
                    ee.detail,
                    ee.payload_json
                FROM execution_events ee
                LEFT JOIN polling_cycles pc ON pc.cycle_id = ee.cycle_id
                ORDER BY ee.execution_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def fetch_recent_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.session() as connection:
            rows = connection.execute(
                """
                SELECT run_id, started_at, status, symbol, timeframe, trading_style, allocation_mode, allocation_value, stop_reason, config_json
                FROM runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def fetch_latest_run_overview(self) -> dict[str, Any] | None:
        with self.session() as connection:
            row = connection.execute(
                """
                SELECT
                    r.run_id,
                    r.started_at,
                    r.status,
                    r.symbol,
                    r.timeframe,
                    r.stop_reason,
                    ms.spread_points,
                    ms.equity,
                    ms.free_margin,
                    ms.snapshot_id,
                    pc.polled_at,
                    ad.action AS last_action
                FROM runs r
                LEFT JOIN polling_cycles pc ON pc.run_id = r.run_id
                LEFT JOIN market_snapshots ms ON ms.cycle_id = pc.cycle_id
                LEFT JOIN ai_decisions ad ON ad.cycle_id = pc.cycle_id
                ORDER BY r.started_at DESC, pc.cycle_id DESC, ms.snapshot_id DESC, ad.decision_id DESC
                LIMIT 1
                """
            ).fetchone()
        return None if row is None else self._row_to_dict(row)

    def fetch_recent_rejections(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.session() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM (
                    SELECT
                        'execution' AS source,
                        ee.cycle_id,
                        pc.polled_at,
                        ee.status,
                        ee.symbol,
                        ee.side,
                        ee.retcode,
                        ee.detail,
                        ee.execution_id AS sort_id
                    FROM execution_events ee
                    LEFT JOIN polling_cycles pc ON pc.cycle_id = ee.cycle_id
                    WHERE ee.status IN ('REJECTED', 'PRECHECK_REJECTED', 'GUARD_REJECTED', 'ERROR')

                    UNION ALL

                    SELECT
                        'risk_guard' AS source,
                        rg.cycle_id,
                        pc.polled_at,
                        rg.mode AS status,
                        NULL AS symbol,
                        NULL AS side,
                        NULL AS retcode,
                        rg.rejection_reason AS detail,
                        rg.guard_id AS sort_id
                    FROM risk_guard_events rg
                    LEFT JOIN polling_cycles pc ON pc.cycle_id = rg.cycle_id
                    WHERE rg.allowed = 0
                )
                ORDER BY polled_at DESC, sort_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def fetch_recent_position_events(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.session() as connection:
            rows = connection.execute(
                """
                SELECT
                    position_event_id,
                    pe.run_id,
                    pe.cycle_id,
                    pc.polled_at,
                    pe.broker_position_id,
                    pe.symbol,
                    pe.side,
                    pe.volume,
                    pe.status,
                    pe.entry_price,
                    pe.exit_price,
                    pe.stop_loss,
                    pe.take_profit,
                    pe.opened_at,
                    pe.closed_at,
                    pe.realized_pnl_cash,
                    pe.commission_cash,
                    pe.swap_cash,
                    pe.payload_json
                FROM position_events pe
                LEFT JOIN polling_cycles pc ON pc.cycle_id = pe.cycle_id
                ORDER BY pe.position_event_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def fetch_latest_risk_guard(self) -> dict[str, Any] | None:
        with self.session() as connection:
            row = connection.execute(
                """
                SELECT
                    rg.guard_id,
                    rg.run_id,
                    rg.cycle_id,
                    pc.polled_at,
                    rg.allowed,
                    rg.mode,
                    rg.rejection_reason,
                    rg.normalized_volume,
                    rg.risk_cash_budget,
                    rg.payload_json
                FROM risk_guard_events rg
                LEFT JOIN polling_cycles pc ON pc.cycle_id = rg.cycle_id
                ORDER BY rg.guard_id DESC
                LIMIT 1
                """
            ).fetchone()
        return None if row is None else self._row_to_dict(row)

    def fetch_execution_health_summary(self, *, limit: int = 100) -> dict[str, Any]:
        with self.session() as connection:
            row = connection.execute(
                """
                WITH terminal AS (
                    SELECT
                        COALESCE(attempt_id, printf('legacy-%d', execution_id)) AS attempt_key,
                        MAX(execution_id) AS terminal_execution_id
                    FROM execution_events
                    WHERE
                        phase IN ('FILL', 'GUARD')
                        OR status = 'PRECHECK_REJECTED'
                        OR (phase IS NULL AND status IN ('FILLED', 'DRY_RUN_OK', 'REJECTED', 'ERROR'))
                    GROUP BY COALESCE(attempt_id, printf('legacy-%d', execution_id))
                ),
                recent AS (
                    SELECT ee.status, ee.slippage_points, ee.fill_latency_ms
                    FROM terminal t
                    JOIN execution_events ee ON ee.execution_id = t.terminal_execution_id
                    ORDER BY ee.execution_id DESC
                    LIMIT ?
                )
                SELECT
                    COUNT(*) AS total_events,
                    SUM(CASE WHEN status = 'FILLED' THEN 1 ELSE 0 END) AS filled_events,
                    SUM(CASE WHEN status = 'DRY_RUN_OK' THEN 1 ELSE 0 END) AS dry_run_events,
                    SUM(CASE WHEN status IN ('REJECTED', 'PRECHECK_REJECTED', 'GUARD_REJECTED', 'ERROR') THEN 1 ELSE 0 END) AS rejected_events,
                    AVG(CASE WHEN status = 'FILLED' THEN slippage_points END) AS average_slippage_points,
                    AVG(CASE WHEN status = 'FILLED' THEN fill_latency_ms END) AS average_fill_latency_ms
                FROM recent
                """,
                (limit,),
            ).fetchone()
        if row is None:
            return {
                "total_events": 0,
                "filled_events": 0,
                "dry_run_events": 0,
                "rejected_events": 0,
                "reject_rate": 0.0,
                "average_slippage_points": 0.0,
                "average_fill_latency_ms": 0.0,
            }
        summary = self._row_to_dict(row)
        total_events = int(summary.get("total_events") or 0)
        rejected_events = int(summary.get("rejected_events") or 0)
        summary["total_events"] = total_events
        summary["filled_events"] = int(summary.get("filled_events") or 0)
        summary["dry_run_events"] = int(summary.get("dry_run_events") or 0)
        summary["rejected_events"] = rejected_events
        summary["reject_rate"] = (rejected_events / total_events) if total_events > 0 else 0.0
        summary["average_slippage_points"] = float(summary.get("average_slippage_points") or 0.0)
        summary["average_fill_latency_ms"] = float(summary.get("average_fill_latency_ms") or 0.0)
        return summary

    def _insert(self, sql: str, params: tuple[Any, ...]) -> None:
        with self.session() as connection:
            connection.execute(sql, params)

    @staticmethod
    def _dump(payload: dict[str, Any] | None) -> str | None:
        if payload is None:
            return None
        return json.dumps(payload, sort_keys=True)

    @staticmethod
    def _ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}")

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for key, value in list(result.items()):
            if key.endswith("_json") and value is not None:
                result[key] = json.loads(value)
        return result
