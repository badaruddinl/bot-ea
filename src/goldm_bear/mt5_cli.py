from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Sequence

from .cli import _offset
from .engine import BearEngine, BearEngineConfig
from .mt5_source import load_mt5_m15_bars


def _jsonable(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read GOLD M15 bars from MT5 and run the standalone bearish scanner."
    )
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--from-server-time", required=True)
    parser.add_argument("--to-server-time", required=True)
    parser.add_argument("--server-utc-offset", default="+03:00")
    return parser


def _server_timestamp(value: str, server_timezone) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=server_timezone)
    return parsed.astimezone(server_timezone)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        server_timezone = _offset(args.server_utc_offset)
        start = _server_timestamp(args.from_server_time, server_timezone)
        end = _server_timestamp(args.to_server_time, server_timezone)
        bars = load_mt5_m15_bars(
            symbol=args.symbol,
            start=start,
            end=end,
            server_timezone=server_timezone,
        )
        engine = BearEngine(BearEngineConfig(symbol=args.symbol))
        payload = {
            "bar_count": len(bars),
            "first_bar": bars[0].time,
            "last_bar": bars[-1].time,
            "signals": [asdict(decision) for decision in engine.scan(bars)],
        }
        print(json.dumps(payload, default=_jsonable, sort_keys=True))
        return 0
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
