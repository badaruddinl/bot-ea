from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bot_ea.mt5_adapter import LiveMT5Adapter, OpenOrderSnapshot
from goldm_signal.deployment import (
    BrokerSnapshot,
    DatabaseSnapshot,
    DeploymentSafetyError,
    assert_cutover_safe,
    collect_broker_snapshot,
)
from goldm_signal.notify import cli


class _OrdersMT5:
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_STATE_PLACED = 1

    def __init__(self, result=()) -> None:
        self.result = result

    def initialize(self, **kwargs):
        del kwargs
        return True

    def shutdown(self):
        return None

    def last_error(self):
        return (1, "orders unavailable")

    def orders_get(self, **kwargs):
        del kwargs
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class BrokerOrderSnapshotTests(unittest.TestCase):
    def test_live_adapter_maps_every_active_order(self) -> None:
        module = _OrdersMT5(
            (
                SimpleNamespace(
                    ticket=91,
                    symbol="GOLD.i#",
                    type=2,
                    state=1,
                    volume_initial=0.2,
                    volume_current=0.1,
                    price_open=2440.5,
                    price_stoplimit=0.0,
                    sl=2430.0,
                    tp=2460.0,
                    time_setup=1_723_689_600,
                    time_expiration=0,
                    magic=260814,
                    position_id=0,
                    comment="not exported by deployment",
                ),
            )
        )

        orders = LiveMT5Adapter(mt5_module=module).load_open_orders()

        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].ticket, 91)
        self.assertEqual(orders[0].order_type, "buy_limit")
        self.assertEqual(orders[0].state, "placed")
        self.assertIsNone(orders[0].position_ticket)

    def test_orders_get_none_and_exception_fail_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "orders_get"):
            LiveMT5Adapter(mt5_module=_OrdersMT5(None)).load_open_orders()
        with self.assertRaisesRegex(OSError, "transport failed"):
            LiveMT5Adapter(
                mt5_module=_OrdersMT5(OSError("transport failed"))
            ).load_open_orders()

    def test_account_switch_during_position_order_sandwich_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            install = root / "install"
            install.mkdir()
            executable = install / "terminal64.exe"
            executable.write_bytes(b"terminal")
            data = root / "data"
            data.mkdir()
            values = {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ADMIN_CHAT_IDS": "123",
                "MT5_PATH": str(executable),
                "MT5_DATA_PATH": str(data),
                "MT5_LAUNCH_MODE": "standard",
                "MT5_LOGIN": "1001",
                "MT5_SERVER": "Demo-Server",
                "GOLDM_EXPECTED_MT5_LOGIN": "1001",
                "GOLDM_EXPECTED_MT5_SERVER": "Demo-Server",
                "GOLDM_EA_SESSION_ID": "deployment-session-1234",
                "GOLDM_ALLOW_LIVE_ACTIVATION": "false",
                "GOLDM_TRADE_LIFECYCLE_ENABLED": "true",
                "GOLDM_EXECUTION_MODE": "off",
            }

            class SwitchingAdapter:
                def __init__(self, **kwargs) -> None:
                    del kwargs
                    self.probes = 0

                def load_terminal_status(self):
                    return SimpleNamespace(
                        path=str(install),
                        data_path=str(data),
                        connected=True,
                    )

                def load_account_fingerprint(self):
                    self.probes += 1
                    return SimpleNamespace(
                        login="1001" if self.probes == 1 else "2002",
                        server="Demo-Server",
                        is_live=False,
                        margin_mode="HEDGING",
                    )

                def load_exact_account_scope(self):
                    return "demo"

                def load_open_positions(self):
                    return []

                def load_open_orders(self):
                    return []

                def shutdown(self):
                    return None

            with self.assertRaisesRegex(DeploymentSafetyError, "identity changed"):
                collect_broker_snapshot(
                    values,
                    terminal_executable=executable,
                    terminal_data_path=data,
                    adapter_factory=SwitchingAdapter,
                )

    def test_collection_includes_all_orders_with_typed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            install = root / "install"
            install.mkdir()
            executable = install / "terminal64.exe"
            executable.write_bytes(b"terminal")
            data = root / "data"
            data.mkdir()
            values = {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ADMIN_CHAT_IDS": "123",
                "MT5_PATH": str(executable),
                "MT5_DATA_PATH": str(data),
                "MT5_LAUNCH_MODE": "standard",
                "MT5_LOGIN": "1001",
                "MT5_SERVER": "Demo-Server",
                "GOLDM_EXPECTED_MT5_LOGIN": "1001",
                "GOLDM_EXPECTED_MT5_SERVER": "Demo-Server",
                "GOLDM_EA_SESSION_ID": "deployment-session-1234",
                "GOLDM_ALLOW_LIVE_ACTIVATION": "false",
                "GOLDM_TRADE_LIFECYCLE_ENABLED": "true",
                "GOLDM_EXECUTION_MODE": "off",
            }

            class BoundAdapter:
                def __init__(self, **kwargs) -> None:
                    del kwargs

                def load_terminal_status(self):
                    return SimpleNamespace(
                        path=str(install),
                        data_path=str(data),
                        connected=True,
                    )

                def load_account_fingerprint(self):
                    return SimpleNamespace(
                        login="1001",
                        server="Demo-Server",
                        is_live=False,
                        margin_mode="HEDGING",
                    )

                def load_exact_account_scope(self):
                    return "demo"

                def load_open_positions(self):
                    return []

                def load_open_orders(self):
                    return [
                        OpenOrderSnapshot(
                            ticket=ticket,
                            symbol="GOLD.i#",
                            order_type="buy_limit",
                            state="placed",
                            volume_initial=0.1,
                            volume_current=0.1,
                            price_open=2400.0 + ticket,
                            price_stoplimit=0.0,
                            sl=2390.0,
                            tp=2420.0,
                            setup_at=None,
                            expiration_at=None,
                            magic=260814,
                        )
                        for ticket in (92, 91)
                    ]

                def shutdown(self):
                    return None

            snapshot = collect_broker_snapshot(
                values,
                terminal_executable=executable,
                terminal_data_path=data,
                adapter_factory=BoundAdapter,
            )

            self.assertEqual([row["ticket"] for row in snapshot.orders], [91, 92])
            self.assertEqual(snapshot.order_count, 2)
            self.assertEqual(snapshot.position_count, 0)
            self.assertEqual(snapshot.snapshot_schema_version, 2)
            self.assertEqual(len(snapshot.orders_sha256), 64)
            self.assertNotIn("comment", snapshot.orders[0])

    def test_orphan_pending_order_blocks_flat_book_preflight(self) -> None:
        database = DatabaseSnapshot(
            path="C:/runtime/goldm.db",
            sha256="a" * 64,
            runtime_execution_mode="off",
            active_executions=(),
            unresolved_actions=(),
        )
        broker = BrokerSnapshot(
            terminal_executable="C:/MT5/terminal64.exe",
            terminal_data_path="C:/MT5Data",
            account_login="1001",
            account_server="Demo-Server",
            account_scope="demo",
            account_margin_mode="HEDGING",
            positions=(),
            orders=(
                {
                    "ticket": 91,
                    "symbol": "GOLD.i#",
                    "order_type": "buy_limit",
                    "state": "placed",
                },
            ),
        )

        self.assertEqual(broker.order_count, 1)
        self.assertEqual(len(broker.orders_sha256), 64)
        with self.assertRaisesRegex(DeploymentSafetyError, "cancel every pending order"):
            assert_cutover_safe(database, broker, release_commit="b" * 40)


class WorkerStartupPathTests(unittest.TestCase):
    def test_cli_import_does_not_eagerly_import_mt5_adapter(self) -> None:
        source_root = Path(__file__).resolve().parents[1] / "src"
        command = (
            "import sys;"
            f"sys.path.insert(0, {str(source_root)!r});"
            "import goldm_signal.notify.cli;"
            "raise SystemExit(1 if 'bot_ea.mt5_adapter' in sys.modules else 0)"
        )
        completed = subprocess.run(
            [sys.executable, "-I", "-c", command],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_env_file_must_be_explicit_absolute_before_runtime_import(self) -> None:
        argv = [
            "goldm-worker",
            "--env-file",
            "relative.env",
            "--release-id",
            "a" * 40,
            "--deployment-nonce",
            "b" * 32,
            "--release-manifest-sha256",
            "c" * 64,
            "--runtime-config-sha256",
            "d" * 64,
            "--production-config-sha256",
            "e" * 64,
        ]
        with (
            patch("sys.argv", argv),
            patch.object(cli, "_import_runtime_dependency") as runtime_import,
        ):
            with self.assertRaisesRegex(RuntimeError, "explicit absolute"):
                cli.main()
        runtime_import.assert_not_called()

    def test_database_wal_or_shm_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            database = root / "worker.db"
            database.write_bytes(b"database")
            target = root / "target"
            target.write_bytes(b"target")
            wal = Path(str(database) + "-wal")
            try:
                wal.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")

            with self.assertRaisesRegex(RuntimeError, "reparse point|symbolic link"):
                cli._inspect_database_paths(database)

    def test_symlinked_ancestor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            real = root / "real"
            real.mkdir()
            env_file = real / "runtime.env"
            env_file.write_text("GOLDM_EXECUTION_MODE=off\n", encoding="utf-8")
            linked = root / "linked"
            try:
                linked.symlink_to(real, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")

            with self.assertRaisesRegex(RuntimeError, "reparse point|symbolic link"):
                cli._read_stable_regular_file(
                    linked / env_file.name, "environment file"
                )

    def test_validated_file_replacement_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            executable = root / "terminal64.exe"
            executable.write_bytes(b"first")
            proof = cli._inspect_startup_path(
                executable, "MT5 executable", kind="file", must_exist=True
            )
            replacement = root / "replacement.exe"
            replacement.write_bytes(b"second")
            os.replace(replacement, executable)

            with self.assertRaisesRegex(RuntimeError, "replaced|changed"):
                cli._assert_path_proof(proof)


if __name__ == "__main__":
    unittest.main()
