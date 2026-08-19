from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Sequence

from .cli import _offset
from .mt5_cli import _server_timestamp
from .mt5_source import load_mt5_bars
from .multitimeframe import BearMultiTimeframeReplay, BearV4Config


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(type(value).__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="goldm_bear confluence-v4 replay")
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--from-server-time", required=True)
    parser.add_argument("--to-server-time", required=True)
    parser.add_argument("--server-utc-offset", default="+03:00")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixed-target-r", type=float)
    parser.add_argument("--cap-target-at-structural-support", action="store_true")
    parser.add_argument("--stop-multiplier", type=float, default=1.0)
    parser.add_argument("--target-multiplier", type=float, default=1.0)
    args = parser.parse_args(argv)
    server_timezone = _offset(args.server_utc_offset)
    start = _server_timestamp(args.from_server_time, server_timezone)
    end = _server_timestamp(args.to_server_time, server_timezone)
    history_start = start - timedelta(days=30)
    data = {
        name: load_mt5_bars(
            symbol=args.symbol,
            timeframe_name=timeframe,
            start=history_start,
            end=end,
            server_timezone=server_timezone,
        )
        for name, timeframe in (
            ("m1", "TIMEFRAME_M1"),
            ("m5", "TIMEFRAME_M5"),
            ("m15", "TIMEFRAME_M15"),
            ("h1", "TIMEFRAME_H1"),
        )
    }
    report = BearMultiTimeframeReplay(
        BearV4Config(
            fixed_target_r=args.fixed_target_r,
            cap_fixed_target_at_structural_support=args.cap_target_at_structural_support,
            stop_multiplier=args.stop_multiplier,
            target_multiplier=args.target_multiplier,
        )
    ).run(
        m1_bars=data["m1"],
        m5_bars=data["m5"],
        m15_bars=data["m15"],
        h1_bars=data["h1"],
        from_time=start,
        to_time=end,
    )
    payload = {
        **asdict(report),
        "candidate": "confluence-v4",
        "symbol": args.symbol,
        "fixed_target_r": args.fixed_target_r,
        "cap_target_at_structural_support": args.cap_target_at_structural_support,
        "stop_multiplier": args.stop_multiplier,
        "target_multiplier": args.target_multiplier,
        "history": {
            key: {
                "bars": len(bars),
                "first": bars[0].time,
                "last": bars[-1].time,
            }
            for key, bars in data.items()
        },
    }
    rendered = json.dumps(payload, default=_json_default, sort_keys=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: payload[key]
                for key in (
                    "m15_setups",
                    "h1_rejected",
                    "m5_armed",
                    "m5_cancelled",
                    "m1_expired_or_cancelled",
                    "executed_signals",
                    "target_count",
                    "stop_count",
                    "ambiguous_count",
                    "targets_crossing_structural_support",
                    "total_r",
                    "expectancy_r",
                    "maximum_drawdown_r",
                )
            },
            sort_keys=True,
        )
    )
    return 0
