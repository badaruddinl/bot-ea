from __future__ import annotations

import argparse
import bisect
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from statistics import fmean


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goldm_revised.replay import RevisedMt5HistoryLoader  # noqa: E402


POLICIES = (
    "NO_MANAGEMENT",
    "CONSERVATIVE",
    "OBSTACLE_AWARE",
    "M5_PERSISTENT",
    "TYPED_STATE",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--stop-multiplier", type=float, default=1.75)
    parser.add_argument("--target-multiplier", type=float, default=2.5)
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    return parser.parse_args()


def _atr(history, period: int = 14) -> float:
    if len(history) < period + 1:
        return 0.0
    values = []
    for previous, current in zip(history[-period - 1 : -1], history[-period:]):
        values.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return fmean(values)


def reversal_evidence(path, index: int, *, entry: float, atr: float) -> dict[str, bool]:
    latest = path[index]
    micro_break = False
    if index >= 3:
        support = min(bar.low for bar in path[index - 3 : index])
        micro_break = latest.close < support and latest.close < latest.open
    momentum = False
    if index >= 2 and atr > 0:
        recent = path[index - 2 : index + 1]
        bearish = sum(bar.close < bar.open for bar in recent) >= 2
        displacement = recent[0].open - recent[-1].close
        close_location = (
            (latest.close - latest.low) / (latest.high - latest.low)
            if latest.high > latest.low
            else 1.0
        )
        momentum = bearish and displacement >= 0.8 * atr and close_location <= 0.35
    acceptance = False
    if index >= 1:
        tolerance = max(0.20, atr * 0.10)
        acceptance = all(
            bar.close < entry - tolerance for bar in path[index - 1 : index + 1]
        )
    m5_persistence = False
    if index >= 9:
        groups = [path[index - 9 : index - 4], path[index - 4 : index + 1]]
        m5_persistence = all(
            len(group) == 5 and group[-1].close < entry for group in groups
        )
    return {
        "micro_break": micro_break,
        "momentum": momentum,
        "acceptance": acceptance,
        "m5_persistence": m5_persistence,
    }


def management_reason(
    *,
    policy: str,
    peak_r: float,
    obstacle_touched: bool,
    near_target: bool,
    bars_since_peak: int,
    evidence: dict[str, bool],
) -> str | None:
    if policy == "NO_MANAGEMENT" or bars_since_peak < 2:
        return None
    micro_momentum = evidence["micro_break"] and evidence["momentum"]
    all_three = micro_momentum and evidence["acceptance"]
    if policy == "CONSERVATIVE":
        if near_target and all_three:
            return "NEAR_TARGET_PERSISTENT_REVERSAL"
        if obstacle_touched and all_three:
            return "OBSTACLE_PERSISTENT_REVERSAL"
        if peak_r >= 1.0 and all_three:
            return "ONE_R_PERSISTENT_INVALIDATION"
    elif policy == "OBSTACLE_AWARE":
        if near_target and micro_momentum:
            return "NEAR_TARGET_MOMENTUM_REVERSAL"
        if obstacle_touched and all_three:
            return "OBSTACLE_PERSISTENT_REVERSAL"
        if peak_r >= 1.0 and all_three:
            return "ONE_R_PERSISTENT_INVALIDATION"
    elif policy == "M5_PERSISTENT":
        if near_target and all_three:
            return "NEAR_TARGET_PERSISTENT_REVERSAL"
        if (
            (obstacle_touched or peak_r >= 1.0)
            and all_three
            and evidence["m5_persistence"]
        ):
            return "M5_PERSISTENT_INVALIDATION"
    elif policy == "TYPED_STATE":
        if 0.50 <= peak_r < 1.0 and all_three:
            return "FAST_FADE_INVALIDATION"
        if near_target and all_three:
            return "NEAR_TARGET_PERSISTENT_REVERSAL"
        if (
            (obstacle_touched or peak_r >= 1.0)
            and all_three
            and evidence["m5_persistence"]
        ):
            return "RUNNER_M5_PERSISTENT_INVALIDATION"
    return None


def replay_policy(report, bars, times, *, policy, stop_multiplier, target_multiplier):
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
        original_risk = abs(entry - float(original["stop"]))
        risk = original_risk * stop_multiplier
        stop = entry - risk
        engine_target = float(original["target"])
        target = entry + (engine_target - entry) * target_multiplier
        if target <= entry:
            invalid += 1
            continue
        target_r = (target - entry) / risk
        obstacle_r = float(original["first_obstacle_r"]) / stop_multiplier
        start_index = bisect.bisect_left(times, opened_at)
        history = bars[max(0, start_index - 20) : start_index]
        atr = _atr(history)
        result = "END_OF_TEST"
        close_reason = "END_OF_TEST"
        closed_at = end
        outcome_r = 0.0
        peak_r = 0.0
        peak_index = 0
        mfe_r = 0.0
        mae_r = 0.0
        path = []
        for bar in bars[start_index:]:
            if bar.time >= end:
                break
            path.append(bar)
            index = len(path) - 1
            current_high_r = (bar.high - entry) / risk
            mfe_r = max(mfe_r, current_high_r)
            mae_r = min(mae_r, (bar.low - entry) / risk)
            if current_high_r > peak_r:
                peak_r = current_high_r
                peak_index = index
            stop_hit = bar.low <= stop
            target_hit = bar.high >= target
            if stop_hit or target_hit:
                closed_at = bar.time + timedelta(minutes=1)
                if stop_hit and target_hit:
                    result = "AMBIGUOUS_SAME_BAR"
                    close_reason = result
                    outcome_r = -1.0
                elif stop_hit:
                    result = "STOP"
                    close_reason = result
                    outcome_r = -1.0
                else:
                    result = "TARGET"
                    close_reason = result
                    outcome_r = target_r
                break
            evidence = reversal_evidence(path, index, entry=entry, atr=atr)
            reason = management_reason(
                policy=policy,
                peak_r=peak_r,
                obstacle_touched=peak_r >= obstacle_r,
                near_target=peak_r >= 0.80 * target_r,
                bars_since_peak=index - peak_index,
                evidence=evidence,
            )
            if reason is None:
                continue
            closed_at = bar.time + timedelta(minutes=1)
            result = "MANAGED_EXIT"
            close_reason = reason
            outcome_r = max(-1.0, min(target_r, (bar.close - entry) / risk))
            break
        if result == "END_OF_TEST":
            last_close = bars[-1].close if bars else entry
            outcome_r = max(-1.0, min(target_r, (last_close - entry) / risk))
        item = dict(original)
        item.update(
            {
                "closed_at": closed_at.isoformat(),
                "result": result,
                "close_reason": close_reason,
                "outcome_r": outcome_r,
                "entry": entry,
                "stop": stop,
                "target": target,
                "engine_target": engine_target,
                "mfe": mfe_r,
                "mae": mae_r,
                "management_policy": policy,
                "peak_r": peak_r,
                "execution_first_obstacle_r": obstacle_r,
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
        "target_count": sum(item["result"] == "TARGET" for item in replayed),
        "stop_count": sum(item["result"] == "STOP" for item in replayed),
        "managed_exit_count": sum(item["result"] == "MANAGED_EXIT" for item in replayed),
        "ambiguous_count": sum(item["result"] == "AMBIGUOUS_SAME_BAR" for item in replayed),
        "total_r": total_r,
        "expectancy_r": total_r / len(replayed) if replayed else 0.0,
        "maximum_drawdown_r": maximum_drawdown,
        "skipped_overlapping_signals": overlap,
        "skipped_invalid_targets": invalid,
        "management_policy": policy,
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
            policy=policy,
            stop_multiplier=args.stop_multiplier,
            target_multiplier=args.target_multiplier,
        )
        path = args.output_dir / f"{policy.lower()}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        reasons = {}
        for item in payload["outcomes"]:
            if item["result"] == "MANAGED_EXIT":
                reasons[item["close_reason"]] = reasons.get(item["close_reason"], 0) + 1
        summary.append(
            {
                "policy": policy,
                "report": str(path),
                "signals": payload["signals"],
                "targets": payload["target_count"],
                "stops": payload["stop_count"],
                "managed_exits": payload["managed_exit_count"],
                "managed_reasons": reasons,
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
