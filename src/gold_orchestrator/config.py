from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[2]


def load_local_env(root: Path = ROOT) -> None:
    env_path = root / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    name: str
    config_path: Path
    enabled_on_first_boot: bool
    health_path: Path
    log_path: Path


@dataclass(frozen=True, slots=True)
class OrchestratorConfig:
    orchestrator_id: str
    python_executable: Path
    poll_timeout_seconds: int
    supervision_interval_seconds: float
    heartbeat_seconds: int
    restart_delay_seconds: float
    health_stale_seconds: int
    shutdown_grace_seconds: float
    state_path: Path
    audit_path: Path
    bot_token: str
    admin_chat_ids: tuple[str, ...]
    workers: Mapping[str, WorkerSpec]


def load_orchestrator_config(path: str | Path) -> OrchestratorConfig:
    load_local_env()
    config_path = _repo_path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("orchestrator config must be a JSON object")
    token_env = str(payload.get("bot_token_env") or "TELEGRAM_BOT_TOKEN")
    admin_env = str(payload.get("admin_chat_ids_env") or "TELEGRAM_ADMIN_CHAT_IDS")
    fallback_env = str(payload.get("fallback_chat_id_env") or "TELEGRAM_CHAT_ID")
    bot_token = os.environ.get(token_env, "").strip()
    raw_admins = os.environ.get(admin_env, "").strip()
    if not raw_admins:
        raw_admins = os.environ.get(fallback_env, "").strip()
    admin_chat_ids = tuple(
        sorted(
            {
                str(int(item.strip()))
                for item in raw_admins.replace(";", ",").split(",")
                if item.strip()
                and item.strip().isascii()
                and item.strip().isdecimal()
                and int(item.strip()) > 0
            },
            key=int,
        )
    )
    if not bot_token:
        raise ValueError(f"required environment variable is missing: {token_env}")
    if not admin_chat_ids:
        raise ValueError("at least one Telegram administrator chat ID is required")
    workers: dict[str, WorkerSpec] = {}
    for name, raw in dict(payload.get("workers") or {}).items():
        values = dict(raw or {})
        worker_name = str(name).strip().lower()
        if worker_name not in {"goldi", "goldm"}:
            raise ValueError(f"unsupported worker: {name}")
        workers[worker_name] = WorkerSpec(
            name=worker_name,
            config_path=_repo_path(str(values["config_path"])),
            enabled_on_first_boot=bool(values.get("enabled_on_first_boot", False)),
            health_path=_repo_path(str(values["health_path"])),
            log_path=_repo_path(str(values["log_path"])),
        )
    if set(workers) != {"goldi", "goldm"}:
        raise ValueError("orchestrator requires exactly goldi and goldm workers")
    from gold_portfolio.config import load_worker_config

    terminal_paths = {
        name: load_worker_config(spec.config_path).terminal.path
        for name, spec in workers.items()
    }
    if terminal_paths["goldi"].casefold() == terminal_paths["goldm"].casefold():
        raise ValueError("GOLD.i and GOLDm workers must use different MT5 paths")
    executable = Path(str(payload.get("python_executable") or sys.executable))
    return OrchestratorConfig(
        orchestrator_id=str(payload.get("orchestrator_id") or "GOLD_GLOBAL_ORCHESTRATOR"),
        python_executable=executable,
        poll_timeout_seconds=int(payload.get("poll_timeout_seconds") or 20),
        supervision_interval_seconds=float(
            payload.get("supervision_interval_seconds") or 5.0
        ),
        heartbeat_seconds=int(payload.get("heartbeat_seconds") or 3600),
        restart_delay_seconds=float(payload.get("restart_delay_seconds") or 15.0),
        health_stale_seconds=int(payload.get("health_stale_seconds") or 120),
        shutdown_grace_seconds=float(payload.get("shutdown_grace_seconds") or 15.0),
        state_path=_repo_path(str(payload["state_path"])),
        audit_path=_repo_path(str(payload["audit_path"])),
        bot_token=bot_token,
        admin_chat_ids=admin_chat_ids,
        workers=workers,
    )
