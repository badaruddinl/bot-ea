from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Sequence

from .engine import RevisedEngine, RevisedEngineConfig
from .replay import RevisedMt5HistoryLoader, RevisedReplay
from .runtime import load_runtime_config


def _server_time(value: str, zone: timezone) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(type(value).__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay GOLDM_REVISED on closed broker bars.")
    parser.add_argument("--config", type=Path, default=Path("config/goldm-revised-shadow.json"))
    parser.add_argument("--from-server-time", required=True)
    parser.add_argument("--to-server-time", required=True)
    parser.add_argument("--server-utc-offset-minutes", type=int, default=180)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--inspect-server-time", action="append", default=[])
    args = parser.parse_args(argv)
    zone = timezone(timedelta(minutes=args.server_utc_offset_minutes))
    start = _server_time(args.from_server_time, zone)
    end = _server_time(args.to_server_time, zone)
    inspect_times = tuple(_server_time(value, zone) for value in args.inspect_server_time)
    if end <= start:
        raise SystemExit("replay end must be after start")
    config = load_runtime_config(args.config)
    engine_values = dict(config.get("engine", {}))
    if "psychological_steps" in engine_values:
        engine_values["psychological_steps"] = tuple(engine_values["psychological_steps"])
    if "strong_m5_patterns" in engine_values:
        engine_values["strong_m5_patterns"] = tuple(engine_values["strong_m5_patterns"])
    engine = RevisedEngine(RevisedEngineConfig(**engine_values))
    loader = RevisedMt5HistoryLoader()
    try:
        data = loader.load(
            symbol=engine.config.symbol,
            start=start,
            end=end,
            server_timezone=zone,
        )
    finally:
        loader.close()
    report = RevisedReplay(engine).run(
        m1_bars=data["m1"],
        m5_bars=data["m5"],
        h1_bars=data["h1"],
        d1_bars=data["d1"],
        from_time=start,
        to_time=end,
        inspect_times=inspect_times,
    )
    payload = json.dumps(asdict(report), default=_json_default, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
