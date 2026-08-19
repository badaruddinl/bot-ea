from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goldm_bear.cli import _offset  # noqa: E402
from goldm_bear.mt5_cli import _server_timestamp  # noqa: E402
from goldm_bear.mt5_source import load_mt5_bars  # noqa: E402
from goldm_bear.multitimeframe import (  # noqa: E402
    BearMultiTimeframeReplay,
    BearV4Config,
)


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--from-server-time", required=True)
    parser.add_argument("--to-server-time", required=True)
    parser.add_argument("--server-utc-offset", default="+03:00")
    parser.add_argument(
        "--target-r",
        type=float,
        nargs="+",
        default=[0.35, 0.5, 0.7, 1.0, 1.25, 1.5, 2.0, 2.5],
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--cap-target-at-structural-support", action="store_true")
    args = parser.parse_args()
    zone = _offset(args.server_utc_offset)
    start = _server_timestamp(args.from_server_time, zone)
    end = _server_timestamp(args.to_server_time, zone)
    history_start = start - timedelta(days=30)
    data = {
        name: load_mt5_bars(
            symbol=args.symbol,
            timeframe_name=timeframe,
            start=history_start,
            end=end,
            server_timezone=zone,
        )
        for name, timeframe in (
            ("m1", "TIMEFRAME_M1"),
            ("m5", "TIMEFRAME_M5"),
            ("m15", "TIMEFRAME_M15"),
            ("h1", "TIMEFRAME_H1"),
        )
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for target_r in args.target_r:
        report = BearMultiTimeframeReplay(
            BearV4Config(
                fixed_target_r=target_r,
                cap_fixed_target_at_structural_support=args.cap_target_at_structural_support,
            )
        ).run(
            m1_bars=data["m1"],
            m5_bars=data["m5"],
            m15_bars=data["m15"],
            h1_bars=data["h1"],
            from_time=start,
            to_time=end,
        )
        tag = str(target_r).replace(".", "p")
        report_path = args.output_dir / f"rr_{tag}.json"
        payload = {
            **asdict(report),
            "candidate": "confluence-v4-fixed-r",
            "symbol": args.symbol,
            "fixed_target_r": target_r,
        }
        report_path.write_text(
            json.dumps(payload, default=_json_default, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        summary.append(
            {
                "fixed_target_r": target_r,
                "report": str(report_path),
                "executed_signals": report.executed_signals,
                "target_count": report.target_count,
                "stop_count": report.stop_count,
                "total_r": report.total_r,
                "expectancy_r": report.expectancy_r,
                "maximum_drawdown_r": report.maximum_drawdown_r,
                "targets_crossing_structural_support": report.targets_crossing_structural_support,
            }
        )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
