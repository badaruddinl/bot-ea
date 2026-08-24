from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .events import EngineEventEnvelope
from .store import EventStore

Sender = Callable[[str, str], None]

_CLOSE_REASON_LABELS = {
    "STOP_LOSS": "Stop Loss",
    "TAKE_PROFIT": "Take Profit",
    "MANUAL_DESKTOP": "Manual dari MT5 desktop",
    "MANUAL_MOBILE": "Manual dari MT5 mobile",
    "MANUAL_WEB": "Manual dari MT5 web",
    "EA": "Ditutup oleh EA",
    "STOP_OUT": "Stop Out broker",
    "BROKER_OTHER": "Broker/penyebab lain",
}


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
                "ENTRY_REJECTED",
                "POSITION_OPENED",
                "POSITION_PARTIALLY_CLOSED",
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
            "POSITION_OPENED",
            "POSITION_PARTIALLY_CLOSED",
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
    def _number(value: Any, *, digits: int = 2, signed: bool = False) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        prefix = "+" if signed and number > 0 else ""
        return f"{prefix}{number:.{digits}f}"

    @staticmethod
    def _duration(seconds: Any) -> str:
        try:
            remaining = max(0, int(float(seconds)))
        except (TypeError, ValueError):
            return str(seconds)
        days, remaining = divmod(remaining, 86_400)
        hours, remaining = divmod(remaining, 3_600)
        minutes, seconds_value = divmod(remaining, 60)
        parts = []
        if days:
            parts.append(f"{days} hari")
        if hours:
            parts.append(f"{hours} jam")
        if minutes:
            parts.append(f"{minutes} menit")
        if seconds_value or not parts:
            parts.append(f"{seconds_value} detik")
        return " ".join(parts)

    @classmethod
    def format_message(
        cls,
        event: EngineEventEnvelope,
        *,
        vm_time: datetime | None = None,
    ) -> str:
        payload = event.payload or {}
        side = str(payload.get("side") or "").upper()
        side_suffix = f" {side}" if side in {"BUY", "SELL"} else ""
        title = {
            "ENTRY_READY": "🟡 SIGNAL SIAP",
            "ENTRY_REJECTED": "⛔ ENTRY DITOLAK",
            "POSITION_OPENED": "✅ ORDER OPEN",
            "POSITION_PARTIALLY_CLOSED": "✂️ ORDER PARTIAL CLOSE",
            "POSITION_CLOSED": "🏁 ORDER CLOSED",
            "ENGINE_ERROR": "⚠️ ENGINE ERROR",
            "ENGINE_STARTED": "🟢 ENGINE STARTED",
            "PROFILE_VALIDATED": "✅ PROFILE VALIDATED",
            "RECOVERY_COMPLETED": "🔄 POSITION RECOVERED",
        }.get(event.event_type, event.event_type.replace("_", " ").title())

        server_time = str(payload.get("server_time_text") or "").strip()
        if not server_time:
            server_time = event.server_time.strftime("%Y-%m-%d %H:%M:%S")
        vm_time_text = str(payload.get("vm_time_text") or "").strip()
        if not vm_time_text:
            observed = vm_time or datetime.now().astimezone()
            vm_time_text = observed.isoformat(timespec="seconds")

        lines = [
            f"{title} — {event.symbol}{side_suffix}",
            f"Profile: {event.profile_id} v{event.profile_version}",
        ]

        strategy = str(payload.get("strategy") or "").strip()
        if strategy:
            lines.append(f"Strategi: {strategy}")

        field_specs = (
            ("Entry rencana", "planned_entry", False, 2),
            ("Harga open", "entry", False, 2),
            ("Stop Loss", "stop_loss", False, 2),
            ("Take Profit", "take_profit", False, 2),
            ("Harga close", "close_price", False, 2),
            ("Lot", "volume", False, 2),
            ("Lot ditutup", "closed_volume", False, 2),
            ("Lot tersisa", "remaining_volume", False, 2),
            ("R:R", "rr", False, 2),
            ("Risk harga", "risk_price", False, 2),
            ("P/L", "profit_loss", True, 2),
            ("Hasil R", "realized_r", True, 2),
            ("Balance", "balance", False, 2),
            ("Equity", "equity", False, 2),
        )
        for label, key, signed, digits in field_specs:
            if key not in payload:
                continue
            rendered = cls._number(payload[key], digits=digits, signed=signed)
            suffix = " USD" if key in {"profit_loss", "balance", "equity"} else ""
            if key == "rr":
                rendered = f"1:{rendered}"
            elif key == "realized_r":
                suffix = "R"
            lines.append(f"{label}: {rendered}{suffix}")

        if event.event_type in {"POSITION_OPENED", "ENTRY_REJECTED"}:
            for label, key, digits in (
                ("Harga request", "requested_entry", 2),
                ("R:R minimum", "minimum_executable_rr", 2),
            ):
                if key in payload:
                    lines.append(f"{label}: {cls._number(payload[key], digits=digits)}")

        close_reason = str(payload.get("close_reason") or "").strip().upper()
        if close_reason:
            lines.append(f"Ditutup oleh: {_CLOSE_REASON_LABELS.get(close_reason, close_reason)}")
        if str(payload.get("recovery_kind") or "").upper() == "RESTART":
            lines.append("Recovery: EA/terminal dimulai ulang")
        if event.event_type == "ENTRY_REJECTED":
            for label, key, digits in (
                ("Bid", "quote_bid", 2),
                ("Ask", "quote_ask", 2),
                ("Drift adverse", "adverse_drift_r", 3),
                ("Batas drift dinamis", "maximum_adverse_drift_r", 3),
                ("Broker retcode", "broker_retcode", 0),
            ):
                if key in payload:
                    lines.append(f"{label}: {cls._number(payload[key], digits=digits)}")

        if "duration_seconds" in payload:
            lines.append(f"Durasi: {cls._duration(payload['duration_seconds'])}")

        for label, value in (
            ("ID sinyal", event.signal_id),
            ("ID order", event.order_id),
            ("ID posisi", event.position_id),
            ("ID deal", str(payload.get("deal_id") or "")),
            ("ID event", event.event_id),
        ):
            if value:
                lines.append(f"{label}: {value}")

        lines.extend(
            (
                f"Waktu server MT5: {server_time}",
                f"Waktu VM/bridge: {vm_time_text}",
                f"Status: {event.reason}",
            )
        )
        return "\n".join(lines)
