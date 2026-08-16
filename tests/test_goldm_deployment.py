from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import venv
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from bot_ea.mt5_adapter import OpenPositionSnapshot
from goldm_signal.deployment import (
    BrokerSnapshot,
    DatabaseSnapshot,
    DeploymentSafetyError,
    RESTORE_ACKNOWLEDGEMENT,
    assert_cutover_safe,
    backup_database,
    build_tree_manifest,
    capture_log_cursor,
    collect_broker_snapshot,
    create_safe_handoff_manifest,
    find_fresh_ea_session_evidence,
    find_latest_ea_session_evidence,
    inspect_database,
    inspect_telegram_poll_readiness,
    load_production_ea_input_contract,
    parse_env_file,
    restore_database,
    seal_json,
    sha256_file,
    validate_runtime_environment,
    verify_runtime_session_file,
    verify_database_backup,
    verify_offline_wheelhouse,
    verify_sealed_json,
    verify_tree_manifest,
    write_runtime_session_file,
)
from goldm_signal.storage import SignalStore, telegram_poll_db_identity


SESSION_ID = "prod-session-20260815"
DEMO_CONFIG_BINDING = (
    "accountScope=demo accountLogin=108098316 "
    "originServerB64=WE1HbG9iYWwtTVQ1IDU"
)


def _production_config_log(
    session_id: str,
    *,
    input_overrides: dict[str, str] | None = None,
    core_overrides: dict[str, str] | None = None,
) -> str:
    contract = load_production_ea_input_contract()
    inputs = dict(contract["inputs"])
    inputs.update(input_overrides or {})
    items = list(inputs.items())
    parts: list[str] = []
    for part_number, part_items in enumerate((items[:31], items[31:]), start=1):
        fields = " ".join(f"{key}={value}" for key, value in part_items)
        parts.append(
            "SNIPER_PRODUCTION_INPUTS schema=1 "
            f"part={part_number}/2 contractSha256={contract['sha256']} {fields}"
        )
    core = {
        "symbol": "GOLD.i#",
        "strategy": "GOLDM_SNIPER_PARITY",
        "strategyVersion": "1.72",
        "productionContractVersion": "1",
        "productionContractSha256": contract["sha256"],
        "directionProfile": "ALL",
        "runId": session_id,
        "accountScope": "demo",
        "accountLogin": "108098316",
        "originServerB64": "WE1HbG9iYWwtTVQ1IDU",
        "signalOnly": "true",
        "strategyMode": inputs.get("InpStrategyMode", "0"),
    }
    core.update(core_overrides or {})
    parts.append(
        "SNIPER_CONFIG "
        + " ".join(f"{key}={value}" for key, value in core.items())
    )
    return "\n".join(parts) + "\n"


class _FakeAdapter:
    terminal_path = ""
    data_path = ""
    positions: list[OpenPositionSnapshot] = []
    shutdown_called = False
    exact_account_scope = "demo"

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        type(self).shutdown_called = False

    def load_terminal_status(self):
        return SimpleNamespace(
            path=self.terminal_path,
            data_path=self.data_path,
            connected=True,
        )

    def load_account_fingerprint(self):
        return SimpleNamespace(
            login="108098316",
            server="XMGlobal-MT5 5",
            is_live=False,
            margin_mode="HEDGING",
        )

    def load_exact_account_scope(self):
        return getattr(type(self), "exact_account_scope", "demo")

    def load_open_positions(self):
        return list(self.positions)

    def load_open_orders(self):
        return []

    def shutdown(self):
        type(self).shutdown_called = True


class GoldMDeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        _FakeAdapter.exact_account_scope = "demo"
        self.install = self.root / "terminal"
        self.data = self.root / "data"
        self.logs = self.data / "MQL5" / "Logs"
        self.install.mkdir()
        self.logs.mkdir(parents=True)
        self.terminal = self.install / "terminal64.exe"
        self.terminal.write_bytes(b"terminal-fixture")
        self.env = self.root / ".env"
        self.env.write_text(
            "\n".join(
                (
                    'TELEGRAM_BOT_TOKEN="secret#inside" # comment',
                    'TELEGRAM_ADMIN_CHAT_IDS="123"',
                    f'MT5_PATH="{self.terminal}"',
                    f'MT5_DATA_PATH="{self.data}"',
                    'MT5_LAUNCH_MODE="standard"',
                    'MT5_LOGIN="108098316"',
                    'MT5_SERVER="XMGlobal-MT5 5"',
                    'GOLDM_EXPECTED_MT5_LOGIN="108098316"',
                    'GOLDM_EXPECTED_MT5_SERVER="XMGlobal-MT5 5"',
                    f'GOLDM_EA_SESSION_ID="{SESSION_ID}"',
                    'GOLDM_ALLOW_LIVE_ACTIVATION="false"',
                    'GOLDM_TRADE_LIFECYCLE_ENABLED="true"',
                    'GOLDM_EXECUTION_MODE="off" # maintenance interlock',
                )
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_demo_release_template_runbook_and_updater_are_fail_closed(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        template = parse_env_file(repo / ".env.example")
        required_demo_bindings = {
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_ADMIN_CHAT_IDS",
            "MT5_PATH",
            "MT5_DATA_PATH",
            "MT5_LAUNCH_MODE",
            "MT5_LOGIN",
            "MT5_SERVER",
            "GOLDM_EXPECTED_MT5_LOGIN",
            "GOLDM_EXPECTED_MT5_SERVER",
            "GOLDM_EA_SESSION_ID",
            "GOLDM_ALLOW_LIVE_ACTIVATION",
            "GOLDM_TRADE_LIFECYCLE_ENABLED",
            "GOLDM_EXECUTION_MODE",
        }
        self.assertTrue(required_demo_bindings.issubset(template))
        self.assertEqual(template["GOLDM_ALLOW_LIVE_ACTIVATION"], "false")
        self.assertEqual(template["GOLDM_EXECUTION_MODE"], "off")
        self.assertEqual(template["GOLDM_ENTRY_SIDE_POLICY"], "ALL")
        self.assertEqual(template["GOLDM_NOTIFICATION_SIDE_FILTER"], "ALL")
        self.assertEqual(template["MT5_LOGIN"], "UNSET")
        self.assertEqual(template["GOLDM_EA_SESSION_ID"], "UNSET")
        self.assertNotIn("MT5_PASSWORD", template)
        self.assertNotIn("GOLDM_LIVE_ORDER_CONSENT", template)

        updater = (repo / "scripts" / "update-goldm-windows-vm.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '[string]$RemoteBranch = "release/goldm-core-v2"', updater
        )
        self.assertNotIn('"feature/core-trading-lifecycle"', updater)

        runbook = (repo / "docs" / "windows-vm-deployment.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("DEMO/shadow only", runbook)
        self.assertIn("self-hosted, Windows, X64, goldm-mt5", runbook)
        self.assertIn("-StageOnly", runbook)
        self.assertNotIn("-RestartTerminal", runbook)
        self.assertNotIn("-TelegramSmokeTest", runbook)
        self.assertNotIn("Two-terminal DEMO and REAL", runbook)

    def test_environment_contract_is_exact_demo_only_and_comment_safe(self) -> None:
        values = parse_env_file(self.env)
        self.assertEqual(values["TELEGRAM_BOT_TOKEN"], "secret#inside")
        contract = validate_runtime_environment(
            values,
            terminal_executable=self.terminal,
            terminal_data_path=self.data,
        )
        self.assertEqual(contract["execution_mode"], "off")
        self.assertEqual(
            contract["ea_session_id_sha256"],
            hashlib.sha256(SESSION_ID.encode()).hexdigest(),
        )

        for explicit_key in (
            "GOLDM_EXECUTION_MODE",
            "GOLDM_TRADE_LIFECYCLE_ENABLED",
            "GOLDM_EXPECTED_MT5_LOGIN",
            "GOLDM_EXPECTED_MT5_SERVER",
        ):
            incomplete = dict(values)
            incomplete.pop(explicit_key)
            with self.assertRaisesRegex(DeploymentSafetyError, explicit_key):
                validate_runtime_environment(
                    incomplete,
                    terminal_executable=self.terminal,
                    terminal_data_path=self.data,
                )

        wrong_data = self.root / "wrong-data"
        wrong_data.mkdir()
        with self.assertRaisesRegex(DeploymentSafetyError, "MT5_DATA_PATH"):
            validate_runtime_environment(
                values,
                terminal_executable=self.terminal,
                terminal_data_path=wrong_data,
            )
        values["GOLDM_ALLOW_LIVE_ACTIVATION"] = "true"
        with self.assertRaisesRegex(DeploymentSafetyError, "exactly false"):
            validate_runtime_environment(
                values,
                terminal_executable=self.terminal,
                terminal_data_path=self.data,
            )
        values["GOLDM_ALLOW_LIVE_ACTIVATION"] = "false"
        values["GOLDM_EXPECTED_MT5_LOGIN"] = "999"
        with self.assertRaisesRegex(DeploymentSafetyError, "EXPECTED_MT5_LOGIN"):
            validate_runtime_environment(
                values,
                terminal_executable=self.terminal,
                terminal_data_path=self.data,
            )
        values["GOLDM_EXPECTED_MT5_LOGIN"] = values["MT5_LOGIN"]
        values["TELEGRAM_ADMIN_CHAT_IDS"] = "-100123"
        with self.assertRaisesRegex(DeploymentSafetyError, "positive private"):
            validate_runtime_environment(
                values,
                terminal_executable=self.terminal,
                terminal_data_path=self.data,
            )
        values["TELEGRAM_ADMIN_CHAT_IDS"] = "123"
        values["GOLDM_EXECUTION_MODE"] = "demo"
        with self.assertRaisesRegex(DeploymentSafetyError, "exactly off"):
            validate_runtime_environment(
                values,
                terminal_executable=self.terminal,
                terminal_data_path=self.data,
            )
        values["GOLDM_EXECUTION_MODE"] = "off"
        values["MT5_PATH"] = self.terminal.name
        with self.assertRaisesRegex(DeploymentSafetyError, "absolute path"):
            validate_runtime_environment(
                values,
                terminal_executable=self.terminal,
                terminal_data_path=self.data,
            )

    def test_environment_duplicate_key_is_rejected(self) -> None:
        self.env.write_text("A=1\nA=2\n", encoding="utf-8")
        with self.assertRaisesRegex(DeploymentSafetyError, "duplicate"):
            parse_env_file(self.env)

        self.env.write_text(
            "GOLDM_EXECUTION_MODE=off\ngoldm_execution_mode=live\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DeploymentSafetyError, "case-insensitive"):
            parse_env_file(self.env)

        self.env.write_text("goldm_execution_mode=off\n", encoding="utf-8")
        with self.assertRaisesRegex(DeploymentSafetyError, "canonical uppercase"):
            parse_env_file(self.env)

    def test_runtime_session_file_is_atomic_exact_and_never_returned_in_clear(self) -> None:
        result = write_runtime_session_file(self.env, self.data)
        session_file = self.data / "MQL5" / "Files" / "goldm_runtime_session.txt"
        self.assertEqual(session_file.read_text(encoding="ascii"), SESSION_ID + "\n")
        self.assertNotIn(SESSION_ID, json.dumps(result))
        self.assertEqual(
            verify_runtime_session_file(self.env, self.data)["sha256"],
            result["sha256"],
        )
        session_file.write_text("wrong-session-token-0001\n", encoding="ascii")
        with self.assertRaisesRegex(DeploymentSafetyError, "does not exactly match"):
            verify_runtime_session_file(self.env, self.data)

    def test_runtime_session_rejects_reparse_before_creating_outside_files(self) -> None:
        reparse_data = self.root / "reparse-data"
        outside = self.root / "outside"
        reparse_data.mkdir()
        outside.mkdir()
        try:
            os.symlink(
                outside,
                reparse_data / "MQL5",
                target_is_directory=True,
            )
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"directory symlink fixture unavailable: {exc}")

        with self.assertRaisesRegex(
            DeploymentSafetyError, "symbolic link|junction"
        ):
            write_runtime_session_file(self.env, reparse_data)
        self.assertFalse((outside / "Files").exists())

    def test_broker_snapshot_binds_exact_terminal_demo_hedging_and_shutdown(self) -> None:
        _FakeAdapter.terminal_path = str(self.install)
        _FakeAdapter.data_path = str(self.data)
        _FakeAdapter.positions = []
        snapshot = collect_broker_snapshot(
            parse_env_file(self.env),
            terminal_executable=self.terminal,
            terminal_data_path=self.data,
            adapter_factory=_FakeAdapter,
        )
        self.assertEqual(snapshot.account_scope, "demo")
        self.assertEqual(snapshot.account_margin_mode, "HEDGING")
        self.assertTrue(_FakeAdapter.shutdown_called)
        self.assertFalse(snapshot.positions)

        _FakeAdapter.exact_account_scope = "contest"
        with self.assertRaisesRegex(DeploymentSafetyError, "CONTEST"):
            collect_broker_snapshot(
                parse_env_file(self.env),
                terminal_executable=self.terminal,
                terminal_data_path=self.data,
                adapter_factory=_FakeAdapter,
            )
        _FakeAdapter.exact_account_scope = "demo"

    def test_environment_rejects_portable_terminal_topology(self) -> None:
        portable_data = self.install / "portable-data"
        (portable_data / "MQL5" / "Logs").mkdir(parents=True)
        values = parse_env_file(self.env)
        values["MT5_DATA_PATH"] = str(portable_data)
        with self.assertRaisesRegex(DeploymentSafetyError, "portable"):
            validate_runtime_environment(
                values,
                terminal_executable=self.terminal,
                terminal_data_path=portable_data,
            )
        values["MT5_DATA_PATH"] = str(self.data)
        values["MT5_LAUNCH_MODE"] = "portable"
        with self.assertRaisesRegex(DeploymentSafetyError, "exactly standard"):
            validate_runtime_environment(
                values,
                terminal_executable=self.terminal,
                terminal_data_path=self.data,
            )

    def test_sqlite_online_backup_captures_wal_and_restore_is_hash_gated(self) -> None:
        source = self.root / "source.db"
        connection = sqlite3.connect(source)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE records(value TEXT NOT NULL)")
        connection.execute("INSERT INTO records VALUES ('in-wal')")
        connection.commit()
        self.assertTrue(source.with_name(source.name + "-wal").exists())

        backup = self.root / "backup.db"
        result = backup_database(source, backup)
        self.assertEqual(result["integrity_check"], "ok")
        with closing(sqlite3.connect(backup)) as backup_connection:
            self.assertEqual(
                backup_connection.execute("SELECT value FROM records").fetchone()[0],
                "in-wal",
            )
        verify_database_backup(backup, expected_sha256=result["sha256"])
        with self.assertRaisesRegex(DeploymentSafetyError, "SHA-256"):
            verify_database_backup(backup, expected_sha256="0" * 64)

        destination = self.root / "restored.db"
        with self.assertRaisesRegex(DeploymentSafetyError, "acknowledgement"):
            restore_database(
                backup,
                destination,
                expected_sha256=result["sha256"],
                acknowledgement="wrong",
            )
        restored = restore_database(
            backup,
            destination,
            expected_sha256=result["sha256"],
            acknowledgement=RESTORE_ACKNOWLEDGEMENT,
        )
        self.assertEqual(restored["integrity_check"], "ok")
        connection.close()

    def test_database_gate_blocks_live_runtime_and_unresolved_action(self) -> None:
        database = self.root / "goldm.db"
        store = SignalStore(database)
        store.initialize()
        snapshot = inspect_database(database)
        self.assertEqual(snapshot.active_executions, ())

        with closing(sqlite3.connect(database)) as connection:
            connection.execute(
                """
                INSERT INTO position_actions (
                    idempotency_key, action_type, status, created_at, updated_at
                ) VALUES ('deploy-fixture', 'OPEN', 'UNKNOWN', 'now', 'now')
                """
            )
            connection.commit()
        snapshot = inspect_database(database)
        self.assertEqual(snapshot.unresolved_actions[0]["status"], "UNKNOWN")

        with closing(sqlite3.connect(database)) as connection:
            connection.execute(
                """
                INSERT INTO runtime_settings (
                    setting_key, value_json, updated_by, updated_at
                ) VALUES ('trade.execution_mode', '"live"', 'fixture', 'now')
                """
            )
            connection.commit()
        with self.assertRaisesRegex(DeploymentSafetyError, "live"):
            inspect_database(database)

    def test_deployment_requires_fresh_exact_telegram_poll_readiness(self) -> None:
        database = self.root / "readiness.db"
        store = SignalStore(database)
        store.initialize()
        started = datetime.now(timezone.utc) - timedelta(seconds=2)
        release_id = "a" * 40
        deployment_nonce_sha256 = hashlib.sha256(b"c" * 32).hexdigest()
        release_manifest_sha256 = hashlib.sha256(b"release-manifest").hexdigest()
        runtime_config_sha256 = sha256_file(self.env)
        production_config_sha256 = load_production_ea_input_contract()["sha256"]
        worker_instance_id = "b" * 32
        store.start_telegram_poll_readiness(
            release_id=release_id,
            session_sha256=hashlib.sha256(SESSION_ID.encode()).hexdigest(),
            db_identity=telegram_poll_db_identity(database),
            deployment_nonce_sha256=deployment_nonce_sha256,
            release_manifest_sha256=release_manifest_sha256,
            runtime_config_sha256=runtime_config_sha256,
            production_config_sha256=production_config_sha256,
            worker_instance_id=worker_instance_id,
            worker_started_at=started,
        )
        self.assertTrue(
            store.record_telegram_poll_success(
                worker_instance_id=worker_instance_id,
                observed_at=started + timedelta(milliseconds=1),
            )
        )
        ready = inspect_telegram_poll_readiness(
            database,
            self.env,
            expected_release_id=release_id,
            expected_deployment_nonce_sha256=deployment_nonce_sha256,
            expected_release_manifest_sha256=release_manifest_sha256,
            expected_runtime_config_sha256=runtime_config_sha256,
            expected_production_config_sha256=production_config_sha256,
            not_before_utc=(started - timedelta(milliseconds=1)).isoformat(),
            max_age_seconds=60.0,
        )
        self.assertTrue(ready["ready"])

        self.assertTrue(
            store.record_telegram_poll_failure(
                worker_instance_id=worker_instance_id,
                error_kind="transport_timeout",
                observed_at=started + timedelta(milliseconds=2),
            )
        )
        with self.assertRaisesRegex(DeploymentSafetyError, "latest_poll_failed"):
            inspect_telegram_poll_readiness(
                database,
                self.env,
                expected_release_id=release_id,
                expected_deployment_nonce_sha256=deployment_nonce_sha256,
                expected_release_manifest_sha256=release_manifest_sha256,
                expected_runtime_config_sha256=runtime_config_sha256,
                expected_production_config_sha256=production_config_sha256,
                not_before_utc=(started - timedelta(milliseconds=1)).isoformat(),
                max_age_seconds=60.0,
            )

    def test_cutover_requires_flat_book_and_handoff_artifact_is_exact(self) -> None:
        database = DatabaseSnapshot(
            path=str(self.root / "goldm.db"),
            sha256="a" * 64,
            runtime_execution_mode="off",
            active_executions=(
                {
                    "setup_id": "setup-1",
                    "execution_mode": "demo",
                    "status": "FILLED",
                    "symbol": "GOLD.i#",
                    "side": "BUY",
                    "client_tag": "abc123def4",
                    "magic": 260814,
                    "account_login": "108098316",
                    "account_server": "XMGlobal-MT5 5",
                    "account_scope": "demo",
                    "account_margin_mode": "HEDGING",
                    "position_ticket": 7001,
                    "position_identifier": 9001,
                    "remaining_volume": 0.01,
                    "current_stop_price": 2300.0,
                    "current_take_profit_price": 2350.0,
                },
            ),
            unresolved_actions=(),
        )
        position = {
            "ticket": 7001,
            "identifier": 9001,
            "symbol": "GOLD.i#",
            "side": "BUY",
            "volume": 0.01,
            "sl": 2300.0,
            "tp": 2350.0,
            "magic": 260814,
            "comment": "GMS: abc123def4",
        }
        broker = BrokerSnapshot(
            terminal_executable=str(self.terminal.resolve()),
            terminal_data_path=str(self.data.resolve()),
            account_login="108098316",
            account_server="XMGlobal-MT5 5",
            account_scope="demo",
            account_margin_mode="HEDGING",
            positions=(position,),
        )
        with self.assertRaisesRegex(DeploymentSafetyError, "flat book"):
            assert_cutover_safe(database, broker, release_commit="f" * 40)

        with self.assertRaisesRegex(DeploymentSafetyError, "must be OFF"):
            assert_cutover_safe(
                replace(database, runtime_execution_mode="demo"),
                broker,
                release_commit="f" * 40,
            )

        generated = self.root / "generated-handoff.json"
        with self.assertRaisesRegex(DeploymentSafetyError, "acknowledgement"):
            create_safe_handoff_manifest(
                database,
                broker,
                release_commit="f" * 40,
                approved_by="root-admin",
                reason="Protected broker position handoff during update",
                output_path=generated,
                acknowledgement="wrong",
            )
        generated_result = create_safe_handoff_manifest(
            database,
            broker,
            release_commit="f" * 40,
            approved_by="root-admin",
            reason="Protected broker position handoff during update",
            output_path=generated,
            acknowledgement="I_ACCEPT_PROTECTED_POSITION_HANDOFF",
        )
        verify_sealed_json(generated)
        self.assertEqual(generated_result["position_count"], 1)

        with self.assertRaisesRegex(DeploymentSafetyError, "flat book"):
            assert_cutover_safe(
                database,
                broker,
                release_commit="f" * 40,
                safe_handoff_path=generated,
                safe_handoff_sha256=generated_result["sha256"],
            )

        for field, value in (
            ("account_login", "999999"),
            ("account_server", "xmglobal-mt5 5"),
            ("account_scope", "live"),
            ("symbol", "GOLDm#"),
            ("side", "SELL"),
            ("position_ticket", 7002),
            ("magic", 260815),
            ("client_tag", "wrongtag00"),
            ("remaining_volume", 0.02),
        ):
            with self.subTest(binding_field=field):
                tampered_execution = {
                    **database.active_executions[0],
                    field: value,
                }
                with self.assertRaisesRegex(
                    DeploymentSafetyError, "execution/position binding mismatch"
                ):
                    create_safe_handoff_manifest(
                        replace(
                            database,
                            active_executions=(tampered_execution,),
                        ),
                        broker,
                        release_commit="f" * 40,
                        approved_by="root-admin",
                        reason="Protected broker position handoff during update",
                        output_path=self.root / f"tampered-{field}.json",
                        acknowledgement="I_ACCEPT_PROTECTED_POSITION_HANDOFF",
                    )

        position["sl"] = 0.0
        with self.assertRaisesRegex(DeploymentSafetyError, "both SL and TP"):
            create_safe_handoff_manifest(
                database,
                broker,
                release_commit="f" * 40,
                approved_by="root-admin",
                reason="Protected broker position handoff during update",
                output_path=self.root / "unprotected.json",
                acknowledgement="I_ACCEPT_PROTECTED_POSITION_HANDOFF",
            )

    def test_sealed_evidence_and_release_tree_detect_tampering(self) -> None:
        source = self.root / "source.json"
        source.write_text('{"b":2,"a":1}', encoding="utf-8")
        sealed_path = self.root / "sealed.json"
        seal_json(source, sealed_path)
        verify_sealed_json(sealed_path)
        sealed_path.chmod(0o600)
        sealed_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(DeploymentSafetyError, "mismatch"):
            verify_sealed_json(sealed_path)

        release = self.root / "release"
        release.mkdir()
        artifact = release / "app.py"
        artifact.write_text("print('safe')\n", encoding="utf-8")
        tree_manifest = release / "release-tree-manifest.json"
        tree_seal = build_tree_manifest(release, tree_manifest)
        verify_tree_manifest(
            release,
            tree_manifest,
            expected_manifest_sha256=tree_seal["sha256"],
        )
        with self.assertRaisesRegex(DeploymentSafetyError, "operator-approved"):
            verify_tree_manifest(
                release,
                tree_manifest,
                expected_manifest_sha256="0" * 64,
            )
        artifact.write_text("print('tampered')\n", encoding="utf-8")
        with self.assertRaisesRegex(DeploymentSafetyError, "mismatch"):
            verify_tree_manifest(
                release,
                tree_manifest,
                expected_manifest_sha256=tree_seal["sha256"],
            )

    def test_release_tree_rejects_symlinked_directories(self) -> None:
        outside = self.root / "outside-release"
        outside.mkdir()
        (outside / "injected.py").write_text("raise SystemExit\n", encoding="utf-8")

        release = self.root / "release-with-link"
        release.mkdir()
        link = release / "hidden"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:  # Windows may require Developer Mode for symlinks.
            self.skipTest(f"directory symlink unavailable: {exc}")
        with self.assertRaisesRegex(DeploymentSafetyError, "symbolic link"):
            build_tree_manifest(release, release / "release-tree-manifest.json")

        verified_release = self.root / "verified-then-linked"
        verified_release.mkdir()
        (verified_release / "app.py").write_text("print('safe')\n", encoding="utf-8")
        manifest = verified_release / "release-tree-manifest.json"
        verified_seal = build_tree_manifest(verified_release, manifest)
        (verified_release / "hidden").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(DeploymentSafetyError, "symbolic link"):
            verify_tree_manifest(
                verified_release,
                manifest,
                expected_manifest_sha256=verified_seal["sha256"],
            )

    def test_offline_wheelhouse_requires_sealed_wheels_and_exact_hash_lock(self) -> None:
        wheelhouse = self.root / "goldm-wheelhouse"
        wheelhouse.mkdir()
        digest = "a" * 64
        lock = wheelhouse / "requirements-goldm-live.lock"
        lock.write_text(
            "\n".join(
                f"{name}=={version} --hash=sha256:{digest}"
                for name, version in (
                    ("MetaTrader5", "5.0.5735"),
                    ("numpy", "2.4.2"),
                )
            )
            + "\n",
            encoding="utf-8",
        )
        (wheelhouse / "metatrader5-5.0.5735-cp314-cp314-win_amd64.whl").write_bytes(
            b"fixture-metatrader5"
        )
        (wheelhouse / "numpy-2.4.2-cp314-cp314-win_amd64.whl").write_bytes(
            b"fixture-numpy"
        )
        manifest = wheelhouse / "goldm-wheelhouse-manifest.json"
        sealed_wheelhouse = build_tree_manifest(wheelhouse, manifest)
        result = verify_offline_wheelhouse(
            wheelhouse,
            expected_manifest_sha256=sealed_wheelhouse["sha256"],
        )
        self.assertEqual(result["locked_packages"], 2)
        self.assertEqual(result["wheel_files"], 2)
        with self.assertRaisesRegex(DeploymentSafetyError, "operator-approved"):
            verify_offline_wheelhouse(
                wheelhouse,
                expected_manifest_sha256="0" * 64,
            )

        lock.chmod(0o600)
        lock.write_text(
            lock.read_text(encoding="utf-8").replace(
                f"numpy==2.4.2 --hash=sha256:{digest}",
                "numpy>=2.4.2",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DeploymentSafetyError, "mismatch"):
            verify_offline_wheelhouse(
                wheelhouse,
                expected_manifest_sha256=sealed_wheelhouse["sha256"],
            )

        invalid = self.root / "invalid-wheelhouse"
        invalid.mkdir()
        (invalid / "requirements-goldm-live.lock").write_text(
            "websockets>=12\n", encoding="utf-8"
        )
        (invalid / "websockets-12-py3-none-any.whl").write_bytes(b"fixture")
        invalid_seal = build_tree_manifest(
            invalid, invalid / "goldm-wheelhouse-manifest.json"
        )
        with self.assertRaisesRegex(DeploymentSafetyError, "exact == pins"):
            verify_offline_wheelhouse(
                invalid,
                expected_manifest_sha256=invalid_seal["sha256"],
            )

    @unittest.skipUnless(
        shutil.which("powershell.exe"),
        "Windows PowerShell 5.1 is unavailable",
    )
    def test_private_wheelhouse_stage_is_immune_to_external_swap(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        common = repo / "scripts" / "goldm-deployment-common.psm1"
        source = self.root / "external-wheelhouse"
        source.mkdir()
        locked_digest = "a" * 64
        (source / "requirements-goldm-live.lock").write_text(
            "MetaTrader5==5.0.5735 --hash=sha256:"
            + locked_digest
            + "\nnumpy==2.4.2 --hash=sha256:"
            + locked_digest
            + "\n",
            encoding="utf-8",
        )
        wheel_name = "metatrader5-5.0.5735-cp314-cp314-win_amd64.whl"
        (source / wheel_name).write_bytes(b"ORIGINAL_WHEEL")
        (source / "numpy-2.4.2-cp314-cp314-win_amd64.whl").write_bytes(
            b"ORIGINAL_NUMPY"
        )
        manifest = source / "goldm-wheelhouse-manifest.json"
        sealed = build_tree_manifest(source, manifest)
        staging_parent = self.root / "sealed-inputs"
        staging_parent.mkdir()
        stage = staging_parent / source.name

        def ps_quote(value: Path | str) -> str:
            return str(value).replace("'", "''")

        script = f"""
$ErrorActionPreference = 'Stop'
Import-Module '{ps_quote(common)}' -Force
$staged = Copy-GoldMVerifiedWheelhouseToPrivateStage `
    -SourcePath '{ps_quote(source)}' `
    -DestinationPath '{ps_quote(stage)}' `
    -ExpectedManifestSha256 '{sealed["sha256"]}' `
    -PythonExecutable '{ps_quote(Path(sys.executable))}' `
    -RepoRoot '{ps_quote(repo)}'
[System.IO.File]::WriteAllBytes(
    '{ps_quote(source / wheel_name)}',
    [System.Text.Encoding]::UTF8.GetBytes('SWAPPED_WHEEL')
)
$stagedWheel = Join-Path $staged.Path '{wheel_name}'
if ([System.Text.Encoding]::UTF8.GetString([System.IO.File]::ReadAllBytes($stagedWheel)) -ne 'ORIGINAL_WHEEL') {{
    throw 'private wheelhouse stage followed an external source swap'
}}
[void](Invoke-GoldMDeploymentHelper `
    -PythonExecutable '{ps_quote(Path(sys.executable))}' `
    -RepoRoot '{ps_quote(repo)}' `
    -Arguments @(
        'verify-offline-wheelhouse',
        '--root', [string]$staged.Path,
        '--expected-manifest-sha256', '{sealed["sha256"]}'
    ))
Write-Output 'WHEELHOUSE_STAGE_SWAP_OK'
"""
        result = subprocess.run(
            [
                shutil.which("powershell.exe") or "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            cwd=repo,
            env={
                **os.environ,
                "PSModulePath": str(
                    Path(os.environ["WINDIR"])
                    / "system32"
                    / "WindowsPowerShell"
                    / "v1.0"
                    / "Modules"
                ),
            },
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout={result.stdout}\nstderr={result.stderr}",
        )
        self.assertIn("WHEELHOUSE_STAGE_SWAP_OK", result.stdout)

    def test_session_evidence_is_exact_and_only_accepts_post_cursor_bytes(self) -> None:
        log = self.logs / "20260815.log"
        old = _production_config_log("old-session-20260815")
        log.write_text(old, encoding="utf-8")
        cursor = self.root / "cursor.json"
        capture_log_cursor(self.logs, cursor)
        with log.open("a", encoding="utf-8") as stream:
            stream.write(_production_config_log(SESSION_ID))
        evidence = find_fresh_ea_session_evidence(
            self.logs,
            cursor,
            session_id=SESSION_ID,
            expected_account_login="108098316",
            expected_account_server="XMGlobal-MT5 5",
        )
        self.assertEqual(evidence["status"], "MATCHED")
        self.assertEqual(
            find_latest_ea_session_evidence(
                self.logs,
                session_id=SESSION_ID,
                expected_account_login="108098316",
                expected_account_server="XMGlobal-MT5 5",
            )["status"],
            "MATCHED",
        )

        second_cursor = self.root / "second-cursor.json"
        capture_log_cursor(self.logs, second_cursor)
        with log.open("a", encoding="utf-8") as stream:
            stream.write(_production_config_log(SESSION_ID))
            stream.write(_production_config_log("different-session-0001"))
        with self.assertRaisesRegex(DeploymentSafetyError, "different session"):
            find_fresh_ea_session_evidence(
                self.logs,
                second_cursor,
                session_id=SESSION_ID,
                expected_account_login="108098316",
                expected_account_server="XMGlobal-MT5 5",
            )

    def test_session_evidence_scans_rotated_utf16_log(self) -> None:
        old = self.logs / "20260814.log"
        old.write_text("old\n", encoding="utf-16")
        cursor = self.root / "cursor.json"
        capture_log_cursor(self.logs, cursor)
        rotated = self.logs / "20260815.log"
        rotated.write_text(
            _production_config_log(SESSION_ID),
            encoding="utf-16",
        )
        self.assertEqual(
            find_fresh_ea_session_evidence(
                self.logs,
                cursor,
                session_id=SESSION_ID,
                expected_account_login="108098316",
                expected_account_server="XMGlobal-MT5 5",
            )["log_file"],
            rotated.name,
        )

    def test_session_evidence_rejects_live_or_wrong_account_config(self) -> None:
        log = self.logs / "20260815.log"
        cursor = self.root / "cursor.json"
        log.write_text("baseline\n", encoding="utf-8")
        capture_log_cursor(self.logs, cursor)
        log.write_text(
            "baseline\n"
            + _production_config_log(
                SESSION_ID, core_overrides={"accountScope": "live"}
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DeploymentSafetyError, "account"):
            find_fresh_ea_session_evidence(
                self.logs,
                cursor,
                session_id=SESSION_ID,
                expected_account_login="108098316",
                expected_account_server="XMGlobal-MT5 5",
            )

        log.write_text(
            _production_config_log(
                SESSION_ID, core_overrides={"accountLogin": "999999"}
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DeploymentSafetyError, "account"):
            find_latest_ea_session_evidence(
                self.logs,
                session_id=SESSION_ID,
                expected_account_login="108098316",
                expected_account_server="XMGlobal-MT5 5",
            )

    def test_session_evidence_rejects_noncanonical_symbol(self) -> None:
        log = self.logs / "20260815.log"
        cursor = self.root / "cursor.json"
        log.write_text("baseline\n", encoding="utf-8")
        capture_log_cursor(self.logs, cursor)
        with log.open("a", encoding="utf-8") as stream:
            stream.write(
                _production_config_log(
                    SESSION_ID, core_overrides={"symbol": "XAUUSD"}
                )
            )

        with self.assertRaisesRegex(DeploymentSafetyError, "symbol"):
            find_fresh_ea_session_evidence(
                self.logs,
                cursor,
                session_id=SESSION_ID,
                expected_account_login="108098316",
                expected_account_server="XMGlobal-MT5 5",
            )

    def test_session_evidence_rejects_any_production_input_or_identity_drift(
        self,
    ) -> None:
        log = self.logs / "20260815.log"
        cases = (
            ("threshold", {"InpM15ReversalRSIThreshold": "41.00000000"}, {}),
            ("engine lineage", {}, {"directionProfile": "BULL_ONLY"}),
            ("strategy mode", {"InpStrategyMode": "1"}, {}),
            ("R lock", {"InpPost1RLockR": "0.30000000"}, {}),
            ("partial", {"InpEnablePartialTake": "true"}, {}),
            ("strategy identity", {}, {"strategy": "EXPERIMENTAL"}),
        )
        for label, input_overrides, core_overrides in cases:
            with self.subTest(label=label):
                log.write_text(
                    _production_config_log(
                        SESSION_ID,
                        input_overrides=input_overrides,
                        core_overrides=core_overrides,
                    ),
                    encoding="utf-8",
                )
                with self.assertRaises(DeploymentSafetyError):
                    find_latest_ea_session_evidence(
                        self.logs,
                        session_id=SESSION_ID,
                        expected_account_login="108098316",
                        expected_account_server="XMGlobal-MT5 5",
                    )

    def test_production_input_evidence_rejects_missing_extra_and_duplicate_fields(
        self,
    ) -> None:
        log = self.logs / "20260815.log"
        valid = _production_config_log(SESSION_ID)
        malformed = (
            valid.replace(" InpRSIPeriod=14", "", 1),
            valid.replace(
                "\nSNIPER_CONFIG", " InpUndeclaredProductionKnob=1\nSNIPER_CONFIG", 1
            ),
            valid.replace(
                " InpRSIPeriod=14", " InpRSIPeriod=14 InpRSIPeriod=14", 1
            ),
        )
        for index, payload in enumerate(malformed):
            with self.subTest(case=index):
                log.write_text(payload, encoding="utf-8")
                with self.assertRaises(DeploymentSafetyError):
                    find_latest_ea_session_evidence(
                        self.logs,
                        session_id=SESSION_ID,
                        expected_account_login="108098316",
                        expected_account_server="XMGlobal-MT5 5",
                    )

    def test_production_contract_covers_every_material_mq5_input(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        mq5 = (repo / "mt5" / "Experts" / "bot-ea" / "GoldMSniperParity.mq5").read_text(
            encoding="utf-8"
        )
        declarations = re.findall(
            r"^input\s+(\w+)\s+(Inp[A-Za-z0-9]+)\s*=\s*([^;]+);",
            mq5,
            flags=re.MULTILINE,
        )
        parsed: dict[str, str] = {}
        for type_name, name, raw_default in declarations:
            if name == "InpResearchRunId":
                continue
            value = raw_default.strip()
            if type_name == "string":
                value = value.removeprefix('"').removesuffix('"')
            elif type_name == "double":
                value = f"{float(value):.8f}"
            elif type_name == "bool":
                value = value.lower()
            parsed[name] = value

        contract = load_production_ea_input_contract()
        self.assertEqual(parsed, contract["inputs"])
        self.assertEqual(len(parsed), len(declarations) - 1)
        self.assertIn(
            f'#define GOLDM_PRODUCTION_INPUT_CONTRACT_SHA256 "{contract["sha256"]}"',
            mq5,
        )
        for name in parsed:
            self.assertEqual(mq5.count(f" {name}=%"), 1, name)

    def test_windows_scripts_are_fail_closed_by_construction(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        deploy = (repo / "scripts" / "deploy-goldm-windows-vm.ps1").read_text()
        bootstrap = (repo / "scripts" / "bootstrap-goldm-windows-vm.ps1").read_text()
        common = (repo / "scripts" / "goldm-deployment-common.psm1").read_text()
        backup = (repo / "scripts" / "backup-goldm-windows-vm.ps1").read_text()
        restore = (repo / "scripts" / "restore-goldm-windows-vm.ps1").read_text()
        update = (repo / "scripts" / "update-goldm-windows-vm.ps1").read_text()
        for source in (deploy, bootstrap):
            self.assertIn("[Parameter(Mandatory = $true)][string]$TerminalExecutable", source)
            self.assertIn("[Parameter(Mandatory = $true)][string]$TerminalDataPath", source)
        self.assertNotIn("git pull", deploy)
        self.assertNotIn("pip install -e", deploy)
        self.assertNotIn("Get-Process terminal64", deploy + common)
        self.assertNotIn("Stop-Process -Force", deploy + common)
        self.assertIn('"backup-db"', deploy)
        self.assertIn('"restore-db"', deploy)
        self.assertIn("RESTORE_STOPPED_GOLDM_DATABASE", deploy)
        self.assertIn('"write-runtime-session"', deploy)
        self.assertIn("runtimeSession", deploy)
        self.assertIn('"verify-tree-manifest"', deploy)
        self.assertIn("Wait-GoldMSessionEvidence", deploy)
        self.assertIn("StageOnly", deploy)
        self.assertIn('"backup-db"', backup)
        self.assertIn("RESTORE_STOPPED_GOLDM_DATABASE", restore)
        self.assertIn("RestoreRuntimeSession", restore)
        self.assertIn("git fetch --no-tags --prune", update)
        self.assertIn('git rev-parse "FETCH_HEAD^{commit}"', update)
        self.assertIn(
            "[Parameter(Mandatory = $true)][string]$ExpectedCommit", update
        )
        self.assertIn("$resolved -cne $ExpectedCommit", update)
        self.assertNotIn("git pull", update)
        self.assertNotIn("set InpResearchRunId", deploy)

    def test_backup_restore_and_handoff_are_portable_and_privately_bound(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        backup = (repo / "scripts" / "backup-goldm-windows-vm.ps1").read_text()
        restore = (repo / "scripts" / "restore-goldm-windows-vm.ps1").read_text()
        handoff = (repo / "scripts" / "new-goldm-safe-handoff.ps1").read_text()

        for source in (backup, restore, handoff):
            self.assertIn(
                "[Parameter(Mandatory = $true)][string]$PythonExecutable", source
            )
            self.assertIn(
                "[Parameter(Mandatory = $true)][string]$PythonSha256", source
            )
            self.assertIn("Assert-GoldMPythonInterpreter", source)
            self.assertIn("Protect-GoldMPrivateFile -Path $EnvFile", source)
            self.assertIn("Protect-GoldMPrivateFile -Path $DatabasePath", source)

        self.assertIn("schemaVersion = 2", backup)
        self.assertIn('member = "goldm_signal.db"', backup)
        self.assertIn('xmlMember = "scheduled-task.xml"', backup)
        for binding in (
            "workerReleaseTreeManifestSha256",
            "workerRuntimeConfigSha256",
            "workerProductionConfigSha256",
        ):
            self.assertIn(binding, backup)
            self.assertIn(binding, restore)
        for legacy_reference in (
            "$manifest.database.destination",
            "$manifest.environment.backup",
            "$manifest.runtimeSession.backup",
            "$manifest.activeEa.mq5Backup",
            "$manifest.activeEa.ex5Backup",
            "$manifest.scheduledTask.xmlBackup",
        ):
            self.assertNotIn(legacy_reference, restore)

        self.assertIn("[int]$manifest.schemaVersion -ne 2", restore)
        self.assertIn(
            "[Parameter(Mandatory = $true)][string]$ManifestSha256", restore
        )
        self.assertIn("operator-supplied SHA-256", restore)
        self.assertIn("undo_manifest_sha256=", restore)
        self.assertIn("[System.IO.Path]::IsPathRooted($Member)", restore)
        self.assertIn("[System.IO.FileAttributes]::ReparsePoint", restore)
        self.assertIn("$canonicalMember.StartsWith", restore)
        self.assertIn("-Member ([string]$manifest.database.member)", restore)
        self.assertIn("-Member ([string]$manifest.environment.member)", restore)

        for source in (backup, restore):
            self.assertIn('Join-Path $runtimeConfigRoot "runtime.env"', source)
            self.assertIn(
                "EnvFile must be the task-bound private runtime snapshot", source
            )
            self.assertNotIn('Join-Path $RepoRoot ".env"', source)

        self.assertIn(".goldm-operator-backup-root", backup)
        self.assertIn("Custom OutputRoot must be a dedicated leaf", backup)
        self.assertNotIn("New-GoldMPrivateDirectory -Path $outputRootParent", backup)

        staged_env_hash = restore.index(
            "Assert-BackupHash -Path $envBackup"
        )
        staged_task_validation = restore.index(
            "$manifestTaskContract = Assert-GoldMWorkerTaskActionContract",
            staged_env_hash,
        )
        self.assertLess(staged_env_hash, staged_task_validation)
        self.assertIn(
            "-RuntimeConfigVerificationFile $envBackup",
            restore,
        )
        self.assertIn(
            "$RestoreEnvironment -and\n    -not $RestoreTaskAction",
            restore,
        )
        self.assertIn(
            "Restored environment digest would break the current worker task binding",
            restore,
        )

        worker_state_branch = restore.rindex("if ($StartWorker) {")
        final_broker_probe = restore.index(
            "$finalStoppedAction = $currentTaskContract",
            worker_state_branch,
        )
        final_disabled_barrier = restore.index(
            "Disable-GoldMScheduledTaskAndWait -TaskName $TaskName",
            final_broker_probe,
        )
        maintenance_complete = restore.index(
            "Complete-GoldMMaintenanceLock", final_disabled_barrier
        )
        restore_ok = restore.index('Write-Output "RESTORE_OK"', maintenance_complete)
        self.assertLess(worker_state_branch, final_broker_probe)
        self.assertLess(final_broker_probe, final_disabled_barrier)
        self.assertLess(final_disabled_barrier, maintenance_complete)
        self.assertLess(maintenance_complete, restore_ok)
        self.assertIn(
            "$finalStoppedContract = Assert-GoldMWorkerTaskActionContract",
            restore[final_disabled_barrier:maintenance_complete],
        )
        self.assertIn(
            '"--skip-existing-session-evidence"',
            restore[final_broker_probe:maintenance_complete],
        )

    def test_restore_stages_external_backup_before_trust_or_use(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        restore = (repo / "scripts" / "restore-goldm-windows-vm.ps1").read_text(
            encoding="utf-8"
        )

        stage_call = restore.index("Copy-GoldMExternalBackupToPrivateStage `")
        staged_authority = restore.index(
            "$ManifestRoot = [string]$staging.Root", stage_call
        )
        trusted_digest = restore.index(
            "$actualManifestSha256 = Get-GoldMFileSha256 -Path $ManifestPath",
            staged_authority,
        )
        seal_verification = restore.index('"verify-seal"', trusted_digest)
        manifest_parse = restore.index("ConvertFrom-Json", seal_verification)
        self.assertLess(stage_call, staged_authority)
        self.assertLess(staged_authority, trusted_digest)
        self.assertLess(trusted_digest, seal_verification)
        self.assertLess(seal_verification, manifest_parse)

        post_stage = restore[staged_authority:]
        self.assertNotIn("$externalManifestItem", post_stage)
        self.assertNotIn("$externalRoot", post_stage)
        self.assertNotIn("-ExternalManifestPath", post_stage)
        self.assertIn("$script:ManifestRoot", restore)
        self.assertIn("Private staged backup contains an undeclared entry", restore)
        self.assertIn("aliases two roles to one member", restore)
        self.assertIn("New-GoldMPrivateDirectory -Path $restoreStagingParent", restore)

        task_lookup = restore.index(
            "$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop"
        )
        trusted_current_action = restore.index(
            "-Action (@($task.Actions)[0])", task_lookup
        )
        disable_barrier = restore.index(
            "Disable-GoldMScheduledTaskAndWait", trusted_current_action
        )
        self.assertLess(task_lookup, trusted_current_action)
        self.assertLess(trusted_current_action, disable_barrier)

    @unittest.skipUnless(
        shutil.which("powershell.exe"),
        "Windows PowerShell 5.1 is unavailable",
    )
    def test_restore_task_contract_rejects_malicious_action_before_mutation(
        self,
    ) -> None:
        repo = Path(__file__).resolve().parents[1]
        common = repo / "scripts" / "goldm-deployment-common.psm1"
        runtime = self.root / "runtime_data"
        releases = runtime / "releases"
        releases.mkdir(parents=True)
        env_file = runtime / "config" / "runtime.env"
        env_file.parent.mkdir()
        env_file.write_text("SECRET=value\n", encoding="utf-8")
        database = runtime / "goldm_signal.db"
        database.write_bytes(b"not-used-before-action-rejection")

        def ps_quote(path: Path) -> str:
            return str(path).replace("'", "''")

        script = f"""
$ErrorActionPreference = 'Stop'
Import-Module '{ps_quote(common)}' -Force
$malicious = [pscustomobject]@{{
    Execute = $env:ComSpec
    Arguments = '/c whoami'
    WorkingDirectory = '{ps_quote(self.root)}'
}}
$rejected = $false
try {{
    [void](Assert-GoldMWorkerTaskActionContract `
        -Action $malicious `
        -ExpectedEnvFile '{ps_quote(env_file)}' `
        -ExpectedDatabasePath '{ps_quote(database)}' `
        -ReleasesRoot '{ps_quote(releases)}' `
        -HelperPythonExecutable '{ps_quote(self.root / "unused-python.exe")}' `
        -HelperRepoRoot '{ps_quote(repo)}')
}}
catch {{
    if ($_.Exception.Message -notlike '*pythonw.exe*') {{ throw }}
    $rejected = $true
}}
if (-not $rejected) {{ throw 'malicious task action was accepted' }}
Write-Output 'MALICIOUS_TASK_ACTION_REJECTED'
"""
        result = subprocess.run(
            [
                shutil.which("powershell.exe") or "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            env={
                **os.environ,
                "PSModulePath": str(
                    Path(os.environ["WINDIR"])
                    / "system32"
                    / "WindowsPowerShell"
                    / "v1.0"
                    / "Modules"
                ),
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout={result.stdout}\nstderr={result.stderr}",
        )
        self.assertIn("MALICIOUS_TASK_ACTION_REJECTED", result.stdout)

    @unittest.skipUnless(
        shutil.which("powershell.exe"),
        "Windows PowerShell 5.1 is unavailable",
    )
    def test_task_action_pins_manifest_digest_against_full_release_reseal(
        self,
    ) -> None:
        repo = Path(__file__).resolve().parents[1]
        common = repo / "scripts" / "goldm-deployment-common.psm1"
        canonical_root = (
            Path(os.environ["LOCALAPPDATA"])
            / "Temp"
            / f"goldm-task-anchor-{self.root.name}"
        )
        canonical_root.mkdir()

        def remove_fixture_tree() -> None:
            if not canonical_root.exists():
                return
            for candidate in canonical_root.rglob("*"):
                candidate.chmod(0o700)
            shutil.rmtree(canonical_root)

        self.addCleanup(remove_fixture_tree)
        runtime = canonical_root / "runtime_data"
        releases = runtime / "releases"
        release_commit = "a" * 40
        release = releases / "20260815T000000Z-aaaaaaaaaaaa-1234abcd"
        app = release / "app"
        shutil.copytree(repo / "src", app / "src")
        shutil.copytree(repo / "config", app / "config")
        pythonw = release / ".venv" / "Scripts" / "pythonw.exe"
        pythonw.parent.mkdir(parents=True)
        pythonw.write_bytes(b"fixture-pythonw")
        env_file = runtime / "config" / "runtime.env"
        env_file.parent.mkdir(parents=True)
        env_file.write_text("GOLDM_EXECUTION_MODE=off\n", encoding="utf-8")
        database = runtime / "goldm_signal.db"
        database.write_bytes(b"fixture-database")
        manifest = release / "release-tree-manifest.json"
        sealed = build_tree_manifest(release, manifest)
        pinned_manifest_sha = str(sealed["sha256"])
        runtime_config_sha = sha256_file(env_file)
        production_config_sha = str(
            load_production_ea_input_contract()["sha256"]
        )

        def ps_quote(value: Path | str) -> str:
            return str(value).replace("'", "''")

        def invoke_contract(
            *,
            expect_success: bool,
            runtime_config_verification_file: Path | None = None,
        ) -> subprocess.CompletedProcess[str]:
            verification_argument = ""
            if runtime_config_verification_file is not None:
                verification_argument = (
                    " `\n        -RuntimeConfigVerificationFile '"
                    + ps_quote(runtime_config_verification_file)
                    + "'"
                )
            script = f"""
$ErrorActionPreference = 'Stop'
Import-Module '{ps_quote(common)}' -Force
$releaseRoot = (Resolve-Path -LiteralPath '{ps_quote(release)}').Path
$applicationRoot = (Resolve-Path -LiteralPath '{ps_quote(app)}').Path
$manifestPath = (Resolve-Path -LiteralPath '{ps_quote(manifest)}').Path
$envPath = (Resolve-Path -LiteralPath '{ps_quote(env_file)}').Path
$databasePath = (Resolve-Path -LiteralPath '{ps_quote(database)}').Path
$pythonwPath = (Resolve-Path -LiteralPath '{ps_quote(pythonw)}').Path
$arguments = New-GoldMWorkerArgumentLine `
    -ReleaseRoot $releaseRoot `
    -ApplicationRoot $applicationRoot `
    -ReleaseManifest $manifestPath `
    -ReleaseManifestSha256 '{pinned_manifest_sha}' `
    -EnvFile $envPath `
    -DatabasePath $databasePath `
    -ReleaseCommit '{release_commit}' `
    -DeploymentNonce '{"b" * 32}' `
    -RuntimeConfigSha256 '{runtime_config_sha}' `
    -ProductionConfigSha256 '{production_config_sha}'
if ($arguments.Length -ge 30000) {{ throw 'worker task argument line exceeds the safe Task Scheduler budget' }}
$action = [pscustomobject]@{{
    Execute = $pythonwPath
    Arguments = $arguments
    WorkingDirectory = $applicationRoot
}}
$accepted = $false
try {{
    $contract = Assert-GoldMWorkerTaskActionContract `
        -Action $action `
        -ExpectedEnvFile $envPath `
        -ExpectedDatabasePath $databasePath `
        -ReleasesRoot '{ps_quote(releases)}' `
        -HelperPythonExecutable '{ps_quote(Path(sys.executable))}' `
        -HelperRepoRoot '{ps_quote(repo)}'{verification_argument}
    $accepted = $true
    if ($contract.ReleaseTreeManifestSha256 -cne '{pinned_manifest_sha}') {{
        throw 'task contract returned the wrong pinned manifest digest'
    }}
}}
catch {{
    if ({'$true' if expect_success else '$false'}) {{ throw }}
    if ($_.Exception.Message -notlike '*manifest*') {{ throw }}
}}
if ({'$true' if expect_success else '$false'} -and -not $accepted) {{
    throw 'valid pinned task action was rejected'
}}
if (-not {'$true' if expect_success else '$false'} -and $accepted) {{
    throw 'resealed release bypassed the task-pinned manifest digest'
}}
Write-Output 'TASK_MANIFEST_ANCHOR_OK'
"""
            return subprocess.run(
                [
                    shutil.which("powershell.exe") or "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
            )

        valid = invoke_contract(expect_success=True)
        self.assertEqual(
            valid.returncode,
            0,
            msg=f"stdout={valid.stdout}\nstderr={valid.stderr}",
        )
        self.assertIn("TASK_MANIFEST_ANCHOR_OK", valid.stdout)

        staged_env = runtime / "restore-staging" / "sealed-runtime.env"
        staged_env.parent.mkdir()
        staged_env.write_text("GOLDM_EXECUTION_MODE=off\n", encoding="utf-8")
        env_file.write_text("GOLDM_EXECUTION_MODE=changed\n", encoding="utf-8")
        restore_precheck = invoke_contract(
            expect_success=True,
            runtime_config_verification_file=staged_env,
        )
        self.assertEqual(
            restore_precheck.returncode,
            0,
            msg=(
                f"stdout={restore_precheck.stdout}\n"
                f"stderr={restore_precheck.stderr}"
            ),
        )
        self.assertIn("TASK_MANIFEST_ANCHOR_OK", restore_precheck.stdout)
        env_file.write_text("GOLDM_EXECUTION_MODE=off\n", encoding="utf-8")

        (app / "src" / "goldm_signal" / "deployment.py").write_text(
            "# attacker replaced the application tree\n", encoding="utf-8"
        )
        manifest.chmod(0o666)
        manifest.with_name(manifest.name + ".sha256").chmod(0o666)
        manifest.unlink()
        manifest.with_name(manifest.name + ".sha256").unlink()
        build_tree_manifest(release, manifest)
        resealed = invoke_contract(expect_success=False)
        self.assertEqual(
            resealed.returncode,
            0,
            msg=f"stdout={resealed.stdout}\nstderr={resealed.stderr}",
        )
        self.assertIn("TASK_MANIFEST_ANCHOR_OK", resealed.stdout)

    @unittest.skipUnless(
        shutil.which("powershell.exe"),
        "Windows PowerShell 5.1 is unavailable",
    )
    def test_predecessor_proof_uses_action_bound_release_not_target_helper(
        self,
    ) -> None:
        repo = Path(__file__).resolve().parents[1]
        common = repo / "scripts" / "goldm-deployment-common.psm1"
        common_source = common.read_text(encoding="utf-8")
        function_source = common_source[
            common_source.index("function Get-GoldMWorkerProofAuthority") :
            common_source.index("function Resolve-GoldMAccountSid")
        ]
        release = self.root / "runtime_data" / "releases" / "old-release"
        application = release / "app"
        scripts = release / ".venv" / "Scripts"
        application.mkdir(parents=True)
        scripts.mkdir(parents=True)
        old_python = scripts / "python.exe"
        old_pythonw = scripts / "pythonw.exe"
        old_python.write_bytes(b"old-python")
        old_pythonw.write_bytes(b"old-pythonw")
        manifest = release / "release-tree-manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        manifest_sha = "a" * 64
        production_sha = "b" * 64

        def ps_quote(value: Path | str) -> str:
            return str(value).replace("'", "''")

        script = f"""
$ErrorActionPreference = 'Stop'
function Resolve-GoldMFile {{
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {{ throw $Label }}
    return (Resolve-Path -LiteralPath $Path).Path
}}
function Resolve-GoldMDirectory {{
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {{ throw $Label }}
    return (Resolve-Path -LiteralPath $Path).Path
}}
function Assert-GoldMPythonRuntime {{
    param([string]$PythonExecutable)
    return [pscustomobject]@{{ Path = $PythonExecutable }}
}}
$oldPython = (Resolve-Path -LiteralPath '{ps_quote(old_python)}').Path
$oldPythonw = (Resolve-Path -LiteralPath '{ps_quote(old_pythonw)}').Path
$oldRepo = (Resolve-Path -LiteralPath '{ps_quote(application)}').Path
$script:Unsupported = $false
function Invoke-GoldMDeploymentHelper {{
    param([string]$PythonExecutable, [string]$RepoRoot, [string[]]$Arguments)
    if (-not [string]::Equals($PythonExecutable, $oldPython, [StringComparison]::OrdinalIgnoreCase)) {{
        throw 'target Python attempted to reinterpret predecessor proof'
    }}
    if (-not [string]::Equals($RepoRoot, $oldRepo, [StringComparison]::OrdinalIgnoreCase)) {{
        throw 'target helper attempted to reinterpret predecessor proof'
    }}
    if ($Arguments[0] -eq 'verify-tree-manifest') {{
        return [pscustomobject]@{{ manifest_sha256 = '{manifest_sha}' }}
    }}
    if ($Arguments[0] -eq 'production-input-contract') {{
        $schema = 1
        if ($script:Unsupported) {{ $schema = 2 }}
        return [pscustomobject]@{{ schema_version = $schema; sha256 = '{production_sha}' }}
    }}
    throw 'unexpected helper operation'
}}
{function_source}
$contract = [pscustomobject]@{{
    ReleaseRoot = '{ps_quote(release)}'
    WorkingDirectory = '{ps_quote(application)}'
    Execute = '{ps_quote(old_pythonw)}'
    ReleaseTreeManifest = '{ps_quote(manifest)}'
    ReleaseTreeManifestSha256 = '{manifest_sha}'
    ProductionConfigSha256 = '{production_sha}'
    ReleaseCommit = '{"c" * 40}'
    RuntimeConfigSha256 = '{"d" * 64}'
    DeploymentNonceSha256 = '{"e" * 64}'
}}
$authority = Get-GoldMWorkerProofAuthority -TaskActionContract $contract
if (
    -not [string]::Equals($authority.PythonExecutable, $oldPython, [StringComparison]::OrdinalIgnoreCase) -or
    -not [string]::Equals($authority.RepoRoot, $oldRepo, [StringComparison]::OrdinalIgnoreCase)
) {{
    throw 'predecessor authority was not returned exactly'
}}
$script:Unsupported = $true
$rejected = $false
try {{ [void](Get-GoldMWorkerProofAuthority -TaskActionContract $contract) }}
catch {{
    if ($_.Exception.Message -notlike '*unsupported or mismatched*') {{ throw }}
    $rejected = $true
}}
if (-not $rejected) {{ throw 'unsupported predecessor proof schema was accepted' }}
Write-Output 'OLD_RELEASE_AUTHORITY_OK'
"""
        result = subprocess.run(
            [
                shutil.which("powershell.exe") or "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout={result.stdout}\nstderr={result.stderr}",
        )
        self.assertIn("OLD_RELEASE_AUTHORITY_OK", result.stdout)

        deploy = (repo / "scripts" / "deploy-goldm-windows-vm.ps1").read_text(
            encoding="utf-8"
        )
        restore = (repo / "scripts" / "restore-goldm-windows-vm.ps1").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            deploy.index("$originalProofAuthority = Get-GoldMWorkerProofAuthority"),
            deploy.index('Write-Output "phase=stop_worker"'),
        )
        rollback = deploy[deploy.index("catch {\n    $deploymentError") :]
        self.assertIn("$originalProofAuthority.PythonExecutable", rollback)
        self.assertIn("$originalProofAuthority.RepoRoot", rollback)
        self.assertIn("$needsManifestProofAuthority", restore)
        self.assertIn("$manifestProofAuthority.PythonExecutable", restore)
        self.assertIn("$finalProofAuthority = $manifestProofAuthority", restore)

    @unittest.skipUnless(
        shutil.which("powershell.exe"),
        "Windows PowerShell 5.1 is unavailable",
    )
    def test_private_env_stage_is_authoritative_after_external_source_swap(
        self,
    ) -> None:
        repo = Path(__file__).resolve().parents[1]
        common = repo / "scripts" / "goldm-deployment-common.psm1"
        common_source = common.read_text(encoding="utf-8")
        function_start = common_source.index(
            "function Install-GoldMFileAtomically"
        )
        function_end = common_source.index(
            "\nfunction Restore-GoldMFile", function_start
        )
        staging_functions = common_source[function_start:function_end]
        external = self.root / "operator.env"
        external.write_text("TELEGRAM_BOT_TOKEN=original\n", encoding="utf-8")
        expected_sha = sha256_file(external)
        private_root = self.root / "runtime_data" / "env-staging"
        private_root.mkdir(parents=True)
        stage_directory = private_root / "deployment-fixture"
        destination = self.root / "runtime_data" / "config" / "runtime.env"
        destination.parent.mkdir()

        def ps_quote(value: Path | str) -> str:
            return str(value).replace("'", "''")

        script = f"""
$ErrorActionPreference = 'Stop'
function Assert-GoldMAbsolutePathInput {{ param([string]$Path, [string]$Label) }}
function Assert-GoldMNoReparsePath {{ param([string]$Path, [string]$Label) }}
function Resolve-GoldMFile {{
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {{ throw $Label }}
    return (Resolve-Path -LiteralPath $Path).Path
}}
function Resolve-GoldMDirectory {{
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {{ throw $Label }}
    return (Resolve-Path -LiteralPath $Path).Path
}}
function New-GoldMPrivateDirectory {{
    param([string]$Path)
    New-Item -ItemType Directory -Path $Path -ErrorAction Stop | Out-Null
}}
function Protect-GoldMPrivateFile {{ param([string]$Path) }}
function Get-GoldMFileSha256 {{
    param([string]$Path)
    $stream = [System.IO.File]::OpenRead($Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {{
        return -join ($sha.ComputeHash($stream) | ForEach-Object {{ $_.ToString('x2') }})
    }}
    finally {{
        $sha.Dispose()
        $stream.Dispose()
    }}
}}
function Get-GoldMFileEvidence {{
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    return [pscustomobject]@{{
        Exists = $true
        Sha256 = Get-GoldMFileSha256 -Path $Path
        Length = [long]$item.Length
    }}
}}
{staging_functions}
$stage = Copy-GoldMFileToPrivateStage `
    -Source '{ps_quote(external)}' `
    -StageDirectory '{ps_quote(stage_directory)}' `
    -ExpectedSha256 '{expected_sha}'
[System.IO.File]::WriteAllText(
    '{ps_quote(external)}',
    "TELEGRAM_BOT_TOKEN=swapped`n",
    [System.Text.UTF8Encoding]::new($false)
)
Install-GoldMFileAtomically `
    -Source ([string]$stage.Path) `
    -Destination '{ps_quote(destination)}' `
    -ExpectedSha256 '{expected_sha}'
if ((Get-GoldMFileSha256 -Path '{ps_quote(destination)}') -cne '{expected_sha}') {{
    throw 'external source swap changed the installed private environment'
}}
if ((Get-Content -LiteralPath '{ps_quote(destination)}' -Raw) -notlike '*original*') {{
    throw 'installed environment did not come from the private stage'
}}
Write-Output 'PRIVATE_ENV_STAGE_SWAP_OK'
"""
        result = subprocess.run(
            [
                shutil.which("powershell.exe") or "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout={result.stdout}\nstderr={result.stderr}",
        )
        self.assertIn("PRIVATE_ENV_STAGE_SWAP_OK", result.stdout)

    @unittest.skipUnless(
        shutil.which("powershell.exe"),
        "Windows PowerShell 5.1 is unavailable",
    )
    def test_restore_private_stage_is_immune_to_external_swap_after_copy(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        restore_source = (
            repo / "scripts" / "restore-goldm-windows-vm.ps1"
        ).read_text(encoding="utf-8")
        function_start = restore_source.index(
            "function Copy-GoldMExternalBackupToPrivateStage"
        )
        function_end = restore_source.index(
            "\nif (-not ($RestoreDatabase", function_start
        )
        staging_function = restore_source[function_start:function_end]

        external = self.root / "external-backup"
        external.mkdir()
        manifest = external / "backup-manifest.json"
        sidecar = external / "backup-manifest.json.sha256"
        member = external / "runtime.env"
        manifest.write_text('{"schemaVersion":2}\n', encoding="utf-8")
        sidecar.write_text("0" * 64 + "  backup-manifest.json\n", encoding="ascii")
        member.write_text("ORIGINAL_SECRET=one\n", encoding="utf-8")
        staging = self.root / "private-stage"

        def ps_quote(path: Path) -> str:
            return str(path).replace("'", "''")

        script = f"""
$ErrorActionPreference = 'Stop'
function Resolve-GoldMDirectory {{
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {{ throw $Label }}
    return (Resolve-Path -LiteralPath $Path).Path
}}
function Resolve-GoldMFile {{
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {{ throw $Label }}
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {{ throw $Label }}
    return (Resolve-Path -LiteralPath $Path).Path
}}
function Assert-GoldMReadOnlyFlatDirectory {{
    param([string]$Path)
    foreach ($item in @(Get-ChildItem -LiteralPath $Path -Force)) {{
        if ($item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {{ throw 'not flat' }}
    }}
    return (Resolve-Path -LiteralPath $Path).Path
}}
function New-GoldMPrivateDirectory {{
    param([string]$Path)
    New-Item -ItemType Directory -Path $Path -ErrorAction Stop | Out-Null
}}
function Protect-GoldMPrivateFile {{ param([string]$Path) }}
{staging_function}
$staged = Copy-GoldMExternalBackupToPrivateStage `
    -ExternalManifestPath '{ps_quote(manifest)}' `
    -StagingRoot '{ps_quote(staging)}'
[System.IO.File]::WriteAllText('{ps_quote(member)}', "SWAPPED_SECRET=two`n")
$stagedMember = Join-Path $staged.Root 'runtime.env'
if ((Get-Content -LiteralPath $stagedMember -Raw).Trim() -ne 'ORIGINAL_SECRET=one') {{
    throw 'private stage followed an external swap'
}}
Write-Output 'RESTORE_STAGE_SWAP_OK'
"""
        result = subprocess.run(
            [
                shutil.which("powershell.exe") or "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout={result.stdout}\nstderr={result.stderr}",
        )
        self.assertIn("RESTORE_STAGE_SWAP_OK", result.stdout)
        self.assertEqual(
            (staging / "runtime.env").read_text(encoding="utf-8"),
            "ORIGINAL_SECRET=one\n",
        )

    def test_windows_release_is_offline_sealed_and_interpreter_bound(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        deploy = (repo / "scripts" / "deploy-goldm-windows-vm.ps1").read_text(
            encoding="utf-8"
        )
        bootstrap = (
            repo / "scripts" / "bootstrap-goldm-windows-vm.ps1"
        ).read_text(encoding="utf-8")
        update = (repo / "scripts" / "update-goldm-windows-vm.ps1").read_text(
            encoding="utf-8"
        )
        common = (repo / "scripts" / "goldm-deployment-common.psm1").read_text(
            encoding="utf-8"
        )
        verify = (repo / "scripts" / "verify-goldm-release.ps1").read_text(
            encoding="utf-8"
        )
        backup = (repo / "scripts" / "backup-goldm-windows-vm.ps1").read_text(
            encoding="utf-8"
        )
        restore = (repo / "scripts" / "restore-goldm-windows-vm.ps1").read_text(
            encoding="utf-8"
        )
        handoff = (
            repo / "scripts" / "new-goldm-safe-handoff.ps1"
        ).read_text(encoding="utf-8")

        for source in (deploy, bootstrap, update):
            self.assertIn(
                "[Parameter(Mandatory = $true)][string]$PythonExecutable", source
            )
            self.assertIn(
                "[Parameter(Mandatory = $true)][string]$PythonSha256", source
            )
            self.assertIn(
                "[Parameter(Mandatory = $true)][string]$WheelhousePath", source
            )
            self.assertIn(
                "[Parameter(Mandatory = $true)][string]$WheelhouseManifestSha256",
                source,
            )
            self.assertIn("Assert-GoldMPythonInterpreter", source)
            self.assertNotIn("PythonLauncher", source)

        self.assertIn("CPython 3.14 64-bit AMD64", common)
        interpreter_contract = common[
            common.index("function Assert-GoldMPythonInterpreter") : common.index(
                "function Assert-GoldMPythonRuntime"
            )
        ]
        self.assertLess(
            interpreter_contract.index("Get-GoldMFileSha256"),
            interpreter_contract.index("Assert-GoldMPythonRuntime"),
        )
        self.assertIn("--no-index", common)
        self.assertIn("--only-binary=:all:", common)
        self.assertIn("--require-hashes", common)
        self.assertNotIn("goldm-sealed-release.pth", common)
        self.assertIn("Assert-GoldMReadOnlyFlatDirectory", common)
        self.assertNotIn("Protect-GoldMPrivateFlatDirectory", common)
        self.assertIn("Copy-GoldMVerifiedWheelhouseToPrivateStage", common)
        self.assertIn("Get-GoldMWorkerBootstrapSource", common)
        self.assertIn("Get-GoldMWorkerBootstrapBase64", common)
        self.assertIn("--release-manifest-sha256", common)
        self.assertIn("--runtime-config-sha256", common)
        self.assertIn("--production-config-sha256", common)
        self.assertIn("Wait-GoldMTelegramPollReadiness", common)
        self.assertIn("function Disable-GoldMScheduledTaskAndWait", common)
        self.assertIn("Get-GoldMExactWorkerProcesses", common)
        self.assertIn("function New-GoldMDeploymentNonce", common)
        self.assertIn("--expected-deployment-nonce-sha256", common)
        self.assertIn("active-maintenance.json", common)
        self.assertIn("[System.IO.FileMode]::CreateNew", common)
        self.assertIn("RecoveryJournalSha256", common)
        self.assertIn("Write-GoldMUtf8NoBomFile", common)
        self.assertNotIn("[System.IO.Path]::IsPathFullyQualified(", common)
        self.assertIn("& $python -I -S -B -c $bootstrap", common)
        self.assertIn("Resolve-GoldMPythonSitePackagesDirectory", common)
        self.assertNotIn("import sysconfig; print(sysconfig.get_paths()", common)
        self.assertNotIn(
            "import sysconfig; print(sysconfig.get_paths()", bootstrap + verify
        )
        self.assertNotIn("$env:PYTHONPATH", common)
        worker_bootstrap = common[
            common.index("function Get-GoldMWorkerBootstrapSource") : common.index(
                "function Get-GoldMWorkerBootstrapBase64"
            )
        ]
        self.assertLess(
            worker_bootstrap.index("if observed != declared:"),
            worker_bootstrap.index("sys.path[:0]"),
        )
        self.assertIn('release / ".venv" / "Lib" / "site-packages"', worker_bootstrap)
        self.assertNotIn('pip install --disable-pip-version-check', deploy + bootstrap)
        self.assertNotIn('$appRoot + "[live]"', deploy)
        self.assertNotIn('$RepoRoot + "[live]"', bootstrap)
        self.assertNotIn("bootstrap-venv", bootstrap)

        for source in (deploy, bootstrap):
            self.assertIn('"verify-offline-wheelhouse"', source)
            self.assertIn("Copy-GoldMVerifiedWheelhouseToPrivateStage", source)
            self.assertIn("-WheelhousePath $stagedWheelhouse", source)
            self.assertNotIn("-WheelhousePath $WheelhousePath", source)
            self.assertIn("git archive --format=zip", source)
            self.assertIn('"verify-tree-manifest"', source)
            self.assertIn("New-GoldMPrivateDirectory -Path $runtimeRoot", source)
            self.assertIn('Join-Path $runtimeConfigRoot "runtime.env"', source)
            self.assertIn("Install-GoldMFileAtomically", source)
            self.assertIn("Copy-GoldMFileToPrivateStage", source)
            self.assertIn("$stagedSourceEnvFile", source)
            self.assertNotIn('"--env-file", $SourceEnvFile', source)
        self.assertIn(
            "[Parameter(Mandatory = $true)][string]$ExpectedSha256",
            common,
        )
        self.assertLess(
            bootstrap.index('"verify-tree-manifest"'),
            bootstrap.index('"database_initialize_from_sealed_release"'),
        )
        self.assertIn("-Disable `", bootstrap)
        self.assertIn("New-ScheduledTaskTrigger -AtLogOn -User $operatorUser", bootstrap)
        self.assertNotIn("New-ScheduledTaskTrigger -AtStartup", bootstrap)
        self.assertIn("Assert-GoldMScheduledTaskControlContract", bootstrap)
        self.assertIn("-RequireDisabled", bootstrap)
        self.assertIn("-RestartCount 255", bootstrap)
        self.assertIn("-StartWhenAvailable", bootstrap)
        self.assertIn("-AllowStartIfOnBatteries", bootstrap)
        self.assertIn("-DontStopIfGoingOnBatteries", bootstrap)
        self.assertNotIn("-Force | Out-Null", bootstrap)
        self.assertIn(
            '"inspect-db", "--database", $databaseBackup, "--require-quiescent"',
            backup,
        )
        self.assertIn("-ReleaseCommit $FullCommit", deploy)
        self.assertIn("--release-id $ReleaseCommit", common)
        self.assertIn("Wait-GoldMTelegramPollReadiness", deploy)

        for source in (deploy, bootstrap, update, backup, restore, handoff):
            self.assertIn("Enter-GoldMMaintenanceLock", source)
            self.assertIn("Complete-GoldMMaintenanceLock", source)
            self.assertIn("Exit-GoldMMaintenanceLock", source)
            self.assertIn("MaintenanceRecoveryJournalSha256", source)
        for source in (deploy, restore):
            self.assertIn("Disable-GoldMScheduledTaskAndWait", source)
        self.assertIn("Global\\GOLDM_DEPLOYMENT_MAINTENANCE_V1", common)
        self.assertIn("Protect-GoldMPrivateFile -Path $temporary", common)
        self.assertIn("Invoke-GoldMAtomicReplaceWithoutBackup", common)
        self.assertNotIn(".replace-backup", common)

        self.assertIn("Assert-GoldMStandardTerminalTopology", common)
        self.assertNotIn('"/portable"', common + deploy + bootstrap)
        self.assertIn("ConvertTo-GoldMMetaEditorArgumentLine", deploy)
        self.assertIn("ConvertTo-GoldMMetaEditorArgumentLine", verify)
        self.assertIn("$compileProcess.ExitCode -ne 1", deploy)
        self.assertIn("$process.ExitCode -ne 1", verify)
        self.assertIn('unittest discover -s tests -p "test_*.py"', verify)
        self.assertNotIn("$productionTestModules", verify)
        self.assertIn("-I -S -B -c", verify)
        self.assertNotIn("$env:PYTHONPATH", verify)
        self.assertIn("--deployment-nonce", common)
        self.assertIn("New-GoldMWorkerArgumentLine", deploy)
        self.assertIn("New-GoldMWorkerArgumentLine", bootstrap)
        self.assertIn("Get-GoldMDeploymentNonceSha256", common)
        for source in (deploy, restore):
            self.assertIn(".DeploymentNonceSha256", source)

    def test_isolated_no_site_worker_flags_block_preverification_sitecustomize(
        self,
    ) -> None:
        venv_root = self.root / "preverification-venv"
        venv.EnvBuilder(with_pip=False).create(venv_root)
        if os.name == "nt":
            python = venv_root / "Scripts" / "python.exe"
        else:
            python = venv_root / "bin" / "python"
        purelib_probe = subprocess.run(
            [
                str(python),
                "-I",
                "-B",
                "-c",
                "import sysconfig; print(sysconfig.get_paths()['purelib'])",
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        purelib = Path(purelib_probe.stdout.strip()).resolve()
        try:
            purelib.relative_to(venv_root.resolve())
        except ValueError as exc:
            self.fail(f"fixture purelib escaped its disposable venv: {exc}")
        purelib.mkdir(parents=True, exist_ok=True)
        sentinel = self.root / "sitecustomize-ran.txt"
        (purelib / "sitecustomize.py").write_text(
            f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('EXECUTED')\n",
            encoding="utf-8",
        )

        # The control proves the fixture is reachable through ordinary site
        # initialization even in isolated mode.  The worker's additional -S
        # must prevent that code from running before its tree verifier exits.
        control = subprocess.run(
            [str(python), "-I", "-B", "-c", "print('CONTROL')"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(control.returncode, 0, msg=control.stderr)
        self.assertTrue(sentinel.is_file())
        sentinel.unlink()
        rejected = subprocess.run(
            [str(python), "-I", "-S", "-B", "-c", "raise SystemExit(37)"],
            cwd=purelib,
            env={**os.environ, "PYTHONPATH": str(purelib)},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(rejected.returncode, 37, msg=rejected.stderr)
        self.assertFalse(sentinel.exists())

    @unittest.skipUnless(
        shutil.which("powershell.exe"),
        "Windows PowerShell 5.1 is unavailable",
    )
    def test_common_module_is_windows_powershell_5_1_compatible_and_no_bom(
        self,
    ) -> None:
        repo = Path(__file__).resolve().parents[1]
        common = repo / "scripts" / "goldm-deployment-common.psm1"
        output = self.root / "ps5-no-bom.json"
        quoted_common = str(common).replace("'", "''")
        quoted_output = str(output).replace("'", "''")
        script = f"""
$ErrorActionPreference = 'Stop'
Import-Module '{quoted_common}' -Force
Assert-GoldMAbsolutePathInput -Path 'C:\\GoldM\\fixture.txt' -Label 'fixture'
foreach ($invalid in @('C:relative', '\\root-relative')) {{
    $rejected = $false
    try {{ Assert-GoldMAbsolutePathInput -Path $invalid -Label 'fixture' }}
    catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw "accepted non-qualified path: $invalid" }}
}}
Write-GoldMUtf8NoBomFile -Value '{{"ok":true}}' -Path '{quoted_output}'
$bytes = [System.IO.File]::ReadAllBytes('{quoted_output}')
if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xef -and $bytes[1] -eq 0xbb -and $bytes[2] -eq 0xbf) {{
    throw 'UTF-8 BOM was emitted'
}}
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 255 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
if (
    [string]$settings.MultipleInstances -ne 'IgnoreNew' -or
    [int]$settings.RestartCount -ne 255 -or
    [string]$settings.RestartInterval -ne 'PT1M' -or
    [string]$settings.ExecutionTimeLimit -ne 'PT0S' -or
    $settings.StartWhenAvailable -ne $true -or
    $settings.DisallowStartIfOnBatteries -ne $false -or
    $settings.StopIfGoingOnBatteries -ne $false
) {{ throw 'Windows PowerShell 5.1 cannot materialize the recovery settings contract' }}
$trigger = New-ScheduledTaskTrigger `
    -AtLogOn `
    -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
if ($trigger.Enabled -ne $true -or [string]$trigger.Delay) {{
    throw 'Windows PowerShell 5.1 cannot materialize the exact immediate AtLogOn trigger'
}}
if (
    $null -ne $trigger.Repetition -and
    ([string]$trigger.Repetition.Interval -or [string]$trigger.Repetition.Duration -or $trigger.Repetition.StopAtDurationEnd -eq $true)
) {{ throw 'Windows PowerShell 5.1 emitted a repeating logon trigger' }}
Write-Output 'PS5_CONTRACT_OK'
"""
        result = subprocess.run(
            [
                shutil.which("powershell.exe") or "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            env={
                **os.environ,
                "PSModulePath": str(
                    Path(os.environ["WINDIR"])
                    / "system32"
                    / "WindowsPowerShell"
                    / "v1.0"
                    / "Modules"
                ),
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout={result.stdout}\nstderr={result.stderr}",
        )
        self.assertIn("PS5_CONTRACT_OK", result.stdout)
        self.assertEqual(output.read_bytes(), b'{"ok":true}')

    @unittest.skipUnless(
        shutil.which("powershell.exe"),
        "Windows PowerShell 5.1 is unavailable",
    )
    def test_maintenance_cleanup_preserves_primary_error_and_seals_evidence(
        self,
    ) -> None:
        repo = Path(__file__).resolve().parents[1]
        common = repo / "scripts" / "goldm-deployment-common.psm1"
        journal = self.root / "maintenance-journal.json"
        evidence = self.root / "rollback-manifest.json"
        journal.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "operation": "fixture",
                    "leaseId": "fixture-lease",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        evidence.write_text("{}\n", encoding="utf-8")

        def ps_quote(value: Path | str) -> str:
            return str(value).replace("'", "''")

        script = f"""
$ErrorActionPreference = 'Stop'
Import-Module '{ps_quote(common)}' -Force
$mutex = New-Object System.Threading.Mutex($false)
if (-not $mutex.WaitOne(0)) {{ throw 'fixture mutex acquisition failed' }}
$lease = [pscustomobject]@{{
    Mutex = $mutex
    OwnsJournal = $true
    Completed = $false
    JournalPath = '{ps_quote(journal)}'
    JournalSha256 = Get-GoldMFileSha256 -Path '{ps_quote(journal)}'
    LeaseId = 'fixture-lease'
}}
$env:GOLDM_MAINTENANCE_LEASE_ID = 'fixture-lease'
$observed = $null
$originalStack = $null
try {{
    try {{ throw [System.InvalidOperationException]::new('PRIMARY_SENTINEL') }}
    catch {{
        $primary = $_
        $originalStack = [string]$primary.ScriptStackTrace
        Record-GoldMMaintenanceFailure `
            -Lease $lease `
            -ErrorRecord $primary `
            -EvidencePath '{ps_quote(evidence)}' `
            -EvidenceSha256 '{sha256_file(evidence)}'
        Exit-GoldMMaintenanceLock -Lease $lease -PrimaryError $primary
        throw $primary
    }}
}}
catch {{ $observed = $_ }}
if (-not $observed -or $observed.Exception.Message -ne 'PRIMARY_SENTINEL') {{
    throw "maintenance cleanup masked the primary error: $($observed.Exception.Message)"
}}
if ([string]$observed.ScriptStackTrace -ne $originalStack) {{
    throw 'maintenance cleanup replaced the primary stack trace'
}}
if (Test-Path Env:GOLDM_MAINTENANCE_LEASE_ID) {{
    throw 'maintenance lease environment identity survived outer exit'
}}
$payload = Get-Content -LiteralPath '{ps_quote(journal)}' -Raw | ConvertFrom-Json
if ($payload.failure.disposition -ne 'operation_failed_inspection_required') {{
    throw 'failure journal lacks sanitized disposition'
}}
if ($payload.failure.evidencePath -ne '{ps_quote(evidence)}' -or $payload.failure.evidenceSha256 -ne '{sha256_file(evidence)}') {{
    throw 'failure journal lacks exact rollback evidence binding'
}}
if ((Get-Content -LiteralPath '{ps_quote(journal)}' -Raw) -like '*PRIMARY_SENTINEL*') {{
    throw 'raw primary error leaked into maintenance journal'
}}
Write-Output 'PRIMARY_FAILURE_PRESERVED'
"""
        result = subprocess.run(
            [
                shutil.which("powershell.exe") or "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            cwd=repo,
            env={
                **os.environ,
                "PSModulePath": str(
                    Path(os.environ["WINDIR"])
                    / "system32"
                    / "WindowsPowerShell"
                    / "v1.0"
                    / "Modules"
                ),
            },
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout={result.stdout}\nstderr={result.stderr}",
        )
        self.assertIn("PRIMARY_FAILURE_PRESERVED", result.stdout)

    def test_automatic_rollback_observes_terminal_and_reproves_session(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        deploy = (repo / "scripts" / "deploy-goldm-windows-vm.ps1").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("$terminalStopped", deploy)
        self.assertNotIn("$terminalRestarted", deploy)
        self.assertIn("$remainingTerminals.Count -ne 0", deploy)
        self.assertIn("rollback-mt5-log-cursor.json", deploy)
        self.assertIn("-CursorPath $rollbackLogCursor", deploy)
        self.assertIn("Wait-ExactBrokerPreflight", deploy)
        rollback_block = deploy[deploy.index("catch {\n    $deploymentError") :]
        self.assertIn("$originalProofAuthority.PythonExecutable", rollback_block)
        self.assertIn("$originalProofAuthority.RepoRoot", rollback_block)
        self.assertNotIn("-PythonExecutable $ReleasePython", rollback_block)
        self.assertNotIn("-RepoRoot $appRoot", rollback_block)
        rollback_start = deploy.index(
            "Start-GoldMExactTerminal `\n                -TerminalExecutable",
            deploy.index("rollback-mt5-log-cursor.json"),
        )
        session_proof = deploy.index(
            "Wait-GoldMSessionEvidence", rollback_start
        )
        old_worker_start = deploy.index(
            "Start-GoldMScheduledTaskAndVerify", session_proof
        )
        self.assertLess(rollback_start, session_proof)
        self.assertLess(session_proof, old_worker_start)


if __name__ == "__main__":
    unittest.main()
