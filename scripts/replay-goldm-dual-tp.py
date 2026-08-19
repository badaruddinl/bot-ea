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


POLICIES = ("FULL_TP2", "FULL_TP1", "SPLIT_KEEP_STOP", "SPLIT_BE_AFTER_TP1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--side", choices=("BUY", "SELL"), required=True)
    parser.add_argument("--tp1-field", required=True)
    parser.add_argument("--tp2-field", default="target")
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    return parser.parse_args()


def replay_policy(report, bars, times, *, side, tp1_field, tp2_field, policy):
    start = datetime.fromisoformat(report["from_time"])
    end = datetime.fromisoformat(report["to_time"])
    replayed = []
    unavailable_until = start
    overlap = 0
    invalid = 0
    for original in sorted(report["outcomes"], key=lambda item: item["opened_at"]):
        opened_at = datetime.fromisoformat(original["opened_at"])
        if opened_at < unavailable_until:
            overlap += 1
            continue
        entry = float(original["entry"])
        stop = float(original["stop"])
        first_candidate = float(original[tp1_field])
        second_candidate = float(original[tp2_field])
        if side == "BUY":
            tp1 = min(first_candidate, second_candidate)
            tp2 = max(first_candidate, second_candidate)
        else:
            tp1 = max(first_candidate, second_candidate)
            tp2 = min(first_candidate, second_candidate)
        risk = abs(entry - stop)
        valid = (
            entry < tp1 < tp2 if side == "BUY" else tp2 < tp1 < entry
        ) and risk > 0
        if not valid:
            invalid += 1
            continue
        tp1_r = abs(tp1 - entry) / risk
        tp2_r = abs(tp2 - entry) / risk
        active_stop = stop
        tp1_taken = False
        result = "END_OF_TEST"
        closed_at = end
        outcome_r = 0.0
        mfe_r = 0.0
        mae_r = 0.0
        start_index = bisect.bisect_left(times, opened_at)
        for bar in bars[start_index:]:
            if bar.time >= end:
                break
            if side == "BUY":
                mfe_r = max(mfe_r, (bar.high - entry) / risk)
                mae_r = min(mae_r, (bar.low - entry) / risk)
                stop_hit = bar.low <= active_stop
                tp1_hit = bar.high >= tp1
                tp2_hit = bar.high >= tp2
            else:
                mfe_r = max(mfe_r, (entry - bar.low) / risk)
                mae_r = min(mae_r, (entry - bar.high) / risk)
                stop_hit = bar.high >= active_stop
                tp1_hit = bar.low <= tp1
                tp2_hit = bar.low <= tp2
            if not tp1_taken:
                if stop_hit and tp1_hit:
                    closed_at = bar.time + timedelta(minutes=1)
                    result = "AMBIGUOUS_SAME_BAR"
                    outcome_r = -1.0
                    break
                if stop_hit:
                    closed_at = bar.time + timedelta(minutes=1)
                    result = "STOP_BEFORE_TP1"
                    outcome_r = -1.0
                    break
                if tp2_hit:
                    closed_at = bar.time + timedelta(minutes=1)
                    result = "TP2"
                    outcome_r = (
                        tp2_r
                        if policy == "FULL_TP2"
                        else tp1_r
                        if policy == "FULL_TP1"
                        else 0.5 * tp1_r + 0.5 * tp2_r
                    )
                    tp1_taken = True
                    break
                if tp1_hit:
                    tp1_taken = True
                    if policy == "FULL_TP1":
                        closed_at = bar.time + timedelta(minutes=1)
                        result = "TP1"
                        outcome_r = tp1_r
                        break
                    if policy == "SPLIT_BE_AFTER_TP1":
                        active_stop = entry
                    continue
            else:
                if stop_hit and tp2_hit:
                    closed_at = bar.time + timedelta(minutes=1)
                    result = "AMBIGUOUS_AFTER_TP1"
                    remaining_r = (active_stop - entry) / risk if side == "BUY" else (entry - active_stop) / risk
                    outcome_r = (
                        remaining_r
                        if policy == "FULL_TP2"
                        else 0.5 * tp1_r + 0.5 * remaining_r
                    )
                    break
                if stop_hit:
                    closed_at = bar.time + timedelta(minutes=1)
                    result = "STOP_AFTER_TP1"
                    remaining_r = (active_stop - entry) / risk if side == "BUY" else (entry - active_stop) / risk
                    outcome_r = (
                        remaining_r
                        if policy == "FULL_TP2"
                        else 0.5 * tp1_r + 0.5 * remaining_r
                    )
                    break
                if tp2_hit:
                    closed_at = bar.time + timedelta(minutes=1)
                    result = "TP2"
                    outcome_r = (
                        tp2_r
                        if policy == "FULL_TP2"
                        else 0.5 * tp1_r + 0.5 * tp2_r
                    )
                    break
        if result == "END_OF_TEST":
            last_close = bars[-1].close if bars else entry
            current_r = (
                (last_close - entry) / risk
                if side == "BUY"
                else (entry - last_close) / risk
            )
            outcome_r = (
                0.5 * tp1_r + 0.5 * current_r
                if tp1_taken and policy.startswith("SPLIT")
                else current_r
            )
        item = dict(original)
        item.update(
            {
                "closed_at": closed_at.isoformat(),
                "result": result,
                "outcome_r": outcome_r,
                "entry": entry,
                "stop": stop,
                "target": tp2,
                "tp1": tp1,
                "tp2": tp2,
                "tp1_r": tp1_r,
                "tp2_r": tp2_r,
                "tp1_taken": tp1_taken,
                "mfe": mfe_r,
                "mae": mae_r,
                "dual_tp_policy": policy,
            }
        )
        replayed.append(item)
        unavailable_until = closed_at
    equity = peak = maximum_drawdown = 0.0
    for item in sorted(replayed, key=lambda value: value["closed_at"]):
        equity += float(item["outcome_r"])
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
    total_r = sum(float(item["outcome_r"]) for item in replayed)
    return {
        **report,
        "outcomes": replayed,
        "signals": len(replayed),
        "tp1_count": sum(item["tp1_taken"] for item in replayed),
        "tp2_count": sum(item["result"] == "TP2" for item in replayed),
        "stop_before_tp1_count": sum(item["result"] == "STOP_BEFORE_TP1" for item in replayed),
        "stop_after_tp1_count": sum(item["result"] == "STOP_AFTER_TP1" for item in replayed),
        "total_r": total_r,
        "expectancy_r": total_r / len(replayed) if replayed else 0.0,
        "maximum_drawdown_r": maximum_drawdown,
        "skipped_overlapping_signals": overlap,
        "skipped_invalid_targets": invalid,
        "dual_tp_policy": policy,
        "side": side,
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
    times = [bar.time for bar in bars]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for policy in POLICIES:
        payload = replay_policy(
            report,
            bars,
            times,
            side=args.side,
            tp1_field=args.tp1_field,
            tp2_field=args.tp2_field,
            policy=policy,
        )
        path = args.output_dir / f"{policy.lower()}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        summary.append(
            {
                "policy": policy,
                "report": str(path),
                "signals": payload["signals"],
                "tp1": payload["tp1_count"],
                "tp2": payload["tp2_count"],
                "stop_before_tp1": payload["stop_before_tp1_count"],
                "stop_after_tp1": payload["stop_after_tp1_count"],
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
