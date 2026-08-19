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


POLICIES: dict[str, tuple[tuple[float, float], ...]] = {
    "NO_TRAIL": (),
    "BE_AT_0P5": ((0.50, 0.00),),
    "LOCK_0P1_AT_0P75": ((0.75, 0.10),),
    "LOCK_0P25_AT_1": ((1.00, 0.25),),
    "STEP_FAST": (
        (0.50, 0.00),
        (0.75, 0.10),
        (1.00, 0.25),
        (1.50, 0.75),
        (2.00, 1.25),
    ),
    "STEP_SLOW": (
        (1.00, 0.00),
        (1.50, 0.50),
        (2.00, 1.00),
        (3.00, 2.00),
    ),
    "BE_AT_1P5": ((1.50, 0.00),),
    "LOCK_0P5_AT_2": ((2.00, 0.50),),
    "STEP_LATE": (
        (1.50, 0.00),
        (2.00, 0.50),
        (3.00, 1.50),
        (4.00, 2.50),
    ),
}


def locked_r_for_close(
    close_r: float,
    policy: tuple[tuple[float, float], ...],
) -> float | None:
    eligible = [locked_r for trigger_r, locked_r in policy if close_r >= trigger_r]
    return max(eligible) if eligible else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--stop-multiplier", type=float, default=1.75)
    parser.add_argument("--target-multiplier", type=float, default=2.5)
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    return parser.parse_args()


def replay_policy(report, bars, bar_times, *, policy_name, policy, stop_multiplier, target_multiplier):
    start = datetime.fromisoformat(report["from_time"])
    end = datetime.fromisoformat(report["to_time"])
    replayed = []
    unavailable_until = start
    skipped_overlap = 0
    skipped_invalid = 0
    for original in sorted(report["outcomes"], key=lambda item: item["opened_at"]):
        opened_at = datetime.fromisoformat(original["opened_at"])
        if opened_at < unavailable_until:
            skipped_overlap += 1
            continue
        entry = float(original["entry"])
        original_risk = abs(entry - float(original["stop"]))
        risk = original_risk * stop_multiplier
        initial_stop = entry - risk
        engine_target = float(original["target"])
        target = entry + (engine_target - entry) * target_multiplier
        if target <= entry:
            skipped_invalid += 1
            continue
        active_stop = initial_stop
        result = "END_OF_TEST"
        closed_at = end
        outcome_r = 0.0
        mfe_r = 0.0
        mae_r = 0.0
        start_index = bisect.bisect_left(bar_times, opened_at)
        for bar in bars[start_index:]:
            if bar.time >= end:
                break
            mfe_r = max(mfe_r, (bar.high - entry) / risk)
            mae_r = min(mae_r, (bar.low - entry) / risk)
            stop_hit = bar.low <= active_stop
            target_hit = bar.high >= target
            if stop_hit or target_hit:
                closed_at = bar.time + timedelta(minutes=1)
                if stop_hit and target_hit:
                    result = "AMBIGUOUS_SAME_BAR"
                    outcome_r = (active_stop - entry) / risk
                elif stop_hit:
                    result = "TRAIL_STOP" if active_stop > initial_stop else "STOP"
                    outcome_r = (active_stop - entry) / risk
                else:
                    result = "TARGET"
                    outcome_r = (target - entry) / risk
                break
            close_r = (bar.close - entry) / risk
            locked_r = locked_r_for_close(close_r, policy)
            if locked_r is None:
                continue
            proposed_stop = entry + locked_r * risk
            # Closed-bar update: the new stop is active from the next M1 bar.
            # It must remain below the confirming close by at least spread.
            if proposed_stop <= bar.close - max(bar.spread, 0.20):
                active_stop = max(active_stop, proposed_stop)
        if result == "END_OF_TEST":
            last_close = bars[-1].close if bars else entry
            outcome_r = (last_close - entry) / risk
        item = dict(original)
        item.update(
            {
                "closed_at": closed_at.isoformat(),
                "result": result,
                "outcome_r": outcome_r,
                "entry": entry,
                "stop": initial_stop,
                "target": target,
                "engine_target": engine_target,
                "final_active_stop": active_stop,
                "mfe": mfe_r,
                "mae": mae_r,
                "trailing_policy": policy_name,
            }
        )
        replayed.append(item)
        unavailable_until = closed_at
    equity = 0.0
    peak = 0.0
    maximum_drawdown = 0.0
    for item in sorted(replayed, key=lambda value: value["closed_at"]):
        equity += float(item["outcome_r"])
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
    total_r = sum(float(item["outcome_r"]) for item in replayed)
    return {
        **report,
        "outcomes": replayed,
        "signals": len(replayed),
        "target_count": sum(item["result"] == "TARGET" for item in replayed),
        "stop_count": sum(item["result"] == "STOP" for item in replayed),
        "trail_stop_count": sum(item["result"] == "TRAIL_STOP" for item in replayed),
        "ambiguous_count": sum(item["result"] == "AMBIGUOUS_SAME_BAR" for item in replayed),
        "total_r": total_r,
        "expectancy_r": total_r / len(replayed) if replayed else 0.0,
        "maximum_drawdown_r": maximum_drawdown,
        "skipped_overlapping_signals": skipped_overlap,
        "skipped_invalid_targets": skipped_invalid,
        "execution_stop_multiplier": stop_multiplier,
        "execution_target_multiplier": target_multiplier,
        "trailing_policy": policy_name,
        "trailing_steps": policy,
    }


def main() -> int:
    args = parse_args()
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
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for policy_name, policy in POLICIES.items():
        payload = replay_policy(
            report,
            bars,
            bar_times,
            policy_name=policy_name,
            policy=policy,
            stop_multiplier=args.stop_multiplier,
            target_multiplier=args.target_multiplier,
        )
        path = args.output_dir / f"{policy_name.lower()}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        summary.append(
            {
                "policy": policy_name,
                "report": str(path),
                "signals": payload["signals"],
                "targets": payload["target_count"],
                "stops": payload["stop_count"],
                "trail_stops": payload["trail_stop_count"],
                "total_r": payload["total_r"],
                "expectancy_r": payload["expectancy_r"],
                "maximum_drawdown_r": payload["maximum_drawdown_r"],
                "skipped_overlapping_signals": payload["skipped_overlapping_signals"],
            }
        )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
