from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar


class EventSchemaError(ValueError):
    """Raised when an EA spool line violates the immutable event contract."""


@dataclass(frozen=True, slots=True)
class EngineEventEnvelope:
    schema_version: int
    event_id: str
    profile_id: str
    profile_version: str
    profile_fingerprint: str
    event_type: str
    symbol: str
    server_time: datetime
    reason: str
    audience: str
    setup_id: str = ""
    signal_id: str = ""
    order_id: str = ""
    position_id: str = ""
    payload: dict[str, Any] | None = None

    EVENT_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "ENGINE_STARTED",
            "PROFILE_VALIDATED",
            "SETUP_CREATED",
            "WATCH_UPDATED",
            "WATCH_CANCELLED",
            "ENTRY_READY",
            "ENTRY_REJECTED",
            "ORDER_SUBMITTED",
            "POSITION_OPENED",
            "POSITION_MODIFIED",
            "POSITION_CLOSED",
            "ENGINE_ERROR",
            "RECOVERY_COMPLETED",
        }
    )

    @classmethod
    def from_json_line(cls, raw: bytes | str) -> EngineEventEnvelope:
        try:
            decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            value = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EventSchemaError("event line is not valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise EventSchemaError("event line must contain an object")
        required = {
            "schema_version",
            "event_id",
            "profile_id",
            "profile_version",
            "profile_fingerprint",
            "event_type",
            "symbol",
            "server_time",
            "reason",
            "audience",
        }
        if missing := sorted(required - value.keys()):
            raise EventSchemaError(f"event fields missing: {missing}")
        try:
            server_time = datetime.fromtimestamp(int(value["server_time"]), tz=UTC)
        except (TypeError, ValueError, OSError) as exc:
            raise EventSchemaError("server_time must be a valid epoch second") from exc
        payload = value.get("payload")
        if payload is not None and not isinstance(payload, dict):
            raise EventSchemaError("payload must be an object or null")
        event = cls(
            schema_version=int(value["schema_version"]),
            event_id=str(value["event_id"]),
            profile_id=str(value["profile_id"]),
            profile_version=str(value["profile_version"]),
            profile_fingerprint=str(value["profile_fingerprint"]),
            event_type=str(value["event_type"]),
            symbol=str(value["symbol"]),
            server_time=server_time,
            reason=str(value["reason"]),
            audience=str(value["audience"]),
            setup_id=str(value.get("setup_id") or ""),
            signal_id=str(value.get("signal_id") or ""),
            order_id=str(value.get("order_id") or ""),
            position_id=str(value.get("position_id") or ""),
            payload=payload,
        )
        event.validate()
        return event

    def validate(self) -> None:
        if self.schema_version != 1:
            raise EventSchemaError("unsupported event schema version")
        if not self.event_id or len(self.event_id) > 240:
            raise EventSchemaError("event_id is empty or too long")
        if self.profile_id not in {"GOLDI", "GOLDM"}:
            raise EventSchemaError("profile_id is not GOLDI or GOLDM")
        if len(self.profile_fingerprint) != 64:
            raise EventSchemaError("profile fingerprint must contain 64 characters")
        if self.event_type not in self.EVENT_TYPES:
            raise EventSchemaError("event_type is unsupported")
        if self.audience not in {"admin_only", "goldi_approved", "internal"}:
            raise EventSchemaError("event audience is unsupported")
        if self.profile_id == "GOLDM" and self.audience != "admin_only":
            raise EventSchemaError("GOLDM event audience must be admin_only")
        if self.profile_id == "GOLDI" and not self.symbol.startswith("GOLD.i"):
            raise EventSchemaError("GOLDI event symbol mismatch")
        if self.profile_id == "GOLDM" and not self.symbol.startswith("GOLDm"):
            raise EventSchemaError("GOLDM event symbol mismatch")

    def canonical_json(self) -> str:
        return json.dumps(
            {
                "audience": self.audience,
                "event_id": self.event_id,
                "event_type": self.event_type,
                "order_id": self.order_id,
                "payload": self.payload or {},
                "position_id": self.position_id,
                "profile_fingerprint": self.profile_fingerprint,
                "profile_id": self.profile_id,
                "profile_version": self.profile_version,
                "reason": self.reason,
                "schema_version": self.schema_version,
                "server_time": int(self.server_time.timestamp()),
                "setup_id": self.setup_id,
                "signal_id": self.signal_id,
                "symbol": self.symbol,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
