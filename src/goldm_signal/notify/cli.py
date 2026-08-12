from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from ..storage.database import SignalStore
from .approval import TelegramApprovalWorker
from .outbox import OutboxWorker
from .telegram import ApprovedTelegramSender, TelegramBotClient


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run approved-only Telegram subscription and notification worker."
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--db", default=None)
    parser.add_argument("--poll-timeout", type=int, default=15)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    _load_env_file(Path(args.env_file))
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    admin_value = os.environ.get("TELEGRAM_ADMIN_CHAT_IDS", "").strip()
    if not admin_value:
        admin_value = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    admin_ids = _parse_chat_ids(admin_value)
    if not admin_ids:
        raise SystemExit("TELEGRAM_ADMIN_CHAT_IDS or TELEGRAM_CHAT_ID is required")

    db_path = Path(
        args.db
        or os.environ.get("GOLDM_SIGNAL_DB", "runtime_data/goldm_signal.db")
    )
    store = SignalStore(db_path)
    store.initialize()
    client = TelegramBotClient(bot_token=token)
    approval_worker = TelegramApprovalWorker(
        store=store, client=client, admin_chat_ids=admin_ids
    )
    outbox_worker = OutboxWorker(
        store,
        ApprovedTelegramSender(store=store, client=client),
    )
    client.set_commands()
    print(
        f"Telegram approval worker ready: admins={len(admin_ids)} db={db_path}",
        flush=True,
    )

    if args.once:
        processed = approval_worker.run_once(timeout=0)
        sent, failed = outbox_worker.run_once()
        print(f"processed={processed} sent={sent} failed={failed}", flush=True)
        return

    while True:
        try:
            processed = approval_worker.run_once(timeout=max(0, args.poll_timeout))
            sent, failed = outbox_worker.run_once()
            if processed or sent or failed:
                print(
                    f"processed={processed} sent={sent} failed={failed}",
                    flush=True,
                )
        except KeyboardInterrupt:
            print("Telegram approval worker stopped.", flush=True)
            return
        except Exception as exc:
            print(f"Telegram worker error: {exc}", flush=True)
            time.sleep(3.0)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _parse_chat_ids(value: str) -> set[str]:
    normalized = value.replace(";", ",").replace(" ", ",")
    return {item for item in normalized.split(",") if item and item.lstrip("-").isdigit()}


if __name__ == "__main__":
    main()
