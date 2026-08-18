from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Sequence

from .engine import BearAction, BearBar, BearEngine, BearEngineConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan closed GOLD M15 CSV bars with the standalone bearish engine."
    )
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument(
        "--server-utc-offset",
        default="+03:00",
        help="Broker server offset used for naive CSV timestamps (default: +03:00).",
    )
    parser.add_argument(
        "--all-signals",
        action="store_true",
        help="Emit every SELL decision instead of only the latest decision.",
    )
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


def _timestamp(value: str, server_timezone: timezone) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=server_timezone)


def load_bars(path: Path, *, server_timezone: timezone) -> list[BearBar]:
    bars: list[BearBar] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"time", "open", "high", "low", "close"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("CSV must contain time, open, high, low, and close columns")
        for row in reader:
            bars.append(
                BearBar(
                    time=_timestamp(row["time"], server_timezone),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    tick_volume=float(row.get("tick_volume") or 0.0),
                    spread=float(row.get("spread") or 0.0),
                )
            )
    return bars


def _jsonable(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        server_timezone = _offset(args.server_utc_offset)
        bars = load_bars(args.csv_file, server_timezone=server_timezone)
        engine = BearEngine(BearEngineConfig(symbol=args.symbol))
        if args.all_signals:
            payload: object = [asdict(decision) for decision in engine.scan(bars)]
        else:
            payload = asdict(engine.evaluate(bars))
        print(json.dumps(payload, default=_jsonable, sort_keys=True))
        if not args.all_signals and payload.get("action") == BearAction.WAIT:
            return 2
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
