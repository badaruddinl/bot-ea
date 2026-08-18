from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcile production baseline events against read-only MT5 bars."
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--from-server-time", required=True)
    parser.add_argument("--to-server-time", required=True)
    parser.add_argument("--server-utc-offset", default="+03:00")
    parser.add_argument("--psychological-step", type=float, default=10.0)
    return parser


def _offset(value: str) -> timezone:
    if len(value) != 6 or value[0] not in "+-" or value[3] != ":":
        raise ValueError("server UTC offset must use +HH:MM or -HH:MM")
    sign = 1 if value[0] == "+" else -1
    return timezone(
        sign
        * timedelta(
            hours=int(value[1:3]),
            minutes=int(value[4:6]),
        )
    )


def _server_timestamp(value: str, server_timezone: timezone) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=server_timezone)
    return parsed.astimezone(server_timezone)


def _utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _float(fields: dict[str, Any], key: str) -> float:
    return float(fields[key])


def _nearest_psychological_above(price: float, step: float) -> float:
    level = math.ceil((price - 1e-12) / step) * step
    if level <= price:
        level += step
    return round(level, 8)


def _average_true_range(bars: Sequence[dict[str, float]], period: int = 14) -> float:
    if len(bars) < period + 1:
        return 0.0
    true_ranges = []
    for previous, current in zip(bars[-(period + 1) : -1], bars[-period:]):
        true_ranges.append(
            max(
                current["high"] - current["low"],
                abs(current["high"] - previous["close"]),
                abs(current["low"] - previous["close"]),
            )
        )
    return sum(true_ranges) / len(true_ranges)


def _swing_highs(bars: Sequence[dict[str, float]], span: int = 2) -> list[float]:
    values: list[float] = []
    for index in range(span, len(bars) - span):
        pivot = bars[index]["high"]
        neighbours = list(bars[index - span : index]) + list(
            bars[index + 1 : index + span + 1]
        )
        if all(pivot > bar["high"] for bar in neighbours):
            values.append(pivot)
    return values


def _first_touch(
    bars: Sequence[dict[str, Any]],
    *,
    side: str,
    stop: float,
    target: float,
) -> dict[str, Any]:
    maximum_favorable = 0.0
    maximum_adverse = 0.0
    for bar in bars:
        if side == "BUY":
            maximum_favorable = max(maximum_favorable, bar["high"])
            maximum_adverse = min(maximum_adverse or bar["low"], bar["low"])
            stop_touched = bar["low"] <= stop
            target_touched = bar["high"] >= target
        else:
            maximum_favorable = min(maximum_favorable or bar["low"], bar["low"])
            maximum_adverse = max(maximum_adverse, bar["high"])
            stop_touched = bar["high"] >= stop
            target_touched = bar["low"] <= target
        if stop_touched and target_touched:
            return {"event": "AMBIGUOUS_SAME_BAR", "time": bar["time"]}
        if target_touched:
            return {"event": "TARGET", "time": bar["time"]}
        if stop_touched:
            return {"event": "STOP", "time": bar["time"]}
    return {"event": "OPEN", "time": None}


def _first_level_touch(
    bars: Sequence[dict[str, Any]],
    *,
    side: str,
    level: float,
) -> datetime | None:
    for bar in bars:
        if (side == "BUY" and bar["high"] >= level) or (
            side == "SELL" and bar["low"] <= level
        ):
            return bar["time"]
    return None


def _load_plans(
    db_path: Path,
    *,
    start_utc: datetime,
    end_utc: datetime,
) -> list[dict[str, Any]]:
    connection = sqlite3.connect(
        f"file:{db_path.resolve(strict=True).as_posix()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            """
            SELECT setup_id, event_type, payload_json
            FROM signal_outbox
            WHERE event_type IN ('SNIPER_SIGNAL', 'SNIPER_OUTCOME')
            ORDER BY id ASC
            """
        ).fetchall()
    finally:
        connection.close()
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        generated = _utc_timestamp(str(payload["generated_at_utc"]))
        if not start_utc <= generated < end_utc:
            continue
        grouped.setdefault(str(row["setup_id"]), {})[str(row["event_type"])] = payload
    plans: list[dict[str, Any]] = []
    for setup_id, events in grouped.items():
        signal = events.get("SNIPER_SIGNAL")
        if signal is None:
            continue
        fields = signal["fields"]
        outcome = events.get("SNIPER_OUTCOME")
        plans.append(
            {
                "setup_id": setup_id,
                "side": str(fields["side"]),
                "entry": _float(fields, "entry"),
                "stop": _float(fields, "stop"),
                "target": _float(fields, "target"),
                "projected_r": _float(fields, "projectedR"),
                "signal_utc": _utc_timestamp(str(signal["generated_at_utc"])),
                "outcome": outcome,
            }
        )
    return sorted(plans, key=lambda plan: plan["signal_utc"])


def _rates(mt5, symbol: str, timeframe: int, start: datetime, end: datetime):
    raw = mt5.copy_rates_range(symbol, timeframe, start, end)
    if raw is None:
        raise RuntimeError(f"MT5 CopyRates failed: {mt5.last_error()}")
    return [
        {
            "time": datetime.fromtimestamp(int(rate["time"]), tz=timezone.utc),
            "open": float(rate["open"]),
            "high": float(rate["high"]),
            "low": float(rate["low"]),
            "close": float(rate["close"]),
        }
        for rate in raw
    ]


def reconcile(mt5, *, symbol: str, plans, end_utc: datetime, psych_step: float):
    results = []
    for plan in plans:
        signal_utc = plan["signal_utc"]
        m15 = [
            bar
            for bar in _rates(
                mt5,
                symbol,
                mt5.TIMEFRAME_M15,
                signal_utc - timedelta(days=4),
                signal_utc,
            )
            if bar["time"] + timedelta(minutes=15) <= signal_utc
        ]
        m1 = _rates(mt5, symbol, mt5.TIMEFRAME_M1, signal_utc, end_utc)
        atr = _average_true_range(m15)
        psych = _nearest_psychological_above(plan["entry"], psych_step)
        swing_candidates = [level for level in _swing_highs(m15[-48:]) if level > plan["entry"]]
        swing = min(swing_candidates) if swing_candidates else None
        obstacle = min([value for value in (psych, swing) if value is not None])
        buffer = max(0.20, 0.08 * atr)
        safe_target = obstacle - buffer
        original = _first_touch(
            m1,
            side=plan["side"],
            stop=plan["stop"],
            target=plan["target"],
        )
        outcome_payload = plan["outcome"]
        outcome_fields = outcome_payload.get("fields", {}) if outcome_payload else {}
        exit_utc = (
            _utc_timestamp(str(outcome_payload["generated_at_utc"]))
            if outcome_payload
            else None
        )
        after_exit = [bar for bar in m1 if exit_utc is not None and bar["time"] >= exit_utc]
        result = {
            "setup_id": plan["setup_id"],
            "side": plan["side"],
            "signal_server": signal_utc,
            "entry": plan["entry"],
            "stop": plan["stop"],
            "target": plan["target"],
            "projected_r": plan["projected_r"],
            "atr_m15": atr,
            "nearest_psychological": psych,
            "nearest_swing_resistance": swing,
            "first_obstacle": obstacle,
            "safe_target_before_obstacle": safe_target,
            "original_first_touch": original,
            "safe_target_touch": _first_level_touch(
                m1,
                side=plan["side"],
                level=safe_target,
            ),
            "model_result": str(outcome_fields.get("result") or "MISSING"),
            "model_outcome_r": outcome_fields.get("outcomeR"),
            "model_exit_server": exit_utc,
            "post_exit_original_target_touch": _first_level_touch(
                after_exit,
                side=plan["side"],
                level=plan["target"],
            ),
            "post_exit_safe_target_touch": _first_level_touch(
                after_exit,
                side=plan["side"],
                level=safe_target,
            ),
        }
        results.append(result)
    return results


def _jsonable(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        server_timezone = _offset(args.server_utc_offset)
        start = _server_timestamp(args.from_server_time, server_timezone)
        end = _server_timestamp(args.to_server_time, server_timezone)
        import MetaTrader5 as mt5

        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        try:
            if not mt5.symbol_select(args.symbol, True):
                raise RuntimeError(f"MT5 symbol selection failed: {mt5.last_error()}")
            plans = _load_plans(
                args.db,
                start_utc=start.astimezone(timezone.utc),
                end_utc=end.astimezone(timezone.utc),
            )
            results = reconcile(
                mt5,
                symbol=args.symbol,
                plans=plans,
                end_utc=end.astimezone(timezone.utc),
                psych_step=args.psychological_step,
            )
        finally:
            mt5.shutdown()
        for result in results:
            for key in tuple(result):
                if key.endswith("_server") and isinstance(result[key], datetime):
                    result[key] = result[key].astimezone(server_timezone)
            for key in (
                "safe_target_touch",
                "post_exit_original_target_touch",
                "post_exit_safe_target_touch",
            ):
                if isinstance(result.get(key), datetime):
                    result[key] = result[key].astimezone(server_timezone)
            touch = result.get("original_first_touch")
            if isinstance(touch, dict) and isinstance(touch.get("time"), datetime):
                touch["time"] = touch["time"].astimezone(server_timezone)
        print(json.dumps({"samples": results}, default=_jsonable, sort_keys=True))
        return 0
    except (ImportError, OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
