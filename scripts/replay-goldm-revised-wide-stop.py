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
    parser.add_argument("--target-multiplier", type=float, default=1.0)
    parser.add_argument("--partial-fraction", type=float, default=0.0)
    parser.add_argument("--partial-target-multiplier", type=float, default=1.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbol", default="GOLD.i#")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.stop_multiplier <= 1.0:
        raise ValueError("wide-stop multiplier must exceed one")
    if args.target_multiplier <= 0:
        raise ValueError("target multiplier must be positive")
    if not 0.0 <= args.partial_fraction < 1.0:
        raise ValueError("partial fraction must be in [0, 1)")
    if args.partial_target_multiplier <= 0:
        raise ValueError("partial target multiplier must be positive")
    if (
        args.partial_fraction > 0
        and args.partial_target_multiplier >= args.target_multiplier
    ):
        raise ValueError("partial target must be before the runner target")
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
    skipped_invalid_target = 0
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
        original_target = float(original["target"])
        target = entry + (original_target - entry) * args.target_multiplier
        partial_target = entry + (
            (original_target - entry) * args.partial_target_multiplier
        )
        if target <= entry or (
            args.partial_fraction > 0 and partial_target <= entry
        ):
            skipped_invalid_target += 1
            continue
        execution_target_r = (target - entry) / widened_risk
        execution_partial_target_r = (partial_target - entry) / widened_risk
        execution_first_obstacle_r = (
            float(original["first_obstacle_r"]) / args.stop_multiplier
        )
        start_index = bisect.bisect_left(bar_times, opened_at)
        result = "END_OF_TEST"
        closed_at = end
        outcome_r = 0.0
        mfe = 0.0
        mae = 0.0
        partial_taken = False
        for bar in bars[start_index:]:
            if bar.time >= end:
                break
            mfe = max(mfe, (bar.high - entry) / widened_risk)
            mae = min(mae, (bar.low - entry) / widened_risk)
            stop_hit = bar.low <= stop
            target_hit = bar.high >= target
            partial_hit = (
                args.partial_fraction > 0
                and not partial_taken
                and bar.high >= partial_target
            )
            if not partial_taken:
                if stop_hit and (partial_hit or target_hit):
                    closed_at = bar.time + timedelta(minutes=1)
                    result = "AMBIGUOUS_SAME_BAR"
                    outcome_r = -1.0
                    break
                if stop_hit:
                    closed_at = bar.time + timedelta(minutes=1)
                    result = "STOP"
                    outcome_r = -1.0
                    break
                if target_hit:
                    closed_at = bar.time + timedelta(minutes=1)
                    result = "TARGET"
                    outcome_r = (
                        args.partial_fraction * execution_partial_target_r
                        + (1.0 - args.partial_fraction) * execution_target_r
                    )
                    partial_taken = args.partial_fraction > 0
                    break
                if partial_hit:
                    partial_taken = True
                continue
            if not stop_hit and not target_hit:
                continue
            closed_at = bar.time + timedelta(minutes=1)
            if stop_hit and target_hit:
                result = "PARTIAL_AMBIGUOUS_SAME_BAR"
                outcome_r = (
                    args.partial_fraction * execution_partial_target_r
                    - (1.0 - args.partial_fraction)
                )
            elif stop_hit:
                result = "PARTIAL_STOP"
                outcome_r = (
                    args.partial_fraction * execution_partial_target_r
                    - (1.0 - args.partial_fraction)
                )
            else:
                result = "TARGET"
                outcome_r = (
                    args.partial_fraction * execution_partial_target_r
                    + (1.0 - args.partial_fraction) * execution_target_r
                )
            break
        if result == "END_OF_TEST":
            last_close = bars[-1].close if bars else entry
            remaining_r = (last_close - entry) / widened_risk
            outcome_r = (
                args.partial_fraction * execution_partial_target_r
                + (1.0 - args.partial_fraction) * remaining_r
                if partial_taken
                else remaining_r
            )
        item = dict(original)
        item.update(
            {
                "closed_at": closed_at.isoformat(),
                "result": result,
                "outcome_r": outcome_r,
                "stop": stop,
                "target": target,
                "engine_target": original_target,
                "execution_target_r": execution_target_r,
                "partial_target": partial_target,
                "execution_partial_target_r": execution_partial_target_r,
                "partial_fraction": args.partial_fraction,
                "partial_taken": partial_taken,
                "execution_first_obstacle_r": execution_first_obstacle_r,
                "mfe": mfe,
                "mae": mae,
                "execution_stop_multiplier": args.stop_multiplier,
                "execution_target_multiplier": args.target_multiplier,
            }
        )
        replayed.append(item)
        unavailable_until = closed_at
    equity_r = 0.0
    peak_r = 0.0
    maximum_drawdown_r = 0.0
    for item in sorted(replayed, key=lambda value: value["closed_at"]):
        equity_r += float(item["outcome_r"])
        peak_r = max(peak_r, equity_r)
        maximum_drawdown_r = max(maximum_drawdown_r, peak_r - equity_r)
    payload = {
        **report,
        "outcomes": replayed,
        "signals": len(replayed),
        "resolved": len(replayed),
        "target_count": sum(item["result"] == "TARGET" for item in replayed),
        "stop_count": sum(item["result"] == "STOP" for item in replayed),
        "ambiguous_count": sum(
            item["result"] in {
                "AMBIGUOUS_SAME_BAR",
                "PARTIAL_AMBIGUOUS_SAME_BAR",
            }
            for item in replayed
        ),
        "partial_taken_count": sum(bool(item["partial_taken"]) for item in replayed),
        "partial_stop_count": sum(
            item["result"] == "PARTIAL_STOP" for item in replayed
        ),
        "total_r": sum(float(item["outcome_r"]) for item in replayed),
        "expectancy_r": (
            sum(float(item["outcome_r"]) for item in replayed) / len(replayed)
            if replayed
            else 0.0
        ),
        "maximum_drawdown_r": maximum_drawdown_r,
        "execution_stop_multiplier": args.stop_multiplier,
        "execution_target_multiplier": args.target_multiplier,
        "partial_fraction": args.partial_fraction,
        "partial_target_multiplier": args.partial_target_multiplier,
        "skipped_overlapping_signals": skipped_overlap,
        "skipped_invalid_targets": skipped_invalid_target,
        "execution_first_obstacle_violations": sum(
            float(item["execution_first_obstacle_r"]) < 1.0 for item in replayed
        ),
        "targets_beyond_first_obstacle": sum(
            float(item["execution_target_r"])
            > float(item["execution_first_obstacle_r"])
            for item in replayed
        ),
        "targets_below_one_r": sum(
            float(item["execution_target_r"]) < 1.0 for item in replayed
        ),
        "partial_targets_beyond_first_obstacle": sum(
            args.partial_fraction > 0
            and float(item["execution_partial_target_r"])
            > float(item["execution_first_obstacle_r"])
            for item in replayed
        ),
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
                    "partial_taken_count",
                    "partial_stop_count",
                    "total_r",
                    "expectancy_r",
                    "maximum_drawdown_r",
                    "execution_stop_multiplier",
                    "execution_target_multiplier",
                    "partial_fraction",
                    "partial_target_multiplier",
                    "skipped_overlapping_signals",
                    "skipped_invalid_targets",
                    "execution_first_obstacle_violations",
                    "targets_beyond_first_obstacle",
                    "targets_below_one_r",
                    "partial_targets_beyond_first_obstacle",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
