from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Sequence

from .cli import _offset
from .candidate import (
    confluence_v1_config,
    confluence_v2_config,
    confluence_v3_config,
)
from .engine import BearEngine, BearEngineConfig
from .mt5_cli import _server_timestamp
from .mt5_source import load_mt5_m15_bars
from .replay import BearReplay


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(type(value).__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Causal standalone goldm_bear replay")
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--from-server-time", required=True)
    parser.add_argument("--to-server-time", required=True)
    parser.add_argument("--server-utc-offset", default="+03:00")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maximum-regime-drop-atr", type=float)
    parser.add_argument(
        "--candidate",
        choices=("baseline", "confluence-v1", "confluence-v2", "confluence-v3"),
        default="baseline",
    )
    args = parser.parse_args(argv)
    server_timezone = _offset(args.server_utc_offset)
    start = _server_timestamp(args.from_server_time, server_timezone)
    end = _server_timestamp(args.to_server_time, server_timezone)
    bars = load_mt5_m15_bars(
        symbol=args.symbol,
        start=start - timedelta(days=30),
        end=end,
        server_timezone=server_timezone,
    )
    engine_config = {
        "baseline": BearEngineConfig(symbol=args.symbol),
        "confluence-v1": confluence_v1_config(symbol=args.symbol),
        "confluence-v2": confluence_v2_config(symbol=args.symbol),
        "confluence-v3": confluence_v3_config(symbol=args.symbol),
    }[args.candidate]
    if args.maximum_regime_drop_atr is not None:
        engine_config = replace(
            engine_config,
            maximum_regime_drop_atr=args.maximum_regime_drop_atr,
        )
    engine = BearEngine(engine_config)
    report = BearReplay(engine).run(bars, from_time=start, to_time=end)
    payload = {
        **asdict(report),
        "symbol": args.symbol,
        "bar_count": len(bars),
        "first_bar": bars[0].time,
        "last_bar": bars[-1].time,
        "maximum_regime_drop_atr": args.maximum_regime_drop_atr,
        "candidate": args.candidate,
    }
    rendered = json.dumps(payload, default=_json_default, sort_keys=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: payload[key]
                for key in (
                    "candidate_signals",
                    "executed_signals",
                    "skipped_overlapping_signals",
                    "target_count",
                    "stop_count",
                    "ambiguous_count",
                    "invalidated_count",
                    "end_of_test_count",
                    "total_r",
                    "expectancy_r",
                    "maximum_drawdown_r",
                )
            },
            sort_keys=True,
        )
    )
    return 0
