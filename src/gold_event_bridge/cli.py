from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
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


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _write_health(path: Path, store: EventStore, delivered: int, failed: int) -> None:
    states = {
        str(row["delivery_state"]): int(row["count"])
        for row in store.connection.execute(
            "SELECT delivery_state, COUNT(*) AS count FROM engine_events GROUP BY delivery_state"
        )
    }
    profiles = {
        str(row["profile_id"]): int(row["count"])
        for row in store.connection.execute(
            "SELECT profile_id, COUNT(*) AS count FROM engine_events GROUP BY profile_id"
        )
    }
    latest = [
        {
            "delivery_state": str(row["delivery_state"]),
            "event_id": str(row["event_id"]),
            "event_type": str(row["event_type"]),
            "profile_id": str(row["profile_id"]),
        }
        for row in store.connection.execute(
            """
            SELECT event_id, profile_id, event_type, delivery_state
            FROM engine_events ORDER BY inserted_at DESC, event_id DESC LIMIT 24
            """
        )
    ]
    payload = {
        "schema_version": 1,
        "pid": os.getpid(),
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "event_count": store.event_count(),
        "profile_event_counts": profiles,
        "delivery_state_counts": states,
        "pending_event_count": len(store.pending_events()),
        "delivered_last_loop": delivered,
        "failed_last_loop": failed,
        "latest_events": latest,
        "production_real_orders": "DISABLED",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    os.replace(temporary, path)


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
    parser.add_argument("--spool-compact-bytes", type=_positive_int, default=16 * 1024 * 1024)
    parser.add_argument("--health-path", type=Path)
    parser.add_argument("--health-seconds", type=_positive_int, default=30)
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
    expected_bot = os.environ.get("TELEGRAM_EXPECTED_BOT_USERNAME", "").strip().lstrip("@")
    if expected_bot:
        identity = client.get_me()
        observed_bot = str(identity.get("username") or "").strip().lstrip("@")
        if not observed_bot or observed_bot.casefold() != expected_bot.casefold():
            raise SystemExit(
                f"Telegram bot identity mismatch: expected @{expected_bot}, "
                f"got @{observed_bot or 'unknown'}"
            )

    def send(chat_id: str, message: str) -> None:
        client.send_message(chat_id=chat_id, text=message)

    store = EventStore(args.database)
    next_health = 0.0
    try:
        while True:
            subscribers = load_goldi_subscribers(args.subscriber_state)
            bridge = EventBridge(
                store,
                RecipientPolicy(admins, subscribers),
                send,
            )
            for spool in (args.goldi_spool, args.goldm_spool):
                store.recover_rotated_spools(spool)
                store.ingest_spool(spool)
                store.compact_ingested_spool(spool, minimum_bytes=args.spool_compact_bytes)
            delivered, failed = bridge.deliver_pending()
            now = time.monotonic()
            if args.health_path is not None and now >= next_health:
                _write_health(args.health_path, store, delivered, failed)
                next_health = now + args.health_seconds
            if args.once:
                return 0
            time.sleep(max(args.poll_seconds, 0.25))
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
