from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import OrchestratorConfig
from .locking import SingleInstanceLock
from .runtime import GlobalOrchestrator


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the G20 Telegram approval-only control poller."
    )
    parser.add_argument("--state-path", required=True, type=Path)
    parser.add_argument("--audit-path", required=True, type=Path)
    parser.add_argument("--poll-timeout", type=int, default=20)
    parser.add_argument("--heartbeat-seconds", type=int, default=3600)
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    admins = _admin_chat_ids(os.environ.get("TELEGRAM_ADMIN_CHAT_IDS", ""))
    expected_bot = os.environ.get("TELEGRAM_EXPECTED_BOT_USERNAME", "").strip().lstrip("@")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    if not admins:
        raise SystemExit("TELEGRAM_ADMIN_CHAT_IDS requires a positive private chat ID")
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
        state_path=args.state_path.resolve(),
        audit_path=args.audit_path.resolve(),
        bot_token=token,
        admin_chat_ids=admins,
        workers={},
        expected_bot_username=expected_bot,
        worker_control_enabled=False,
    )
    runtime = GlobalOrchestrator(config)
    if args.check:
        runtime._validate_bot_identity()
        print(f"G20_TELEGRAM_APPROVAL config OK: admins={len(admins)} order_authority=NONE")
        return 0
    lock_path = config.state_path.with_name("telegram-control.lock")
    with SingleInstanceLock(lock_path):
        runtime.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
