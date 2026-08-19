from __future__ import annotations

import argparse
import bisect
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import fmean, median


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goldm_revised.replay import RevisedMt5HistoryLoader  # noqa: E402


THRESHOLDS = (0.25, 0.50, 0.75, 1.0, 1.5, 2.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _minutes(start: datetime, end: datetime | None) -> float | None:
    return (end - start).total_seconds() / 60.0 if end is not None else None


def _session(hour: int) -> str:
    if 1 <= hour < 8:
        return "ASIA"
    if 8 <= hour < 15:
        return "LONDON"
    if 15 <= hour < 19:
        return "LONDON_NY_OVERLAP"
    return "NEW_YORK_LATE"


def _atr(bars, period: int = 14) -> float:
    if len(bars) < period + 1:
        return 0.0
    values = []
    for previous, current in zip(bars[-period - 1 : -1], bars[-period:]):
        values.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return fmean(values)


def classify_path(mfe_r: float, target_r: float) -> str:
    proximity = mfe_r / target_r if target_r > 0 else 0.0
    if mfe_r >= 1.0 and proximity >= 0.80:
        return "NEAR_TARGET_REVERSAL"
    if mfe_r >= 2.0:
        return "DEEP_RUNNER_FADE"
    if mfe_r >= 1.0:
        return "ONE_R_PLUS_ROUND_TRIP"
    if mfe_r >= 0.50:
        return "MEDIUM_PROFIT_FADE"
    if mfe_r >= 0.25:
        return "SHALLOW_PROFIT_FADE"
    return "NO_MEANINGFUL_PROFIT"


def _first_momentum_reversal(path, peak_index: int, atr: float):
    if atr <= 0:
        return None
    for index in range(max(peak_index + 1, 2), len(path)):
        window = path[index - 2 : index + 1]
        bearish = sum(bar.close < bar.open for bar in window) >= 2
        displacement = window[0].open - window[-1].close
        latest = window[-1]
        close_location = (
            (latest.close - latest.low) / (latest.high - latest.low)
            if latest.high > latest.low
            else 1.0
        )
        if bearish and displacement >= 0.8 * atr and close_location <= 0.35:
            return latest.time + timedelta(minutes=1)
    return None


def _first_micro_break(path, peak_index: int):
    for index in range(max(peak_index + 1, 3), len(path)):
        support = min(bar.low for bar in path[index - 3 : index])
        latest = path[index]
        if latest.close < support and latest.close < latest.open:
            return latest.time + timedelta(minutes=1)
    return None


def _first_acceptance_below_entry(path, peak_index: int, entry: float, atr: float):
    tolerance = max(0.20, atr * 0.10)
    for index in range(max(peak_index + 1, 1), len(path)):
        if all(
            bar.close < entry - tolerance
            for bar in path[index - 1 : index + 1]
        ):
            return path[index].time + timedelta(minutes=1)
    return None


def _group_summary(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[str(row.get(key))].append(row)
    result = []
    for value, items in groups.items():
        result.append(
            {
                key: value,
                "count": len(items),
                "share_percent": len(items) / len(rows) * 100.0 if rows else 0.0,
                "mean_mfe_r": fmean(item["mfe_r"] for item in items),
                "median_peak_to_stop_minutes": median(
                    item["peak_to_stop_minutes"] for item in items
                ),
                "mean_target_r": fmean(item["target_r"] for item in items),
                "mean_obstacle_r": fmean(
                    item["execution_first_obstacle_r"] for item in items
                ),
                "near_target_count": sum(
                    item["archetype"] == "NEAR_TARGET_REVERSAL" for item in items
                ),
                "momentum_reversal_detected_percent": sum(
                    item["momentum_reversal_minutes_after_peak"] is not None
                    for item in items
                )
                / len(items)
                * 100.0,
            }
        )
    return sorted(result, key=lambda item: item["count"], reverse=True)


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
    rows = []
    for outcome in report["outcomes"]:
        if outcome["result"] != "STOP":
            continue
        entry = float(outcome["entry"])
        stop = float(outcome["stop"])
        target = float(outcome["target"])
        risk = abs(entry - stop)
        opened_at = datetime.fromisoformat(outcome["opened_at"])
        closed_at = datetime.fromisoformat(outcome["closed_at"])
        start_index = bisect.bisect_left(times, opened_at)
        end_index = bisect.bisect_left(times, closed_at)
        path = bars[start_index:end_index]
        if not path or risk <= 0:
            continue
        history = bars[max(0, start_index - 20) : start_index]
        atr_m1 = _atr(history)
        peak_index = max(
            range(len(path)),
            key=lambda index: path[index].high,
        )
        peak_bar = path[peak_index]
        mfe_r = (peak_bar.high - entry) / risk
        target_r = (target - entry) / risk
        peak_time = peak_bar.time + timedelta(minutes=1)
        first_threshold = {}
        for threshold in THRESHOLDS:
            touched = next(
                (
                    bar.time + timedelta(minutes=1)
                    for bar in path
                    if bar.high >= entry + threshold * risk
                ),
                None,
            )
            first_threshold[str(threshold)] = (
                touched.isoformat() if touched is not None else None
            )
        post_peak = path[peak_index + 1 :]
        returned_to_entry = next(
            (
                bar.time + timedelta(minutes=1)
                for bar in post_peak
                if bar.low <= entry
            ),
            None,
        )
        closed_below_entry = next(
            (
                bar.time + timedelta(minutes=1)
                for bar in post_peak
                if bar.close <= entry
            ),
            None,
        )
        micro_break = _first_micro_break(path, peak_index)
        momentum_reversal = _first_momentum_reversal(path, peak_index, atr_m1)
        acceptance = _first_acceptance_below_entry(
            path,
            peak_index,
            entry,
            atr_m1,
        )
        regime = outcome.get("market_regime") or {}
        supply = outcome.get("supply_zone") or {}
        demand = outcome.get("demand_zone") or {}
        row = {
            "opened_at": opened_at.isoformat(),
            "closed_at": closed_at.isoformat(),
            "entry_hour": opened_at.hour,
            "session": _session(opened_at.hour),
            "duration_minutes": _minutes(opened_at, closed_at),
            "mfe_r": mfe_r,
            "mae_r": float(outcome["mae"]),
            "target_r": target_r,
            "target_proximity": mfe_r / target_r if target_r > 0 else 0.0,
            "archetype": classify_path(mfe_r, target_r),
            "time_to_peak_minutes": _minutes(opened_at, peak_time),
            "peak_to_stop_minutes": _minutes(peak_time, closed_at),
            "return_to_entry_minutes_after_peak": _minutes(peak_time, returned_to_entry),
            "close_below_entry_minutes_after_peak": _minutes(peak_time, closed_below_entry),
            "micro_break_minutes_after_peak": _minutes(peak_time, micro_break),
            "momentum_reversal_minutes_after_peak": _minutes(peak_time, momentum_reversal),
            "acceptance_below_entry_minutes_after_peak": _minutes(peak_time, acceptance),
            "first_threshold_times": first_threshold,
            "m5_pattern": outcome.get("m5_pattern"),
            "confirmation_mode": outcome.get("confirmation_mode"),
            "retest_count": int(outcome.get("retest_count", 0)),
            "obstacle_kind": outcome.get("obstacle_kind"),
            "execution_first_obstacle_r": float(
                outcome.get("execution_first_obstacle_r", 0.0)
            ),
            "target_beyond_first_obstacle": target_r
            > float(outcome.get("execution_first_obstacle_r", 0.0)),
            "above_h1_sma20": bool(regime.get("above_h1_sma20")),
            "h1_trend_atr": float(regime.get("h1_trend_atr", 0.0)),
            "h1_efficiency": float(regime.get("h1_efficiency", 0.0)),
            "m5_atr_expansion": float(regime.get("m5_atr_expansion", 0.0)),
            "supply_kind": supply.get("kind"),
            "supply_distance": supply.get("distance"),
            "demand_kind": demand.get("kind"),
            "demand_distance": demand.get("distance"),
        }
        rows.append(row)
    profitable_fades = [row for row in rows if row["mfe_r"] >= 0.25]
    winner_controls = []
    for outcome in report["outcomes"]:
        if outcome["result"] != "TARGET":
            continue
        entry = float(outcome["entry"])
        stop = float(outcome["stop"])
        risk = abs(entry - stop)
        opened_at = datetime.fromisoformat(outcome["opened_at"])
        closed_at = datetime.fromisoformat(outcome["closed_at"])
        start_index = bisect.bisect_left(times, opened_at)
        end_index = bisect.bisect_left(times, closed_at)
        path = bars[start_index:end_index]
        if not path or risk <= 0:
            continue
        threshold_index = next(
            (
                index
                for index, bar in enumerate(path)
                if bar.high >= entry + 0.50 * risk
            ),
            None,
        )
        if threshold_index is None:
            continue
        history = bars[max(0, start_index - 20) : start_index]
        atr_m1 = _atr(history)
        after_threshold = path[threshold_index + 1 :]
        winner_controls.append(
            {
                "returned_to_entry": any(bar.low <= entry for bar in after_threshold),
                "closed_below_entry": any(
                    bar.close <= entry for bar in after_threshold
                ),
                "micro_break": _first_micro_break(path, threshold_index) is not None,
                "momentum_reversal": _first_momentum_reversal(
                    path,
                    threshold_index,
                    atr_m1,
                )
                is not None,
                "acceptance_below_entry": _first_acceptance_below_entry(
                    path,
                    threshold_index,
                    entry,
                    atr_m1,
                )
                is not None,
                "target_r": (float(outcome["target"]) - entry) / risk,
            }
        )
    payload = {
        "source_report": str(args.report),
        "all_stop_count": len(rows),
        "profitable_fade_count": len(profitable_fades),
        "threshold_counts": {
            str(threshold): sum(row["mfe_r"] >= threshold for row in rows)
            for threshold in THRESHOLDS
        },
        "archetypes": _group_summary(profitable_fades, "archetype"),
        "hours": _group_summary(profitable_fades, "entry_hour"),
        "sessions": _group_summary(profitable_fades, "session"),
        "patterns": _group_summary(profitable_fades, "m5_pattern"),
        "confirmation_modes": _group_summary(profitable_fades, "confirmation_mode"),
        "obstacle_kinds": _group_summary(profitable_fades, "obstacle_kind"),
        "winner_after_0p5r_control": {
            "count": len(winner_controls),
            "returned_to_entry_count": sum(
                item["returned_to_entry"] for item in winner_controls
            ),
            "closed_below_entry_count": sum(
                item["closed_below_entry"] for item in winner_controls
            ),
            "micro_break_count": sum(item["micro_break"] for item in winner_controls),
            "momentum_reversal_count": sum(
                item["momentum_reversal"] for item in winner_controls
            ),
            "acceptance_below_entry_count": sum(
                item["acceptance_below_entry"] for item in winner_controls
            ),
            "micro_momentum_acceptance_count": sum(
                item["micro_break"]
                and item["momentum_reversal"]
                and item["acceptance_below_entry"]
                for item in winner_controls
            ),
            "mean_target_r": fmean(
                item["target_r"] for item in winner_controls
            )
            if winner_controls
            else None,
        },
        "profitable_stop_invalidation_combinations": {
            "micro_momentum_acceptance_count": sum(
                row["micro_break_minutes_after_peak"] is not None
                and row["momentum_reversal_minutes_after_peak"] is not None
                and row["acceptance_below_entry_minutes_after_peak"] is not None
                for row in profitable_fades
            ),
            "micro_and_momentum_count": sum(
                row["micro_break_minutes_after_peak"] is not None
                and row["momentum_reversal_minutes_after_peak"] is not None
                for row in profitable_fades
            ),
        },
        "rows": profitable_fades,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    printable = {key: value for key, value in payload.items() if key != "rows"}
    print(json.dumps(printable, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
