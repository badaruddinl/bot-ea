from __future__ import annotations

import argparse
import json
import os
import time
from importlib import import_module
from pathlib import Path

from .bridge import EventBridge, RecipientPolicy
from .store import EventStore


def _chat_ids(value: str) -> tuple[str, ...]:
    result: list[str] = []
    for item in value.replace(";", ",").split(","):
        normalized = item.strip()
        digits = normalized[1:] if normalized.startswith("-") else normalized
        if normalized and normalized.isascii() and digits.isdecimal() and int(normalized) != 0:
            result.append(str(int(normalized)))
    return tuple(dict.fromkeys(result))


def load_goldi_subscribers(path: Path | None) -> tuple[str, ...]:
    if path is None:
        return ()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    raw = value.get("goldi_subscribers") if isinstance(value, dict) else []
    return _chat_ids(",".join(str(item) for item in (raw or [])))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest MQL5 event spools and deliver Telegram")
    parser.add_argument("--goldi-spool", type=Path, required=True)
    parser.add_argument("--goldm-spool", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--subscriber-state", type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    admins = _chat_ids(
        os.environ.get("TELEGRAM_ADMIN_CHAT_IDS", "") or os.environ.get("TELEGRAM_CHAT_ID", "")
    )
    if not token or not admins:
        raise SystemExit("Telegram token and at least one administrator chat ID are required")
    client_type = import_module("goldm_signal.notify.telegram").TelegramBotClient
    client = client_type(bot_token=token)

    def send(chat_id: str, message: str) -> None:
        client.send_message(chat_id=chat_id, text=message)

    store = EventStore(args.database)
    try:
        while True:
            subscribers = load_goldi_subscribers(args.subscriber_state)
            bridge = EventBridge(
                store,
                RecipientPolicy(admins, subscribers),
                send,
            )
            for spool in (args.goldi_spool, args.goldm_spool):
                store.ingest_spool(spool)
            bridge.deliver_pending()
            if args.once:
                return 0
            time.sleep(max(args.poll_seconds, 0.25))
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
