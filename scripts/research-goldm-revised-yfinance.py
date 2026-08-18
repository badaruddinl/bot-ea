from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from goldm_revised.yfinance_research import run_yfinance_research


def main() -> int:
    parser = argparse.ArgumentParser(description="Auxiliary GOLDM_REVISED replay using Yahoo GC=F.")
    parser.add_argument("--from-server-time", required=True)
    parser.add_argument("--to-server-time", required=True)
    parser.add_argument("--server-utc-offset-minutes", type=int, default=180)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    zone = timezone(timedelta(minutes=args.server_utc_offset_minutes))
    start = datetime.fromisoformat(args.from_server_time).replace(tzinfo=zone)
    end = datetime.fromisoformat(args.to_server_time).replace(tzinfo=zone)
    payload = run_yfinance_research(start=start, end=end, server_timezone=zone, output_dir=args.output_dir)
    report = payload["report"]
    print(json.dumps({key: report[key] for key in (
        "signals", "buy_signals", "sell_signals", "resolved", "total_r", "expectancy_r",
        "maximum_drawdown_r", "target_count", "stop_count", "first_obstacle_violations",
        "fallback_promotions", "duplicate_trigger_promotions",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
