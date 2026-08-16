from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldm_signal.storage import SignalStore, telegram_poll_db_identity
from goldm_signal.strategy import SetupRecord, SetupState


NOW = datetime(2026, 8, 15, 4, 30, tzinfo=timezone.utc)


class GoldMStoreMigrationTests(unittest.TestCase):
    def test_telegram_poll_readiness_is_identity_bound_fresh_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / ".." / "signal.db"
            store = SignalStore(path)
            store.initialize()
            release_id = "a" * 40
            session_sha256 = hashlib.sha256(b"immutable-ea-session").hexdigest()
            database_identity = telegram_poll_db_identity(path)
            deployment_nonce_sha256 = hashlib.sha256(b"b" * 32).hexdigest()
            release_manifest_sha256 = hashlib.sha256(b"release-manifest").hexdigest()
            runtime_config_sha256 = hashlib.sha256(b"runtime-config").hexdigest()
            production_config_sha256 = hashlib.sha256(b"production-config").hexdigest()
            worker_id = "1" * 32
            store.start_telegram_poll_readiness(
                release_id=release_id,
                session_sha256=session_sha256,
                db_identity=database_identity,
                deployment_nonce_sha256=deployment_nonce_sha256,
                release_manifest_sha256=release_manifest_sha256,
                runtime_config_sha256=runtime_config_sha256,
                production_config_sha256=production_config_sha256,
                worker_instance_id=worker_id,
                worker_started_at=NOW,
            )
            self.assertTrue(
                store.record_telegram_poll_success(
                    worker_instance_id=worker_id,
                    observed_at=NOW + timedelta(seconds=1),
                )
            )

            ready = store.telegram_poll_readiness(
                expected_release_id=release_id,
                expected_session_sha256=session_sha256,
                expected_db_identity=database_identity,
                expected_deployment_nonce_sha256=deployment_nonce_sha256,
                expected_release_manifest_sha256=release_manifest_sha256,
                expected_runtime_config_sha256=runtime_config_sha256,
                expected_production_config_sha256=production_config_sha256,
                not_before=NOW - timedelta(seconds=1),
                max_age_seconds=30,
                now=NOW + timedelta(seconds=2),
            )
            self.assertTrue(ready["ready"])
            self.assertEqual(ready["reason"], "ready")

            moved_path = Path(tmpdir) / "moved" / "signal.db"
            moved_path.parent.mkdir()
            with (
                closing(sqlite3.connect(path)) as source,
                closing(sqlite3.connect(moved_path)) as destination,
            ):
                source.backup(destination)
            moved_store = SignalStore(moved_path)
            moved = moved_store.telegram_poll_readiness(
                expected_release_id=release_id,
                expected_session_sha256=session_sha256,
                expected_db_identity=telegram_poll_db_identity(moved_path),
                expected_deployment_nonce_sha256=deployment_nonce_sha256,
                expected_release_manifest_sha256=release_manifest_sha256,
                expected_runtime_config_sha256=runtime_config_sha256,
                expected_production_config_sha256=production_config_sha256,
                not_before=NOW - timedelta(seconds=1),
                max_age_seconds=30,
                now=NOW + timedelta(seconds=2),
            )
            self.assertFalse(moved["ready"])
            self.assertEqual(moved["reason"], "database_mismatch")

            mismatches = (
                ({"expected_release_id": "b" * 40}, "release_mismatch"),
                ({"expected_session_sha256": "c" * 64}, "session_mismatch"),
                ({"expected_db_identity": "d" * 64}, "database_path_mismatch"),
                (
                    {"expected_deployment_nonce_sha256": "e" * 64},
                    "deployment_nonce_mismatch",
                ),
                ({"expected_release_manifest_sha256": "f" * 64}, "release_manifest_mismatch"),
                ({"expected_runtime_config_sha256": "1" * 64}, "runtime_config_mismatch"),
                ({"expected_production_config_sha256": "2" * 64}, "production_config_mismatch"),
                (
                    {"not_before": NOW + timedelta(seconds=2)},
                    "worker_started_before_window",
                ),
                (
                    {
                        "now": NOW + timedelta(minutes=2),
                        "max_age_seconds": 30,
                    },
                    "stale_success",
                ),
            )
            baseline = {
                "expected_release_id": release_id,
                "expected_session_sha256": session_sha256,
                "expected_db_identity": database_identity,
                "expected_deployment_nonce_sha256": deployment_nonce_sha256,
                "expected_release_manifest_sha256": release_manifest_sha256,
                "expected_runtime_config_sha256": runtime_config_sha256,
                "expected_production_config_sha256": production_config_sha256,
                "not_before": NOW - timedelta(seconds=1),
                "max_age_seconds": 30,
                "now": NOW + timedelta(seconds=2),
            }
            for overrides, reason in mismatches:
                with self.subTest(reason=reason):
                    arguments = {**baseline, **overrides}
                    rejected = store.telegram_poll_readiness(**arguments)
                    self.assertFalse(rejected["ready"])
                    self.assertEqual(rejected["reason"], reason)

    def test_telegram_poll_worker_restart_resets_and_rejects_old_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "signal.db"
            release_id = "a" * 40
            session_sha256 = hashlib.sha256(b"immutable-ea-session").hexdigest()
            database_identity = telegram_poll_db_identity(path)
            deployment_nonce_sha256 = hashlib.sha256(b"b" * 32).hexdigest()
            release_manifest_sha256 = hashlib.sha256(b"release-manifest").hexdigest()
            runtime_config_sha256 = hashlib.sha256(b"runtime-config").hexdigest()
            production_config_sha256 = hashlib.sha256(b"production-config").hexdigest()
            first_worker = "1" * 32
            second_worker = "2" * 32
            store = SignalStore(path)
            store.initialize()
            store.start_telegram_poll_readiness(
                release_id=release_id,
                session_sha256=session_sha256,
                db_identity=database_identity,
                deployment_nonce_sha256=deployment_nonce_sha256,
                release_manifest_sha256=release_manifest_sha256,
                runtime_config_sha256=runtime_config_sha256,
                production_config_sha256=production_config_sha256,
                worker_instance_id=first_worker,
                worker_started_at=NOW,
            )
            store.record_telegram_poll_success(
                worker_instance_id=first_worker,
                observed_at=NOW + timedelta(seconds=1),
            )

            restarted = SignalStore(path)
            restarted.initialize()
            restarted.start_telegram_poll_readiness(
                release_id=release_id,
                session_sha256=session_sha256,
                db_identity=database_identity,
                deployment_nonce_sha256=deployment_nonce_sha256,
                release_manifest_sha256=release_manifest_sha256,
                runtime_config_sha256=runtime_config_sha256,
                production_config_sha256=production_config_sha256,
                worker_instance_id=second_worker,
                worker_started_at=NOW + timedelta(seconds=5),
            )
            self.assertFalse(
                store.record_telegram_poll_success(
                    worker_instance_id=first_worker,
                    observed_at=NOW + timedelta(seconds=6),
                )
            )
            reset = restarted.telegram_poll_readiness(
                expected_release_id=release_id,
                expected_session_sha256=session_sha256,
                expected_db_identity=database_identity,
                expected_deployment_nonce_sha256=deployment_nonce_sha256,
                expected_release_manifest_sha256=release_manifest_sha256,
                expected_runtime_config_sha256=runtime_config_sha256,
                expected_production_config_sha256=production_config_sha256,
                not_before=NOW + timedelta(seconds=4),
                max_age_seconds=30,
                now=NOW + timedelta(seconds=6),
            )
            self.assertFalse(reset["ready"])
            self.assertEqual(reset["reason"], "no_successful_poll")
            self.assertEqual(
                reset["evidence"]["worker_instance_id"], second_worker
            )

            restarted.record_telegram_poll_success(
                worker_instance_id=second_worker,
                observed_at=NOW + timedelta(seconds=7),
            )
            recovered = restarted.telegram_poll_readiness(
                expected_release_id=release_id,
                expected_session_sha256=session_sha256,
                expected_db_identity=database_identity,
                expected_deployment_nonce_sha256=deployment_nonce_sha256,
                expected_release_manifest_sha256=release_manifest_sha256,
                expected_runtime_config_sha256=runtime_config_sha256,
                expected_production_config_sha256=production_config_sha256,
                not_before=NOW + timedelta(seconds=4),
                max_age_seconds=30,
                now=NOW + timedelta(seconds=8),
            )
            self.assertTrue(recovered["ready"])

    def test_current_legacy_database_upgrades_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "legacy.db"
            _create_legacy_database_for_test(path)

            store = SignalStore(path)
            store.initialize()

            execution = store.trade_execution("legacy-setup")
            assert execution is not None
            self.assertEqual(execution["status"], "FILLED")
            self.assertEqual(execution["position_ticket"], 3003)
            self.assertEqual(execution["management_policy"], "")
            self.assertEqual(execution["account_login"], "")
            self.assertEqual(execution["account_server"], "")
            self.assertEqual(execution["account_scope"], "")
            self.assertIsNone(execution["account_margin_mode"])
            self.assertEqual(store.schema_version(), 9)

            with closing(sqlite3.connect(path)) as connection:
                migrations = connection.execute(
                    "SELECT version, name FROM schema_migrations ORDER BY version"
                ).fetchall()
                user_version = connection.execute("PRAGMA user_version").fetchone()[0]
                action_table = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'position_actions'"
                ).fetchone()
                execution_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(trade_executions)").fetchall()
                }
            self.assertEqual(
                migrations,
                [
                    (1, "baseline"),
                    (2, "position_action_ledger"),
                    (3, "open_action_targets"),
                    (4, "position_action_projection"),
                    (5, "execution_broker_snapshots"),
                    (6, "terminal_open_fence"),
                    (7, "execution_account_margin_mode"),
                    (8, "mt5_log_cursor_continuity"),
                    (9, "entry_side_policy"),
                ],
            )
            self.assertEqual(user_version, 9)
            self.assertEqual(action_table, ("position_actions",))
            self.assertTrue(
                {
                    "strategy_id",
                    "strategy_version",
                    "direction_profile",
                    "entry_side_policy",
                    "execution_profile",
                    "magic",
                    "position_identifier",
                    "initial_volume",
                    "remaining_volume",
                    "initial_stop_price",
                    "current_stop_price",
                    "initial_take_profit_price",
                    "current_take_profit_price",
                    "initial_risk_distance",
                    "management_policy",
                    "management_policy_version",
                    "management_policy_json",
                    "account_login",
                    "account_server",
                    "account_scope",
                    "account_margin_mode",
                    "highest_observed_r",
                    "r1_reached_at",
                    "r2_reached_at",
                    "r3_reached_at",
                    "r1_protection_status",
                    "r2_protection_status",
                    "r3_close_status",
                    "last_broker_sync_at",
                    "max_holding_minutes",
                    "deferred_close_reason",
                    "deferred_close_terminal_outbox_id",
                    "deferred_close_requested_at",
                    "cancelled_at",
                    "cancelled_by_terminal_outbox_id",
                }.issubset(execution_columns)
            )

    def test_reinitialize_is_idempotent_and_connection_pragmas_are_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            store.initialize()

            with store._connect() as connection:
                migration_count = connection.execute(
                    "SELECT COUNT(*) FROM schema_migrations"
                ).fetchone()[0]
                journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
                busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
                foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
            self.assertEqual(migration_count, 9)
            self.assertEqual(str(journal_mode).lower(), "wal")
            self.assertEqual(busy_timeout, 5000)
            self.assertEqual(foreign_keys, 1)

    def test_v6_database_adds_nullable_account_margin_mode_in_v7(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "signal.db"
            store = SignalStore(path)
            store.initialize()
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    "ALTER TABLE trade_executions DROP COLUMN account_margin_mode"
                )
                connection.execute("DELETE FROM schema_migrations WHERE version = 7")
                connection.execute("PRAGMA user_version = 6")
                connection.commit()

            store.initialize()

            with closing(sqlite3.connect(path)) as connection:
                columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(trade_executions)"
                    ).fetchall()
                }
            self.assertEqual(store.schema_version(), 9)
            self.assertIn("account_margin_mode", columns)

    def test_v7_cursor_migration_adds_continuity_fields_without_losing_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "signal.db"
            store = SignalStore(path)
            store.initialize()
            store.set_mt5_log_cursor(
                log_path="terminal.log",
                byte_offset=321,
                encoding="utf-16-le",
                fragment="partial",
            )
            with closing(sqlite3.connect(path)) as connection:
                for column in (
                    "raw_tail_b64",
                    "anchor_sha256",
                    "anchor_offset",
                    "file_identity",
                ):
                    connection.execute(
                        f"ALTER TABLE mt5_log_cursors DROP COLUMN {column}"
                    )
                connection.execute("DELETE FROM schema_migrations WHERE version = 8")
                connection.execute("PRAGMA user_version = 7")
                connection.commit()

            store.initialize()

            migrated = store.mt5_log_cursor("terminal.log")
            assert migrated is not None
            self.assertEqual(store.schema_version(), 9)
            self.assertEqual(migrated["byte_offset"], 321)
            self.assertEqual(migrated["encoding"], "utf-16-le")
            self.assertEqual(migrated["fragment"], "partial")
            self.assertEqual(migrated["file_identity"], "")
            self.assertEqual(migrated["anchor_offset"], 0)
            self.assertEqual(migrated["anchor_sha256"], "")
            self.assertEqual(migrated["raw_tail_b64"], "")

            store.set_mt5_log_cursor(
                log_path="terminal.log",
                byte_offset=400,
                encoding="utf-8",
                fragment="",
                file_identity="a:b",
                anchor_offset=400,
                anchor_sha256="c" * 64,
                raw_tail_b64="AAE",
            )
            refreshed = store.mt5_log_cursor("terminal.log")
            assert refreshed is not None
            self.assertEqual(refreshed["file_identity"], "a:b")
            self.assertEqual(refreshed["anchor_offset"], 400)
            self.assertEqual(refreshed["anchor_sha256"], "c" * 64)
            self.assertEqual(refreshed["raw_tail_b64"], "AAE")

    def test_existing_v2_action_ledger_rebuilds_for_ticketless_open_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "signal.db"
            store = SignalStore(path)
            store.initialize()
            original, _ = store.create_position_action(
                idempotency_key="position:3003:r1",
                position_ticket=3003,
                action_type="MODIFY_PROTECTION",
                payload={"stop": 4381.575},
            )
            _downgrade_position_actions_to_v2(path)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    """
                    INSERT INTO position_actions (
                        idempotency_key, setup_id, position_ticket, action_type,
                        payload_json, created_at, updated_at
                    ) VALUES ('open:v2-sentinel', 'legacy-open', 0, 'OPEN', '{}', ?, ?)
                    """,
                    (NOW.isoformat(), NOW.isoformat()),
                )
                connection.commit()

            store.initialize()

            migrated = store.position_action("position:3003:r1")
            assert migrated is not None
            self.assertEqual(migrated["id"], original["id"])
            self.assertEqual(migrated["position_ticket"], 3003)
            self.assertIsNone(migrated["position_identifier"])
            self.assertEqual(store.schema_version(), 9)
            with closing(sqlite3.connect(path)) as connection:
                columns = {
                    str(row[1]): int(row[3])
                    for row in connection.execute(
                        "PRAGMA table_info(position_actions)"
                    ).fetchall()
                }
            self.assertIn("position_identifier", columns)
            self.assertEqual(columns["position_ticket"], 0)
            self.assertIn("projected_at", columns)
            migrated_open = store.position_action("open:v2-sentinel")
            assert migrated_open is not None
            self.assertIsNone(migrated_open["position_ticket"])
            open_action, created = store.create_position_action(
                idempotency_key="open:after-v2",
                action_type="OPEN",
            )
            self.assertTrue(created)
            self.assertIsNone(open_action["position_ticket"])

    def test_trade_execution_management_and_account_metadata_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            record = _base_execution_record(
                "immutable-setup", _save_setup_and_signal(store, "immutable-setup")
            )
            record.update(
                {
                    "strategy_id": "D7",
                    "strategy_version": "1.7",
                    "direction_profile": "ALL",
                    "execution_profile": "DEMO_AUTO",
                    "magic": 260814,
                    "position_identifier": 9009,
                    "initial_volume": 0.08,
                    "remaining_volume": 0.08,
                    "initial_stop_price": 4374.2,
                    "current_stop_price": 4374.2,
                    "initial_take_profit_price": 4397.8,
                    "current_take_profit_price": 4397.8,
                    "initial_risk_distance": 5.9,
                    "management_policy": "R_LOCK_V1",
                    "management_policy_version": "1",
                    "management_policy_json": {"r1_lock_r": 0.25, "r2_lock_r": 1.0},
                    "account_login": "108098316",
                    "account_server": "XMGlobal-MT5 5",
                    "account_scope": "demo",
                    "account_margin_mode": "HEDGING",
                    "max_holding_minutes": 180,
                }
            )
            store.save_trade_execution(record)

            changed = {
                **record,
                "status": "CLOSED",
                "strategy_id": "OTHER",
                "strategy_version": "999",
                "direction_profile": "SELL_ONLY",
                "execution_profile": "LIVE_AUTO",
                "magic": 1,
                "position_identifier": 2,
                "initial_volume": 9.0,
                "initial_stop_price": 1.0,
                "initial_take_profit_price": 2.0,
                "initial_risk_distance": 99.0,
                "management_policy": "UNSAFE_REPLACEMENT",
                "management_policy_version": "999",
                "management_policy_json": {"unsafe": True},
                "account_login": "999",
                "account_server": "Other-Live",
                "account_scope": "live",
                "account_margin_mode": "NETTING",
                "max_holding_minutes": 999,
            }
            store.save_trade_execution(changed)

            execution = store.trade_execution(str(record["setup_id"]))
            assert execution is not None
            self.assertEqual(execution["status"], "CLOSED")
            self.assertEqual(execution["strategy_id"], "D7")
            self.assertEqual(execution["strategy_version"], "1.7")
            self.assertEqual(execution["direction_profile"], "ALL")
            self.assertEqual(execution["execution_profile"], "DEMO_AUTO")
            self.assertEqual(execution["magic"], 260814)
            self.assertEqual(execution["position_identifier"], 9009)
            self.assertEqual(execution["initial_volume"], 0.08)
            self.assertEqual(execution["initial_stop_price"], 4374.2)
            self.assertEqual(execution["initial_take_profit_price"], 4397.8)
            self.assertEqual(execution["initial_risk_distance"], 5.9)
            self.assertEqual(execution["management_policy"], "R_LOCK_V1")
            self.assertEqual(execution["management_policy_version"], "1")
            self.assertEqual(
                json.loads(execution["management_policy_json"]),
                {"r1_lock_r": 0.25, "r2_lock_r": 1.0},
            )
            self.assertEqual(execution["account_login"], "108098316")
            self.assertEqual(execution["account_server"], "XMGlobal-MT5 5")
            self.assertEqual(execution["account_scope"], "demo")
            self.assertEqual(execution["account_margin_mode"], "HEDGING")
            self.assertEqual(execution["max_holding_minutes"], 180)

            self.assertTrue(
                store.update_trade_execution_management(
                    str(record["setup_id"]),
                    remaining_volume=0.04,
                    current_stop_price=4381.575,
                    current_take_profit_price=4397.8,
                    highest_observed_r=1.25,
                    r1_reached_at=NOW,
                    r1_protection_status="confirmed",
                    last_broker_sync_at=NOW,
                )
            )
            self.assertTrue(
                store.update_trade_execution_management(
                    str(record["setup_id"]),
                    highest_observed_r=0.75,
                    r1_reached_at=NOW + timedelta(hours=1),
                )
            )
            managed = store.trade_execution(str(record["setup_id"]))
            assert managed is not None
            self.assertEqual(managed["remaining_volume"], 0.04)
            self.assertEqual(managed["current_stop_price"], 4381.575)
            self.assertEqual(managed["current_take_profit_price"], 4397.8)
            self.assertEqual(managed["highest_observed_r"], 1.25)
            self.assertEqual(managed["r1_reached_at"], "2026-08-15T04:30:00Z")
            self.assertEqual(managed["r1_protection_status"], "CONFIRMED")


class GoldMPositionActionLedgerTests(unittest.TestCase):
    def test_open_execution_intent_and_action_are_atomic_and_replay_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            record = _new_open_intent_record(store, "open-setup")

            execution, action, created = store.create_open_execution_intent(
                record,
                action_idempotency_key="open:open-setup",
                action_payload={"run_id": "run-1"},
            )
            replay_execution, replay_action, replay_created = (
                store.create_open_execution_intent(
                    record,
                    action_idempotency_key="open:open-setup",
                    action_payload={"run_id": "run-1"},
                )
            )

            self.assertTrue(created)
            self.assertFalse(replay_created)
            self.assertEqual(execution["setup_id"], replay_execution["setup_id"])
            self.assertEqual(action["id"], replay_action["id"])
            self.assertEqual(action["action_type"], "OPEN")
            self.assertIsNone(action["position_ticket"])
            self.assertIsNone(action["position_identifier"])
            self.assertEqual(action["payload"]["client_tag"], "open-client")
            self.assertEqual(store.active_trade_executions()[0]["status"], "OPEN_PENDING")

            with self.assertRaisesRegex(ValueError, "immutable strategy_version"):
                store.create_open_execution_intent(
                    {**record, "strategy_version": "different"},
                    action_idempotency_key="open:open-setup",
                    action_payload={"run_id": "run-1"},
                )
            with self.assertRaisesRegex(ValueError, "requires account_margin_mode"):
                store.create_open_execution_intent(
                    {**record, "setup_id": "missing-margin", "account_margin_mode": None},
                    action_idempotency_key="open:missing-margin",
                )

    def test_guarded_open_intent_rejects_same_batch_terminal_and_stale_setup(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            terminal_record = _new_active_open_intent_record(store, "terminal-before-open")
            signal_id = int(terminal_record["signal_outbox_id"])
            terminal_id = _enqueue_terminal_event(
                store,
                "terminal-before-open",
                event_type="SNIPER_OUTCOME",
                event_key="SNIPER_OUTCOME:terminal-before-open",
            )
            self.assertGreater(terminal_id, signal_id)

            execution, action, created, disposition = (
                store.create_open_execution_intent_if_setup_current(
                    terminal_record,
                    action_idempotency_key="open:terminal-before-open",
                    expected_signal_outbox_id=signal_id,
                )
            )
            self.assertEqual(disposition, "TERMINAL_EVENT")
            self.assertFalse(created)
            self.assertIsNone(execution)
            self.assertIsNone(action)
            self.assertIsNone(store.trade_execution("terminal-before-open"))
            self.assertIsNone(store.position_action("open:terminal-before-open"))

            store.save_setup(
                SetupRecord(
                    setup_id="terminal-before-signal",
                    symbol="GOLD.i#",
                    side="BUY",
                    level=4380.1,
                    breakout_at=NOW,
                    state=SetupState.ACTIVE_SIGNAL,
                )
            )
            earlier_terminal_id = _enqueue_terminal_event(
                store,
                "terminal-before-signal",
                event_type="SNIPER_EARLY_CANCELLED",
                event_key="SNIPER_EARLY_CANCELLED:before-signal",
            )
            reverse_record = _new_active_open_intent_record(
                store, "terminal-before-signal"
            )
            self.assertLess(
                earlier_terminal_id, int(reverse_record["signal_outbox_id"])
            )
            reverse = store.create_open_execution_intent_if_setup_current(
                reverse_record,
                action_idempotency_key="open:terminal-before-signal",
                expected_signal_outbox_id=int(reverse_record["signal_outbox_id"]),
            )
            self.assertEqual(reverse, (None, None, False, "TERMINAL_EVENT"))

            stale_record = _new_active_open_intent_record(store, "stale-active-signal")
            store.save_setup(
                SetupRecord(
                    setup_id="stale-active-signal",
                    symbol="GOLD.i#",
                    side="BUY",
                    level=4380.1,
                    breakout_at=NOW,
                    state=SetupState.CANCELLED,
                    reason="cancelled before execution writer resumed",
                )
            )
            stale = store.create_open_execution_intent_if_setup_current(
                stale_record,
                action_idempotency_key="open:stale-active-signal",
                expected_signal_outbox_id=int(stale_record["signal_outbox_id"]),
            )
            self.assertEqual(stale, (None, None, False, "STALE_SETUP"))
            self.assertIsNone(store.trade_execution("stale-active-signal"))

    def test_terminal_event_atomically_cancels_pending_open_and_replays_after_restart(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "signal.db"
            store = SignalStore(path)
            store.initialize()
            record = _new_active_open_intent_record(store, "cancel-pending-open")
            created = store.create_open_execution_intent_if_setup_current(
                record,
                action_idempotency_key="open:cancel-pending-open",
                expected_signal_outbox_id=int(record["signal_outbox_id"]),
            )
            self.assertEqual(created[3], "CREATED")
            claimed = store.claim_position_action(
                lease_owner="crashed-entry-worker", now=NOW
            )
            assert claimed is not None
            terminal_id = _enqueue_terminal_event(
                store,
                "cancel-pending-open",
                event_type="SNIPER_EARLY_CANCELLED",
                event_key="SNIPER_EARLY_CANCELLED:cancel-pending-open",
            )

            restarted = SignalStore(path)
            restarted.initialize()
            result = restarted.cancel_pending_open_for_terminal_event(
                "cancel-pending-open",
                terminal_outbox_id=terminal_id,
                reason="pattern invalidated before broker submission",
            )
            replay = restarted.cancel_pending_open_for_terminal_event(
                "cancel-pending-open",
                terminal_outbox_id=terminal_id,
                reason="pattern invalidated before broker submission",
            )

            self.assertEqual(result["disposition"], "CANCELLED")
            self.assertEqual(replay["disposition"], "CANCELLED")
            self.assertEqual(result["execution"]["status"], "CANCELLED")
            self.assertEqual(result["action"]["status"], "FAILED")
            self.assertEqual(
                result["execution"]["cancelled_by_terminal_outbox_id"], terminal_id
            )
            self.assertFalse(
                restarted.retry_position_action("open:cancel-pending-open")
            )
            self.assertFalse(
                restarted.mark_position_action_submitted(
                    "open:cancel-pending-open",
                    lease_owner="crashed-entry-worker",
                )
            )
            self.assertIsNone(restarted.claim_position_action(lease_owner="late-worker"))
            with self.assertRaisesRegex(ValueError, "immutable receipt"):
                restarted.cancel_pending_open_for_terminal_event(
                    "cancel-pending-open",
                    terminal_outbox_id=terminal_id,
                    reason="different replay reason",
                )
            with restarted._connect() as connection:
                receipt_count = connection.execute(
                    "SELECT COUNT(*) FROM trade_event_receipts WHERE outbox_id = ?",
                    (terminal_id,),
                ).fetchone()[0]
            self.assertEqual(receipt_count, 1)

    def test_submitted_open_latches_first_terminal_for_deferred_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "signal.db"
            store = SignalStore(path)
            store.initialize()
            record = _new_active_open_intent_record(store, "defer-submitted-open")
            store.create_open_execution_intent_if_setup_current(
                record,
                action_idempotency_key="open:defer-submitted-open",
                expected_signal_outbox_id=int(record["signal_outbox_id"]),
            )
            claimed = store.claim_position_action(lease_owner="entry-worker", now=NOW)
            assert claimed is not None
            self.assertTrue(
                store.mark_position_action_submitted(
                    claimed["idempotency_key"], lease_owner="entry-worker"
                )
            )
            store.save_trade_execution({**record, "status": "OPEN_SUBMITTED"})
            terminal_id = _enqueue_terminal_event(
                store,
                "defer-submitted-open",
                event_type="SNIPER_OUTCOME",
                event_key="SNIPER_OUTCOME:defer-submitted-open",
            )

            result = store.cancel_pending_open_for_terminal_event(
                "defer-submitted-open",
                terminal_outbox_id=terminal_id,
                reason="model outcome arrived while broker result was ambiguous",
            )
            self.assertEqual(result["disposition"], "DEFERRED_CLOSE")
            self.assertEqual(result["execution"]["status"], "OPEN_SUBMITTED")
            self.assertEqual(result["action"]["status"], "SUBMITTED")
            self.assertEqual(
                result["deferred_close_reason"],
                "model outcome arrived while broker result was ambiguous",
            )
            second_terminal_id = _enqueue_terminal_event(
                store,
                "defer-submitted-open",
                event_type="SNIPER_EARLY_CANCELLED",
                event_key="SNIPER_EARLY_CANCELLED:defer-submitted-open",
            )
            second = store.cancel_pending_open_for_terminal_event(
                "defer-submitted-open",
                terminal_outbox_id=second_terminal_id,
                reason="later cancellation must not rewrite the first close cause",
            )
            self.assertEqual(
                second["deferred_close_reason"],
                "model outcome arrived while broker result was ambiguous",
            )

            restarted = SignalStore(path)
            restarted.initialize()
            confirmed = restarted.confirm_trade_position(
                "defer-submitted-open",
                action_idempotency_key="open:defer-submitted-open",
                **_confirmation_values(),
            )
            self.assertEqual(confirmed["status"], "FILLED")
            self.assertEqual(
                confirmed["deferred_close_terminal_outbox_id"], terminal_id
            )
            self.assertEqual(
                confirmed["deferred_close_reason"],
                "model outcome arrived while broker result was ambiguous",
            )

    def test_initial_protection_confirmation_closes_related_open_fence_atomically(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            record = _new_active_open_intent_record(store, "protected-confirm")
            store.create_open_execution_intent_if_setup_current(
                record,
                action_idempotency_key="open:protected-confirm",
                expected_signal_outbox_id=int(record["signal_outbox_id"]),
            )
            open_claim = store.claim_position_action(lease_owner="entry-worker", now=NOW)
            assert open_claim is not None
            self.assertTrue(
                store.mark_position_action_submitted(
                    open_claim["idempotency_key"], lease_owner="entry-worker"
                )
            )
            self.assertTrue(
                store.mark_position_action_unknown(
                    "open:protected-confirm",
                    error="broker open outcome requires reconciliation",
                )
            )
            store.save_trade_execution({**record, "status": "UNPROTECTED"})
            _, created = store.create_position_action(
                idempotency_key="protect:protected-confirm",
                setup_id="protected-confirm",
                action_type="SET_INITIAL_PROTECTION",
                position_ticket=3003,
                position_identifier=7001,
                payload={"stop": 4374.2, "take_profit": 4397.8},
                management_policy="D7_R_LOCK",
                account_login="108098316",
                account_server="XMGlobal-MT5 5",
                account_scope="demo",
            )
            self.assertTrue(created)
            protection_claim = store.claim_position_action(
                lease_owner="protection-worker", now=NOW
            )
            assert protection_claim is not None
            self.assertEqual(
                protection_claim["idempotency_key"], "protect:protected-confirm"
            )
            self.assertTrue(
                store.mark_position_action_submitted(
                    protection_claim["idempotency_key"],
                    lease_owner="protection-worker",
                )
            )

            confirmed = store.confirm_trade_position(
                "protected-confirm",
                action_idempotency_key="protect:protected-confirm",
                **_confirmation_values(),
            )
            replay = store.confirm_trade_position(
                "protected-confirm",
                action_idempotency_key="protect:protected-confirm",
                **_confirmation_values(),
            )
            self.assertEqual(confirmed["status"], "FILLED")
            self.assertEqual(replay["position_identifier"], 7001)
            self.assertEqual(
                store.position_action("open:protected-confirm")["status"], "CONFIRMED"
            )
            self.assertEqual(
                store.position_action("protect:protected-confirm")["status"],
                "CONFIRMED",
            )

    def test_confirmation_replay_repairs_legacy_filled_open_fence_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "signal.db"
            store = SignalStore(path)
            store.initialize()
            record = _new_active_open_intent_record(store, "repair-confirm-split")
            store.create_open_execution_intent_if_setup_current(
                record,
                action_idempotency_key="open:repair-confirm-split",
                expected_signal_outbox_id=int(record["signal_outbox_id"]),
            )
            open_claim = store.claim_position_action(lease_owner="entry-worker", now=NOW)
            assert open_claim is not None
            self.assertTrue(
                store.mark_position_action_submitted(
                    open_claim["idempotency_key"], lease_owner="entry-worker"
                )
            )
            self.assertTrue(
                store.mark_position_action_unknown(
                    "open:repair-confirm-split", error="process stopped after broker send"
                )
            )
            store.save_trade_execution({**record, "status": "UNPROTECTED"})
            store.create_position_action(
                idempotency_key="protect:repair-confirm-split",
                setup_id="repair-confirm-split",
                action_type="SET_INITIAL_PROTECTION",
                position_ticket=3003,
                position_identifier=7001,
                payload={"stop": 4374.2, "take_profit": 4397.8},
                management_policy="D7_R_LOCK",
                account_login="108098316",
                account_server="XMGlobal-MT5 5",
                account_scope="demo",
            )
            protection_claim = store.claim_position_action(
                lease_owner="protection-worker", now=NOW
            )
            assert protection_claim is not None
            self.assertTrue(
                store.mark_position_action_submitted(
                    protection_claim["idempotency_key"],
                    lease_owner="protection-worker",
                )
            )

            # Reproduce a database written by the former two-transaction flow:
            # the execution and protection action committed, but the OPEN fence did not.
            with store._connect() as connection:
                connection.execute(
                    """
                    UPDATE trade_executions
                    SET status = 'FILLED', position_ticket = 3003,
                        position_identifier = 7001, actual_entry = 4380.1,
                        opened_at = ?, volume = 0.08, initial_volume = 0.08,
                        remaining_volume = 0.08, initial_stop_price = 4374.2,
                        current_stop_price = 4374.2,
                        initial_take_profit_price = 4397.8,
                        current_take_profit_price = 4397.8,
                        initial_risk_distance = 5.9, last_broker_sync_at = ?
                    WHERE setup_id = 'repair-confirm-split'
                    """,
                    ("2026-08-15T04:30:00Z", "2026-08-15T04:30:00Z"),
                )
                connection.execute(
                    """
                    UPDATE position_actions
                    SET status = 'CONFIRMED', position_ticket = 3003,
                        position_identifier = 7001, broker_position_ticket = 3003,
                        confirmed_at = ?
                    WHERE idempotency_key = 'protect:repair-confirm-split'
                    """,
                    ("2026-08-15T04:30:00Z",),
                )

            restarted = SignalStore(path)
            restarted.initialize()
            repaired = restarted.confirm_trade_position(
                "repair-confirm-split",
                action_idempotency_key="protect:repair-confirm-split",
                **_confirmation_values(),
            )
            self.assertEqual(repaired["status"], "FILLED")
            self.assertEqual(
                restarted.position_action("open:repair-confirm-split")["status"],
                "CONFIRMED",
            )

    def test_open_action_has_no_fake_ticket_and_mutations_require_a_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            action, created = store.create_position_action(
                idempotency_key="open:standalone",
                setup_id="setup-1",
                action_type="OPEN",
                payload={"client_tag": "abc"},
            )
            self.assertTrue(created)
            self.assertIsNone(action["position_ticket"])
            self.assertIsNone(action["position_identifier"])
            with self.assertRaisesRegex(ValueError, "must not have a position target"):
                store.create_position_action(
                    idempotency_key="open:bad-target",
                    action_type="OPEN",
                    position_ticket=1,
                )
            with self.assertRaisesRegex(ValueError, "requires a positive ticket"):
                store.create_position_action(
                    idempotency_key="close:no-target",
                    action_type="CLOSE_FULL",
                )

    def test_confirm_trade_position_is_atomic_idempotent_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            record = _new_open_intent_record(store, "confirm-setup")
            store.create_open_execution_intent(
                record,
                action_idempotency_key="open:confirm-setup",
            )
            claimed = store.claim_position_action(lease_owner="entry-worker", now=NOW)
            assert claimed is not None
            self.assertTrue(
                store.mark_position_action_submitted(
                    claimed["idempotency_key"], lease_owner="entry-worker"
                )
            )
            confirmation = _confirmation_values()

            confirmed = store.confirm_trade_position(
                "confirm-setup",
                action_idempotency_key="open:confirm-setup",
                **confirmation,
            )
            replay = store.confirm_trade_position(
                "confirm-setup",
                action_idempotency_key="open:confirm-setup",
                **confirmation,
            )

            self.assertEqual(confirmed["status"], "FILLED")
            self.assertEqual(replay["position_identifier"], 7001)
            self.assertEqual(confirmed["initial_volume"], 0.08)
            self.assertEqual(confirmed["remaining_volume"], 0.08)
            self.assertEqual(confirmed["initial_take_profit_price"], 4397.8)
            self.assertEqual(confirmed["current_take_profit_price"], 4397.8)
            self.assertEqual(confirmed["max_holding_minutes"], 180)
            self.assertAlmostEqual(confirmed["initial_risk_distance"], 5.9)
            action = store.position_action("open:confirm-setup")
            assert action is not None
            self.assertEqual(action["status"], "CONFIRMED")
            self.assertEqual(action["position_identifier"], 7001)
            self.assertEqual(action["broker_position_ticket"], 3003)

            with self.assertRaisesRegex(ValueError, "stable identifier"):
                store.confirm_trade_position(
                    "confirm-setup",
                    action_idempotency_key="open:confirm-setup",
                    **{**confirmation, "position_identifier": 9999},
                )
            with self.assertRaisesRegex(ValueError, "BUY take-profit"):
                store.confirm_trade_position(
                    "confirm-setup",
                    action_idempotency_key="open:confirm-setup",
                    **{
                        **confirmation,
                        "initial_take_profit_price": 4370.0,
                        "current_take_profit_price": 4370.0,
                    },
                )
            with self.assertRaisesRegex(ValueError, "account_margin_mode"):
                store.confirm_trade_position(
                    "confirm-setup",
                    action_idempotency_key="open:confirm-setup",
                    **{**confirmation, "account_margin_mode": "NETTING"},
                )

    def test_stale_execution_writer_cannot_regress_confirmed_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            stale_record, confirmed = _create_confirmed_execution(store, "stale-setup")

            store.save_trade_execution(
                {
                    **stale_record,
                    "status": "OPEN_PENDING",
                    "volume": 9.0,
                    "position_ticket": 9999,
                    "actual_entry": 1.0,
                    "last_error": "stale writer",
                }
            )

            persisted = store.trade_execution("stale-setup")
            assert persisted is not None
            self.assertEqual(persisted["status"], "FILLED")
            self.assertEqual(persisted["position_ticket"], confirmed["position_ticket"])
            self.assertEqual(persisted["position_identifier"], 7001)
            self.assertEqual(persisted["actual_entry"], 4380.1)
            self.assertEqual(persisted["volume"], 0.08)
            self.assertEqual(persisted["initial_volume"], 0.08)
            self.assertEqual(persisted["initial_take_profit_price"], 4397.8)
            self.assertEqual(persisted["current_take_profit_price"], 4397.8)
            self.assertIsNone(persisted["last_error"])

            store.save_trade_execution(
                {
                    **persisted,
                    "status": "CLOSED",
                    "closed_at": NOW + timedelta(hours=1),
                    "exit_price": 4390.0,
                    "profit_cash": 79.2,
                    "close_reason": "R3_TARGET",
                    "closed_by": "strategy_auto",
                }
            )
            first_close = store.trade_execution("stale-setup")
            assert first_close is not None
            store.save_trade_execution(
                {
                    **first_close,
                    "closed_at": NOW + timedelta(hours=2),
                    "exit_price": 1.0,
                    "profit_cash": -999.0,
                    "close_reason": "stale-close",
                    "closed_by": "stale-writer",
                    "last_error": "stale closed replay",
                }
            )
            final_close = store.trade_execution("stale-setup")
            assert final_close is not None
            self.assertEqual(final_close["closed_at"], "2026-08-15T05:30:00Z")
            self.assertEqual(final_close["exit_price"], 4390.0)
            self.assertEqual(final_close["profit_cash"], 79.2)
            self.assertEqual(final_close["close_reason"], "R3_TARGET")
            self.assertEqual(final_close["closed_by"], "strategy_auto")
            self.assertIsNone(final_close["last_error"])

    def test_ticket_churn_sync_is_stable_identifier_and_account_guarded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            _, _ = _create_confirmed_execution(store, "churn-setup")
            observed = {
                "position_ticket": 4004,
                "position_identifier": 7001,
                "symbol": "GOLD.i#",
                "side": "buy",
                "comment": "GMS: open-client",
                "remaining_volume": 0.04,
                "current_stop_price": 4381.575,
                "current_take_profit_price": 4397.8,
                "magic": 260814,
                "account_login": "108098316",
                "account_server": "XMGlobal-MT5 5",
                "account_scope": "demo",
                "last_broker_sync_at": NOW + timedelta(minutes=1),
            }

            refreshed = store.sync_trade_position_binding("churn-setup", **observed)
            self.assertEqual(refreshed["position_ticket"], 4004)
            self.assertEqual(refreshed["position_identifier"], 7001)
            self.assertEqual(refreshed["remaining_volume"], 0.04)
            self.assertEqual(refreshed["current_stop_price"], 4381.575)
            self.assertEqual(refreshed["current_take_profit_price"], 4397.8)

            replay = store.confirm_trade_position(
                "churn-setup",
                action_idempotency_key="open:churn-setup",
                **_confirmation_values(),
            )
            self.assertEqual(replay["position_ticket"], 4004)

            for field, bad_value, expected_error in (
                ("position_identifier", 9999, "stable identifier"),
                ("account_login", "999", "account_login"),
                ("magic", 1, "magic"),
                ("comment", "unrelated", "client tag"),
                ("current_take_profit_price", 4370.0, "take-profit"),
            ):
                with self.subTest(field=field):
                    with self.assertRaisesRegex(ValueError, expected_error):
                        store.sync_trade_position_binding(
                            "churn-setup", **{**observed, field: bad_value}
                        )
            persisted = store.trade_execution("churn-setup")
            assert persisted is not None
            self.assertEqual(persisted["position_ticket"], 4004)
            self.assertEqual(persisted["remaining_volume"], 0.04)

    def test_management_stage_and_finalize_are_atomic_replay_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            _, _ = _create_confirmed_execution(store, "manage-setup")

            execution, action, created = store.stage_position_management_action(
                "manage-setup",
                action_idempotency_key="manage:setup:r2",
                action_type="MODIFY_SL",
                milestone="R2",
                reached_milestones=("R1", "R2"),
                reached_at=NOW + timedelta(minutes=2),
                current_r=2.1,
                payload={"target_stop": 4386.0},
            )
            replay_execution, replay_action, replay_created = (
                store.stage_position_management_action(
                    "manage-setup",
                    action_idempotency_key="manage:setup:r2",
                    action_type="MODIFY_SL",
                    milestone="R2",
                    reached_milestones=("R1", "R2"),
                    reached_at=NOW + timedelta(minutes=2),
                    current_r=2.1,
                    payload={"target_stop": 4386.0},
                )
            )
            self.assertTrue(created)
            self.assertFalse(replay_created)
            self.assertEqual(action["id"], replay_action["id"])
            self.assertEqual(execution["r1_reached_at"], "2026-08-15T04:32:00Z")
            self.assertEqual(execution["r2_reached_at"], "2026-08-15T04:32:00Z")
            self.assertEqual(execution["r2_protection_status"], "PENDING")
            self.assertEqual(replay_execution["highest_observed_r"], 2.1)

            claimed = store.claim_position_action(
                lease_owner="manager", now=NOW + timedelta(minutes=3)
            )
            assert claimed is not None
            self.assertTrue(
                store.mark_position_action_submitted(
                    claimed["idempotency_key"], lease_owner="manager"
                )
            )
            with self.assertRaisesRegex(ValueError, "initial volume|must not increase"):
                store.finalize_position_management_action(
                    "manage:setup:r2",
                    setup_id="manage-setup",
                    outcome="CONFIRMED",
                    milestone="R2",
                    remaining_volume=0.09,
                    current_stop_price=4386.0,
                )
            unchanged_action = store.position_action("manage:setup:r2")
            unchanged_execution = store.trade_execution("manage-setup")
            assert unchanged_action is not None and unchanged_execution is not None
            self.assertEqual(unchanged_action["status"], "SUBMITTED")
            self.assertEqual(unchanged_execution["r2_protection_status"], "PENDING")

            unknown_execution, unknown_action = (
                store.finalize_position_management_action(
                    "manage:setup:r2",
                    setup_id="manage-setup",
                    outcome="UNKNOWN",
                    milestone="R2",
                    remaining_volume=0.08,
                    current_stop_price=4374.2,
                    last_broker_sync_at=NOW + timedelta(minutes=4),
                    error="broker response lost",
                )
            )
            self.assertEqual(unknown_action["status"], "UNKNOWN")
            self.assertEqual(unknown_execution["r2_protection_status"], "UNKNOWN")
            exact_execution, exact_action = store.finalize_position_management_action(
                "manage:setup:r2",
                setup_id="manage-setup",
                outcome="UNKNOWN",
                milestone="R2",
                remaining_volume=0.08,
                current_stop_price=4374.2,
                last_broker_sync_at=NOW + timedelta(minutes=4),
                error="broker response lost",
            )
            self.assertEqual(exact_action["id"], unknown_action["id"])
            self.assertEqual(exact_execution["r2_protection_status"], "UNKNOWN")

            projection = store.claim_position_action_projection(
                lease_owner="projector",
                statuses=("UNKNOWN",),
                now=NOW + timedelta(minutes=5),
            )
            assert projection is not None
            self.assertEqual(projection["idempotency_key"], "manage:setup:r2")
            self.assertTrue(
                store.mark_position_action_projected(
                    "manage:setup:r2", lease_owner="projector"
                )
            )
            confirmed_execution, confirmed_action = (
                store.finalize_position_management_action(
                    "manage:setup:r2",
                    setup_id="manage-setup",
                    outcome="CONFIRMED",
                    milestone="R2",
                    remaining_volume=0.08,
                    current_stop_price=4386.0,
                    current_take_profit_price=4397.8,
                    last_broker_sync_at=NOW + timedelta(minutes=6),
                )
            )
            self.assertEqual(confirmed_execution["r2_protection_status"], "CONFIRMED")
            self.assertEqual(confirmed_execution["current_take_profit_price"], 4397.8)
            self.assertEqual(confirmed_action["status"], "CONFIRMED")
            self.assertIsNone(confirmed_action["projected_at"])

            repaired_execution, repair_action, repair_created = (
                store.stage_position_management_action(
                    "manage-setup",
                    action_idempotency_key="manage:setup:r2:repair-1",
                    action_type="MODIFY_SL",
                    milestone="R2",
                    reached_at=NOW + timedelta(minutes=7),
                    current_r=1.5,
                    payload={"target_stop": 4386.0},
                    repair=True,
                )
            )
            self.assertTrue(repair_created)
            self.assertTrue(repair_action["payload"]["repair"])
            self.assertEqual(repaired_execution["r2_protection_status"], "PENDING")

    def test_management_stage_rolls_back_on_idempotency_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            _, _ = _create_confirmed_execution(store, "collision-setup")
            store.create_position_action(
                idempotency_key="manage:collision:r1",
                setup_id="collision-setup",
                position_identifier=7001,
                action_type="MODIFY_SL",
                payload={"target_stop": 1.0},
                management_policy="D7_R_LOCK",
                account_login="108098316",
                account_server="XMGlobal-MT5 5",
                account_scope="demo",
            )

            with self.assertRaisesRegex(ValueError, "replay mismatch"):
                store.stage_position_management_action(
                    "collision-setup",
                    action_idempotency_key="manage:collision:r1",
                    action_type="MODIFY_SL",
                    milestone="R1",
                    reached_milestones=("R1",),
                    reached_at=NOW,
                    current_r=1.0,
                    payload={"target_stop": 4381.0},
                )
            persisted = store.trade_execution("collision-setup")
            assert persisted is not None
            self.assertIsNone(persisted["r1_reached_at"])
            self.assertIsNone(persisted["r1_protection_status"])

    def test_close_action_outcome_projects_execution_status_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            _, _ = _create_confirmed_execution(store, "close-setup")
            store.stage_position_management_action(
                "close-setup",
                action_idempotency_key="manage:close:r3",
                action_type="CLOSE_FULL",
                milestone="R3",
                reached_milestones=("R3",),
                reached_at=NOW,
                current_r=3.1,
                payload={"volume": 0.08},
            )
            claimed = store.claim_position_action(lease_owner="closer", now=NOW)
            assert claimed is not None
            self.assertTrue(
                store.mark_position_action_submitted(
                    claimed["idempotency_key"], lease_owner="closer"
                )
            )

            unknown_execution, _ = store.finalize_position_management_action(
                "manage:close:r3",
                setup_id="close-setup",
                outcome="UNKNOWN",
                milestone="R3",
                remaining_volume=0.08,
                current_stop_price=4374.2,
                current_take_profit_price=4397.8,
                error="close transport ambiguous",
            )
            self.assertEqual(unknown_execution["status"], "CLOSE_UNKNOWN")
            self.assertEqual(unknown_execution["r3_close_status"], "UNKNOWN")

            confirmed_execution, confirmed_action = (
                store.finalize_position_management_action(
                    "manage:close:r3",
                    setup_id="close-setup",
                    outcome="CONFIRMED",
                    milestone="R3",
                    remaining_volume=0.0,
                    broker_reference="position absent",
                )
            )
            self.assertEqual(confirmed_action["status"], "CONFIRMED")
            self.assertEqual(confirmed_execution["status"], "CLOSE_SUBMITTED")
            self.assertEqual(confirmed_execution["remaining_volume"], 0.0)
            self.assertEqual(confirmed_execution["r3_close_status"], "CONFIRMED")

    def test_projection_claim_skips_more_than_one_page_of_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            with store._connect() as connection:
                connection.executemany(
                    """
                    INSERT INTO position_actions (
                        idempotency_key, position_identifier, action_type, status,
                        payload_json, last_error, created_at, failed_at,
                        projected_at, updated_at
                    ) VALUES (?, 7001, 'CLOSE_FULL', 'FAILED', '{}', 'old', ?, ?, ?, ?)
                    """,
                    [
                        (
                            f"old-projected:{index}",
                            NOW.isoformat(),
                            NOW.isoformat(),
                            NOW.isoformat(),
                            NOW.isoformat(),
                        )
                        for index in range(101)
                    ],
                )
            store.create_position_action(
                idempotency_key="new-unprojected",
                position_identifier=7001,
                action_type="CLOSE_FULL",
            )
            self.assertTrue(
                store.mark_position_action_failed("new-unprojected", "new failure")
            )

            claimed = store.claim_position_action_projection(
                lease_owner="projector", statuses=("FAILED",), now=NOW
            )
            assert claimed is not None
            self.assertEqual(claimed["idempotency_key"], "new-unprojected")
            self.assertEqual(claimed["projection_attempt_count"], 1)
            self.assertTrue(
                store.mark_position_action_projected(
                    "new-unprojected", lease_owner="projector", projected_at=NOW
                )
            )
            self.assertTrue(
                store.mark_position_action_projected(
                    "new-unprojected", lease_owner="projector", projected_at=NOW
                )
            )
            self.assertIsNone(
                store.claim_position_action_projection(
                    lease_owner="projector", statuses=("FAILED",), now=NOW
                )
            )

    def test_action_intent_is_unique_and_status_updates_keep_broker_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            action, created = store.create_position_action(
                idempotency_key="position:3003:r1-lock",
                setup_id="setup-1",
                position_ticket=3003,
                action_type="modify_sl",
                payload={"stop_price": 4381.575, "milestone": "R1"},
                management_policy="R_LOCK_V1",
                account_login=108098316,
                account_server="XMGlobal-MT5 5",
                account_scope="demo",
                created_at=NOW,
            )
            duplicate, duplicate_created = store.create_position_action(
                idempotency_key="position:3003:r1-lock",
                setup_id="setup-1",
                position_ticket=3003,
                action_type="MODIFY_SL",
                payload={"milestone": "R1", "stop_price": 4381.575},
                management_policy="R_LOCK_V1",
                account_login="108098316",
                account_server="XMGlobal-MT5 5",
                account_scope="demo",
                created_at=NOW + timedelta(minutes=5),
            )

            self.assertTrue(created)
            self.assertFalse(duplicate_created)
            self.assertEqual(action["id"], duplicate["id"])
            self.assertEqual(action["payload"], {"milestone": "R1", "stop_price": 4381.575})
            with self.assertRaisesRegex(ValueError, "different intent"):
                store.create_position_action(
                    idempotency_key="position:3003:r1-lock",
                    setup_id="setup-1",
                    position_ticket=3003,
                    action_type="MODIFY_SL",
                    payload={"stop_price": 4382.0, "milestone": "R1"},
                )

            claimed = store.claim_position_action(lease_owner="worker-a", now=NOW)
            assert claimed is not None
            self.assertEqual(claimed["attempt_count"], 1)
            self.assertEqual(claimed["lease_owner"], "worker-a")
            self.assertFalse(
                store.mark_position_action_submitted(claimed["idempotency_key"])
            )
            self.assertTrue(
                store.mark_position_action_submitted(
                    claimed["idempotency_key"],
                    lease_owner="worker-a",
                    broker_order_ticket=4004,
                    broker_retcode=10009,
                    broker_reference="request-abc",
                )
            )
            self.assertTrue(
                store.mark_position_action_unknown(
                    claimed["idempotency_key"], "confirmation timed out"
                )
            )
            projection = store.claim_position_action_projection(
                lease_owner="projector", statuses=("UNKNOWN",), now=NOW
            )
            assert projection is not None
            self.assertTrue(
                store.mark_position_action_projected(
                    claimed["idempotency_key"], lease_owner="projector", projected_at=NOW
                )
            )
            self.assertTrue(
                store.mark_position_action_confirmed(
                    claimed["idempotency_key"], broker_deal_ticket=5005
                )
            )

            final = store.position_action(claimed["idempotency_key"])
            assert final is not None
            self.assertEqual(final["status"], "CONFIRMED")
            self.assertEqual(final["broker_order_ticket"], 4004)
            self.assertEqual(final["broker_deal_ticket"], 5005)
            self.assertEqual(final["broker_retcode"], 10009)
            self.assertEqual(final["broker_reference"], "request-abc")
            self.assertIsNone(final["last_error"])
            self.assertIsNone(final["lease_owner"])
            self.assertIsNotNone(final["submitted_at"])
            self.assertIsNotNone(final["unknown_at"])
            self.assertIsNotNone(final["confirmed_at"])
            self.assertIsNone(final["projected_at"])

    def test_failed_action_requires_explicit_retry_and_preserves_attempt_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            store.create_position_action(
                idempotency_key="position:3003:partial-r2",
                position_ticket=3003,
                action_type="PARTIAL_CLOSE",
                payload={"volume": 0.04},
            )

            first = store.claim_position_action(lease_owner="worker-a", now=NOW)
            assert first is not None
            self.assertTrue(
                store.mark_position_action_failed(
                    first["idempotency_key"],
                    "broker rejected",
                    lease_owner="worker-a",
                    broker_retcode=10016,
                )
            )
            self.assertIsNone(
                store.claim_position_action(
                    lease_owner="worker-b", now=NOW + timedelta(minutes=1)
                )
            )
            self.assertTrue(store.retry_position_action(first["idempotency_key"]))
            second = store.claim_position_action(
                lease_owner="worker-b", now=NOW + timedelta(minutes=1)
            )
            assert second is not None
            self.assertEqual(second["attempt_count"], 2)

    def test_expired_pending_lease_can_be_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            store.create_position_action(
                idempotency_key="position:3003:r2-lock",
                position_ticket=3003,
                action_type="MODIFY_SL",
            )

            self.assertIsNotNone(
                store.claim_position_action(
                    lease_owner="worker-a", lease_seconds=30, now=NOW
                )
            )
            self.assertIsNone(
                store.claim_position_action(
                    lease_owner="worker-b", now=NOW + timedelta(seconds=29)
                )
            )
            reclaimed = store.claim_position_action(
                lease_owner="worker-b", now=NOW + timedelta(seconds=31)
            )
            assert reclaimed is not None
            self.assertEqual(reclaimed["lease_owner"], "worker-b")
            self.assertEqual(reclaimed["attempt_count"], 2)

    def test_concurrent_claim_has_exactly_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            store.create_position_action(
                idempotency_key="position:3003:r3-close",
                position_ticket=3003,
                action_type="CLOSE",
            )
            barrier = threading.Barrier(2)

            def claim(owner: str) -> dict[str, object] | None:
                barrier.wait(timeout=5)
                return store.claim_position_action(lease_owner=owner, now=NOW)

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(claim, ("worker-a", "worker-b")))

            winners = [row for row in results if row is not None]
            self.assertEqual(len(winners), 1)
            persisted = store.position_action("position:3003:r3-close")
            assert persisted is not None
            self.assertEqual(persisted["attempt_count"], 1)
            self.assertEqual(persisted["lease_owner"], winners[0]["lease_owner"])


def _legacy_trade_execution_schema() -> str:
    return """
    PRAGMA foreign_keys = ON;
    CREATE TABLE setups (
        setup_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL,
        level REAL NOT NULL, breakout_at TEXT NOT NULL, state TEXT NOT NULL,
        retest_bars_elapsed INTEGER NOT NULL DEFAULT 0,
        reason TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
    );
    CREATE TABLE signal_outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        setup_id TEXT NOT NULL REFERENCES setups(setup_id),
        event_type TEXT NOT NULL, event_key TEXT NOT NULL,
        payload_json TEXT NOT NULL, created_at TEXT NOT NULL, sent_at TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 0, last_error TEXT,
        UNIQUE(setup_id, event_key)
    );
    CREATE TABLE trade_executions (
        setup_id TEXT PRIMARY KEY REFERENCES setups(setup_id),
        signal_outbox_id INTEGER NOT NULL UNIQUE REFERENCES signal_outbox(id),
        execution_mode TEXT NOT NULL, status TEXT NOT NULL, symbol TEXT NOT NULL,
        side TEXT NOT NULL, requested_entry REAL NOT NULL, stop_price REAL NOT NULL,
        target_price REAL NOT NULL, volume REAL NOT NULL DEFAULT 0,
        risk_cash REAL NOT NULL DEFAULT 0, expected_profit_cash REAL NOT NULL DEFAULT 0,
        valid_until TEXT, client_tag TEXT NOT NULL DEFAULT '', order_ticket INTEGER,
        deal_ticket INTEGER, position_ticket INTEGER, actual_entry REAL,
        opened_at TEXT, closed_at TEXT, exit_price REAL, profit_cash REAL,
        close_reason TEXT, closed_by TEXT, last_error TEXT, updated_at TEXT NOT NULL
    );
    """


def _execution_values(setup_id: str, outbox_id: int) -> tuple[object, ...]:
    return (
        setup_id,
        outbox_id,
        "demo",
        "FILLED",
        "GOLD.i#",
        "BUY",
        4380.1,
        4374.2,
        4397.8,
        0.08,
        47.2,
        141.6,
        "2026-08-15T05:00:00Z",
        "legacy-tag",
        1001,
        2002,
        3003,
        4380.1,
        "2026-08-15T04:30:00Z",
        None,
        None,
        None,
        None,
        None,
        None,
        "2026-08-15T04:30:00Z",
    )


def _execution_insert_sql() -> str:
    return """
        INSERT INTO trade_executions (
            setup_id, signal_outbox_id, execution_mode, status, symbol, side,
            requested_entry, stop_price, target_price, volume, risk_cash,
            expected_profit_cash, valid_until, client_tag, order_ticket,
            deal_ticket, position_ticket, actual_entry, opened_at, closed_at,
            exit_price, profit_cash, close_reason, closed_by, last_error, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """


def _base_execution_record(setup_id: str, outbox_id: int) -> dict[str, object]:
    names = (
        "setup_id",
        "signal_outbox_id",
        "execution_mode",
        "status",
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
        "order_ticket",
        "deal_ticket",
        "position_ticket",
        "actual_entry",
        "opened_at",
        "closed_at",
        "exit_price",
        "profit_cash",
        "close_reason",
        "closed_by",
        "last_error",
        "updated_at",
    )
    record = dict(zip(names, _execution_values(setup_id, outbox_id), strict=True))
    record.pop("updated_at")
    return record


def _save_setup_and_signal(store: SignalStore, setup_id: str) -> int:
    store.save_setup(
        SetupRecord(
            setup_id=setup_id,
            symbol="GOLD.i#",
            side="BUY",
            level=4380.1,
            breakout_at=NOW,
        )
    )
    store.enqueue(setup_id=setup_id, event_type="SNIPER_SIGNAL", payload={"entry": 4380.1})
    with store._connect() as connection:
        row = connection.execute(
            """
            SELECT id FROM signal_outbox
            WHERE setup_id = ? AND event_type = 'SNIPER_SIGNAL'
            ORDER BY id DESC LIMIT 1
            """,
            (setup_id,),
        ).fetchone()
    assert row is not None
    return int(row["id"])


def _new_open_intent_record(store: SignalStore, setup_id: str) -> dict[str, object]:
    record = _base_execution_record(
        setup_id, _save_setup_and_signal(store, setup_id)
    )
    record.update(
        {
            "status": "OPEN_PENDING",
            "client_tag": "open-client",
            "order_ticket": None,
            "deal_ticket": None,
            "position_ticket": None,
            "actual_entry": None,
            "opened_at": None,
            "volume": 0.08,
            "risk_cash": 47.2,
            "expected_profit_cash": 141.6,
            "strategy_id": "D7",
            "strategy_version": "1.8",
            "direction_profile": "ALL",
            "execution_profile": "DEMO_AUTO",
            "magic": 260814,
            "management_policy": "D7_R_LOCK",
            "management_policy_version": "1",
            "management_policy_json": {"r1_lock_r": 0.25, "r2_lock_r": 1.0},
            "max_holding_minutes": 180,
            "account_login": "108098316",
            "account_server": "XMGlobal-MT5 5",
            "account_scope": "demo",
            "account_margin_mode": "HEDGING",
        }
    )
    return record


def _new_active_open_intent_record(
    store: SignalStore, setup_id: str
) -> dict[str, object]:
    record = _new_open_intent_record(store, setup_id)
    store.save_setup(
        SetupRecord(
            setup_id=setup_id,
            symbol="GOLD.i#",
            side="BUY",
            level=4380.1,
            breakout_at=NOW,
            state=SetupState.ACTIVE_SIGNAL,
            reason="signal is current",
        )
    )
    return record


def _enqueue_terminal_event(
    store: SignalStore,
    setup_id: str,
    *,
    event_type: str,
    event_key: str,
) -> int:
    self_created = store.enqueue(
        setup_id=setup_id,
        event_type=event_type,
        event_key=event_key,
        payload={"reason": "terminal test event"},
    )
    if not self_created:
        raise AssertionError("terminal test event was unexpectedly deduplicated")
    with store._connect() as connection:
        row = connection.execute(
            """
            SELECT id FROM signal_outbox
            WHERE setup_id = ? AND event_key = ?
            """,
            (setup_id, event_key),
        ).fetchone()
    assert row is not None
    return int(row["id"])


def _confirmation_values() -> dict[str, object]:
    return {
        "position_ticket": 3003,
        "position_identifier": 7001,
        "symbol": "GOLD.i#",
        "side": "buy",
        "comment": "GMS: open-client",
        "actual_entry": 4380.1,
        "opened_at": NOW,
        "initial_volume": 0.08,
        "initial_stop_price": 4374.2,
        "current_stop_price": 4374.2,
        "initial_take_profit_price": 4397.8,
        "current_take_profit_price": 4397.8,
        "magic": 260814,
        "strategy_id": "D7",
        "strategy_version": "1.8",
        "direction_profile": "ALL",
        "execution_profile": "DEMO_AUTO",
        "management_policy": "D7_R_LOCK",
        "management_policy_version": "1",
        "management_policy_json": {"r1_lock_r": 0.25, "r2_lock_r": 1.0},
        "account_login": "108098316",
        "account_server": "XMGlobal-MT5 5",
        "account_scope": "demo",
        "account_margin_mode": "HEDGING",
        "last_broker_sync_at": NOW,
    }


def _create_confirmed_execution(
    store: SignalStore,
    setup_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    record = _new_open_intent_record(store, setup_id)
    store.create_open_execution_intent(
        record,
        action_idempotency_key=f"open:{setup_id}",
    )
    claimed = store.claim_position_action(lease_owner="entry-worker", now=NOW)
    assert claimed is not None
    assert store.mark_position_action_submitted(
        claimed["idempotency_key"], lease_owner="entry-worker"
    )
    confirmed = store.confirm_trade_position(
        setup_id,
        action_idempotency_key=f"open:{setup_id}",
        **_confirmation_values(),
    )
    return record, confirmed


def _create_legacy_database_for_test(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(_legacy_trade_execution_schema())
        connection.execute(
            """
            INSERT INTO setups (
                setup_id, symbol, side, level, breakout_at, state,
                retest_bars_elapsed, reason, updated_at
            ) VALUES ('legacy-setup', 'GOLD.i#', 'BUY', 4380.1,
                      '2026-08-15T04:30:00Z', 'CONFIRMED_A_PLUS', 0, '',
                      '2026-08-15T04:30:00Z')
            """
        )
        cursor = connection.execute(
            """
            INSERT INTO signal_outbox (
                setup_id, event_type, event_key, payload_json, created_at
            ) VALUES ('legacy-setup', 'SNIPER_SIGNAL', 'SNIPER_SIGNAL', ?,
                      '2026-08-15T04:30:00Z')
            """,
            (json.dumps({"entry": 4380.1}),),
        )
        connection.execute(
            _execution_insert_sql(), _execution_values("legacy-setup", int(cursor.lastrowid))
        )
        connection.commit()


def _downgrade_position_actions_to_v2(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            DROP INDEX IF EXISTS idx_trade_executions_account_position;
            DROP INDEX IF EXISTS idx_position_actions_claim;
            DROP INDEX IF EXISTS idx_position_actions_setup;
            DROP INDEX IF EXISTS idx_position_actions_position;
            DROP INDEX IF EXISTS idx_position_actions_identifier;
            ALTER TABLE position_actions RENAME TO position_actions_v3_backup;
            CREATE TABLE position_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT NOT NULL UNIQUE,
                setup_id TEXT,
                position_ticket INTEGER NOT NULL,
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
                updated_at TEXT NOT NULL
            );
            INSERT INTO position_actions (
                id, idempotency_key, setup_id, position_ticket, action_type, status,
                payload_json, management_policy, account_login, account_server,
                account_scope, attempt_count, lease_owner, lease_acquired_at,
                lease_expires_at, broker_order_ticket, broker_deal_ticket,
                broker_position_ticket, broker_retcode, broker_reference, last_error,
                created_at, last_attempt_at, submitted_at, confirmed_at, failed_at,
                unknown_at, updated_at
            )
            SELECT
                id, idempotency_key, setup_id, position_ticket, action_type, status,
                payload_json, management_policy, account_login, account_server,
                account_scope, attempt_count, lease_owner, lease_acquired_at,
                lease_expires_at, broker_order_ticket, broker_deal_ticket,
                broker_position_ticket, broker_retcode, broker_reference, last_error,
                created_at, last_attempt_at, submitted_at, confirmed_at, failed_at,
                unknown_at, updated_at
            FROM position_actions_v3_backup;
            DROP TABLE position_actions_v3_backup;
            CREATE INDEX idx_position_actions_claim
                ON position_actions(status, lease_expires_at, created_at, id);
            CREATE INDEX idx_position_actions_setup
                ON position_actions(setup_id, created_at, id);
            CREATE INDEX idx_position_actions_position
                ON position_actions(position_ticket, created_at, id);
            DELETE FROM schema_migrations WHERE version >= 3;
            PRAGMA user_version = 2;
            """
        )
        connection.commit()


if __name__ == "__main__":
    unittest.main()
