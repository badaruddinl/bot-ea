from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .events import EngineEventEnvelope
from .store import EventStore

Sender = Callable[[str, str], None]


@dataclass(frozen=True, slots=True)
class RecipientPolicy:
    admin_chat_ids: tuple[str, ...]
    goldi_approved_chat_ids: tuple[str, ...]

    def recipients(self, event: EngineEventEnvelope) -> tuple[str, ...]:
        if (
            event.event_type
            not in {
                "ENGINE_STARTED",
                "PROFILE_VALIDATED",
                "ENTRY_READY",
                "POSITION_OPENED",
                "POSITION_CLOSED",
                "ENGINE_ERROR",
                "RECOVERY_COMPLETED",
            }
            or event.audience == "internal"
        ):
            return ()
        if event.profile_id == "GOLDM":
            return tuple(dict.fromkeys(self.admin_chat_ids))
        if event.audience == "goldi_approved" and event.event_type in {
            "ENTRY_READY",
            "POSITION_OPENED",
            "POSITION_CLOSED",
        }:
            return tuple(dict.fromkeys((*self.admin_chat_ids, *self.goldi_approved_chat_ids)))
        return tuple(dict.fromkeys(self.admin_chat_ids))


class EventBridge:
    def __init__(self, store: EventStore, policy: RecipientPolicy, sender: Sender) -> None:
        self.store = store
        self.policy = policy
        self.sender = sender

    def deliver_pending(self, *, limit: int = 100) -> tuple[int, int]:
        delivered = failed = 0
        for row in self.store.pending_events()[:limit]:
            event = EngineEventEnvelope.from_json_line(str(row["raw_event"]))
            recipients = self.policy.recipients(event)
            with self.store.connection:
                if not recipients:
                    self.store.connection.execute(
                        "UPDATE engine_events SET delivery_state='SUPPRESSED' WHERE event_id=?",
                        (event.event_id,),
                    )
                    continue
                self.store.connection.executemany(
                    "INSERT OR IGNORE INTO deliveries(event_id, chat_id) VALUES (?, ?)",
                    ((event.event_id, chat_id) for chat_id in recipients),
                )
            pending = tuple(
                self.store.connection.execute(
                    """
                    SELECT chat_id FROM deliveries
                    WHERE event_id=? AND state!='DELIVERED' ORDER BY chat_id
                    """,
                    (event.event_id,),
                )
            )
            for delivery in pending:
                chat_id = str(delivery["chat_id"])
                try:
                    self.sender(chat_id, self.format_message(event))
                except Exception as exc:  # sender boundary: persist and retry later
                    failed += 1
                    with self.store.connection:
                        self.store.connection.execute(
                            """
                            UPDATE deliveries SET state='RETRY', attempts=attempts+1,
                                last_error=? WHERE event_id=? AND chat_id=?
                            """,
                            (type(exc).__name__, event.event_id, chat_id),
                        )
                else:
                    delivered += 1
                    with self.store.connection:
                        self.store.connection.execute(
                            """
                            UPDATE deliveries SET state='DELIVERED', attempts=attempts+1,
                                last_error=NULL, delivered_at=?
                            WHERE event_id=? AND chat_id=?
                            """,
                            (datetime.now(UTC).isoformat(), event.event_id, chat_id),
                        )
            remaining = self.store.connection.execute(
                "SELECT COUNT(*) FROM deliveries WHERE event_id=? AND state!='DELIVERED'",
                (event.event_id,),
            ).fetchone()[0]
            if remaining == 0:
                with self.store.connection:
                    self.store.connection.execute(
                        "UPDATE engine_events SET delivery_state='DELIVERED' WHERE event_id=?",
                        (event.event_id,),
                    )
        return delivered, failed

    @staticmethod
    def format_message(event: EngineEventEnvelope) -> str:
        payload = event.payload or {}
        lines = [
            f"{event.event_type.replace('_', ' ').title()} — {event.profile_id}",
            f"Instrumen: {event.symbol}",
            f"ID event: {event.event_id}",
            f"Waktu server: {event.server_time.isoformat()}",
            f"Alasan: {event.reason}",
        ]
        for label, key in (
            ("Entry", "entry"),
            ("Stop Loss", "stop_loss"),
            ("Take Profit", "take_profit"),
            ("Volume", "volume"),
            ("P/L", "profit_loss"),
            ("Saldo", "balance"),
        ):
            if key in payload:
                lines.append(f"{label}: {payload[key]}")
        return "\n".join(lines)
