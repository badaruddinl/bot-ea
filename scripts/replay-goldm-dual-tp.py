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


POLICIES = (
    "FULL_TP2",
    "FULL_TP1",
    "SPLIT_KEEP_STOP",
    "SPLIT_BE_AFTER_TP1",
    "SPLIT_PROFIT_LOCK_AFTER_TP1",
    "FULL_TP2_BE_AFTER_TP1",
    "ENGINE_BE_AFTER_TP1",
    "ENGINE_PARTIAL_KEEP_STOP",
    "ENGINE_PARTIAL_BE",
    "ENGINE_PARTIAL_PROFIT_LOCK",
    "ADAPTIVE_ENGINE",
)

PROFIT_LOCK_RETAINED_FRACTION = 0.25


def adaptive_runner_fraction(side: str, outcome, tp1_r: float, tp2_r: float) -> float:
    """Map causal engine evidence to executable 0/0.01/0.02 runner allocation."""

    score = 0
    if side == "BUY":
        obstacle_r = float(
            outcome.get("execution_first_obstacle_r")
            or outcome.get("first_obstacle_r", 0.0)
        )
        target_obstacle_ratio = tp2_r / obstacle_r if obstacle_r > 0 else 99.0
        score += 2 if obstacle_r >= 1.5 else 1 if obstacle_r >= 1.0 else -2
        score += 1 if target_obstacle_ratio <= 2.0 else -2 if target_obstacle_ratio > 3.0 else 0
        if outcome.get("confirmation_mode") == "MOMENTUM":
            score += 1
        if outcome.get("m5_pattern") in {
            "BULL_ENGULFING",
            "BULL_MORNING_STAR",
        }:
            score += 1
        regime = outcome.get("market_regime") or {}
        if float(regime.get("h1_trend_atr", 0.0)) >= 2.0:
            score += 1
        if float(regime.get("m5_atr_expansion", 0.0)) >= 1.0:
            score += 1
        if int(outcome.get("retest_count", 0)) >= 2:
            score += 1
        return 1.0 if score >= 5 else 0.5 if score >= 2 else 0.0

    target_ratio = tp2_r / tp1_r if tp1_r > 0 else 99.0
    score += 2 if int(outcome.get("m5_rejections", 0)) >= 2 else 0
    score += 1 if int(outcome.get("m5_touches", 0)) >= 2 else 0
    score += 1 if int(outcome.get("m1_touches", 0)) >= 2 else 0
    score += 1 if target_ratio <= 2.0 else -1 if target_ratio > 3.0 else 0
    if outcome.get("target_crosses_structural_support"):
        score -= 1
    reason = str(outcome.get("setup_reason", ""))
    if "continuation_through_near_support" in reason:
        score += 1
    if "target_capped_at_nearest_psychological_support" in reason:
        score -= 1
    return 1.0 if score >= 4 else 0.5 if score >= 2 else 0.0


def engine_partial_runner_fraction(
    side: str,
    outcome,
    tp1_r: float,
    tp2_r: float,
    *,
    risk_atr_limit: float = 1.0,
) -> float:
    """Choose whether a 0.02 position needs a 0.01 structural partial.

    The price of TP1 is supplied by the engine and is never derived from the
    TP2 midpoint. BUY partials require a close structural TP1, a materially
    farther TP2, and an entry stop tighter than one M5 ATR. The ATR condition
    prevents wide-dollar-risk setups from dominating fixed-lot cash results.
    No SELL sample justified reducing its runner, so SELL remains full-size
    until separate causal evidence exists.
    """

    target_ratio = tp2_r / tp1_r if tp1_r > 0 else 99.0
    market_regime = outcome.get("market_regime") or {}
    m5_atr = float(market_regime.get("m5_atr", 0.0))
    entry = float(outcome.get("entry", 0.0))
    stop = float(outcome.get("stop", entry))
    risk_atr = abs(entry - stop) / m5_atr if m5_atr > 0.0 else 99.0
    if side == "BUY" and bool(
        outcome.get("confirmation_mode") == "RANGE"
        and 0.75 <= tp1_r < 1.0
        and target_ratio >= 2.0
        and risk_atr < risk_atr_limit
    ):
        return 0.5
    return 1.0


def policy_runner_fraction(
    policy: str,
    side: str,
    outcome,
    tp1_r: float,
    tp2_r: float,
    *,
    partial_risk_atr_limit: float = 1.0,
) -> float:
    if policy == "FULL_TP2":
        return 1.0
    if policy in {"FULL_TP2_BE_AFTER_TP1", "ENGINE_BE_AFTER_TP1"}:
        return 1.0
    if policy == "FULL_TP1":
        return 0.0
    if policy in {
        "SPLIT_KEEP_STOP",
        "SPLIT_BE_AFTER_TP1",
        "SPLIT_PROFIT_LOCK_AFTER_TP1",
    }:
        return 0.5
    if policy in {
        "ENGINE_PARTIAL_KEEP_STOP",
        "ENGINE_PARTIAL_BE",
        "ENGINE_PARTIAL_PROFIT_LOCK",
    }:
        return engine_partial_runner_fraction(
            side,
            outcome,
            tp1_r,
            tp2_r,
            risk_atr_limit=partial_risk_atr_limit,
        )
    return adaptive_runner_fraction(side, outcome, tp1_r, tp2_r)


def engine_should_move_be(side: str, outcome, tp1_r: float, tp2_r: float) -> bool:
    target_ratio = tp2_r / tp1_r if tp1_r > 0 else 99.0
    if side == "BUY":
        return bool(
            outcome.get("confirmation_mode") == "RANGE"
            and float(outcome.get("execution_first_obstacle_r", 0.0)) >= 1.0
            and target_ratio >= 2.0
        )
    return bool(
        int(outcome.get("m1_touches", 0)) >= 2
        and bool(outcome.get("target_crosses_structural_support"))
        and target_ratio >= 1.5
    )


def policy_moves_be_after_tp1(
    policy: str,
    side: str,
    outcome,
    tp1_r: float,
    tp2_r: float,
    runner_fraction: float,
) -> bool:
    """Return the entry-time BEP decision for the remaining runner.

    ENGINE_PARTIAL_BE is intentionally different from ENGINE_BE_AFTER_TP1:
    it moves the stop only when the engine selected an executable 0.01/0.01
    partial allocation. Strong setups keep the full 0.02 runner and its
    structural stop. The policy does not force a TP1-only exit.
    """

    if policy in {"SPLIT_BE_AFTER_TP1", "FULL_TP2_BE_AFTER_TP1"}:
        return runner_fraction > 0.0
    if policy == "ENGINE_BE_AFTER_TP1":
        return runner_fraction > 0.0 and engine_should_move_be(
            side,
            outcome,
            tp1_r,
            tp2_r,
        )
    if policy == "ENGINE_PARTIAL_BE":
        return runner_fraction == 0.5
    return False


def profit_lock_runner_stop_r(
    tp1_r: float,
    tp1_fraction: float,
    runner_fraction: float,
    *,
    retained_fraction: float = PROFIT_LOCK_RETAINED_FRACTION,
) -> float:
    """Return a sub-BEP runner stop that keeps basket P/L positive.

    The retained fraction applies to realized TP1 profit, not to TP2 distance.
    The stop is clamped to the original -1R risk and never placed beyond BEP.
    """

    if not 0.0 < runner_fraction < 1.0:
        raise ValueError("profit lock requires a partial allocation")
    if not 0.0 < retained_fraction < 1.0:
        raise ValueError("retained fraction must be between zero and one")
    realized_r = tp1_fraction * tp1_r
    basket_floor_r = realized_r * retained_fraction
    runner_stop_r = (basket_floor_r - realized_r) / runner_fraction
    return max(-1.0, min(0.0, runner_stop_r))


def policy_uses_profit_lock(policy: str, runner_fraction: float) -> bool:
    return bool(
        policy
        in {
            "SPLIT_PROFIT_LOCK_AFTER_TP1",
            "ENGINE_PARTIAL_PROFIT_LOCK",
        }
        and 0.0 < runner_fraction < 1.0
    )


def allocation_mode(runner_fraction: float) -> str:
    if runner_fraction == 0.0:
        return "FULL_TP1"
    if runner_fraction == 0.5:
        return "PARTIAL_TP1_RUNNER_TP2"
    if runner_fraction == 1.0:
        return "FULL_TP2"
    raise ValueError(f"unsupported runner fraction: {runner_fraction}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--side", choices=("BUY", "SELL"), required=True)
    parser.add_argument("--tp1-field", required=True)
    parser.add_argument("--tp2-field", default="target")
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--policy",
        action="append",
        choices=POLICIES,
        help="Replay only the selected policy; repeat for multiple policies.",
    )
    parser.add_argument("--partial-risk-atr-limit", type=float, default=1.0)
    return parser.parse_args()


def replay_policy(
    report,
    bars,
    times,
    *,
    side,
    tp1_field,
    tp2_field,
    policy,
    partial_risk_atr_limit=1.0,
):
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
        runner_fraction = policy_runner_fraction(
            policy,
            side,
            original,
            tp1_r,
            tp2_r,
            partial_risk_atr_limit=partial_risk_atr_limit,
        )
        tp1_fraction = 1.0 - runner_fraction
        move_be_after_tp1 = policy_moves_be_after_tp1(
            policy,
            side,
            original,
            tp1_r,
            tp2_r,
            runner_fraction,
        )
        use_profit_lock = policy_uses_profit_lock(policy, runner_fraction)
        runner_stop_after_tp1_r = (
            profit_lock_runner_stop_r(
                tp1_r,
                tp1_fraction,
                runner_fraction,
            )
            if use_profit_lock
            else 0.0 if move_be_after_tp1 else -1.0
        )
        active_stop = stop
        tp1_taken = False
        tp1_taken_at = None
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
                    outcome_r = tp1_fraction * tp1_r + runner_fraction * tp2_r
                    tp1_taken = True
                    tp1_taken_at = closed_at
                    break
                if tp1_hit:
                    tp1_taken = True
                    tp1_taken_at = bar.time + timedelta(minutes=1)
                    if runner_fraction <= 0.0:
                        closed_at = bar.time + timedelta(minutes=1)
                        result = "TP1"
                        outcome_r = tp1_r
                        break
                    if use_profit_lock:
                        active_stop = (
                            entry + risk * runner_stop_after_tp1_r
                            if side == "BUY"
                            else entry - risk * runner_stop_after_tp1_r
                        )
                    elif move_be_after_tp1:
                        active_stop = entry
                    continue
            else:
                if stop_hit and tp2_hit:
                    closed_at = bar.time + timedelta(minutes=1)
                    result = "AMBIGUOUS_AFTER_TP1"
                    remaining_r = (active_stop - entry) / risk if side == "BUY" else (entry - active_stop) / risk
                    outcome_r = tp1_fraction * tp1_r + runner_fraction * remaining_r
                    break
                if stop_hit:
                    closed_at = bar.time + timedelta(minutes=1)
                    result = "STOP_AFTER_TP1"
                    remaining_r = (active_stop - entry) / risk if side == "BUY" else (entry - active_stop) / risk
                    outcome_r = tp1_fraction * tp1_r + runner_fraction * remaining_r
                    break
                if tp2_hit:
                    closed_at = bar.time + timedelta(minutes=1)
                    result = "TP2"
                    outcome_r = tp1_fraction * tp1_r + runner_fraction * tp2_r
                    break
        if result == "END_OF_TEST":
            last_close = bars[-1].close if bars else entry
            current_r = (
                (last_close - entry) / risk
                if side == "BUY"
                else (entry - last_close) / risk
            )
            outcome_r = (
                tp1_fraction * tp1_r + runner_fraction * current_r
                if tp1_taken
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
                "tp1_taken_at": (
                    tp1_taken_at.isoformat() if tp1_taken_at is not None else None
                ),
                "tp1_fraction": tp1_fraction,
                "runner_fraction": runner_fraction,
                "allocation_mode": allocation_mode(runner_fraction),
                "partial_close_taken": bool(
                    tp1_taken and 0.0 < tp1_fraction < 1.0
                ),
                "engine_be_enabled": move_be_after_tp1,
                "profit_lock_enabled": use_profit_lock,
                "runner_stop_after_tp1_r": runner_stop_after_tp1_r,
                "locked_basket_profit_r": (
                    tp1_fraction * tp1_r
                    + runner_fraction * runner_stop_after_tp1_r
                    if use_profit_lock
                    else None
                ),
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
        "tp1_only_count": sum(item["runner_fraction"] == 0.0 for item in replayed),
        "split_count": sum(item["runner_fraction"] == 0.5 for item in replayed),
        "tp2_only_count": sum(item["runner_fraction"] == 1.0 for item in replayed),
        "partial_close_count": sum(item["partial_close_taken"] for item in replayed),
        "engine_be_enabled_count": sum(item["engine_be_enabled"] for item in replayed),
        "profit_lock_enabled_count": sum(item["profit_lock_enabled"] for item in replayed),
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
    for policy in args.policy or POLICIES:
        payload = replay_policy(
            report,
            bars,
            times,
            side=args.side,
            tp1_field=args.tp1_field,
            tp2_field=args.tp2_field,
            policy=policy,
            partial_risk_atr_limit=args.partial_risk_atr_limit,
        )
        path = args.output_dir / f"{policy.lower()}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        summary.append(
            {
                "policy": policy,
                "partial_risk_atr_limit": args.partial_risk_atr_limit,
                "report": str(path),
                "signals": payload["signals"],
                "tp1": payload["tp1_count"],
                "tp2": payload["tp2_count"],
                "stop_before_tp1": payload["stop_before_tp1_count"],
                "stop_after_tp1": payload["stop_after_tp1_count"],
                "tp1_only": payload["tp1_only_count"],
                "split": payload["split_count"],
                "tp2_only": payload["tp2_only_count"],
                "partial_close": payload["partial_close_count"],
                "engine_be_enabled": payload["engine_be_enabled_count"],
                "profit_lock_enabled": payload["profit_lock_enabled_count"],
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
