from __future__ import annotations

import argparse
import hashlib
import importlib
import math
import os
import re
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from ..config import gold_i_profile


MIN_MANAGEMENT_INTERVAL_SECONDS = 0.10
MAX_MANAGEMENT_INTERVAL_SECONDS = 60.0
MIN_WORKER_INTERVAL_SECONDS = 0.10
MAX_WORKER_INTERVAL_SECONDS = 60.0
RUNTIME_SESSION_FILENAME = "goldm_runtime_session.txt"


@dataclass(frozen=True, slots=True)
class _PathIdentity:
    device: int
    inode: int
    mode: int
    size: int
    modified_ns: int
    file_attributes: int

    @classmethod
    def from_stat(cls, metadata: os.stat_result) -> "_PathIdentity":
        return cls(
            device=int(metadata.st_dev),
            inode=int(metadata.st_ino),
            mode=int(metadata.st_mode),
            size=int(metadata.st_size),
            modified_ns=int(metadata.st_mtime_ns),
            file_attributes=int(getattr(metadata, "st_file_attributes", 0) or 0),
        )

    def object_key(self) -> tuple[int, int, int, int]:
        return (self.device, self.inode, stat.S_IFMT(self.mode), self.file_attributes)

    def content_key(self) -> tuple[int, int, int, int, int, int]:
        # Windows may advance ctime merely by opening a file. Size and mtime,
        # together with the object identity, detect content replacement without
        # treating that access-time metadata behavior as a mutation.
        return (*self.object_key(), self.size, self.modified_ns)


@dataclass(frozen=True, slots=True)
class _PathProof:
    path: Path
    label: str
    kind: str
    identity: _PathIdentity | None


@dataclass(frozen=True, slots=True)
class _DatabasePathProof:
    database: _PathProof
    parent: _PathProof
    sidecars: tuple[_PathProof, ...]


_RUNTIME_DEPENDENCIES = {
    "LiveMT5Adapter": ("bot_ea.mt5_adapter", "LiveMT5Adapter"),
    "SignalStore": ("goldm_signal.storage.database", "SignalStore"),
    "telegram_poll_db_identity": (
        "goldm_signal.storage.database",
        "telegram_poll_db_identity",
    ),
    "TelegramApprovalWorker": (
        "goldm_signal.notify.approval",
        "TelegramApprovalWorker",
    ),
    "Mt5LogBridge": ("goldm_signal.notify.mt5_log", "Mt5LogBridge"),
    "OutboxWorker": ("goldm_signal.notify.outbox", "OutboxWorker"),
    "ApprovedTelegramSender": (
        "goldm_signal.notify.telegram",
        "ApprovedTelegramSender",
    ),
    "TelegramBotClient": ("goldm_signal.notify.telegram", "TelegramBotClient"),
    "TradeLifecycleConfig": (
        "goldm_signal.notify.trade_lifecycle",
        "TradeLifecycleConfig",
    ),
    "TradeLifecycleWorker": (
        "goldm_signal.notify.trade_lifecycle",
        "TradeLifecycleWorker",
    ),
}


def __getattr__(name: str) -> Any:
    """Preserve patch/import compatibility without eager runtime imports."""

    if name not in _RUNTIME_DEPENDENCIES:
        raise AttributeError(name)
    value = _import_runtime_dependency(name)
    globals()[name] = value
    return value


def _import_runtime_dependency(name: str) -> Any:
    existing = globals().get(name)
    if existing is not None:
        return existing
    module_name, attribute = _RUNTIME_DEPENDENCIES[name]
    return getattr(importlib.import_module(module_name), attribute)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run approved-only Telegram subscription and notification worker."
    )
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--db", default=None)
    parser.add_argument(
        "--release-id",
        required=True,
        type=_release_id_argument,
        help="Immutable deployed Git commit (exactly 40 lowercase hex characters).",
    )
    parser.add_argument(
        "--deployment-nonce",
        required=True,
        type=_deployment_nonce_argument,
        help="Per-start deployment binding (exactly 32 lowercase hex characters).",
    )
    parser.add_argument(
        "--release-manifest-sha256", required=True, type=_sha256_argument
    )
    parser.add_argument(
        "--runtime-config-sha256", required=True, type=_sha256_argument
    )
    parser.add_argument(
        "--production-config-sha256", required=True, type=_sha256_argument
    )
    parser.add_argument("--poll-timeout", type=int, default=15)
    parser.add_argument(
        "--worker-interval",
        type=float,
        default=None,
        help=(
            "MT5-log, signal, and outbox cadence in seconds; defaults to "
            "GOLDM_WORKER_INTERVAL_SECONDS or 1.0."
        ),
    )
    parser.add_argument(
        "--management-interval",
        type=float,
        default=None,
        help=(
            "Broker-position reconciliation cadence in seconds; defaults to "
            "GOLDM_MANAGEMENT_INTERVAL_SECONDS or 0.5."
        ),
    )
    parser.add_argument(
        "--mt5-log",
        action="append",
        default=None,
        help="Explicit MT5 MQL5 log path; repeat for multiple terminals.",
    )
    parser.add_argument("--no-mt5-log-bridge", action="store_true")
    parser.add_argument(
        "--debug-notification",
        action="store_true",
        help="Queue a harmless end-to-end Telegram diagnostic notification.",
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    env_proof, env_bytes = _read_stable_regular_file(
        Path(args.env_file), "authoritative runtime environment snapshot"
    )
    runtime_config_sha256 = hashlib.sha256(env_bytes).hexdigest()
    if runtime_config_sha256 != args.runtime_config_sha256:
        raise SystemExit("authoritative runtime environment SHA-256 mismatch")
    values = _parse_env_bytes(env_bytes)
    _install_env_values(values)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    admin_value = os.environ.get("TELEGRAM_ADMIN_CHAT_IDS", "").strip()
    if not admin_value:
        admin_value = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    admin_ids = _parse_chat_ids(admin_value)
    if not admin_ids:
        raise SystemExit("TELEGRAM_ADMIN_CHAT_IDS or TELEGRAM_CHAT_ID is required")

    # Derive every runtime path from the now-authenticated env bytes, then
    # validate all of them before importing the broker/runtime dependency graph.
    lifecycle_enabled = _configured_lifecycle_enabled(values)
    mt5_path = ""
    mt5_data_path = ""
    mt5_login = ""
    mt5_server = ""
    mt5_executable_proof = None
    mt5_data_proof = None
    required_ea_session_id = ""
    if lifecycle_enabled:
        mt5_path = str(values.get("MT5_PATH", "")).strip()
        mt5_data_path = str(values.get("MT5_DATA_PATH", "")).strip()
        mt5_login = str(values.get("MT5_LOGIN", "")).strip()
        mt5_server = str(values.get("MT5_SERVER", "")).strip()
        missing_binding = [
            name
            for name, value in (
                ("MT5_PATH", mt5_path),
                ("MT5_DATA_PATH", mt5_data_path),
                ("MT5_LOGIN", mt5_login),
                ("MT5_SERVER", mt5_server),
            )
            if not value
        ]
        if missing_binding:
            raise RuntimeError(
                "lifecycle broker mutation requires explicit "
                + ", ".join(missing_binding)
            )
        mt5_executable_proof = _inspect_startup_path(
            Path(mt5_path), "MT5 executable", kind="file", must_exist=True
        )
        mt5_data_proof = _inspect_startup_path(
            Path(mt5_data_path), "MT5 data path", kind="directory", must_exist=True
        )
        required_ea_session_id = _required_ea_session_id(
            str(values.get("GOLDM_EA_SESSION_ID", ""))
        )
        _verify_runtime_session_token_secure(
            required_ea_session_id,
            mt5_data_proof,
        )
    else:
        required_ea_session_id = _required_ea_session_id(
            str(values.get("GOLDM_EA_SESSION_ID", ""))
        )

    raw_database_path = str(args.db or values.get("GOLDM_SIGNAL_DB", "")).strip()
    if not raw_database_path:
        raise RuntimeError(
            "worker database path must be explicitly supplied by --db or GOLDM_SIGNAL_DB"
        )
    database_proof = _inspect_database_paths(Path(raw_database_path))
    db_path = database_proof.database.path

    if lifecycle_enabled and args.mt5_log:
        raise RuntimeError(
            "lifecycle mode forbids arbitrary --mt5-log paths; the source is "
            "bound to the active terminal data path"
        )
    if not lifecycle_enabled and not args.no_mt5_log_bridge and not args.mt5_log:
        raise RuntimeError(
            "notification-only MT5 log bridge requires an explicit absolute --mt5-log"
        )
    mt5_log_proofs = tuple(
        _inspect_startup_path(
            Path(raw_path), "explicit MT5 log file", kind="file", must_exist=True
        )
        for raw_path in (args.mt5_log or ())
    )

    _assert_path_proof(env_proof)
    _assert_database_proof(database_proof)
    for proof in mt5_log_proofs:
        _assert_path_proof(proof, require_unchanged_content=False)
    if mt5_executable_proof is not None:
        _assert_path_proof(mt5_executable_proof)
    if mt5_data_proof is not None:
        _assert_path_proof(mt5_data_proof)

    # Import only after the complete path fence above. In particular, importing
    # the deployment/lifecycle graph imports the LiveMT5Adapter definition.
    deployment_module = importlib.import_module("goldm_signal.deployment")
    production_contract = deployment_module.load_production_ea_input_contract()
    if production_contract["sha256"] != args.production_config_sha256:
        raise SystemExit("production EA input contract SHA-256 mismatch")

    SignalStoreClass = _import_runtime_dependency("SignalStore")
    telegram_poll_db_identity_fn = _import_runtime_dependency(
        "telegram_poll_db_identity"
    )
    LiveMT5AdapterClass = _import_runtime_dependency("LiveMT5Adapter")
    TelegramApprovalWorkerClass = _import_runtime_dependency(
        "TelegramApprovalWorker"
    )
    Mt5LogBridgeClass = _import_runtime_dependency("Mt5LogBridge")
    OutboxWorkerClass = _import_runtime_dependency("OutboxWorker")
    ApprovedTelegramSenderClass = _import_runtime_dependency(
        "ApprovedTelegramSender"
    )
    TelegramBotClientClass = _import_runtime_dependency("TelegramBotClient")
    TradeLifecycleConfigClass = _import_runtime_dependency("TradeLifecycleConfig")
    TradeLifecycleWorkerClass = _import_runtime_dependency("TradeLifecycleWorker")

    base_lifecycle_config = TradeLifecycleConfigClass.from_env()
    if bool(base_lifecycle_config.enabled) != lifecycle_enabled:
        raise RuntimeError("lifecycle enablement changed after environment validation")

    mt5_adapter = None
    lifecycle_data_path = None
    if lifecycle_enabled:
        assert mt5_executable_proof is not None
        assert mt5_data_proof is not None
        _assert_path_proof(env_proof)
        _assert_path_proof(mt5_executable_proof)
        _assert_path_proof(mt5_data_proof)
        mt5_adapter = LiveMT5AdapterClass(
            path=str(mt5_executable_proof.path),
            login=int(mt5_login),
            password=os.environ.get("MT5_PASSWORD") or None,
            server=mt5_server,
            require_mutation_binding=True,
        )
        terminal_status = mt5_adapter.load_terminal_status()
        lifecycle_data_path = _resolve_lifecycle_terminal_data_path(
            mt5_path=str(mt5_executable_proof.path),
            expected_terminal_data_path=str(mt5_data_proof.path),
            terminal_path=terminal_status.path,
            terminal_data_path=terminal_status.data_path,
        )

    _assert_path_proof(env_proof)
    _assert_database_proof(database_proof)
    for proof in mt5_log_proofs:
        _assert_path_proof(proof, require_unchanged_content=False)
    store = SignalStoreClass(db_path)
    store.initialize()
    # SQLite may create WAL/SHM during initialization. Re-inspect them before
    # any worker uses the store and reject anything link-like or non-regular.
    post_initialize_database_proof = _inspect_database_paths(db_path)
    _assert_database_proof(post_initialize_database_proof)
    for proof in mt5_log_proofs:
        _assert_path_proof(proof, require_unchanged_content=False)
    poll_worker_started_at = datetime.now(timezone.utc)
    poll_worker_instance_id = uuid.uuid4().hex
    poll_session_sha256 = hashlib.sha256(
        required_ea_session_id.encode("utf-8")
    ).hexdigest()
    store.start_telegram_poll_readiness(
        release_id=args.release_id,
        session_sha256=poll_session_sha256,
        db_identity=telegram_poll_db_identity_fn(db_path),
        deployment_nonce_sha256=hashlib.sha256(
            args.deployment_nonce.encode("ascii")
        ).hexdigest(),
        release_manifest_sha256=args.release_manifest_sha256,
        runtime_config_sha256=runtime_config_sha256,
        production_config_sha256=args.production_config_sha256,
        worker_instance_id=poll_worker_instance_id,
        worker_started_at=poll_worker_started_at,
    )
    # Long-polling and notification delivery use independent HTTP client
    # instances. Telegram permits concurrent API calls, but only the control
    # client is ever allowed to consume getUpdates.
    control_client = TelegramBotClientClass(bot_token=token)
    outbox_client = TelegramBotClientClass(bot_token=token)
    outbox_worker = OutboxWorkerClass(
        store,
        ApprovedTelegramSenderClass(
            store=store,
            client=outbox_client,
            admin_chat_ids=admin_ids,
        ),
    )
    log_bridge = None
    lifecycle_config = TradeLifecycleConfigClass.from_sources(
        store, fallback=base_lifecycle_config
    )
    lifecycle_worker = None
    mt5_lock = threading.RLock()
    if lifecycle_config.enabled:
        assert mt5_adapter is not None
        assert lifecycle_data_path is not None
        if not args.no_mt5_log_bridge:
            log_input = lifecycle_data_path / "MQL5" / "Logs"
            log_directory_proof = _inspect_startup_path(
                log_input,
                "active MT5 log directory",
                kind="directory",
                must_exist=True,
            )
            log_directory = log_directory_proof.path
            try:
                log_directory.relative_to(lifecycle_data_path)
            except ValueError as exc:
                raise RuntimeError(
                    "active MT5 log directory escapes MT5_DATA_PATH"
                ) from exc
            _assert_path_proof(
                log_directory_proof, require_unchanged_content=False
            )
            log_bridge = Mt5LogBridgeClass(
                store,
                log_directories=[log_directory],
                required_run_id=required_ea_session_id,
                expected_symbol=gold_i_profile().symbol,
                account_context_provider=_make_bridge_account_context_provider(
                    adapter=mt5_adapter,
                    mt5_lock=mt5_lock,
                    mt5_path=mt5_path,
                    mt5_data_path=mt5_data_path,
                    expected_login=mt5_login,
                    expected_server=mt5_server,
                    # Entry OFF is the safe deployment default, but the bound
                    # terminal is still required to remain a DEMO account.
                    expected_scope=(
                        "live"
                        if base_lifecycle_config.execution_mode == "live"
                        else "demo"
                    ),
                    allow_live=base_lifecycle_config.allow_live_activation,
                ),
            )
        lifecycle_worker = TradeLifecycleWorkerClass(
            store=store,
            adapter=mt5_adapter,
            config=lifecycle_config,
        )
    elif not args.no_mt5_log_bridge:
        log_bridge = Mt5LogBridgeClass(
            store,
            log_paths=[proof.path for proof in mt5_log_proofs] or None,
            expected_symbol=gold_i_profile().symbol,
        )
    approval_worker = TelegramApprovalWorkerClass(
        store=store,
        client=control_client,
        admin_chat_ids=admin_ids,
        readiness_worker_instance_id=poll_worker_instance_id,
        account_probe=(
            lambda: _with_mt5_lock(mt5_lock, lambda: _probe_account(mt5_adapter))
        )
        if mt5_adapter
        else None,
    )
    if args.debug_notification:
        log_bridge = log_bridge or Mt5LogBridgeClass(
            store,
            log_paths=[],
            expected_symbol=gold_i_profile().symbol,
        )
        log_bridge.enqueue_debug_notification()
    control_client.set_commands(admin_chat_ids=admin_ids)
    print(
        f"Telegram approval worker ready: admins={len(admin_ids)} db={db_path}",
        flush=True,
    )

    if args.once:
        files, lines, ingested = log_bridge.run_once() if log_bridge else (0, 0, 0)
        planned, outcomes, closed = (
            _with_mt5_lock(mt5_lock, lifecycle_worker.run_once)
            if lifecycle_worker
            else (0, 0, 0)
        )
        sent, failed = outbox_worker.run_once()
        processed = approval_worker.run_once(timeout=0)
        print(
            f"files={files} lines={lines} ingested={ingested} "
            f"planned={planned} outcomes={outcomes} closed={closed} "
            f"processed={processed} sent={sent} failed={failed}",
            flush=True,
        )
        return

    worker_stop = threading.Event()
    management_thread = None
    if lifecycle_worker:
        management_interval = _management_interval_seconds(args.management_interval)
        management_thread = threading.Thread(
            target=_run_position_management_loop,
            kwargs={
                "worker": lifecycle_worker,
                "mt5_lock": mt5_lock,
                "interval_seconds": management_interval,
                "stop_event": worker_stop,
            },
            name="goldm-position-management",
            daemon=False,
        )
        management_thread.start()
        print(
            f"Broker position manager ready: interval={management_interval:.3f}s",
            flush=True,
        )

    telegram_thread = threading.Thread(
        target=_run_telegram_poll_loop,
        kwargs={
            "worker": approval_worker,
            "timeout": max(0, args.poll_timeout),
            "stop_event": worker_stop,
        },
        name="goldm-telegram-control",
        daemon=False,
    )
    telegram_thread.start()
    operational_interval = _worker_interval_seconds(args.worker_interval)
    print(
        f"GoldM operational loop ready: interval={operational_interval:.3f}s",
        flush=True,
    )

    try:
        while True:
            try:
                files, lines, ingested = log_bridge.run_once() if log_bridge else (0, 0, 0)
                planned, outcomes, closed = (
                    _with_mt5_lock(mt5_lock, lifecycle_worker.run_once)
                    if lifecycle_worker
                    else (0, 0, 0)
                )
                sent, failed = outbox_worker.run_once()
                if ingested or planned or outcomes or closed or sent or failed:
                    print(
                        f"files={files} lines={lines} ingested={ingested} "
                        f"planned={planned} outcomes={outcomes} closed={closed} "
                        f"sent={sent} failed={failed}",
                        flush=True,
                    )
            except Exception as exc:
                print(f"GoldM operational loop error: {exc}", flush=True)
                if worker_stop.wait(3.0):
                    break
                continue
            if worker_stop.wait(operational_interval):
                break
    except KeyboardInterrupt:
        print("Telegram approval worker stopped.", flush=True)
    finally:
        worker_stop.set()
        if management_thread is not None:
            # Do not abandon or kill an in-flight broker mutation. The adapter's
            # own IPC timeout bounds this join if MT5 becomes unresponsive.
            management_thread.join()
        telegram_thread.join()


def _management_interval_seconds(cli_value: float | None) -> float:
    return _bounded_interval_seconds(
        cli_value
        if cli_value is not None
        else os.environ.get("GOLDM_MANAGEMENT_INTERVAL_SECONDS", "0.5"),
        label="GOLDM management interval",
        minimum=MIN_MANAGEMENT_INTERVAL_SECONDS,
        maximum=MAX_MANAGEMENT_INTERVAL_SECONDS,
    )


def _worker_interval_seconds(cli_value: float | None) -> float:
    return _bounded_interval_seconds(
        cli_value
        if cli_value is not None
        else os.environ.get("GOLDM_WORKER_INTERVAL_SECONDS", "1.0"),
        label="GOLDM worker interval",
        minimum=MIN_WORKER_INTERVAL_SECONDS,
        maximum=MAX_WORKER_INTERVAL_SECONDS,
    )


def _bounded_interval_seconds(
    raw_value: object,
    *,
    label: str,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"{label} must be a number") from exc
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise SystemExit(
            f"{label} must be between {minimum:g} and {maximum:g} seconds"
        )
    return value


def _with_mt5_lock(lock: threading.RLock, operation: Callable[[], object]):
    with lock:
        return operation()


def _run_position_management_loop(
    *,
    worker: TradeLifecycleWorker,
    mt5_lock: threading.RLock,
    interval_seconds: float,
    stop_event: threading.Event,
) -> None:
    """Run broker management independently from Telegram's long poll.

    All access to the process-global MetaTrader5 Python binding shares the same
    lock with signal execution and Telegram account probes. A failed cycle is
    isolated; broker-side idempotency remains the responsibility of the durable
    action ledger in ``BrokerPositionManager``.
    """

    next_deadline = time.monotonic()
    while not stop_event.is_set():
        try:
            cycle = _with_mt5_lock(mt5_lock, worker.manage_positions_once)
            activity = sum(
                int(getattr(cycle, field, 0) or 0)
                for field in (
                    "actions_claimed",
                    "actions_confirmed",
                    "actions_failed",
                    "actions_unknown",
                    "notifications_enqueued",
                    "isolated_failures",
                    "closed_positions",
                )
            )
            if activity:
                print(f"Broker position management: {cycle}", flush=True)
        except Exception as exc:
            # The loop must stay alive after a transient MT5/SQLite failure.
            # Mutation calls themselves are single-attempt and reconciled from
            # UNKNOWN; this catch never retries an individual broker request.
            print(f"Broker position management error: {exc}", flush=True)

        next_deadline += interval_seconds
        remaining = next_deadline - time.monotonic()
        if remaining <= 0:
            next_deadline = time.monotonic()
            remaining = 0.0
        stop_event.wait(remaining)


def _run_telegram_poll_loop(
    *,
    worker: TelegramApprovalWorker,
    timeout: int,
    stop_event: threading.Event,
    retry_delay_seconds: float = 3.0,
) -> None:
    """Own Telegram getUpdates without delaying trading/log processing."""

    while not stop_event.is_set():
        try:
            processed = worker.run_once(timeout=timeout)
            if processed:
                print(f"Telegram updates processed={processed}", flush=True)
        except Exception as exc:
            print(f"Telegram control polling error: {exc}", flush=True)
            if stop_event.wait(max(0.0, retry_delay_seconds)):
                return
        if timeout == 0 and stop_event.wait(0.10):
            return


def _load_env_file(path: Path) -> None:
    """Securely read and install a standalone env file.

    ``main`` reads once so its SHA-256 and parsed values cover identical bytes;
    this helper remains available for tests and administrative callers.
    """

    try:
        _, content = _read_stable_regular_file(path, "environment file")
        values = _parse_env_bytes(content)
    except RuntimeError as exc:
        raise RuntimeError(f"invalid environment file: {exc}") from exc
    _install_env_values(values)


def _install_env_values(values: Mapping[str, str]) -> None:
    # An explicitly selected private env file is the runtime authority. Windows
    # Scheduled Tasks inherit user/system variables; retaining those with
    # setdefault() could silently turn a validated OFF/demo file into an
    # ambient live configuration. Clear the application-owned namespaces first
    # (including keys absent from the file), then assign every parsed value.
    managed_prefixes = ("GOLDM_", "MT5_", "TELEGRAM_")
    for key in tuple(os.environ):
        if key.upper().startswith(managed_prefixes):
            del os.environ[key]
    for key, value in values.items():
        os.environ[key] = value


def _parse_env_bytes(content: bytes) -> dict[str, str]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError as exc:
        raise RuntimeError("environment file is not valid UTF-8") from exc

    values: dict[str, str] = {}
    observed_keys: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = _strip_unquoted_comment(raw_line).strip()
        if not line:
            continue
        if "=" not in line:
            raise RuntimeError(
                f"invalid environment assignment at line {line_number}"
            )
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is None:
            raise RuntimeError(f"invalid environment key at line {line_number}")
        normalized_key = key.casefold()
        if normalized_key in observed_keys:
            raise RuntimeError(
                "duplicate environment key (case-insensitive on Windows): "
                f"{observed_keys[normalized_key]} / {key}"
            )
        managed_key = key.upper().startswith(("GOLDM_", "MT5_", "TELEGRAM_"))
        if managed_key and key != key.upper():
            raise RuntimeError(
                f"managed environment key must use canonical uppercase: {key}"
            )
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        observed_keys[normalized_key] = key
        values[key] = value
    return values


def _strip_unquoted_comment(value: str) -> str:
    quote = ""
    for index, character in enumerate(value):
        if character in {'"', "'"}:
            if not quote:
                quote = character
            elif quote == character:
                quote = ""
            continue
        if character == "#" and not quote:
            return value[:index]
    if quote:
        raise RuntimeError("unterminated quote in environment file")
    return value


def _configured_lifecycle_enabled(values: Mapping[str, str]) -> bool:
    return str(values.get("GOLDM_TRADE_LIFECYCLE_ENABLED", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _absolute_startup_path(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise RuntimeError(f"{label} must be an explicit absolute path")
    return Path(os.path.abspath(os.fspath(path)))


def _metadata_is_reparse(metadata: os.stat_result) -> bool:
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    attributes = int(getattr(metadata, "st_file_attributes", 0) or 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def _reject_reparse_components(path: Path, label: str) -> None:
    """Reject links, junctions, and generic Windows reparse points lexically."""

    candidate = _absolute_startup_path(path, label)
    components: list[Path] = []
    current = candidate
    while True:
        components.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    for component in reversed(components):
        try:
            metadata = os.lstat(component)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise RuntimeError(
                f"{label} reparse-point status cannot be inspected: {component}"
            ) from exc
        try:
            is_junction = bool(
                getattr(component, "is_junction", lambda: False)()
            )
        except OSError as exc:
            raise RuntimeError(
                f"{label} junction status cannot be inspected: {component}"
            ) from exc
        if _metadata_is_reparse(metadata) or is_junction:
            raise RuntimeError(
                f"{label} cannot traverse a reparse point, symbolic link, or junction: "
                f"{component}"
            )


def _inspect_startup_path(
    path: Path,
    label: str,
    *,
    kind: str,
    must_exist: bool,
) -> _PathProof:
    candidate = _absolute_startup_path(path, label)
    _reject_reparse_components(candidate, label)
    try:
        metadata = os.lstat(candidate)
    except FileNotFoundError as exc:
        if must_exist:
            raise RuntimeError(f"{label} does not exist: {candidate}") from exc
        return _PathProof(candidate, label, kind, None)
    except OSError as exc:
        raise RuntimeError(f"{label} cannot be inspected: {candidate}") from exc
    if _metadata_is_reparse(metadata):
        raise RuntimeError(f"{label} must not be a reparse point: {candidate}")
    if kind == "file" and not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"{label} is not a regular file: {candidate}")
    if kind == "directory" and not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"{label} is not a directory: {candidate}")
    if kind not in {"file", "directory"}:
        raise RuntimeError(f"unsupported startup path kind: {kind}")
    return _PathProof(candidate, label, kind, _PathIdentity.from_stat(metadata))


def _assert_path_proof(
    proof: _PathProof,
    *,
    require_unchanged_content: bool = True,
) -> None:
    current = _inspect_startup_path(
        proof.path,
        proof.label,
        kind=proof.kind,
        must_exist=proof.identity is not None,
    )
    if proof.identity is None:
        if current.identity is not None:
            raise RuntimeError(
                f"{proof.label} appeared after startup validation: {proof.path}"
            )
        return
    assert current.identity is not None
    if current.identity.object_key() != proof.identity.object_key():
        raise RuntimeError(
            f"{proof.label} was replaced after startup validation: {proof.path}"
        )
    if (
        require_unchanged_content
        and current.identity.content_key() != proof.identity.content_key()
    ):
        raise RuntimeError(
            f"{proof.label} changed after startup validation: {proof.path}"
        )


def _read_stable_regular_file(path: Path, label: str) -> tuple[_PathProof, bytes]:
    proof = _inspect_startup_path(path, label, kind="file", must_exist=True)
    assert proof.identity is not None
    flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    descriptor: int | None = None
    try:
        descriptor = os.open(proof.path, flags)
        opened = _PathIdentity.from_stat(os.fstat(descriptor))
        if _metadata_is_reparse(os.fstat(descriptor)) or not stat.S_ISREG(opened.mode):
            raise RuntimeError(f"{label} did not open as a regular file")
        if opened.content_key() != proof.identity.content_key():
            raise RuntimeError(f"{label} changed while it was being opened")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            content = stream.read()
            completed = _PathIdentity.from_stat(os.fstat(stream.fileno()))
        if completed.content_key() != opened.content_key():
            raise RuntimeError(f"{label} changed while it was being read")
    except RuntimeError:
        raise
    except OSError as exc:
        raise RuntimeError(f"{label} is unreadable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    _assert_path_proof(proof)
    return proof, content


def _inspect_database_paths(path: Path) -> _DatabasePathProof:
    database_path = _absolute_startup_path(path, "worker database")
    parent = _inspect_startup_path(
        database_path.parent,
        "worker database parent directory",
        kind="directory",
        must_exist=True,
    )
    database = _inspect_startup_path(
        database_path, "worker database", kind="file", must_exist=True
    )
    sidecars = tuple(
        _inspect_startup_path(
            Path(str(database_path) + suffix),
            f"worker database {suffix} sidecar",
            kind="file",
            must_exist=False,
        )
        for suffix in ("-wal", "-shm")
    )
    return _DatabasePathProof(database=database, parent=parent, sidecars=sidecars)


def _assert_database_proof(proof: _DatabasePathProof) -> None:
    _assert_path_proof(proof.parent, require_unchanged_content=False)
    _assert_path_proof(proof.database, require_unchanged_content=False)
    for sidecar in proof.sidecars:
        _assert_path_proof(sidecar, require_unchanged_content=False)


def _verify_runtime_session_token_secure(
    expected: str,
    data_proof: _PathProof,
) -> dict[str, str]:
    _assert_path_proof(data_proof, require_unchanged_content=False)
    mql5 = _inspect_startup_path(
        data_proof.path / "MQL5",
        "MT5 MQL5 directory",
        kind="directory",
        must_exist=True,
    )
    files = _inspect_startup_path(
        mql5.path / "Files",
        "runtime session file parent directory",
        kind="directory",
        must_exist=True,
    )
    session, content = _read_stable_regular_file(
        files.path / RUNTIME_SESSION_FILENAME,
        "runtime session file",
    )
    try:
        lines = content.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise RuntimeError("runtime session file is not valid ASCII") from exc
    if lines != [expected]:
        raise RuntimeError(
            "runtime session file does not exactly match GOLDM_EA_SESSION_ID"
        )
    _assert_path_proof(data_proof, require_unchanged_content=False)
    _assert_path_proof(mql5, require_unchanged_content=False)
    _assert_path_proof(files, require_unchanged_content=False)
    return {
        "path": str(session.path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "session_id_sha256": hashlib.sha256(expected.encode("ascii")).hexdigest(),
    }


def _release_id_argument(value: str) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", normalized):
        raise argparse.ArgumentTypeError(
            "release id must be exactly 40 lowercase hexadecimal characters"
        )
    return normalized


def _deployment_nonce_argument(value: str) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", normalized):
        raise argparse.ArgumentTypeError(
            "deployment nonce must be exactly 32 lowercase hexadecimal characters"
        )
    return normalized


def _sha256_argument(value: str) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise argparse.ArgumentTypeError(
            "SHA-256 binding must be exactly 64 lowercase hexadecimal characters"
        )
    return normalized


def _parse_chat_ids(value: str) -> set[str]:
    normalized = value.replace(";", ",").replace(" ", ",")
    return {item for item in normalized.split(",") if item and item.lstrip("-").isdigit()}


def _required_ea_session_id(value: str) -> str:
    token = str(value or "").strip()
    if (
        token.upper() == "UNSET"
        or re.fullmatch(r"[A-Za-z0-9._-]{16,96}", token) is None
    ):
        raise RuntimeError(
            "GOLDM_EA_SESSION_ID must be an explicit 16-96 character session token"
        )
    return token


def _resolve_lifecycle_log_directory(
    *,
    mt5_path: str,
    expected_terminal_data_path: str,
    terminal_path: str,
    terminal_data_path: str,
) -> Path:
    data_path = _resolve_lifecycle_terminal_data_path(
        mt5_path=mt5_path,
        expected_terminal_data_path=expected_terminal_data_path,
        terminal_path=terminal_path,
        terminal_data_path=terminal_data_path,
    )
    _reject_reparse_components(data_path / "MQL5" / "Logs", "active MT5 log directory")
    log_directory = (data_path / "MQL5" / "Logs").resolve(strict=True)
    if not log_directory.is_dir():
        raise RuntimeError("active MT5 MQL5/Logs directory is unavailable")
    return log_directory


def _resolve_lifecycle_terminal_data_path(
    *,
    mt5_path: str,
    expected_terminal_data_path: str,
    terminal_path: str,
    terminal_data_path: str,
) -> Path:
    _reject_reparse_components(Path(mt5_path), "MT5 executable")
    _reject_reparse_components(Path(terminal_path), "active MT5 installation")
    _reject_reparse_components(Path(terminal_data_path), "active MT5 data path")
    _reject_reparse_components(
        Path(expected_terminal_data_path), "configured MT5 data path"
    )
    executable = Path(mt5_path).expanduser().resolve(strict=True)
    if not executable.is_file():
        raise RuntimeError("MT5_PATH must point to the exact terminal executable")
    expected_install = executable.parent

    observed_install = Path(terminal_path).expanduser().resolve(strict=True)
    if observed_install.is_file():
        observed_install = observed_install.parent
    if str(observed_install).casefold() != str(expected_install).casefold():
        raise RuntimeError(
            "active MT5 installation does not match the explicit MT5_PATH"
        )

    data_path = Path(terminal_data_path).expanduser().resolve(strict=True)
    if not data_path.is_dir():
        raise RuntimeError("active MT5 data_path is not a directory")
    expected_data_path = (
        Path(expected_terminal_data_path).expanduser().resolve(strict=True)
    )
    if not expected_data_path.is_dir():
        raise RuntimeError("MT5_DATA_PATH must point to the exact terminal data directory")
    if str(data_path).casefold() != str(expected_data_path).casefold():
        raise RuntimeError(
            "active MT5 data_path does not match the explicit MT5_DATA_PATH"
        )
    mql5_path = data_path / "MQL5"
    _reject_reparse_components(mql5_path, "active MT5 MQL5 directory")
    resolved_mql5 = mql5_path.resolve(strict=True)
    if not resolved_mql5.is_dir():
        raise RuntimeError("active MT5 MQL5 directory is unavailable")
    try:
        resolved_mql5.relative_to(data_path)
    except ValueError as exc:
        raise RuntimeError("active MT5 MQL5 directory escapes MT5_DATA_PATH") from exc
    return data_path


def _probe_account(adapter: LiveMT5Adapter) -> dict[str, object]:
    fingerprint = adapter.load_account_fingerprint()
    terminal = adapter.load_terminal_status()
    return {
        "login": fingerprint.login,
        "server": fingerprint.server,
        "broker": fingerprint.broker,
        "is_live": fingerprint.is_live,
        "trade_allowed": bool(
            terminal.connected
            and terminal.trade_allowed
            and terminal.account_trade_allowed
            and terminal.account_trade_expert
            and not terminal.tradeapi_disabled
        ),
    }


def _make_bridge_account_context_provider(
    *,
    adapter: LiveMT5Adapter,
    mt5_lock: threading.RLock,
    mt5_path: str,
    mt5_data_path: str,
    expected_login: str,
    expected_server: str,
    expected_scope: str,
    allow_live: bool,
) -> Callable[[], dict[str, object]]:
    """Return a serialized, exact-terminal account probe for event routing.

    Mt5LogBridge catches provider failures and persists the event as
    unknown/admin-only.  No password or EA session token is returned.
    """

    def provider() -> dict[str, object]:
        return _with_mt5_lock(
            mt5_lock,
            lambda: _probe_bound_bridge_account(
                adapter,
                mt5_path=mt5_path,
                mt5_data_path=mt5_data_path,
                expected_login=expected_login,
                expected_server=expected_server,
                expected_scope=expected_scope,
                allow_live=allow_live,
            ),
        )

    return provider


def _probe_bound_bridge_account(
    adapter: LiveMT5Adapter,
    *,
    mt5_path: str,
    mt5_data_path: str,
    expected_login: str,
    expected_server: str,
    expected_scope: str,
    allow_live: bool,
) -> dict[str, object]:
    terminal = adapter.load_terminal_status()
    _resolve_lifecycle_terminal_data_path(
        mt5_path=mt5_path,
        expected_terminal_data_path=mt5_data_path,
        terminal_path=terminal.path,
        terminal_data_path=terminal.data_path,
    )
    fingerprint = adapter.load_account_fingerprint()
    normalized_scope = str(expected_scope or "").strip().lower()
    if str(fingerprint.login) != str(expected_login):
        raise RuntimeError("active MT5 login does not match MT5_LOGIN")
    if str(fingerprint.server) != str(expected_server):
        raise RuntimeError("active MT5 server does not match MT5_SERVER")
    if normalized_scope == "demo":
        if fingerprint.is_live is not False:
            raise RuntimeError("demo lifecycle requires a verified demo account")
    elif normalized_scope == "live":
        if not allow_live:
            raise RuntimeError("live account binding is disabled by the deployment kill switch")
        if fingerprint.is_live is not True:
            raise RuntimeError("live lifecycle requires a verified live account")
    else:
        raise RuntimeError("lifecycle execution mode is not a verified account scope")
    return {
        "login": fingerprint.login,
        "server": fingerprint.server,
        "is_live": fingerprint.is_live,
        "margin_mode": fingerprint.margin_mode,
    }


if __name__ == "__main__":
    main()
