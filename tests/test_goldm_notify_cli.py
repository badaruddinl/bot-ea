from __future__ import annotations

import argparse
import hashlib
import io
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from goldm_signal.deployment import load_production_ea_input_contract
from goldm_signal.notify.cli import (
    _deployment_nonce_argument,
    _load_env_file,
    _make_bridge_account_context_provider,
    _management_interval_seconds,
    _release_id_argument,
    _required_ea_session_id,
    _resolve_lifecycle_log_directory,
    _resolve_lifecycle_terminal_data_path,
    _run_position_management_loop,
    _run_telegram_poll_loop,
    _worker_interval_seconds,
    main,
)


class _RecordingWorker:
    def __init__(self, *, lock: threading.Lock, stop: threading.Event) -> None:
        self.lock = lock
        self.stop = stop
        self.calls = 0
        self.observed_serialization: list[bool] = []

    def manage_positions_once(self):
        self.calls += 1
        self.observed_serialization.append(self.lock.locked())
        if self.calls >= 3:
            self.stop.set()
        return SimpleNamespace(
            actions_claimed=0,
            actions_confirmed=0,
            actions_failed=0,
            actions_unknown=0,
            notifications_enqueued=0,
            isolated_failures=0,
            closed_positions=0,
        )


class _TransientFailureWorker(_RecordingWorker):
    def manage_positions_once(self):
        if self.calls == 0:
            self.calls += 1
            raise RuntimeError("temporary MT5 failure")
        return super().manage_positions_once()


class _TelegramWorker:
    def __init__(self, stop: threading.Event, *, fail_first: bool = False) -> None:
        self.stop = stop
        self.fail_first = fail_first
        self.calls: list[int] = []

    def run_once(self, *, timeout: int) -> int:
        self.calls.append(timeout)
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("temporary Telegram failure")
        if len(self.calls) >= 3:
            self.stop.set()
        return 1


class GoldMNotifyCliTests(unittest.TestCase):
    def test_explicit_env_file_overrides_and_clears_managed_ambient_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "\n".join(
                    (
                        "TELEGRAM_BOT_TOKEN=file-token",
                        "TELEGRAM_ADMIN_CHAT_IDS=123",
                        "GOLDM_EXECUTION_MODE=off",
                        "GOLDM_ALLOW_LIVE_ACTIVATION=false",
                        "MT5_LOGIN=108098316",
                        "CUSTOM_SETTING=file-value",
                    )
                ),
                encoding="utf-8",
            )
            inherited = {
                "TELEGRAM_BOT_TOKEN": "ambient-token",
                "GOLDM_EXECUTION_MODE": "live",
                "GOLDM_ALLOW_LIVE_ACTIVATION": "true",
                "GOLDM_LIVE_ORDER_CONSENT": "I_UNDERSTAND_LIVE_ORDERS",
                "MT5_LOGIN": "999",
                "MT5_PASSWORD": "ambient-password",
                "CUSTOM_SETTING": "ambient-value",
                "OS_KEEP": "preserved",
            }
            with patch.dict(os.environ, inherited, clear=True):
                _load_env_file(env_file)
                self.assertEqual(os.environ["TELEGRAM_BOT_TOKEN"], "file-token")
                self.assertEqual(os.environ["GOLDM_EXECUTION_MODE"], "off")
                self.assertEqual(os.environ["GOLDM_ALLOW_LIVE_ACTIVATION"], "false")
                self.assertEqual(os.environ["MT5_LOGIN"], "108098316")
                self.assertEqual(os.environ["CUSTOM_SETTING"], "file-value")
                self.assertEqual(os.environ["OS_KEEP"], "preserved")
                self.assertNotIn("GOLDM_LIVE_ORDER_CONSENT", os.environ)
                self.assertNotIn("MT5_PASSWORD", os.environ)

    def test_missing_managed_file_value_cannot_be_supplied_by_ambient_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("TELEGRAM_BOT_TOKEN=file-token\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "MT5_DATA_PATH": "C:/ambient/data",
                    "GOLDM_EXECUTION_MODE": "live",
                    "TELEGRAM_ADMIN_CHAT_IDS": "-100123",
                },
                clear=True,
            ):
                _load_env_file(env_file)
                self.assertNotIn("MT5_DATA_PATH", os.environ)
                self.assertNotIn("GOLDM_EXECUTION_MODE", os.environ)
                self.assertNotIn("TELEGRAM_ADMIN_CHAT_IDS", os.environ)

    def test_explicit_env_file_is_required_and_duplicate_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaisesRegex(RuntimeError, "does not exist"):
                _load_env_file(root / "missing.env")
            duplicate = root / ".env"
            duplicate.write_text("GOLDM_EXECUTION_MODE=off\nGOLDM_EXECUTION_MODE=live\n")
            with self.assertRaisesRegex(RuntimeError, "duplicate"):
                _load_env_file(duplicate)

    def test_missing_explicit_data_path_fails_before_store_or_worker_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "\n".join(
                    (
                        "TELEGRAM_BOT_TOKEN=test-token",
                        "TELEGRAM_ADMIN_CHAT_IDS=123",
                        "GOLDM_TRADE_LIFECYCLE_ENABLED=true",
                        "MT5_PATH=C:/exact/terminal64.exe",
                        "MT5_LOGIN=108098316",
                        "MT5_SERVER=XMGlobal-MT5-5",
                    )
                ),
                encoding="utf-8",
            )
            with (
                patch.dict(os.environ, {}, clear=True),
                patch(
                    "sys.argv",
                    [
                        "goldm-worker",
                        "--env-file",
                        str(env_file),
                        "--release-id",
                        "a" * 40,
                        "--deployment-nonce",
                        "b" * 32,
                        "--release-manifest-sha256",
                        "c" * 64,
                        "--runtime-config-sha256",
                        hashlib.sha256(env_file.read_bytes()).hexdigest(),
                        "--production-config-sha256",
                        load_production_ea_input_contract()["sha256"],
                    ],
                ),
                patch("goldm_signal.notify.cli.SignalStore.initialize") as initialize,
                patch("goldm_signal.notify.cli.TelegramBotClient") as telegram_client,
            ):
                with self.assertRaisesRegex(RuntimeError, "MT5_DATA_PATH"):
                    main()
            initialize.assert_not_called()
            telegram_client.assert_not_called()

    def test_missing_runtime_session_file_fails_before_adapter_or_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            terminal = root / "terminal64.exe"
            terminal.write_bytes(b"fixture")
            data = root / "data"
            (data / "MQL5").mkdir(parents=True)
            env_file = root / ".env"
            env_file.write_text(
                "\n".join(
                    (
                        "TELEGRAM_BOT_TOKEN=test-token",
                        "TELEGRAM_ADMIN_CHAT_IDS=123",
                        "GOLDM_TRADE_LIFECYCLE_ENABLED=true",
                        f"MT5_PATH={terminal}",
                        f"MT5_DATA_PATH={data}",
                        "MT5_LOGIN=108098316",
                        "MT5_SERVER=XMGlobal-MT5-5",
                        "GOLDM_EA_SESSION_ID=prod-session-20260815",
                    )
                ),
                encoding="utf-8",
            )
            with (
                patch.dict(os.environ, {}, clear=True),
                patch(
                    "sys.argv",
                    [
                        "goldm-worker",
                        "--env-file",
                        str(env_file),
                        "--release-id",
                        "a" * 40,
                        "--deployment-nonce",
                        "b" * 32,
                        "--release-manifest-sha256",
                        "c" * 64,
                        "--runtime-config-sha256",
                        hashlib.sha256(env_file.read_bytes()).hexdigest(),
                        "--production-config-sha256",
                        load_production_ea_input_contract()["sha256"],
                    ],
                ),
                patch("goldm_signal.notify.cli.SignalStore.initialize") as initialize,
                patch("goldm_signal.notify.cli.LiveMT5Adapter") as adapter,
            ):
                with self.assertRaisesRegex(RuntimeError, "runtime session file"):
                    main()
            initialize.assert_not_called()
            adapter.assert_not_called()

    def test_ea_session_id_is_required_and_strict(self) -> None:
        self.assertEqual(
            _required_ea_session_id("prod-session-20260815"),
            "prod-session-20260815",
        )
        for invalid in ("", "UNSET", "short", "bad session token"):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                _required_ea_session_id(invalid)

    def test_release_id_is_full_lowercase_commit(self) -> None:
        self.assertEqual(_release_id_argument("a" * 40), "a" * 40)
        for invalid in ("", "a" * 39, "A" * 40, "release-main"):
            with self.subTest(invalid=invalid), self.assertRaises(
                argparse.ArgumentTypeError
            ):
                _release_id_argument(invalid)

    def test_deployment_nonce_is_strict_lowercase_random_token_shape(self) -> None:
        self.assertEqual(_deployment_nonce_argument("b" * 32), "b" * 32)
        for invalid in ("", "b" * 31, "B" * 32, "not-a-nonce"):
            with self.subTest(invalid=invalid), self.assertRaises(
                argparse.ArgumentTypeError
            ):
                _deployment_nonce_argument(invalid)

    def test_lifecycle_log_directory_is_bound_to_exact_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            install = root / "terminal"
            data = root / "data"
            logs = data / "MQL5" / "Logs"
            install.mkdir()
            logs.mkdir(parents=True)
            executable = install / "terminal64.exe"
            executable.write_bytes(b"fixture")

            self.assertEqual(
                _resolve_lifecycle_log_directory(
                    mt5_path=str(executable),
                    expected_terminal_data_path=str(data),
                    terminal_path=str(install),
                    terminal_data_path=str(data),
                ),
                logs.resolve(),
            )
            other_install = root / "other-terminal"
            other_install.mkdir()
            with self.assertRaises(RuntimeError):
                _resolve_lifecycle_log_directory(
                    mt5_path=str(executable),
                    expected_terminal_data_path=str(data),
                    terminal_path=str(other_install),
                    terminal_data_path=str(data),
                )
            other_data = root / "other-data"
            other_data.mkdir()
            with self.assertRaisesRegex(RuntimeError, "MT5_DATA_PATH"):
                _resolve_lifecycle_terminal_data_path(
                    mt5_path=str(executable),
                    expected_terminal_data_path=str(other_data),
                    terminal_path=str(install),
                    terminal_data_path=str(data),
                )

    def test_bridge_account_provider_uses_shared_lock_and_exact_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            install = root / "terminal"
            data = root / "data"
            install.mkdir()
            (data / "MQL5").mkdir(parents=True)
            executable = install / "terminal64.exe"
            executable.write_bytes(b"fixture")
            mt5_lock = threading.RLock()
            lock_observations: list[bool] = []

            def load_terminal_status() -> SimpleNamespace:
                lock_observations.append(mt5_lock._is_owned())
                return SimpleNamespace(path=str(install), data_path=str(data))

            def load_account_fingerprint() -> SimpleNamespace:
                lock_observations.append(mt5_lock._is_owned())
                return SimpleNamespace(
                    login="108098316",
                    server="XMGlobal-MT5-5",
                    is_live=False,
                    margin_mode="HEDGING",
                    password="must-not-leak",
                )

            adapter = SimpleNamespace(
                load_terminal_status=load_terminal_status,
                load_account_fingerprint=load_account_fingerprint,
            )
            provider = _make_bridge_account_context_provider(
                adapter=adapter,
                mt5_lock=mt5_lock,
                mt5_path=str(executable),
                mt5_data_path=str(data),
                expected_login="108098316",
                expected_server="XMGlobal-MT5-5",
                expected_scope="demo",
                allow_live=False,
            )

            self.assertEqual(
                provider(),
                {
                    "login": "108098316",
                    "server": "XMGlobal-MT5-5",
                    "is_live": False,
                    "margin_mode": "HEDGING",
                },
            )
            self.assertEqual(lock_observations, [True, True])

            other_data = root / "other-data"
            other_data.mkdir()
            mismatched_provider = _make_bridge_account_context_provider(
                adapter=adapter,
                mt5_lock=mt5_lock,
                mt5_path=str(executable),
                mt5_data_path=str(other_data),
                expected_login="108098316",
                expected_server="XMGlobal-MT5-5",
                expected_scope="demo",
                allow_live=False,
            )
            with self.assertRaisesRegex(RuntimeError, "MT5_DATA_PATH"):
                mismatched_provider()

            live_adapter = SimpleNamespace(
                load_terminal_status=load_terminal_status,
                load_account_fingerprint=lambda: SimpleNamespace(
                    login="108098316",
                    server="XMGlobal-MT5-5",
                    is_live=True,
                    margin_mode="HEDGING",
                ),
            )
            live_provider = _make_bridge_account_context_provider(
                adapter=live_adapter,
                mt5_lock=mt5_lock,
                mt5_path=str(executable),
                mt5_data_path=str(data),
                expected_login="108098316",
                expected_server="XMGlobal-MT5-5",
                expected_scope="demo",
                allow_live=False,
            )
            with self.assertRaisesRegex(RuntimeError, "verified demo"):
                live_provider()

    def test_management_interval_defaults_and_cli_precedence(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_management_interval_seconds(None), 0.5)
        with patch.dict(
            os.environ,
            {"GOLDM_MANAGEMENT_INTERVAL_SECONDS": "0.75"},
            clear=True,
        ):
            self.assertEqual(_management_interval_seconds(None), 0.75)
            self.assertEqual(_management_interval_seconds(1.25), 1.25)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_worker_interval_seconds(None), 1.0)
        with patch.dict(
            os.environ,
            {"GOLDM_WORKER_INTERVAL_SECONDS": "0.25"},
            clear=True,
        ):
            self.assertEqual(_worker_interval_seconds(None), 0.25)
            self.assertEqual(_worker_interval_seconds(2.0), 2.0)

    def test_management_interval_is_bounded_and_finite(self) -> None:
        for invalid in ("bad", "nan", "inf", "-inf", "0.09", "60.01"):
            with self.subTest(invalid=invalid):
                with patch.dict(
                    os.environ,
                    {"GOLDM_MANAGEMENT_INTERVAL_SECONDS": invalid},
                    clear=True,
                ):
                    with self.assertRaises(SystemExit):
                        _management_interval_seconds(None)

        self.assertEqual(_management_interval_seconds(0.1), 0.1)
        self.assertEqual(_management_interval_seconds(60.0), 60.0)
        with self.assertRaises(SystemExit):
            _worker_interval_seconds(float("nan"))
        with self.assertRaises(SystemExit):
            _worker_interval_seconds(0.01)

    def test_management_loop_serializes_mt5_access(self) -> None:
        lock = threading.Lock()
        stop = threading.Event()
        worker = _RecordingWorker(lock=lock, stop=stop)
        thread = threading.Thread(
            target=_run_position_management_loop,
            kwargs={
                "worker": worker,
                "mt5_lock": lock,
                "interval_seconds": 0.001,
                "stop_event": stop,
            },
        )
        thread.start()
        thread.join(timeout=1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(worker.calls, 3)
        self.assertEqual(worker.observed_serialization, [True, True, True])

    def test_management_loop_survives_a_transient_cycle_failure(self) -> None:
        lock = threading.Lock()
        stop = threading.Event()
        worker = _TransientFailureWorker(lock=lock, stop=stop)
        output = io.StringIO()
        thread = threading.Thread(
            target=_run_position_management_loop,
            kwargs={
                "worker": worker,
                "mt5_lock": lock,
                "interval_seconds": 0.001,
                "stop_event": stop,
            },
        )
        with redirect_stdout(output):
            thread.start()
            thread.join(timeout=1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(worker.calls, 3)
        self.assertIn("temporary MT5 failure", output.getvalue())

    def test_telegram_polling_is_independent_and_survives_failure(self) -> None:
        stop = threading.Event()
        worker = _TelegramWorker(stop, fail_first=True)
        output = io.StringIO()
        thread = threading.Thread(
            target=_run_telegram_poll_loop,
            kwargs={
                "worker": worker,
                "timeout": 0,
                "stop_event": stop,
                "retry_delay_seconds": 0.001,
            },
        )
        with redirect_stdout(output):
            thread.start()
            thread.join(timeout=4.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(worker.calls, [0, 0, 0])
        self.assertIn("temporary Telegram failure", output.getvalue())


if __name__ == "__main__":
    unittest.main()
