from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import OrchestratorConfig
from .locking import SingleInstanceLock
from .runtime import GlobalOrchestrator

ADMIN_STATE_KEY = "admin_private_chat_ids"


def _admin_chat_ids(raw: str) -> tuple[str, ...]:
    values: set[str] = set()
    for item in raw.replace(";", ",").split(","):
        candidate = item.strip()
        if not candidate or not candidate.isascii() or not candidate.isdecimal():
            continue
        normalized = int(candidate)
        if normalized > 0:
            values.add(str(normalized))
    return tuple(sorted(values, key=int))


def _read_state(state_path: Path) -> dict[str, object]:
    if not state_path.exists():
        return {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Telegram subscriber state is invalid: {state_path}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Telegram subscriber state must contain a JSON object: {state_path}")
    return payload


def _state_admin_chat_ids(state_path: Path) -> tuple[str, ...]:
    payload = _read_state(state_path)
    raw_values = payload.get(ADMIN_STATE_KEY, [])
    if not isinstance(raw_values, list):
        raise SystemExit(f"{ADMIN_STATE_KEY} must be a JSON array")
    normalized: list[str] = []
    for value in raw_values:
        candidate = str(value).strip()
        if not candidate.isascii() or not candidate.isdecimal() or int(candidate) <= 0:
            raise SystemExit(f"{ADMIN_STATE_KEY} contains an invalid private chat ID")
        normalized.append(candidate)
    return _admin_chat_ids(",".join(normalized))


def _resolve_admin_chat_ids(raw: str, state_path: Path) -> tuple[tuple[str, ...], str]:
    configured = _admin_chat_ids(raw)
    if configured:
        return configured, "CONFIG"
    persisted = _state_admin_chat_ids(state_path)
    if persisted:
        return persisted, "STATE_FALLBACK"
    return (), "NONE"


def _persist_admin_chat_ids(state_path: Path, admins: tuple[str, ...]) -> None:
    payload = _read_state(state_path)
    normalized = list(admins)
    if payload.get(ADMIN_STATE_KEY) == normalized:
        return
    payload[ADMIN_STATE_KEY] = normalized
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_name(f".{state_path.name}.admin.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, state_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the G20 Telegram approval-only control poller."
    )
    parser.add_argument("--state-path", required=True, type=Path)
    parser.add_argument("--audit-path", required=True, type=Path)
    parser.add_argument("--poll-timeout", type=int, default=20)
    parser.add_argument("--heartbeat-seconds", type=int, default=3600)
    parser.add_argument("--entry-gate-root", type=Path)
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state_path = args.state_path.resolve()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    admins, admin_source = _resolve_admin_chat_ids(
        os.environ.get("TELEGRAM_ADMIN_CHAT_IDS", ""),
        state_path,
    )
    expected_bot = os.environ.get("TELEGRAM_EXPECTED_BOT_USERNAME", "").strip().lstrip("@")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    if not admins:
        raise SystemExit(
            "TELEGRAM_ADMIN_CHAT_IDS requires a positive private chat ID; "
            "no trusted state fallback is available"
        )
    if not expected_bot:
        raise SystemExit("TELEGRAM_EXPECTED_BOT_USERNAME is required")
    if args.poll_timeout < 0:
        raise SystemExit("--poll-timeout must be non-negative")
    if args.heartbeat_seconds <= 0:
        raise SystemExit("--heartbeat-seconds must be positive")

    config = OrchestratorConfig(
        orchestrator_id="G20_TELEGRAM_APPROVAL",
        python_executable=Path(sys.executable),
        poll_timeout_seconds=args.poll_timeout,
        supervision_interval_seconds=5.0,
        heartbeat_seconds=args.heartbeat_seconds,
        restart_delay_seconds=15.0,
        health_stale_seconds=120,
        shutdown_grace_seconds=15.0,
        state_path=state_path,
        audit_path=args.audit_path.resolve(),
        bot_token=token,
        admin_chat_ids=admins,
        workers={},
        expected_bot_username=expected_bot,
        worker_control_enabled=False,
        entry_gate_root=(args.entry_gate_root.resolve() if args.entry_gate_root else None),
    )
    if args.check:
        runtime = GlobalOrchestrator(config)
        runtime._validate_bot_identity()
        print(
            "G20_TELEGRAM_APPROVAL config OK: "
            f"admins={len(admins)} admin_source={admin_source} order_authority=NONE"
        )
        return 0
    lock_path = config.state_path.with_name("telegram-control.lock")
    with SingleInstanceLock(lock_path):
        _persist_admin_chat_ids(config.state_path, admins)
        runtime = GlobalOrchestrator(config)
        runtime.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
