from __future__ import annotations

import json
import os
from hashlib import sha256
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"config must be a JSON object: {path}")
    return payload


def _repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _environment(name: str, *, required: bool = False) -> str:
    value = os.environ.get(name, "").strip()
    if required and not value:
        raise ValueError(f"required environment variable is missing: {name}")
    return value


@dataclass(frozen=True, slots=True)
class TerminalBinding:
    path: str
    expected_login: int
    expected_server: str
    expected_trade_mode: str
    require_account_binding: bool


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    bot_token: str
    chat_ids: tuple[str, ...]
    send_health: bool


@dataclass(frozen=True, slots=True)
class PortfolioWorkerConfig:
    group: str
    portfolio_id: str
    symbol: str
    execution_mode: str
    revised: Mapping[str, Any]
    bear: Mapping[str, Any]
    terminal: TerminalBinding
    balance_tiers: tuple[tuple[float, float], ...]
    magic: int
    deviation_points: int
    maximum_positions: int
    maximum_total_lot: float
    orders_enabled: bool
    poll_seconds: float
    server_utc_offset_minutes: int
    state_path: Path
    audit_path: Path
    telegram: TelegramConfig

    @property
    def real_execution(self) -> bool:
        return self.execution_mode == "real" and self.orders_enabled


def load_worker_config(path: str | Path) -> PortfolioWorkerConfig:
    worker_path = _repo_path(path)
    worker = _read_json(worker_path)
    for pinned_path, expected_hash in dict(worker.get("pinned_files") or {}).items():
        resolved = _repo_path(str(pinned_path))
        content = resolved.read_bytes()
        actual_hash = sha256(content).hexdigest()
        canonical_hash = sha256(content.replace(b"\r\n", b"\n")).hexdigest()
        expected = str(expected_hash).lower()
        if expected not in {actual_hash, canonical_hash}:
            raise ValueError(
                f"pinned config hash mismatch: {pinned_path} "
                f"expected={expected_hash} actual={actual_hash} "
                f"canonical={canonical_hash}"
            )
    portfolio = _read_json(_repo_path(str(worker["portfolio_config"])))
    revised = _read_json(_repo_path(str(portfolio["revised_config"])))
    bear = _read_json(_repo_path(str(portfolio["bear_config"])))
    terminal_values = dict(portfolio.get("terminal") or {})
    terminal_path = str(terminal_values.get("path") or "").strip()
    if not terminal_path and terminal_values.get("path_env"):
        terminal_path = _environment(str(terminal_values["path_env"]), required=False)
    login = int(terminal_values.get("expected_login") or 0)
    if not login and terminal_values.get("expected_login_env"):
        raw_login = _environment(str(terminal_values["expected_login_env"]), required=False)
        login = int(raw_login) if raw_login else 0
    server = str(terminal_values.get("expected_server") or "").strip()
    if not server and terminal_values.get("expected_server_env"):
        server = _environment(str(terminal_values["expected_server_env"]), required=False)
    telegram_values = dict(worker.get("telegram") or {})
    token = _environment(str(telegram_values.get("bot_token_env") or "TELEGRAM_BOT_TOKEN"))
    chat_value = _environment(str(telegram_values.get("chat_ids_env") or "TELEGRAM_ADMIN_CHAT_IDS"))
    if not chat_value:
        chat_value = _environment(str(telegram_values.get("fallback_chat_id_env") or "TELEGRAM_CHAT_ID"))
    chat_ids = tuple(
        item.strip()
        for item in chat_value.replace(";", ",").split(",")
        if item.strip()
    )
    tiers = tuple(
        sorted(
            (
                float(item["minimum_balance"]),
                float(item["lot"]),
            )
            for item in (portfolio.get("sizing") or {}).get("balance_tiers", [])
        )
    )
    mode = str(portfolio.get("execution_mode") or "signal_only").lower()
    if mode not in {"signal_only", "real"}:
        raise ValueError(f"unsupported execution mode: {mode}")
    if mode == "real" and (not terminal_path or not login or not server):
        raise ValueError("real execution requires terminal path, login, and server binding")
    if bool(terminal_values.get("require_account_binding", False)) and (
        not terminal_path or not login or not server
    ):
        raise ValueError("required terminal binding is incomplete")
    if mode == "real" and (not tiers or tiers[0][0] != 0.0):
        raise ValueError("real execution requires balance tiers beginning at zero")
    return PortfolioWorkerConfig(
        group=str(worker["group"]),
        portfolio_id=str(portfolio["portfolio_id"]),
        symbol=str(portfolio["symbol"]),
        execution_mode=mode,
        revised=revised,
        bear=bear,
        terminal=TerminalBinding(
            path=terminal_path,
            expected_login=login,
            expected_server=server,
            expected_trade_mode=str(terminal_values.get("expected_trade_mode") or "").lower(),
            require_account_binding=bool(terminal_values.get("require_account_binding", False)),
        ),
        balance_tiers=tiers,
        magic=int(portfolio.get("magic") or 0),
        deviation_points=int(portfolio.get("deviation_points") or 20),
        maximum_positions=int(portfolio.get("maximum_positions") or 0),
        maximum_total_lot=float(portfolio.get("maximum_total_lot") or 0.0),
        orders_enabled=bool(portfolio.get("orders_enabled", False)),
        poll_seconds=float(worker.get("poll_seconds") or 15.0),
        server_utc_offset_minutes=int(worker.get("server_utc_offset_minutes") or 180),
        state_path=_repo_path(str(worker["state_path"])),
        audit_path=_repo_path(str(worker["audit_path"])),
        telegram=TelegramConfig(
            bot_token=token,
            chat_ids=chat_ids,
            send_health=bool(telegram_values.get("send_health", True)),
        ),
    )
