from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any

from gold_event_bridge import EventBridge, EventStore, RecipientPolicy


class TelegramE2EError(RuntimeError):
    pass


def normalize_chat_ids(value: str) -> tuple[str, ...]:
    result: list[str] = []
    for item in value.replace(";", ",").split(","):
        text = item.strip()
        digits = text[1:] if text.startswith("-") else text
        if text and text.isascii() and digits.isdecimal() and int(text) != 0:
            result.append(str(int(text)))
    return tuple(dict.fromkeys(result))


def run_delivery(
    goldi_spool: Path,
    goldm_spool: Path,
    database: Path,
    admins: tuple[str, ...],
    approved: tuple[str, ...],
    sender: Callable[[str, str], Any],
) -> dict[str, Any]:
    if not admins or not approved:
        raise TelegramE2EError("admin and approved GOLDI recipients are required")
    receipts: list[dict[str, Any]] = []

    def recording_sender(chat_id: str, message: str) -> None:
        response = sender(chat_id, message)
        receipts.append(
            {
                "chat_id_sha256": hashlib.sha256(chat_id.encode()).hexdigest(),
                "message_id": int(response.get("message_id", 0))
                if isinstance(response, dict)
                else 0,
                "message_sha256": hashlib.sha256(message.encode()).hexdigest(),
                "title": message.splitlines()[0],
            }
        )

    store = EventStore(database)
    try:
        store.ingest_spool(goldi_spool)
        store.ingest_spool(goldm_spool)
        bridge = EventBridge(store, RecipientPolicy(admins, approved), recording_sender)
        delivered, failed = bridge.deliver_pending(limit=100)
        admin_set = set(admins)
        approved_set = set(approved)
        expected_deliveries = 3 * len(admin_set) + 3 * len(admin_set | approved_set)
        if failed or delivered != expected_deliveries:
            raise TelegramE2EError(
                f"expected {expected_deliveries} final recipient deliveries, "
                f"got delivered={delivered} failed={failed}"
            )
        approved_only = approved_set - admin_set
        goldm_leaks = [
            receipt
            for receipt in receipts
            if receipt["chat_id_sha256"]
            in {hashlib.sha256(value.encode()).hexdigest() for value in approved_only}
            and "GOLDM" in receipt["title"]
        ]
        if goldm_leaks:
            raise TelegramE2EError("GOLDM Telegram delivery leaked to GOLDI approved recipient")
        return {
            "schema_version": 1,
            "status": "PASS",
            "transport": "TELEGRAM_BOT_API",
            "delivery_calls": delivered,
            "expected_delivery_calls": expected_deliveries,
            "failed_calls": failed,
            "goldm_approved_leak_count": len(goldm_leaks),
            "admin_recipient_count": len(admin_set),
            "approved_recipient_count": len(approved_set),
            "approved_only_recipient_count": len(approved_only),
            "recipient_overlap_count": len(admin_set & approved_set),
            "receipts": receipts,
            "production_real_orders": "DISABLED",
        }
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run actual G17 Telegram E2E delivery")
    parser.add_argument("--goldi-spool", type=Path, required=True)
    parser.add_argument("--goldm-spool", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    admins = normalize_chat_ids(
        os.environ.get("TELEGRAM_ADMIN_CHAT_IDS", "") or os.environ.get("TELEGRAM_CHAT_ID", "")
    )
    approved = normalize_chat_ids(os.environ.get("G17_APPROVED_CHAT_IDS", ""))
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    client_type = import_module("goldm_signal.notify.telegram").TelegramBotClient
    client = client_type(bot_token=token)
    report = run_delivery(
        args.goldi_spool,
        args.goldm_spool,
        args.database,
        admins,
        approved,
        lambda chat_id, message: client.send_message(chat_id=chat_id, text=message),
    )
    encoded = (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    args.output.with_suffix(".sha256").write_text(
        f"{hashlib.sha256(encoded).hexdigest()}  {args.output.name}\n", encoding="ascii"
    )
    print(json.dumps({key: value for key, value in report.items() if key != "receipts"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
