from __future__ import annotations

import argparse
import bisect
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goldm_revised.replay import RevisedMt5HistoryLoader  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--stop-multiplier", type=float, default=2.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbol", default="GOLD.i#")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.stop_multiplier <= 1.0:
        raise ValueError("wide-stop multiplier must exceed one")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    start = datetime.fromisoformat(report["from_time"])
    end = datetime.fromisoformat(report["to_time"])
    loader = RevisedMt5HistoryLoader()
    loader.connect()
    try:
        mt5 = loader._module()
        info = mt5.symbol_info(args.symbol)
        if info is None:
            raise RuntimeError(f"MT5 symbol info unavailable: {mt5.last_error()}")
        bars = loader._rates(
            args.symbol,
            mt5.TIMEFRAME_M1,
            start,
            end,
            start.tzinfo,
            float(info.point),
        )
    finally:
        loader.close()
    bar_times = [bar.time for bar in bars]
    replayed: list[dict[str, object]] = []
    skipped_overlap = 0
    unavailable_until = start
    for original in sorted(report["outcomes"], key=lambda item: item["opened_at"]):
        opened_at = datetime.fromisoformat(original["opened_at"])
        if opened_at < unavailable_until:
            skipped_overlap += 1
            continue
        entry = float(original["entry"])
        original_risk = abs(entry - float(original["stop"]))
        widened_risk = original_risk * args.stop_multiplier
        stop = entry - widened_risk
        target = float(original["target"])
        start_index = bisect.bisect_left(bar_times, opened_at)
        result = "END_OF_TEST"
        closed_at = end
        outcome_r = 0.0
        mfe = 0.0
        mae = 0.0
        for bar in bars[start_index:]:
            if bar.time >= end:
                break
            mfe = max(mfe, (bar.high - entry) / widened_risk)
            mae = min(mae, (bar.low - entry) / widened_risk)
            stop_hit = bar.low <= stop
            target_hit = bar.high >= target
            if not stop_hit and not target_hit:
                continue
            closed_at = bar.time + timedelta(minutes=1)
            if stop_hit and target_hit:
                result = "AMBIGUOUS_SAME_BAR"
                outcome_r = -1.0
            elif stop_hit:
                result = "STOP"
                outcome_r = -1.0
            else:
                result = "TARGET"
                outcome_r = (target - entry) / widened_risk
            break
        if result == "END_OF_TEST":
            last_close = bars[-1].close if bars else entry
            outcome_r = (last_close - entry) / widened_risk
        item = dict(original)
        item.update(
            {
                "closed_at": closed_at.isoformat(),
                "result": result,
                "outcome_r": outcome_r,
                "stop": stop,
                "mfe": mfe,
                "mae": mae,
                "execution_stop_multiplier": args.stop_multiplier,
            }
        )
        replayed.append(item)
        unavailable_until = closed_at
    payload = {
        **report,
        "outcomes": replayed,
        "signals": len(replayed),
        "resolved": len(replayed),
        "target_count": sum(item["result"] == "TARGET" for item in replayed),
        "stop_count": sum(item["result"] == "STOP" for item in replayed),
        "ambiguous_count": sum(
            item["result"] == "AMBIGUOUS_SAME_BAR" for item in replayed
        ),
        "total_r": sum(float(item["outcome_r"]) for item in replayed),
        "expectancy_r": (
            sum(float(item["outcome_r"]) for item in replayed) / len(replayed)
            if replayed
            else 0.0
        ),
        "execution_stop_multiplier": args.stop_multiplier,
        "skipped_overlapping_signals": skipped_overlap,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: payload[key]
                for key in (
                    "signals",
                    "target_count",
                    "stop_count",
                    "ambiguous_count",
                    "total_r",
                    "expectancy_r",
                    "execution_stop_multiplier",
                    "skipped_overlapping_signals",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
