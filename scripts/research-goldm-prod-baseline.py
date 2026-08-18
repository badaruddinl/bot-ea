from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence


SAFE_FIELD_NAMES = frozenset(
    {
        "status",
        "strategy",
        "strategyVersion",
        "directionProfile",
        "strategyMode",
        "autoEntry",
        "autoEntryEligible",
        "side",
        "level",
        "watchPrice",
        "invalidation",
        "expectedSl",
        "expectedTp",
        "provisionalProjectedR",
        "confidence",
        "confidenceEarly",
        "threshold",
        "entry",
        "stop",
        "target",
        "entryDistanceATR",
        "stopDistanceATR",
        "projectedR",
        "score",
        "scoreFinal",
        "m5Votes",
        "pattern",
        "fibonacciAligned",
        "fibonacciReaction",
        "m1Confirmed",
        "retestBars",
        "result",
        "outcomeR",
        "exitPrice",
        "hit1R",
        "hit2R",
        "hit3R",
        "mfeR",
        "maeR",
        "durationMinutes",
        "reason",
        "maxHoldingMinutes",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export sanitized GOLDM production-baseline evidence read-only."
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--from-server-time", required=True)
    parser.add_argument("--to-server-time", required=True)
    parser.add_argument("--server-utc-offset", default="+03:00")
    parser.add_argument("--latest-setups", type=int, default=12)
    return parser


def _offset(value: str) -> timezone:
    if len(value) != 6 or value[0] not in "+-" or value[3] != ":":
        raise ValueError("server UTC offset must use +HH:MM or -HH:MM")
    sign = 1 if value[0] == "+" else -1
    hours = int(value[1:3])
    minutes = int(value[4:6])
    if hours > 14 or minutes > 59:
        raise ValueError("server UTC offset is outside the supported range")
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def _server_timestamp(value: str, server_timezone: timezone) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=server_timezone)
    return parsed.astimezone(server_timezone)


def _iso_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _safe_fields(payload: dict[str, Any]) -> dict[str, str]:
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return {}
    return {
        key: str(fields[key])
        for key in SAFE_FIELD_NAMES
        if key in fields and fields[key] is not None
    }


def load_evidence(
    db_path: Path,
    *,
    start: datetime,
    end: datetime,
    server_timezone: timezone,
) -> dict[str, Any]:
    resolved = db_path.resolve(strict=True)
    connection = sqlite3.connect(
        f"file:{resolved.as_posix()}?mode=ro",
        uri=True,
        timeout=5.0,
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            """
            SELECT
                o.id,
                o.setup_id,
                o.event_type,
                o.created_at,
                o.sent_at,
                o.payload_json,
                s.symbol,
                s.side,
                s.level,
                s.breakout_at,
                s.state,
                s.reason
            FROM signal_outbox AS o
            JOIN setups AS s ON s.setup_id = o.setup_id
            ORDER BY o.id ASC
            """
        ).fetchall()
    finally:
        connection.close()

    events: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except (TypeError, ValueError):
            payload = {}
        generated_raw = str(payload.get("generated_at_utc") or row["created_at"])
        generated = _iso_timestamp(generated_raw).astimezone(server_timezone)
        if not start <= generated < end:
            continue
        setup_raw = str(payload.get("setup_at_utc") or row["breakout_at"])
        setup_at = _iso_timestamp(setup_raw).astimezone(server_timezone)
        events.append(
            {
                "id": int(row["id"]),
                "setup_id": str(row["setup_id"]),
                "event_type": str(row["event_type"]),
                "symbol": str(row["symbol"]),
                "side": str(row["side"]),
                "level": float(row["level"]),
                "setup_at_server": setup_at.isoformat(),
                "generated_at_server": generated.isoformat(),
                "sent": bool(row["sent_at"]),
                "state": str(row["state"]),
                "setup_reason": str(row["reason"]),
                "fields": _safe_fields(payload),
            }
        )

    event_counts = Counter(event["event_type"] for event in events)
    signals = [event for event in events if event["event_type"] == "SNIPER_SIGNAL"]
    outcomes = [event for event in events if event["event_type"] == "SNIPER_OUTCOME"]
    side_counts = Counter(event["side"] for event in signals)
    result_counts = Counter(event["fields"].get("result", "UNKNOWN") for event in outcomes)
    outcome_r = [
        float(event["fields"]["outcomeR"])
        for event in outcomes
        if "outcomeR" in event["fields"]
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[event["setup_id"]].append(event)
    ordered_setups = sorted(
        grouped.values(),
        key=lambda group: group[-1]["generated_at_server"],
    )
    return {
        "database": str(resolved),
        "range_server": {"from": start.isoformat(), "to": end.isoformat()},
        "event_counts": dict(sorted(event_counts.items())),
        "signal_side_counts": dict(sorted(side_counts.items())),
        "outcome_result_counts": dict(sorted(result_counts.items())),
        "outcome_r": {
            "count": len(outcome_r),
            "sum": sum(outcome_r),
            "average": sum(outcome_r) / len(outcome_r) if outcome_r else None,
        },
        "setups": ordered_setups,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        server_timezone = _offset(args.server_utc_offset)
        start = _server_timestamp(args.from_server_time, server_timezone)
        end = _server_timestamp(args.to_server_time, server_timezone)
        if end <= start:
            raise ValueError("research range end must be after start")
        payload = load_evidence(
            args.db,
            start=start,
            end=end,
            server_timezone=server_timezone,
        )
        payload["setups"] = payload["setups"][-max(1, args.latest_setups) :]
        print(json.dumps(payload, sort_keys=True))
        return 0
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
