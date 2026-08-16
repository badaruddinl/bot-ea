from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from bot_ea.mt5_adapter import LiveMT5Adapter
from goldm_signal.config import gold_i_profile


ACTIVE_EXECUTION_STATUSES = frozenset(
    {
        "OPEN_PENDING",
        "OPEN_SUBMITTED",
        "PLACED",
        "OPEN_UNKNOWN",
        "UNKNOWN",
        "PARTIAL",
        "UNPROTECTED",
        "FILLED",
        "CLOSE_SUBMITTED",
        "CLOSE_UNKNOWN",
        "CLOSE_REJECTED",
    }
)
UNRESOLVED_ACTION_STATUSES = frozenset({"PENDING", "SUBMITTED", "UNKNOWN"})
SAFE_HANDOFF_PURPOSE = "GOLDM_DEPLOY_SAFE_HANDOFF"
SAFE_HANDOFF_SCHEMA_VERSION = 1
RESTORE_ACKNOWLEDGEMENT = "RESTORE_STOPPED_GOLDM_DATABASE"
HANDOFF_ACKNOWLEDGEMENT = "I_ACCEPT_PROTECTED_POSITION_HANDOFF"
SESSION_TOKEN_RE = re.compile(r"[A-Za-z0-9._-]{16,96}\Z")
CONFIG_MARKER = "SNIPER_CONFIG"
PRODUCTION_INPUTS_MARKER = "SNIPER_PRODUCTION_INPUTS"
PRODUCTION_INPUT_CONTRACT_RELATIVE_PATH = Path(
    "config/goldm-production-ea-inputs.json"
)
CANONICAL_GOLD_SYMBOL = gold_i_profile().symbol
MAX_SESSION_LOG_BYTES = 64 * 1024 * 1024
RUNTIME_SESSION_FILENAME = "goldm_runtime_session.txt"
OFFLINE_WHEELHOUSE_MANIFEST = "goldm-wheelhouse-manifest.json"
OFFLINE_WHEELHOUSE_LOCK = "requirements-goldm-live.lock"
OFFLINE_WHEELHOUSE_REQUIRED_PACKAGES = {
    "metatrader5": "5.0.5735",
    "numpy": "2.4.2",
}


class DeploymentSafetyError(RuntimeError):
    """A fail-closed deployment or recovery precondition was not met."""


def load_production_ea_input_contract() -> dict[str, Any]:
    """Load and strictly validate the release-sealed production EA inputs."""

    contract_path = (
        Path(__file__).resolve().parents[2]
        / PRODUCTION_INPUT_CONTRACT_RELATIVE_PATH
    )
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentSafetyError(
            "production EA input contract is missing or invalid JSON"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schemaVersion",
        "strategy",
        "strategyVersion",
        "inputs",
    }:
        raise DeploymentSafetyError("production EA input contract shape is invalid")
    if (
        payload.get("schemaVersion") != 1
        or payload.get("strategy") != "GOLDM_SNIPER_PARITY"
        or payload.get("strategyVersion") != "1.72"
    ):
        raise DeploymentSafetyError(
            "production EA input contract identity is unsupported"
        )
    inputs = payload.get("inputs")
    if (
        not isinstance(inputs, dict)
        or not inputs
        or any(
            not isinstance(key, str)
            or re.fullmatch(r"Inp[A-Za-z0-9]+", key) is None
            or not isinstance(value, str)
            or not value
            or any(character.isspace() for character in value)
            for key, value in inputs.items()
        )
    ):
        raise DeploymentSafetyError(
            "production EA input contract contains an invalid input mapping"
        )
    if "InpResearchRunId" in inputs:
        raise DeploymentSafetyError(
            "production EA input contract must not bind the run/session lineage input"
        )
    if inputs.get("InpExpectedSymbol") != CANONICAL_GOLD_SYMBOL:
        raise DeploymentSafetyError(
            "production EA input contract must bind the canonical GOLD symbol"
        )
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return {
        "payload": payload,
        "inputs": dict(inputs),
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "path": str(contract_path),
    }


class DeploymentMT5Adapter(LiveMT5Adapter):
    """Expose MT5's exact trade-mode enum for deployment-only account proof.

    The runtime fingerprint deliberately models live/demo as a conservative
    tri-state.  Deployment needs a stronger statement: CONTEST is not DEMO.
    Keeping this adapter local avoids weakening the generic trading adapter's
    public contract while still using MT5's authoritative enum rather than
    broker/server-name heuristics.
    """

    def load_exact_account_scope(self) -> str:
        mt5 = self._ensure_initialized()
        account_info = mt5.account_info()
        if account_info is None:
            raise RuntimeError(f"MT5 account_info() failed: {mt5.last_error()}")
        trade_mode = getattr(account_info, "trade_mode", None)
        demo_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
        real_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", None)
        contest_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_CONTEST", None)
        if demo_mode is not None and trade_mode == demo_mode:
            return "demo"
        if real_mode is not None and trade_mode == real_mode:
            return "live"
        if contest_mode is not None and trade_mode == contest_mode:
            return "contest"
        return "unknown"


@dataclass(frozen=True, slots=True)
class DatabaseSnapshot:
    path: str
    sha256: str
    runtime_execution_mode: str
    active_executions: tuple[dict[str, Any], ...]
    unresolved_actions: tuple[dict[str, Any], ...]
    integrity_check: str = "ok"


@dataclass(frozen=True, slots=True)
class BrokerSnapshot:
    terminal_executable: str
    terminal_data_path: str
    account_login: str
    account_server: str
    account_scope: str
    account_margin_mode: str
    positions: tuple[dict[str, Any], ...]
    orders: tuple[dict[str, Any], ...] = ()
    snapshot_schema_version: int = field(init=False, default=2)
    position_count: int = field(init=False)
    order_count: int = field(init=False)
    positions_sha256: str = field(init=False)
    orders_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "position_count", len(self.positions))
        object.__setattr__(self, "order_count", len(self.orders))
        object.__setattr__(self, "positions_sha256", _broker_rows_sha256(self.positions))
        object.__setattr__(self, "orders_sha256", _broker_rows_sha256(self.orders))


def _broker_rows_sha256(rows: tuple[dict[str, Any], ...]) -> str:
    canonical = json.dumps(
        list(rows), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse the deliberately small KEY=VALUE subset used by GOLDM.

    Comments are recognized only outside quotes.  Values are never printed by
    this module, so the MT5 password and Telegram token do not leak to logs.
    """

    if not path.is_file():
        raise DeploymentSafetyError(f"environment file does not exist: {path}")
    values: dict[str, str] = {}
    observed_keys: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = _strip_unquoted_comment(raw_line).strip()
        if not line:
            continue
        if "=" not in line:
            raise DeploymentSafetyError(
                f"invalid environment assignment at line {line_number}"
            )
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is None:
            raise DeploymentSafetyError(
                f"invalid environment key at line {line_number}"
            )
        normalized_key = key.casefold()
        if normalized_key in observed_keys:
            raise DeploymentSafetyError(
                "duplicate environment key (case-insensitive on Windows): "
                f"{observed_keys[normalized_key]} / {key}"
            )
        managed_key = key.upper().startswith(("GOLDM_", "MT5_", "TELEGRAM_"))
        if managed_key and key != key.upper():
            raise DeploymentSafetyError(
                f"managed environment key must use canonical uppercase: {key}"
            )
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        observed_keys[normalized_key] = key
        values[key] = value
    return values


def validate_runtime_environment(
    values: Mapping[str, str],
    *,
    terminal_executable: Path,
    terminal_data_path: Path,
) -> dict[str, str]:
    if not terminal_executable.expanduser().is_absolute():
        raise DeploymentSafetyError("deployment terminal executable must be absolute")
    if not terminal_data_path.expanduser().is_absolute():
        raise DeploymentSafetyError("deployment terminal data path must be absolute")
    executable = _canonical_file(terminal_executable, "terminal executable")
    data_path = _canonical_directory(terminal_data_path, "terminal data path")
    if executable.name.casefold() != "terminal64.exe":
        raise DeploymentSafetyError(
            "deployment terminal executable must be the exact 64-bit terminal64.exe"
        )

    required = (
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
    )
    missing = [key for key in required if not str(values.get(key, "")).strip()]
    if missing:
        raise DeploymentSafetyError(
            "missing required deployment environment keys: " + ", ".join(missing)
        )
    admin_tokens = [
        token
        for token in re.split(r"[,;\s]+", str(values["TELEGRAM_ADMIN_CHAT_IDS"]).strip())
        if token
    ]
    if not admin_tokens or any(
        not token.isdigit() or int(token) <= 0 for token in admin_tokens
    ):
        raise DeploymentSafetyError(
            "TELEGRAM_ADMIN_CHAT_IDS must contain only positive private user IDs"
        )

    configured_executable_input = Path(values["MT5_PATH"]).expanduser()
    configured_data_path_input = Path(values["MT5_DATA_PATH"]).expanduser()
    if not configured_executable_input.is_absolute():
        raise DeploymentSafetyError("MT5_PATH must be an absolute path")
    if not configured_data_path_input.is_absolute():
        raise DeploymentSafetyError("MT5_DATA_PATH must be an absolute path")
    configured_executable = _canonical_file(configured_executable_input, "MT5_PATH")
    configured_data_path = _canonical_directory(
        configured_data_path_input, "MT5_DATA_PATH"
    )
    if not _same_path(configured_executable, executable):
        raise DeploymentSafetyError(
            "MT5_PATH does not match the explicit deployment terminal executable"
        )
    if not _same_path(configured_data_path, data_path):
        raise DeploymentSafetyError(
            "MT5_DATA_PATH does not match the explicit deployment terminal data path"
        )
    if str(values["MT5_LAUNCH_MODE"]).strip().lower() != "standard":
        raise DeploymentSafetyError(
            "MT5_LAUNCH_MODE must be exactly standard; portable topology is refused"
        )
    if _path_is_within(data_path, executable.parent):
        raise DeploymentSafetyError(
            "portable MT5 topology is unsupported: MT5_DATA_PATH must remain "
            "outside the terminal installation directory"
        )

    if str(values["GOLDM_ALLOW_LIVE_ACTIVATION"]).strip().lower() != "false":
        raise DeploymentSafetyError(
            "GOLDM_ALLOW_LIVE_ACTIVATION must remain exactly false for demo deployment"
        )
    configured_mode = str(values["GOLDM_EXECUTION_MODE"]).strip().lower()
    if configured_mode != "off":
        raise DeploymentSafetyError(
            "GOLDM_EXECUTION_MODE must be exactly off during deployment; "
            "enable demo entry from the admin control only after DEPLOY_OK"
        )
    if str(values.get("GOLDM_TRADE_LIFECYCLE_ENABLED", "true")).strip().lower() not in {
        "true",
        "1",
        "yes",
        "on",
    }:
        raise DeploymentSafetyError(
            "GOLDM_TRADE_LIFECYCLE_ENABLED must be true for the production worker"
        )
    session_id = str(values["GOLDM_EA_SESSION_ID"]).strip()
    if session_id.upper() == "UNSET" or SESSION_TOKEN_RE.fullmatch(session_id) is None:
        raise DeploymentSafetyError(
            "GOLDM_EA_SESSION_ID must be an explicit 16-96 character safe token"
        )
    login = str(values["MT5_LOGIN"]).strip()
    if not login.isdigit() or int(login) <= 0:
        raise DeploymentSafetyError("MT5_LOGIN must be a positive integer")
    if str(values["GOLDM_EXPECTED_MT5_LOGIN"]).strip() != login:
        raise DeploymentSafetyError(
            "GOLDM_EXPECTED_MT5_LOGIN must exactly match MT5_LOGIN"
        )
    server = str(values["MT5_SERVER"]).strip()
    if str(values["GOLDM_EXPECTED_MT5_SERVER"]).strip() != server:
        raise DeploymentSafetyError(
            "GOLDM_EXPECTED_MT5_SERVER must exactly match MT5_SERVER"
        )

    return {
        "terminal_executable": str(executable),
        "terminal_data_path": str(data_path),
        "account_login": login,
        "account_server": server,
        "execution_mode": configured_mode,
        "mt5_launch_mode": "standard",
        "ea_session_id_sha256": hashlib.sha256(session_id.encode("utf-8")).hexdigest(),
        "telegram_admin_count": str(len(set(admin_tokens))),
    }


def write_runtime_session_file(
    env_file: Path,
    terminal_data_path: Path,
) -> dict[str, str]:
    values = parse_env_file(env_file)
    token = str(values.get("GOLDM_EA_SESSION_ID", "")).strip()
    if token.upper() == "UNSET" or SESSION_TOKEN_RE.fullmatch(token) is None:
        raise DeploymentSafetyError(
            "GOLDM_EA_SESSION_ID must be an explicit 16-96 character safe token"
        )
    destination = _runtime_session_path(terminal_data_path, create_files_directory=True)
    if destination.is_symlink():
        raise DeploymentSafetyError("runtime session file must not be a symbolic link")
    temporary = destination.with_name(
        destination.name + f".{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary.open("x", encoding="ascii", newline="\n") as stream:
            stream.write(token + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    verified = verify_runtime_session_file(env_file, terminal_data_path)
    return verified


def verify_runtime_session_file(
    env_file: Path,
    terminal_data_path: Path,
) -> dict[str, str]:
    values = parse_env_file(env_file)
    expected = str(values.get("GOLDM_EA_SESSION_ID", "")).strip()
    return verify_runtime_session_token(expected, terminal_data_path)


def verify_runtime_session_token(
    expected: str,
    terminal_data_path: Path,
) -> dict[str, str]:
    expected = str(expected or "").strip()
    if expected.upper() == "UNSET" or SESSION_TOKEN_RE.fullmatch(expected) is None:
        raise DeploymentSafetyError("GOLDM_EA_SESSION_ID is invalid")
    try:
        path = _runtime_session_path(terminal_data_path, create_files_directory=False)
    except DeploymentSafetyError as exc:
        raise DeploymentSafetyError(f"runtime session file is unavailable: {exc}") from exc
    if path.is_symlink() or not path.is_file():
        raise DeploymentSafetyError("runtime session file is missing or not regular")
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise DeploymentSafetyError("runtime session file is not valid ASCII") from exc
    if lines != [expected]:
        raise DeploymentSafetyError(
            "runtime session file does not exactly match GOLDM_EA_SESSION_ID"
        )
    return {
        "path": str(path.resolve(strict=True)),
        "sha256": sha256_file(path),
        "session_id_sha256": hashlib.sha256(expected.encode("ascii")).hexdigest(),
    }


def inspect_database(path: Path) -> DatabaseSnapshot:
    database = _canonical_file(path, "GOLDM database")
    connection = _connect_read_only(database)
    connection.row_factory = sqlite3.Row
    try:
        integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        integrity = "; ".join(str(row[0]) for row in integrity_rows)
        if integrity != "ok":
            raise DeploymentSafetyError(
                f"database integrity_check failed: {integrity}"
            )
        required_tables = {"trade_executions", "position_actions", "runtime_settings"}
        actual_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        missing_tables = sorted(required_tables - actual_tables)
        if missing_tables:
            raise DeploymentSafetyError(
                "database is not fully migrated; missing tables: "
                + ", ".join(missing_tables)
            )
        action_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(position_actions)")
        }
        if "projected_at" not in action_columns:
            raise DeploymentSafetyError(
                "database is not fully migrated; position_actions.projected_at is missing"
            )

        placeholders = ",".join("?" for _ in ACTIVE_EXECUTION_STATUSES)
        executions = connection.execute(
            f"""
            SELECT setup_id, execution_mode, status, symbol, side, client_tag,
                   magic, account_login, account_server, account_scope,
                   account_margin_mode, position_ticket, position_identifier,
                   remaining_volume, current_stop_price,
                   current_take_profit_price, updated_at
            FROM trade_executions
            WHERE status IN ({placeholders})
            ORDER BY setup_id
            """,
            tuple(sorted(ACTIVE_EXECUTION_STATUSES)),
        ).fetchall()
        unresolved = connection.execute(
            """
            SELECT id, idempotency_key, setup_id, action_type, status,
                   position_ticket, position_identifier, updated_at
            FROM position_actions
            WHERE status IN ('PENDING', 'SUBMITTED', 'UNKNOWN')
               OR (status IN ('CONFIRMED', 'FAILED') AND projected_at IS NULL)
            ORDER BY id
            """
        ).fetchall()
        setting = connection.execute(
            "SELECT value_json FROM runtime_settings "
            "WHERE setting_key = 'trade.execution_mode'"
        ).fetchone()
        runtime_mode = ""
        if setting is not None:
            try:
                runtime_mode = str(json.loads(str(setting[0]))).strip().lower()
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise DeploymentSafetyError(
                    "trade.execution_mode contains invalid JSON"
                ) from exc
        if runtime_mode == "live":
            raise DeploymentSafetyError(
                "runtime trade.execution_mode is live; demo deployment refuses cutover"
            )
        if runtime_mode and runtime_mode not in {"off", "demo"}:
            raise DeploymentSafetyError(
                f"runtime trade.execution_mode is invalid: {runtime_mode}"
            )
    finally:
        connection.close()

    return DatabaseSnapshot(
        path=str(database),
        sha256=sha256_file(database),
        runtime_execution_mode=runtime_mode,
        active_executions=tuple(dict(row) for row in executions),
        unresolved_actions=tuple(dict(row) for row in unresolved),
        integrity_check=integrity,
    )


def collect_broker_snapshot(
    values: Mapping[str, str],
    *,
    terminal_executable: Path,
    terminal_data_path: Path,
    adapter_factory: Callable[..., Any] = DeploymentMT5Adapter,
) -> BrokerSnapshot:
    contract = validate_runtime_environment(
        values,
        terminal_executable=terminal_executable,
        terminal_data_path=terminal_data_path,
    )
    adapter = adapter_factory(
        path=contract["terminal_executable"],
        login=int(contract["account_login"]),
        password=values.get("MT5_PASSWORD") or None,
        server=contract["account_server"],
        portable=False,
        require_mutation_binding=True,
    )
    try:
        terminal = adapter.load_terminal_status()
        account_before = adapter.load_account_fingerprint()
        scope_before = _load_exact_deployment_account_scope(adapter)
        positions = adapter.load_open_positions()
        orders = adapter.load_open_orders()
        account = adapter.load_account_fingerprint()
        account_scope = _load_exact_deployment_account_scope(adapter)
    finally:
        adapter.shutdown()

    account_before_identity = (
        str(account_before.login),
        str(account_before.server),
        str(getattr(account_before, "broker", "") or ""),
        account_before.is_live,
        str(account_before.margin_mode).upper(),
        scope_before,
    )
    account_after_identity = (
        str(account.login),
        str(account.server),
        str(getattr(account, "broker", "") or ""),
        account.is_live,
        str(account.margin_mode).upper(),
        account_scope,
    )
    if account_before_identity != account_after_identity:
        raise DeploymentSafetyError(
            "MT5 account identity changed while deployment captured broker positions/orders"
        )

    observed_executable = _terminal_executable_from_status(terminal.path)
    observed_data_path = _canonical_directory(
        Path(terminal.data_path), "observed terminal data path"
    )
    if not _same_path(observed_executable, Path(contract["terminal_executable"])):
        raise DeploymentSafetyError(
            "MT5 Python API attached to a different terminal installation"
        )
    if not _same_path(observed_data_path, Path(contract["terminal_data_path"])):
        raise DeploymentSafetyError(
            "MT5 Python API attached to a different terminal data path"
        )
    if not terminal.connected:
        raise DeploymentSafetyError("the exact MT5 terminal is not connected")
    if str(account.login) != contract["account_login"]:
        raise DeploymentSafetyError("connected MT5 login does not match MT5_LOGIN")
    if str(account.server) != contract["account_server"]:
        raise DeploymentSafetyError("connected MT5 server does not match MT5_SERVER")
    if account_scope != "demo" or account.is_live is not False:
        raise DeploymentSafetyError(
            "deployment requires the exact MT5 DEMO trade mode; "
            "REAL/CONTEST/unclassified accounts are refused"
        )
    if str(account.margin_mode).upper() != "HEDGING":
        raise DeploymentSafetyError(
            "deployment requires a HEDGING account; NETTING/EXCHANGE/UNKNOWN is refused"
        )

    sanitized_positions = tuple(
        {
            "ticket": int(position.ticket),
            "identifier": int(position.position_identifier or position.ticket),
            "symbol": str(position.symbol),
            "side": str(position.side).upper(),
            "volume": float(position.volume),
            "sl": float(position.sl),
            "tp": float(position.tp),
            "magic": int(position.magic),
            "comment": str(position.comment),
        }
        for position in sorted(
            positions,
            key=lambda item: (int(item.position_identifier or item.ticket), int(item.ticket)),
        )
    )
    sanitized_orders = tuple(
        {
            "ticket": int(order.ticket),
            "symbol": str(order.symbol),
            "order_type": str(order.order_type).lower(),
            "state": str(order.state).lower(),
            "volume_initial": float(order.volume_initial),
            "volume_current": float(order.volume_current),
            "price_open": float(order.price_open),
            "price_stoplimit": float(order.price_stoplimit),
            "sl": float(order.sl),
            "tp": float(order.tp),
            "setup_at": order.setup_at,
            "expiration_at": order.expiration_at,
            "magic": int(order.magic),
            "position_ticket": (
                int(order.position_ticket)
                if order.position_ticket is not None
                else None
            ),
        }
        for order in sorted(orders, key=lambda item: int(item.ticket))
    )
    return BrokerSnapshot(
        terminal_executable=contract["terminal_executable"],
        terminal_data_path=contract["terminal_data_path"],
        account_login=contract["account_login"],
        account_server=contract["account_server"],
        account_scope=account_scope,
        account_margin_mode=str(account.margin_mode).upper(),
        positions=sanitized_positions,
        orders=sanitized_orders,
    )


def assert_cutover_safe(
    database: DatabaseSnapshot,
    broker: BrokerSnapshot,
    *,
    release_commit: str,
    safe_handoff_path: Path | None = None,
    safe_handoff_sha256: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if database.runtime_execution_mode not in {"", "off"}:
        raise DeploymentSafetyError(
            "runtime trade.execution_mode must be OFF before deployment cutover"
        )
    if database.unresolved_actions:
        raise DeploymentSafetyError(
            "unresolved or unprojected broker actions block deployment"
        )
    if database.active_executions or broker.positions or broker.orders:
        raise DeploymentSafetyError(
            "automated deployment requires a flat book: cancel every pending order, "
            "then close and reconcile every broker position first. "
            "Protected-position handoff is disabled until a "
            "mutation-free cutover maintenance barrier is implemented and proven"
        )
    if safe_handoff_path is not None or safe_handoff_sha256 is not None:
        raise DeploymentSafetyError(
            "safe handoff was supplied but automated protected-position handoff is disabled"
        )
    return {"disposition": "NO_OPEN_POSITIONS", "safe_handoff_sha256": ""}


def create_safe_handoff_manifest(
    database: DatabaseSnapshot,
    broker: BrokerSnapshot,
    *,
    release_commit: str,
    approved_by: str,
    reason: str,
    output_path: Path,
    acknowledgement: str,
    validity_minutes: int = 10,
    now: datetime | None = None,
) -> dict[str, Any]:
    if acknowledgement != HANDOFF_ACKNOWLEDGEMENT:
        raise DeploymentSafetyError(
            "safe handoff creation requires the exact risk acknowledgement"
        )
    if re.fullmatch(r"[0-9a-f]{40}", release_commit) is None:
        raise DeploymentSafetyError("safe handoff release commit must be 40 lowercase hex")
    if validity_minutes < 1 or validity_minutes > 15:
        raise DeploymentSafetyError("safe handoff validity must be between 1 and 15 minutes")
    if broker.orders:
        raise DeploymentSafetyError(
            "safe handoff requires zero active or pending broker orders"
        )
    if not database.active_executions or not broker.positions:
        raise DeploymentSafetyError("safe handoff requires an existing protected position")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = {
        "schemaVersion": SAFE_HANDOFF_SCHEMA_VERSION,
        "purpose": SAFE_HANDOFF_PURPOSE,
        "releaseCommit": release_commit,
        "approvedBy": str(approved_by).strip(),
        "reason": str(reason).strip(),
        "createdAtUtc": current.isoformat().replace("+00:00", "Z"),
        "expiresAtUtc": (current + timedelta(minutes=validity_minutes))
        .isoformat()
        .replace("+00:00", "Z"),
        "terminalExecutable": broker.terminal_executable,
        "terminalDataPath": broker.terminal_data_path,
        "account": {
            "login": broker.account_login,
            "server": broker.account_server,
            "scope": broker.account_scope,
        },
        "activeSetupIds": [
            str(row["setup_id"]) for row in database.active_executions
        ],
        "positions": list(broker.positions),
    }
    _validate_safe_handoff_payload(
        payload,
        database=database,
        broker=broker,
        release_commit=release_commit,
        now=current,
    )
    output = output_path.expanduser().absolute()
    temporary = output.with_name(output.name + f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        sealed = seal_json(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "path": sealed["path"],
        "sha256": sealed["sha256"],
        "expires_at_utc": payload["expiresAtUtc"],
        "position_count": len(broker.positions),
    }


def backup_database(source: Path, destination: Path) -> dict[str, Any]:
    source_path = _canonical_file(source, "source database")
    destination_path = destination.expanduser().absolute()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        raise DeploymentSafetyError(
            f"refusing to overwrite database backup: {destination_path}"
        )
    source_connection = _connect_read_only(source_path)
    destination_connection = sqlite3.connect(destination_path)
    try:
        source_connection.execute("PRAGMA busy_timeout=10000")
        source_connection.backup(destination_connection)
        destination_connection.commit()
        integrity_rows = destination_connection.execute("PRAGMA integrity_check").fetchall()
        integrity = "; ".join(str(row[0]) for row in integrity_rows)
        if integrity != "ok":
            raise DeploymentSafetyError(
                f"backup database integrity_check failed: {integrity}"
            )
        foreign_key_rows = destination_connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        if foreign_key_rows:
            raise DeploymentSafetyError("backup database foreign_key_check failed")
        page_count = int(destination_connection.execute("PRAGMA page_count").fetchone()[0])
    except Exception:
        destination_connection.close()
        source_connection.close()
        destination_path.unlink(missing_ok=True)
        raise
    finally:
        try:
            destination_connection.close()
        finally:
            source_connection.close()
    return {
        "source": str(source_path),
        "destination": str(destination_path),
        "sha256": sha256_file(destination_path),
        "integrity_check": "ok",
        "foreign_key_check": "ok",
        "page_count": page_count,
    }


def verify_database_backup(path: Path, *, expected_sha256: str) -> dict[str, Any]:
    backup_path = _canonical_file(path, "database backup")
    expected = _validated_sha256(expected_sha256)
    actual = sha256_file(backup_path)
    if actual != expected:
        raise DeploymentSafetyError("database backup SHA-256 mismatch")
    connection = _connect_read_only(backup_path)
    try:
        integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        integrity = "; ".join(str(row[0]) for row in integrity_rows)
        foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    if integrity != "ok":
        raise DeploymentSafetyError(
            f"database backup integrity_check failed: {integrity}"
        )
    if foreign_key_rows:
        raise DeploymentSafetyError("database backup foreign_key_check failed")
    return {"path": str(backup_path), "sha256": actual, "integrity_check": "ok"}


def restore_database(
    backup: Path,
    destination: Path,
    *,
    expected_sha256: str,
    acknowledgement: str,
) -> dict[str, Any]:
    if acknowledgement != RESTORE_ACKNOWLEDGEMENT:
        raise DeploymentSafetyError(
            "database restore requires the exact stopped-task acknowledgement"
        )
    verified = verify_database_backup(backup, expected_sha256=expected_sha256)
    destination_path = destination.expanduser().absolute()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_name(
        destination_path.name + f".restore-{uuid.uuid4().hex}.tmp"
    )
    source_connection = _connect_read_only(Path(verified["path"]))
    target_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
        integrity = str(target_connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise DeploymentSafetyError(
                f"restored database integrity_check failed: {integrity}"
            )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        target_connection.close()
        source_connection.close()
    os.replace(temporary, destination_path)
    # A restored main database must never inherit WAL/SHM from the replaced file.
    for suffix in ("-wal", "-shm"):
        destination_path.with_name(destination_path.name + suffix).unlink(missing_ok=True)
    return {
        "destination": str(destination_path),
        "sha256": sha256_file(destination_path),
        "source_backup_sha256": verified["sha256"],
        "integrity_check": "ok",
    }


def seal_json(input_path: Path, output_path: Path) -> dict[str, str]:
    source = _canonical_file(input_path, "evidence JSON input")
    destination = output_path.expanduser().absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    sidecar = destination.with_name(destination.name + ".sha256")
    if destination.exists() or sidecar.exists():
        raise DeploymentSafetyError("refusing to overwrite sealed deployment evidence")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentSafetyError("evidence input is invalid JSON") from exc
    canonical = (
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    )
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical)
        stream.flush()
        os.fsync(stream.fileno())
    digest = sha256_file(destination)
    with sidecar.open("x", encoding="ascii", newline="\n") as stream:
        stream.write(f"{digest}  {destination.name}\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        destination.chmod(destination.stat().st_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
        sidecar.chmod(sidecar.stat().st_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
    except OSError:
        # The SHA sidecar remains authoritative on filesystems without a
        # meaningful read-only bit (the deployment scripts verify it again).
        pass
    return {"path": str(destination), "sha256": digest, "sidecar": str(sidecar)}


def capture_log_cursor(log_directory: Path, output_path: Path) -> dict[str, Any]:
    directory = _canonical_directory(log_directory, "MT5 MQL5 log directory")
    output = output_path.expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise DeploymentSafetyError("refusing to overwrite an MT5 log cursor")
    files = {
        path.name: {
            "size": path.stat().st_size,
            "identity": _file_identity(path),
        }
        for path in sorted(directory.glob("*.log"))
        if path.is_file()
    }
    payload = {
        "schemaVersion": 1,
        "logDirectory": str(directory),
        "capturedAtUtc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": files,
    }
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(output), "files": len(files)}


def find_fresh_ea_session_evidence(
    log_directory: Path,
    cursor_path: Path,
    *,
    session_id: str,
    expected_account_login: str,
    expected_account_server: str,
    expected_account_scope: str = "demo",
) -> dict[str, Any]:
    directory = _canonical_directory(log_directory, "MT5 MQL5 log directory")
    cursor_file = _canonical_file(cursor_path, "MT5 log cursor")
    if session_id.upper() == "UNSET" or SESSION_TOKEN_RE.fullmatch(session_id) is None:
        raise DeploymentSafetyError("session evidence requires a valid session token")
    try:
        cursor = json.loads(cursor_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentSafetyError("MT5 log cursor is invalid JSON") from exc
    if not isinstance(cursor, Mapping) or cursor.get("schemaVersion") != 1:
        raise DeploymentSafetyError("MT5 log cursor schema is unsupported")
    if not _same_path(Path(str(cursor.get("logDirectory", ""))), directory):
        raise DeploymentSafetyError("MT5 log cursor belongs to a different directory")
    baseline_files = cursor.get("files")
    if not isinstance(baseline_files, Mapping):
        raise DeploymentSafetyError("MT5 log cursor file map is invalid")

    fresh_configs: list[
        tuple[int, str, int, dict[str, str], dict[str, str]]
    ] = []
    for path in sorted(directory.glob("*.log")):
        if not path.is_file():
            continue
        file_size = path.stat().st_size
        baseline = baseline_files.get(path.name)
        start = 0
        if isinstance(baseline, Mapping):
            baseline_size = int(baseline.get("size", -1))
            if baseline_size < 0:
                raise DeploymentSafetyError("MT5 log cursor contains a negative size")
            if baseline.get("identity") == _file_identity(path):
                if file_size < baseline_size:
                    # Rotation/truncation with the same name means the whole new
                    # file is fresh evidence; never seek beyond its beginning.
                    start = 0
                else:
                    start = baseline_size
        fresh_size = file_size - start
        if fresh_size > MAX_SESSION_LOG_BYTES:
            raise DeploymentSafetyError(
                f"fresh MT5 log segment exceeds the session-evidence safety limit: {path.name}"
            )
        with path.open("rb") as stream:
            stream.seek(start)
            raw = stream.read(MAX_SESSION_LOG_BYTES + 1)
        if not raw:
            continue
        text = _decode_mt5_log_bytes(raw, offset=start)
        lines = text.splitlines()
        for line_index, line in enumerate(lines):
            if CONFIG_MARKER not in line:
                continue
            fields = _parse_log_fields(line)
            production_inputs = _production_inputs_for_config(
                lines, line_index=line_index, config_fields=fields
            )
            fresh_configs.append(
                (
                    _log_file_chronology(path),
                    path.name,
                    line_index,
                    fields,
                    production_inputs,
                )
            )
    if not fresh_configs:
        raise DeploymentSafetyError(
            "no fresh SNIPER_CONFIG proves the configured GOLDM_EA_SESSION_ID; "
            "attach the EA and restart the exact terminal"
        )
    invalid = [
        fields
        for _, _, _, fields, production_inputs in fresh_configs
        if not _ea_config_matches_expected_binding(
            fields,
            production_inputs=production_inputs,
            session_id=session_id,
            expected_account_login=expected_account_login,
            expected_account_server=expected_account_server,
            expected_account_scope=expected_account_scope,
        )
    ]
    if invalid:
        raise DeploymentSafetyError(
            "at least one fresh SNIPER_CONFIG has a different session/symbol/strategy/account; "
            "worker activation is refused"
        )
    _, file_name, _, _, _ = max(fresh_configs, key=lambda item: item[:3])
    contract = load_production_ea_input_contract()
    return {
        "status": "MATCHED",
        "log_file": file_name,
        "session_id_sha256": hashlib.sha256(session_id.encode("utf-8")).hexdigest(),
        "production_config_sha256": contract["sha256"],
    }


def find_latest_ea_session_evidence(
    log_directory: Path,
    *,
    session_id: str,
    expected_account_login: str,
    expected_account_server: str,
    expected_account_scope: str = "demo",
) -> dict[str, Any]:
    directory = _canonical_directory(log_directory, "MT5 MQL5 log directory")
    if session_id.upper() == "UNSET" or SESSION_TOKEN_RE.fullmatch(session_id) is None:
        raise DeploymentSafetyError("session evidence requires a valid session token")
    candidates: list[
        tuple[int, str, int, dict[str, str], dict[str, str]]
    ] = []
    for path in sorted(directory.glob("*.log")):
        if not path.is_file():
            continue
        if path.stat().st_size > MAX_SESSION_LOG_BYTES:
            raise DeploymentSafetyError(
                f"MT5 log exceeds the session-evidence safety limit: {path.name}"
            )
        raw = path.read_bytes()
        if not raw:
            continue
        text = _decode_mt5_log_bytes(raw, offset=0)
        lines = text.splitlines()
        for line_index, line in enumerate(lines):
            if CONFIG_MARKER in line:
                fields = _parse_log_fields(line)
                candidates.append(
                    (
                        _log_file_chronology(path),
                        path.name,
                        line_index,
                        fields,
                        _production_inputs_for_config(
                            lines, line_index=line_index, config_fields=fields
                        ),
                    )
                )
    if not candidates:
        raise DeploymentSafetyError(
            "no SNIPER_CONFIG exists in the exact terminal log directory; "
            "stage the EA and attach it manually before activation"
        )
    _, file_name, _, latest, production_inputs = max(
        candidates, key=lambda item: item[:3]
    )
    if not _ea_config_matches_expected_binding(
        latest,
        production_inputs=production_inputs,
        session_id=session_id,
        expected_account_login=expected_account_login,
        expected_account_server=expected_account_server,
        expected_account_scope=expected_account_scope,
    ):
        raise DeploymentSafetyError(
            "the latest SNIPER_CONFIG does not match GOLDM_EA_SESSION_ID/symbol/strategy/account; "
            "stage the file-backed runtime session and restart the exact terminal "
            "before activation"
        )
    contract = load_production_ea_input_contract()
    return {
        "status": "MATCHED",
        "log_file": file_name,
        "session_id_sha256": hashlib.sha256(session_id.encode("utf-8")).hexdigest(),
        "production_config_sha256": contract["sha256"],
    }


def verify_sealed_json(path: Path) -> dict[str, str]:
    if _is_link_like(path.expanduser()):
        raise DeploymentSafetyError("sealed evidence must not be a symbolic link")
    evidence = _canonical_file(path, "sealed evidence")
    sidecar_input = evidence.with_name(evidence.name + ".sha256")
    if _is_link_like(sidecar_input):
        raise DeploymentSafetyError(
            "sealed evidence SHA sidecar must not be a symbolic link"
        )
    sidecar = _canonical_file(sidecar_input, "sealed evidence SHA sidecar")
    parts = sidecar.read_text(encoding="ascii").strip().split()
    if len(parts) != 2 or parts[1] != evidence.name:
        raise DeploymentSafetyError("sealed evidence SHA sidecar is malformed")
    expected = _validated_sha256(parts[0])
    actual = sha256_file(evidence)
    if actual != expected:
        raise DeploymentSafetyError("sealed deployment evidence SHA-256 mismatch")
    try:
        json.loads(evidence.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DeploymentSafetyError("sealed deployment evidence is invalid JSON") from exc
    return {"path": str(evidence), "sha256": actual}


def build_tree_manifest(root: Path, output_path: Path) -> dict[str, Any]:
    directory = _canonical_directory(root, "release tree")
    output_input = output_path.expanduser()
    output = output_input.parent.resolve(strict=True) / output_input.name
    try:
        output.relative_to(directory)
    except ValueError as exc:
        raise DeploymentSafetyError(
            "release tree manifest must be written inside the release tree"
        ) from exc
    sidecar = output.with_name(output.name + ".sha256")
    if output.exists() or sidecar.exists():
        raise DeploymentSafetyError("refusing to overwrite a release tree manifest")
    records: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
        if path == output or path == sidecar:
            continue
        if _is_link_like(path):
            raise DeploymentSafetyError(
                f"release tree contains a symbolic link: {path.relative_to(directory)}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise DeploymentSafetyError(
                f"release tree contains a non-regular file: {path.relative_to(directory)}"
            )
        records.append(
            {
                "path": path.relative_to(directory).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    payload = {
        "schemaVersion": 1,
        "rootName": directory.name,
        "files": records,
    }
    temporary = output.with_name(output.name + f".{uuid.uuid4().hex}.json")
    try:
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        sealed = seal_json(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "path": sealed["path"],
        "sha256": sealed["sha256"],
        "file_count": len(records),
    }


def verify_tree_manifest(
    root: Path, manifest_path: Path, *, expected_manifest_sha256: str
) -> dict[str, Any]:
    directory = _canonical_directory(root, "release tree")
    if _is_link_like(manifest_path.expanduser()):
        raise DeploymentSafetyError("release tree manifest must not be a symbolic link")
    manifest_file = _canonical_file(manifest_path, "release tree manifest")
    expected_manifest = _validated_sha256(expected_manifest_sha256)
    actual_manifest = sha256_file(manifest_file)
    if actual_manifest != expected_manifest:
        raise DeploymentSafetyError(
            "release tree manifest does not match the operator-approved SHA-256"
        )
    verify_sealed_json(manifest_file)
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1 or payload.get("rootName") != directory.name:
        raise DeploymentSafetyError("release tree manifest identity mismatch")
    expected_records = payload.get("files")
    if not isinstance(expected_records, list):
        raise DeploymentSafetyError("release tree manifest files are invalid")
    actual_paths: set[str] = set()
    for record in expected_records:
        if not isinstance(record, Mapping):
            raise DeploymentSafetyError("release tree manifest record is invalid")
        relative = str(record.get("path", ""))
        raw_candidate = directory / Path(relative)
        if _is_link_like(raw_candidate):
            raise DeploymentSafetyError(f"release file is a symbolic link: {relative}")
        candidate = raw_candidate.resolve(strict=True)
        try:
            candidate.relative_to(directory)
        except ValueError as exc:
            raise DeploymentSafetyError("release tree manifest path escapes root") from exc
        if not candidate.is_file():
            raise DeploymentSafetyError(f"release file is not regular: {relative}")
        if relative in actual_paths:
            raise DeploymentSafetyError(f"duplicate release manifest path: {relative}")
        actual_paths.add(relative)
        if candidate.stat().st_size != int(record.get("size", -1)):
            raise DeploymentSafetyError(f"release file size mismatch: {relative}")
        if sha256_file(candidate) != str(record.get("sha256", "")):
            raise DeploymentSafetyError(f"release file SHA-256 mismatch: {relative}")
    excluded = {manifest_file, manifest_file.with_name(manifest_file.name + ".sha256")}
    on_disk: set[str] = set()
    for path in directory.rglob("*"):
        if path in excluded:
            continue
        if _is_link_like(path):
            raise DeploymentSafetyError(
                f"release tree contains a symbolic link: {path.relative_to(directory)}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise DeploymentSafetyError(
                f"release tree contains a non-regular file: {path.relative_to(directory)}"
            )
        on_disk.add(path.relative_to(directory).as_posix())
    if on_disk != actual_paths:
        raise DeploymentSafetyError("release tree contains missing or unmanifested files")
    return {
        "status": "VERIFIED",
        "manifest_sha256": actual_manifest,
        "file_count": len(actual_paths),
    }


def verify_offline_wheelhouse(
    root: Path, *, expected_manifest_sha256: str
) -> dict[str, Any]:
    """Verify one sealed, hash-locked, wheel-only dependency input.

    The deployment scripts invoke pip with both ``--no-index`` and
    ``--require-hashes``.  This verifier makes those command-line controls
    auditable before pip executes: the lock contains exact pins and SHA-256
    hashes, required runtime/build packages are present in the lock, and the
    sealed directory contains no source distributions or unmanifested files.
    The caller-supplied manifest digest is the external root of trust; the
    manifest's sibling sidecar alone cannot authorize a replaced dependency set.
    """

    directory = _canonical_directory(root, "offline wheelhouse")
    manifest_input = directory / OFFLINE_WHEELHOUSE_MANIFEST
    lock_input = directory / OFFLINE_WHEELHOUSE_LOCK
    if manifest_input.is_symlink() or lock_input.is_symlink():
        raise DeploymentSafetyError(
            "offline wheelhouse manifest/lock must not be symbolic links"
        )
    manifest = _canonical_file(manifest_input, "offline wheelhouse manifest")
    lock = _canonical_file(lock_input, "offline wheelhouse requirements lock")
    tree = verify_tree_manifest(
        directory,
        manifest,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    expected_manifest = _validated_sha256(expected_manifest_sha256)
    if tree["manifest_sha256"] != expected_manifest:
        raise DeploymentSafetyError(
            "offline wheelhouse manifest does not match the operator-approved SHA-256"
        )

    allowed_metadata = {
        manifest.name,
        manifest.name + ".sha256",
        lock.name,
    }
    wheel_files = []
    for path in directory.iterdir():
        if path.name in allowed_metadata:
            continue
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".whl":
            raise DeploymentSafetyError(
                "offline wheelhouse may contain only sealed .whl files and its lock"
            )
        wheel_files.append(path)
    if not wheel_files:
        raise DeploymentSafetyError("offline wheelhouse contains no wheel files")

    packages = _parse_hashed_requirements_lock(lock)
    missing = sorted(set(OFFLINE_WHEELHOUSE_REQUIRED_PACKAGES) - set(packages))
    if missing:
        raise DeploymentSafetyError(
            "offline wheelhouse lock is missing required exact packages: "
            + ", ".join(missing)
        )
    unexpected = sorted(set(packages) - set(OFFLINE_WHEELHOUSE_REQUIRED_PACKAGES))
    if unexpected:
        raise DeploymentSafetyError(
            "offline wheelhouse lock contains packages outside the production worker contract: "
            + ", ".join(unexpected)
        )
    wrong_versions = sorted(
        name
        for name, expected in OFFLINE_WHEELHOUSE_REQUIRED_PACKAGES.items()
        if packages.get(name) != expected
    )
    if wrong_versions:
        raise DeploymentSafetyError(
            "offline wheelhouse lock has a version outside the approved contract: "
            + ", ".join(wrong_versions)
        )
    expected_wheel_prefixes = {
        f"{name.replace('-', '_')}-{version}-"
        for name, version in OFFLINE_WHEELHOUSE_REQUIRED_PACKAGES.items()
    }
    actual_wheel_names = {path.name.lower() for path in wheel_files}
    for prefix in expected_wheel_prefixes:
        matches = [name for name in actual_wheel_names if name.startswith(prefix)]
        if len(matches) != 1 or "cp314" not in matches[0] or not matches[0].endswith(
            "win_amd64.whl"
        ):
            raise DeploymentSafetyError(
                "offline wheelhouse requires one CPython 3.14 win_amd64 wheel for "
                + prefix.rstrip("-")
            )
    if len(wheel_files) != len(expected_wheel_prefixes):
        raise DeploymentSafetyError(
            "offline wheelhouse contains an unexpected wheel count"
        )
    return {
        "status": "VERIFIED",
        "root": str(directory),
        "manifest": str(manifest),
        "manifest_sha256": tree["manifest_sha256"],
        "lock": str(lock),
        "lock_sha256": sha256_file(lock),
        "locked_packages": len(packages),
        "wheel_files": len(wheel_files),
    }


def _parse_hashed_requirements_lock(path: Path) -> dict[str, str]:
    logical_lines: list[str] = []
    pending = ""
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pending = (pending + " " + stripped).strip() if pending else stripped
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical_lines.append(pending)
        pending = ""
    if pending:
        raise DeploymentSafetyError(
            "offline wheelhouse lock ends with an unterminated continuation"
        )

    packages: dict[str, str] = {}
    requirement_re = re.compile(
        r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)=="
        r"(?P<version>[A-Za-z0-9][A-Za-z0-9._+!-]*)"
        r"(?P<hashes>(?:\s+--hash=sha256:[0-9a-fA-F]{64})+)\Z"
    )
    for line in logical_lines:
        match = requirement_re.fullmatch(line)
        if match is None:
            raise DeploymentSafetyError(
                "offline wheelhouse lock permits only exact == pins with SHA-256 hashes"
            )
        package = re.sub(r"[-_.]+", "-", match.group("name")).lower()
        if package in packages:
            raise DeploymentSafetyError(
                f"offline wheelhouse lock contains duplicate package: {package}"
            )
        packages[package] = match.group("version")
    if not packages:
        raise DeploymentSafetyError("offline wheelhouse lock contains no packages")
    return packages


def inspect_telegram_poll_readiness(
    database_path: Path,
    env_file: Path,
    *,
    expected_release_id: str,
    expected_deployment_nonce_sha256: str,
    expected_release_manifest_sha256: str,
    expected_runtime_config_sha256: str,
    expected_production_config_sha256: str,
    not_before_utc: str,
    max_age_seconds: float,
) -> dict[str, Any]:
    """Require fresh, exact successful Telegram polling by this worker epoch."""

    if re.fullmatch(r"[0-9a-f]{40}", expected_release_id) is None:
        raise DeploymentSafetyError(
            "Telegram readiness expected release id must be full lowercase commit SHA"
        )
    for label, digest in (
        ("deployment nonce", expected_deployment_nonce_sha256),
        ("release manifest", expected_release_manifest_sha256),
        ("runtime config", expected_runtime_config_sha256),
        ("production config", expected_production_config_sha256),
    ):
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise DeploymentSafetyError(
                f"Telegram readiness {label} digest must be 64 lowercase hex"
            )
    try:
        not_before = datetime.fromisoformat(
            str(not_before_utc).strip().replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise DeploymentSafetyError(
            "Telegram readiness not-before timestamp is invalid"
        ) from exc
    if not_before.tzinfo is None or not_before.utcoffset() is None:
        raise DeploymentSafetyError(
            "Telegram readiness not-before timestamp must include UTC offset"
        )
    not_before = not_before.astimezone(timezone.utc)
    if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
        raise DeploymentSafetyError(
            "Telegram readiness max age must be a positive finite number"
        )
    values = parse_env_file(env_file)
    if sha256_file(_canonical_file(env_file, "runtime environment snapshot")) != expected_runtime_config_sha256:
        raise DeploymentSafetyError(
            "Telegram readiness runtime environment digest does not match its file"
        )
    if load_production_ea_input_contract()["sha256"] != expected_production_config_sha256:
        raise DeploymentSafetyError(
            "Telegram readiness production input contract digest mismatch"
        )
    session_id = str(values.get("GOLDM_EA_SESSION_ID", "")).strip()
    if session_id.upper() == "UNSET" or SESSION_TOKEN_RE.fullmatch(session_id) is None:
        raise DeploymentSafetyError(
            "Telegram readiness requires a valid GOLDM_EA_SESSION_ID"
        )
    try:
        from goldm_signal.storage import SignalStore, telegram_poll_db_identity

        store = SignalStore(database_path)
        result = store.telegram_poll_readiness(
            expected_release_id=expected_release_id,
            expected_session_sha256=hashlib.sha256(
                session_id.encode("utf-8")
            ).hexdigest(),
            expected_db_identity=telegram_poll_db_identity(database_path),
            expected_deployment_nonce_sha256=expected_deployment_nonce_sha256,
            expected_release_manifest_sha256=expected_release_manifest_sha256,
            expected_runtime_config_sha256=expected_runtime_config_sha256,
            expected_production_config_sha256=expected_production_config_sha256,
            not_before=not_before,
            max_age_seconds=float(max_age_seconds),
        )
    except (AttributeError, ImportError, OSError, sqlite3.Error, ValueError) as exc:
        raise DeploymentSafetyError(
            "Telegram poll readiness could not be evaluated"
        ) from exc
    if not isinstance(result, Mapping) or result.get("ready") is not True:
        reason = (
            str(result.get("reason", "missing"))
            if isinstance(result, Mapping)
            else "invalid"
        )
        raise DeploymentSafetyError(
            f"Telegram poll readiness is not ready: {reason}"
        )
    return dict(result)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_safe_handoff_payload(
    payload: Mapping[str, Any],
    *,
    database: DatabaseSnapshot,
    broker: BrokerSnapshot,
    release_commit: str,
    now: datetime,
) -> None:
    if broker.orders:
        raise DeploymentSafetyError(
            "safe handoff is invalid while active or pending broker orders exist"
        )
    if payload.get("schemaVersion") != SAFE_HANDOFF_SCHEMA_VERSION:
        raise DeploymentSafetyError("safe handoff schemaVersion is unsupported")
    if payload.get("purpose") != SAFE_HANDOFF_PURPOSE:
        raise DeploymentSafetyError("safe handoff purpose is invalid")
    if str(payload.get("releaseCommit", "")) != release_commit:
        raise DeploymentSafetyError("safe handoff releaseCommit mismatch")
    if len(str(payload.get("approvedBy", "")).strip()) < 3:
        raise DeploymentSafetyError("safe handoff approvedBy is required")
    if len(str(payload.get("reason", "")).strip()) < 12:
        raise DeploymentSafetyError("safe handoff reason is too short")
    try:
        expires = datetime.fromisoformat(str(payload.get("expiresAtUtc", "")).replace("Z", "+00:00"))
        created = datetime.fromisoformat(str(payload.get("createdAtUtc", "")).replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeploymentSafetyError("safe handoff createdAtUtc/expiresAtUtc is invalid") from exc
    if expires.tzinfo is None or expires.astimezone(timezone.utc) <= now.astimezone(timezone.utc):
        raise DeploymentSafetyError("safe handoff has expired")
    if created.tzinfo is None:
        raise DeploymentSafetyError("safe handoff createdAtUtc must include a timezone")
    created_utc = created.astimezone(timezone.utc)
    expires_utc = expires.astimezone(timezone.utc)
    now_utc = now.astimezone(timezone.utc)
    if created_utc > now_utc + timedelta(minutes=1):
        raise DeploymentSafetyError("safe handoff creation time is in the future")
    if now_utc - created_utc > timedelta(minutes=15):
        raise DeploymentSafetyError("safe handoff is older than 15 minutes")
    if expires_utc - created_utc > timedelta(minutes=15):
        raise DeploymentSafetyError("safe handoff validity exceeds 15 minutes")
    if str(payload.get("terminalExecutable", "")).casefold() != broker.terminal_executable.casefold():
        raise DeploymentSafetyError("safe handoff terminalExecutable mismatch")
    if str(payload.get("terminalDataPath", "")).casefold() != broker.terminal_data_path.casefold():
        raise DeploymentSafetyError("safe handoff terminalDataPath mismatch")
    account = payload.get("account")
    if not isinstance(account, Mapping):
        raise DeploymentSafetyError("safe handoff account is required")
    if str(account.get("login", "")) != broker.account_login:
        raise DeploymentSafetyError("safe handoff account login mismatch")
    if str(account.get("server", "")) != broker.account_server:
        raise DeploymentSafetyError("safe handoff account server mismatch")
    if str(account.get("scope", "")).lower() != "demo":
        raise DeploymentSafetyError("safe handoff must be scoped to demo")

    active = list(database.active_executions)
    if any(str(row["status"]) != "FILLED" for row in active):
        raise DeploymentSafetyError(
            "safe handoff permits only reconciled FILLED executions"
        )
    manifest_setup_ids = sorted(str(item) for item in payload.get("activeSetupIds", []))
    database_setup_ids = sorted(str(row["setup_id"]) for row in active)
    if manifest_setup_ids != database_setup_ids:
        raise DeploymentSafetyError("safe handoff activeSetupIds mismatch")

    manifest_positions = payload.get("positions")
    if not isinstance(manifest_positions, list):
        raise DeploymentSafetyError("safe handoff positions must be a list")
    normalized_manifest = sorted(
        (_normalize_handoff_position(item) for item in manifest_positions),
        key=lambda item: (item["identifier"], item["ticket"]),
    )
    normalized_broker = sorted(
        (_normalize_handoff_position(item) for item in broker.positions),
        key=lambda item: (item["identifier"], item["ticket"]),
    )
    if normalized_manifest != normalized_broker:
        raise DeploymentSafetyError("safe handoff broker position set mismatch")
    if any(item["sl"] <= 0 or item["tp"] <= 0 for item in normalized_broker):
        raise DeploymentSafetyError(
            "safe handoff requires every broker position to have both SL and TP"
        )
    active_identifiers = sorted(int(row["position_identifier"] or 0) for row in active)
    broker_identifiers = sorted(item["identifier"] for item in normalized_broker)
    if active_identifiers != broker_identifiers:
        raise DeploymentSafetyError(
            "safe handoff database executions do not match broker positions"
        )
    broker_by_identifier = {item["identifier"]: item for item in normalized_broker}
    if len(broker_by_identifier) != len(normalized_broker):
        raise DeploymentSafetyError("safe handoff broker position identifiers are not unique")
    for execution in active:
        identifier = int(execution.get("position_identifier") or 0)
        position = broker_by_identifier[identifier]
        expected_comment = f"GMS: {str(execution.get('client_tag') or '')}"
        exact_fields = {
            "execution_mode": (str(execution.get("execution_mode") or ""), "demo"),
            "account_login": (
                str(execution.get("account_login") or ""),
                broker.account_login,
            ),
            "account_server": (
                str(execution.get("account_server") or ""),
                broker.account_server,
            ),
            "account_scope": (
                str(execution.get("account_scope") or "").lower(),
                "demo",
            ),
            "account_margin_mode": (
                str(execution.get("account_margin_mode") or "").upper(),
                "HEDGING",
            ),
            "symbol": (str(execution.get("symbol") or ""), position["symbol"]),
            "side": (str(execution.get("side") or "").upper(), position["side"]),
            "position_ticket": (
                int(execution.get("position_ticket") or 0),
                position["ticket"],
            ),
            "magic": (int(execution.get("magic") or 0), position["magic"]),
            "client_tag": (expected_comment, position["comment"]),
        }
        mismatched = [
            name for name, (observed, expected) in exact_fields.items()
            if observed != expected
        ]
        if mismatched:
            raise DeploymentSafetyError(
                "safe handoff execution/position binding mismatch: "
                + ", ".join(mismatched)
            )
        numeric_fields = {
            "remaining_volume": (
                execution.get("remaining_volume"),
                position["volume"],
            ),
            "current_stop_price": (
                execution.get("current_stop_price"),
                position["sl"],
            ),
            "current_take_profit_price": (
                execution.get("current_take_profit_price"),
                position["tp"],
            ),
        }
        for name, (observed, expected) in numeric_fields.items():
            try:
                matches = observed is not None and math.isclose(
                    float(observed), float(expected), rel_tol=1e-12, abs_tol=1e-9
                )
            except (TypeError, ValueError):
                matches = False
            if not matches:
                raise DeploymentSafetyError(
                    f"safe handoff execution/position binding mismatch: {name}"
                )


def _normalize_handoff_position(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise DeploymentSafetyError("safe handoff position must be an object")
    try:
        normalized = {
            "ticket": int(raw["ticket"]),
            "identifier": int(raw["identifier"]),
            "symbol": str(raw["symbol"]),
            "side": str(raw["side"]).upper(),
            "volume": float(raw["volume"]),
            "sl": float(raw["sl"]),
            "tp": float(raw["tp"]),
            "magic": int(raw["magic"]),
            "comment": str(raw["comment"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise DeploymentSafetyError("safe handoff position is incomplete") from exc
    if normalized["ticket"] <= 0 or normalized["identifier"] <= 0:
        raise DeploymentSafetyError("safe handoff position identifiers must be positive")
    if normalized["side"] not in {"BUY", "SELL"} or normalized["volume"] <= 0:
        raise DeploymentSafetyError("safe handoff position side/volume is invalid")
    return normalized


def _strip_unquoted_comment(line: str) -> str:
    quote = ""
    for index, character in enumerate(line):
        if character in {'"', "'"}:
            if not quote:
                quote = character
            elif quote == character:
                quote = ""
        elif character == "#" and not quote:
            return line[:index]
    if quote:
        raise DeploymentSafetyError("unterminated quote in environment file")
    return line


def _file_identity(path: Path) -> str:
    stat_result = path.stat()
    return (
        f"{getattr(stat_result, 'st_dev', 0)}:"
        f"{getattr(stat_result, 'st_ino', 0)}:"
        f"{getattr(stat_result, 'st_birthtime_ns', 0)}"
    )


def _log_file_chronology(path: Path) -> int:
    date_match = re.search(r"(?<!\d)(20\d{6})(?!\d)", path.stem)
    if date_match:
        try:
            log_date = datetime.strptime(date_match.group(1), "%Y%m%d").replace(
                tzinfo=timezone.utc
            )
            return int(log_date.timestamp() * 1_000_000_000)
        except ValueError:
            pass
    return path.stat().st_mtime_ns


def _decode_mt5_log_bytes(raw: bytes, *, offset: int) -> str:
    # MetaTrader commonly writes UTF-16LE, while fixtures and some Wine builds
    # use UTF-8.  A non-zero UTF-16 offset no longer carries a BOM.
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    sample = raw[: min(len(raw), 256)]
    odd_nuls = sum(sample[index] == 0 for index in range(1, len(sample), 2))
    even_nuls = sum(sample[index] == 0 for index in range(0, len(sample), 2))
    pairs = max(1, len(sample) // 2)
    if odd_nuls > pairs // 3 and even_nuls < pairs // 8:
        if offset % 2:
            raise DeploymentSafetyError("UTF-16 MT5 log cursor is not code-unit aligned")
        return raw.decode("utf-16-le")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DeploymentSafetyError("fresh MT5 log bytes have an unknown encoding") from exc


def _ea_config_matches_expected_binding(
    fields: Mapping[str, str],
    *,
    production_inputs: Mapping[str, str],
    session_id: str,
    expected_account_login: str,
    expected_account_server: str,
    expected_account_scope: str,
) -> bool:
    contract = load_production_ea_input_contract()
    expected_inputs = contract["inputs"]
    if dict(production_inputs) != expected_inputs:
        return False
    login = str(expected_account_login).strip()
    server = str(expected_account_server).strip()
    scope = str(expected_account_scope).strip().lower()
    if not login.isdigit() or int(login) <= 0:
        raise DeploymentSafetyError("expected CONFIG account login must be positive")
    if not server or server != expected_account_server:
        raise DeploymentSafetyError("expected CONFIG account server is invalid")
    if scope != "demo":
        raise DeploymentSafetyError(
            "deployment CONFIG evidence is restricted to the demo account scope"
        )
    encoded_server = str(fields.get("originServerB64", ""))
    if re.fullmatch(r"[A-Za-z0-9_-]+", encoded_server) is None or len(encoded_server) % 4 == 1:
        decoded_server = None
    else:
        padded = encoded_server + "=" * ((4 - len(encoded_server) % 4) % 4)
        try:
            raw_server = base64.b64decode(padded, altchars=b"-_", validate=True)
            decoded_server = raw_server.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            decoded_server = None
        if decoded_server is not None:
            canonical = (
                base64.urlsafe_b64encode(decoded_server.encode("utf-8"))
                .decode("ascii")
                .rstrip("=")
            )
            if canonical != encoded_server:
                decoded_server = None
    return bool(
        fields.get("runId") == session_id
        and fields.get("symbol") == CANONICAL_GOLD_SYMBOL
        and fields.get("strategy") == "GOLDM_SNIPER_PARITY"
        and fields.get("strategyVersion") == "1.72"
        and fields.get("productionContractVersion") == "1"
        and fields.get("productionContractSha256") == contract["sha256"]
        and fields.get("directionProfile") == "ALL"
        and fields.get("strategyMode") == expected_inputs["InpStrategyMode"]
        and fields.get("signalOnly", "").lower() == "true"
        and fields.get("accountScope") == scope
        and fields.get("accountLogin") == login
        and decoded_server is not None
        and decoded_server == server
    )


def _production_inputs_for_config(
    lines: Sequence[str],
    *,
    line_index: int,
    config_fields: Mapping[str, str],
) -> dict[str, str]:
    """Parse the two input records immediately preceding one CONFIG record.

    The adjacency requirement prevents a stale or interleaved input dump from
    being paired with a later EA initialization.  Each part is strict: only
    metadata and declared ``Inp*`` fields are accepted, and the combined map
    must reproduce the release-sealed canonical contract digest.
    """

    contract = load_production_ea_input_contract()
    expected_digest = contract["sha256"]
    if (
        config_fields.get("productionContractVersion") != "1"
        or config_fields.get("productionContractSha256") != expected_digest
    ):
        raise DeploymentSafetyError(
            "SNIPER_CONFIG production contract identity is missing or mismatched"
        )
    if line_index < 2:
        raise DeploymentSafetyError(
            "SNIPER_CONFIG is not preceded by its complete production input evidence"
        )

    combined: dict[str, str] = {}
    for expected_part, line in enumerate(lines[line_index - 2 : line_index], start=1):
        marker_count = line.count(PRODUCTION_INPUTS_MARKER)
        if marker_count != 1:
            raise DeploymentSafetyError(
                "SNIPER_CONFIG production input evidence is missing or ambiguous"
            )
        payload = line.split(PRODUCTION_INPUTS_MARKER, 1)[1].strip()
        fields = _parse_log_fields(payload)
        metadata = {
            "schema": fields.pop("schema", None),
            "part": fields.pop("part", None),
            "contractSha256": fields.pop("contractSha256", None),
        }
        if metadata != {
            "schema": "1",
            "part": f"{expected_part}/2",
            "contractSha256": expected_digest,
        }:
            raise DeploymentSafetyError(
                "SNIPER_CONFIG production input part metadata is invalid"
            )
        if not fields or any(
            re.fullmatch(r"Inp[A-Za-z0-9]+", key) is None for key in fields
        ):
            raise DeploymentSafetyError(
                "SNIPER_CONFIG production input part contains an undeclared field"
            )
        duplicates = set(combined).intersection(fields)
        if duplicates:
            raise DeploymentSafetyError(
                "SNIPER_CONFIG production inputs contain a duplicate field"
            )
        combined.update(fields)

    expected_inputs = contract["inputs"]
    if set(combined) != set(expected_inputs):
        raise DeploymentSafetyError(
            "SNIPER_CONFIG production inputs are missing or contain extra fields"
        )
    reconstructed = {
        "schemaVersion": 1,
        "strategy": "GOLDM_SNIPER_PARITY",
        "strategyVersion": "1.72",
        "inputs": combined,
    }
    canonical = json.dumps(
        reconstructed, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    actual_digest = hashlib.sha256(canonical).hexdigest()
    if actual_digest != expected_digest or combined != expected_inputs:
        raise DeploymentSafetyError(
            "SNIPER_CONFIG production input values do not match the sealed contract"
        )
    return combined


def _parse_log_fields(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in line.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key in fields:
            raise DeploymentSafetyError(
                f"fresh {CONFIG_MARKER} contains duplicate field {key}"
            )
        fields[key] = value
    return fields


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _canonical_file(path: Path, label: str) -> Path:
    _reject_reparse_components(path, label)
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise DeploymentSafetyError(f"{label} does not exist: {path}") from exc
    if not resolved.is_file():
        raise DeploymentSafetyError(f"{label} is not a file: {resolved}")
    return resolved


def _canonical_directory(path: Path, label: str) -> Path:
    _reject_reparse_components(path, label)
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise DeploymentSafetyError(f"{label} does not exist: {path}") from exc
    if not resolved.is_dir():
        raise DeploymentSafetyError(f"{label} is not a directory: {resolved}")
    return resolved


def _runtime_session_path(
    terminal_data_path: Path,
    *,
    create_files_directory: bool,
) -> Path:
    data_path = _canonical_directory(terminal_data_path, "terminal data path")
    mql5_directory = _canonical_directory(data_path / "MQL5", "terminal MQL5 directory")
    try:
        mql5_directory.relative_to(data_path)
    except ValueError as exc:
        raise DeploymentSafetyError("terminal MQL5 directory escapes data path") from exc
    files_input = mql5_directory / "Files"
    _reject_reparse_components(files_input, "terminal MQL5 Files directory")
    if create_files_directory:
        files_input.mkdir(parents=False, exist_ok=True)
    files_directory = _canonical_directory(files_input, "terminal MQL5 Files directory")
    try:
        files_directory.relative_to(data_path)
    except ValueError as exc:
        raise DeploymentSafetyError("terminal MQL5 Files directory escapes data path") from exc
    return files_directory / RUNTIME_SESSION_FILENAME


def _reject_reparse_components(path: Path, label: str) -> None:
    """Reject symlink/junction traversal before resolving or mutating a path."""

    candidate = path.expanduser().absolute()
    while True:
        try:
            is_junction = bool(
                getattr(candidate, "is_junction", lambda: False)()
            )
            if candidate.is_symlink() or is_junction:
                raise DeploymentSafetyError(
                    f"{label} cannot traverse a symbolic link or junction: {candidate}"
                )
        except OSError as exc:
            raise DeploymentSafetyError(
                f"{label} reparse-point status cannot be inspected: {candidate}"
            ) from exc
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(str(first.resolve(strict=True))) == os.path.normcase(
        str(second.resolve(strict=True))
    )


def _path_is_within(path: Path, parent: Path) -> bool:
    resolved_path = path.resolve(strict=True)
    resolved_parent = parent.resolve(strict=True)
    try:
        resolved_path.relative_to(resolved_parent)
    except ValueError:
        return False
    return True


def _terminal_executable_from_status(path_value: str) -> Path:
    observed = Path(path_value).expanduser().resolve(strict=True)
    if observed.is_dir():
        observed = (observed / "terminal64.exe").resolve(strict=True)
    if not observed.is_file():
        raise DeploymentSafetyError(
            "observed MT5 terminal path is not an executable file or installation directory"
        )
    return observed


def _load_exact_deployment_account_scope(adapter: Any) -> str:
    loader = getattr(adapter, "load_exact_account_scope", None)
    if not callable(loader):
        raise DeploymentSafetyError(
            "deployment adapter cannot prove the exact MT5 account trade mode"
        )
    scope = str(loader() or "").strip().lower()
    if scope not in {"demo", "live", "contest", "unknown"}:
        return "unknown"
    return scope


def _connect_read_only(path: Path) -> sqlite3.Connection:
    uri = path.resolve(strict=True).as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10.0)
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA query_only=ON")
    return connection


def _validated_sha256(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
        raise DeploymentSafetyError("expected SHA-256 must contain 64 hexadecimal characters")
    return normalized


def _json_default(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed GOLDM deployment, backup, and rollback helper."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--env-file", type=Path, required=True)
    preflight.add_argument("--database", type=Path, required=True)
    preflight.add_argument("--terminal-executable", type=Path, required=True)
    preflight.add_argument("--terminal-data-path", type=Path, required=True)
    preflight.add_argument("--release-commit", required=True)
    preflight.add_argument("--safe-handoff", type=Path)
    preflight.add_argument("--safe-handoff-sha256")
    preflight.add_argument("--skip-existing-session-evidence", action="store_true")

    handoff = subparsers.add_parser("create-handoff")
    handoff.add_argument("--env-file", type=Path, required=True)
    handoff.add_argument("--database", type=Path, required=True)
    handoff.add_argument("--terminal-executable", type=Path, required=True)
    handoff.add_argument("--terminal-data-path", type=Path, required=True)
    handoff.add_argument("--release-commit", required=True)
    handoff.add_argument("--approved-by", required=True)
    handoff.add_argument("--reason", required=True)
    handoff.add_argument("--output", type=Path, required=True)
    handoff.add_argument("--acknowledgement", required=True)
    handoff.add_argument("--validity-minutes", type=int, default=10)

    validate_env = subparsers.add_parser("validate-env")
    validate_env.add_argument("--env-file", type=Path, required=True)
    validate_env.add_argument("--terminal-executable", type=Path, required=True)
    validate_env.add_argument("--terminal-data-path", type=Path, required=True)

    write_session = subparsers.add_parser("write-runtime-session")
    write_session.add_argument("--env-file", type=Path, required=True)
    write_session.add_argument("--terminal-data-path", type=Path, required=True)

    verify_session_file = subparsers.add_parser("verify-runtime-session")
    verify_session_file.add_argument("--env-file", type=Path, required=True)
    verify_session_file.add_argument("--terminal-data-path", type=Path, required=True)

    backup = subparsers.add_parser("backup-db")
    backup.add_argument("--source", type=Path, required=True)
    backup.add_argument("--destination", type=Path, required=True)

    inspect = subparsers.add_parser("inspect-db")
    inspect.add_argument("--database", type=Path, required=True)
    inspect.add_argument("--require-quiescent", action="store_true")

    verify = subparsers.add_parser("verify-db")
    verify.add_argument("--database", type=Path, required=True)
    verify.add_argument("--expected-sha256", required=True)

    restore = subparsers.add_parser("restore-db")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    restore.add_argument("--expected-sha256", required=True)
    restore.add_argument("--acknowledgement", required=True)

    seal = subparsers.add_parser("seal-json")
    seal.add_argument("--input", type=Path, required=True)
    seal.add_argument("--output", type=Path, required=True)

    verify_seal = subparsers.add_parser("verify-seal")
    verify_seal.add_argument("--evidence", type=Path, required=True)

    cursor = subparsers.add_parser("capture-log-cursor")
    cursor.add_argument("--log-directory", type=Path, required=True)
    cursor.add_argument("--output", type=Path, required=True)

    evidence = subparsers.add_parser("session-evidence")
    evidence.add_argument("--log-directory", type=Path, required=True)
    evidence.add_argument("--cursor", type=Path, required=True)
    evidence.add_argument("--env-file", type=Path, required=True)

    latest_evidence = subparsers.add_parser("latest-session-evidence")
    latest_evidence.add_argument("--log-directory", type=Path, required=True)
    latest_evidence.add_argument("--env-file", type=Path, required=True)

    tree = subparsers.add_parser("build-tree-manifest")
    tree.add_argument("--root", type=Path, required=True)
    tree.add_argument("--output", type=Path, required=True)

    verify_tree = subparsers.add_parser("verify-tree-manifest")
    verify_tree.add_argument("--root", type=Path, required=True)
    verify_tree.add_argument("--manifest", type=Path, required=True)
    verify_tree.add_argument("--expected-manifest-sha256", required=True)

    wheelhouse = subparsers.add_parser("verify-offline-wheelhouse")
    wheelhouse.add_argument("--root", type=Path, required=True)
    wheelhouse.add_argument("--expected-manifest-sha256", required=True)

    subparsers.add_parser("production-input-contract")

    readiness = subparsers.add_parser("telegram-readiness")
    readiness.add_argument("--database", type=Path, required=True)
    readiness.add_argument("--env-file", type=Path, required=True)
    readiness.add_argument("--expected-release-id", required=True)
    readiness.add_argument("--expected-deployment-nonce-sha256", required=True)
    readiness.add_argument("--expected-release-manifest-sha256", required=True)
    readiness.add_argument("--expected-runtime-config-sha256", required=True)
    readiness.add_argument("--expected-production-config-sha256", required=True)
    readiness.add_argument("--not-before-utc", required=True)
    readiness.add_argument("--max-age-seconds", type=float, default=90.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "preflight":
            values = parse_env_file(args.env_file)
            database = inspect_database(args.database)
            broker = collect_broker_snapshot(
                values,
                terminal_executable=args.terminal_executable,
                terminal_data_path=args.terminal_data_path,
            )
            handoff = assert_cutover_safe(
                database,
                broker,
                release_commit=args.release_commit,
                safe_handoff_path=args.safe_handoff,
                safe_handoff_sha256=args.safe_handoff_sha256,
            )
            session_evidence = None
            runtime_session_file = None
            if not args.skip_existing_session_evidence:
                runtime_session_file = verify_runtime_session_file(
                    args.env_file, Path(broker.terminal_data_path)
                )
                session_evidence = find_latest_ea_session_evidence(
                    Path(broker.terminal_data_path) / "MQL5" / "Logs",
                    session_id=str(values["GOLDM_EA_SESSION_ID"]).strip(),
                    expected_account_login=str(values["MT5_LOGIN"]).strip(),
                    expected_account_server=str(values["MT5_SERVER"]).strip(),
                )
            result: Any = {
                "status": "SAFE",
                "database": database,
                "broker": broker,
                "handoff": handoff,
                "session_evidence": session_evidence,
                "runtime_session_file": runtime_session_file,
            }
        elif args.command == "create-handoff":
            values = parse_env_file(args.env_file)
            database = inspect_database(args.database)
            broker = collect_broker_snapshot(
                values,
                terminal_executable=args.terminal_executable,
                terminal_data_path=args.terminal_data_path,
            )
            verify_runtime_session_file(args.env_file, Path(broker.terminal_data_path))
            find_latest_ea_session_evidence(
                Path(broker.terminal_data_path) / "MQL5" / "Logs",
                session_id=str(values["GOLDM_EA_SESSION_ID"]).strip(),
                expected_account_login=str(values["MT5_LOGIN"]).strip(),
                expected_account_server=str(values["MT5_SERVER"]).strip(),
            )
            result = create_safe_handoff_manifest(
                database,
                broker,
                release_commit=args.release_commit,
                approved_by=args.approved_by,
                reason=args.reason,
                output_path=args.output,
                acknowledgement=args.acknowledgement,
                validity_minutes=args.validity_minutes,
            )
        elif args.command == "validate-env":
            result = validate_runtime_environment(
                parse_env_file(args.env_file),
                terminal_executable=args.terminal_executable,
                terminal_data_path=args.terminal_data_path,
            )
        elif args.command == "write-runtime-session":
            result = write_runtime_session_file(
                args.env_file, args.terminal_data_path
            )
        elif args.command == "verify-runtime-session":
            result = verify_runtime_session_file(
                args.env_file, args.terminal_data_path
            )
        elif args.command == "backup-db":
            result = backup_database(args.source, args.destination)
        elif args.command == "inspect-db":
            result = inspect_database(args.database)
            if args.require_quiescent and (
                result.active_executions
                or result.unresolved_actions
                or result.runtime_execution_mode not in {"", "off"}
            ):
                raise DeploymentSafetyError(
                    "database is not quiescent/OFF; runtime mode, active executions, "
                    "or unresolved actions block recovery"
                )
        elif args.command == "verify-db":
            result = verify_database_backup(
                args.database, expected_sha256=args.expected_sha256
            )
        elif args.command == "restore-db":
            result = restore_database(
                args.backup,
                args.destination,
                expected_sha256=args.expected_sha256,
                acknowledgement=args.acknowledgement,
            )
        elif args.command == "seal-json":
            result = seal_json(args.input, args.output)
        elif args.command == "verify-seal":
            result = verify_sealed_json(args.evidence)
        elif args.command == "capture-log-cursor":
            result = capture_log_cursor(args.log_directory, args.output)
        elif args.command == "session-evidence":
            values = parse_env_file(args.env_file)
            result = find_fresh_ea_session_evidence(
                args.log_directory,
                args.cursor,
                session_id=str(values.get("GOLDM_EA_SESSION_ID", "")).strip(),
                expected_account_login=str(values.get("MT5_LOGIN", "")).strip(),
                expected_account_server=str(values.get("MT5_SERVER", "")).strip(),
            )
        elif args.command == "latest-session-evidence":
            values = parse_env_file(args.env_file)
            result = find_latest_ea_session_evidence(
                args.log_directory,
                session_id=str(values.get("GOLDM_EA_SESSION_ID", "")).strip(),
                expected_account_login=str(values.get("MT5_LOGIN", "")).strip(),
                expected_account_server=str(values.get("MT5_SERVER", "")).strip(),
            )
        elif args.command == "build-tree-manifest":
            result = build_tree_manifest(args.root, args.output)
        elif args.command == "verify-tree-manifest":
            result = verify_tree_manifest(
                args.root,
                args.manifest,
                expected_manifest_sha256=args.expected_manifest_sha256,
            )
        elif args.command == "verify-offline-wheelhouse":
            result = verify_offline_wheelhouse(
                args.root,
                expected_manifest_sha256=args.expected_manifest_sha256,
            )
        elif args.command == "production-input-contract":
            contract = load_production_ea_input_contract()
            result = {
                "schema_version": 1,
                "sha256": contract["sha256"],
                "input_count": len(contract["inputs"]),
            }
        elif args.command == "telegram-readiness":
            result = inspect_telegram_poll_readiness(
                args.database,
                args.env_file,
                expected_release_id=args.expected_release_id,
                expected_deployment_nonce_sha256=(
                    args.expected_deployment_nonce_sha256
                ),
                expected_release_manifest_sha256=(
                    args.expected_release_manifest_sha256
                ),
                expected_runtime_config_sha256=args.expected_runtime_config_sha256,
                expected_production_config_sha256=(
                    args.expected_production_config_sha256
                ),
                not_before_utc=args.not_before_utc,
                max_age_seconds=args.max_age_seconds,
            )
        else:  # pragma: no cover - argparse owns this invariant.
            raise AssertionError(args.command)
    except (DeploymentSafetyError, OSError, sqlite3.Error, ValueError) as exc:
        print(f"DEPLOYMENT_SAFETY_ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, default=_json_default, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
