from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Sequence

from .cli import _offset
from .engine import BearDecision, BearEngine, BearEngineConfig
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


def signal_outcome(signal: BearDecision, bars) -> dict[str, object]:
    if signal.entry is None or signal.stop is None or signal.take_profit is None:
        raise ValueError("SELL signal is missing its price plan")
    future = [bar for bar in bars if bar.time > signal.time]
    minimum_low = signal.entry
    maximum_high = signal.entry
    first_event = "OPEN"
    first_event_time = None
    tp2_time = None
    for bar in future:
        minimum_low = min(minimum_low, bar.low)
        maximum_high = max(maximum_high, bar.high)
        stop_touched = bar.high >= signal.stop
        tp1_touched = bar.low <= signal.take_profit
        if first_event == "OPEN" and stop_touched and tp1_touched:
            first_event = "AMBIGUOUS_SAME_BAR"
            first_event_time = bar.time
        elif first_event == "OPEN" and stop_touched:
            first_event = "STOP"
            first_event_time = bar.time
        elif first_event == "OPEN" and tp1_touched:
            first_event = "TP1"
            first_event_time = bar.time
        if signal.take_profit_2 is not None and bar.low <= signal.take_profit_2:
            tp2_time = bar.time
            break
        if first_event == "STOP":
            break
    return {
        "first_event": first_event,
        "first_event_time": first_event_time,
        "tp2_time": tp2_time,
        "maximum_favorable_excursion": signal.entry - minimum_low,
        "maximum_adverse_excursion": maximum_high - signal.entry,
        "bars_observed": len(future),
    }


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
        signals = engine.scan(bars)
        payload = {
            "bar_count": len(bars),
            "first_bar": bars[0].time,
            "last_bar": bars[-1].time,
            "signals": [
                {
                    **asdict(decision),
                    "outcome": signal_outcome(decision, bars),
                }
                for decision in signals
            ],
        }
        print(json.dumps(payload, default=_jsonable, sort_keys=True))
        return 0
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
