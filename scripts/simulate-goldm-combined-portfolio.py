from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from math import isclose
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goldm_revised.replay import RevisedMt5HistoryLoader  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--buy-report", type=Path, required=True)
    parser.add_argument("--sell-report", type=Path, required=True)
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--buy-lot", type=float, default=0.02)
    parser.add_argument("--sell-lot", type=float, default=0.02)
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--from-time", type=datetime.fromisoformat)
    parser.add_argument("--to-time", type=datetime.fromisoformat)
    parser.add_argument("--adaptive-lot-balance", type=float)
    parser.add_argument("--adaptive-low-lot", type=float, default=0.01)
    parser.add_argument("--adaptive-high-lot", type=float, default=0.02)
    parser.add_argument("--round-trip-spread-usd", type=float, default=0.0)
    parser.add_argument("--slippage-per-side-usd", type=float, default=0.0)
    parser.add_argument("--commission-per-lot-side-usd", type=float, default=0.0)
    parser.add_argument(
        "--adaptive-lot-tier",
        action="append",
        type=_lot_tier,
        default=[],
        metavar="BALANCE:LOT",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _lot_tier(value: str) -> tuple[float, float]:
    try:
        balance_text, lot_text = value.split(":", 1)
        balance = float(balance_text)
        lot = float(lot_text)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("lot tier must be BALANCE:LOT") from exc
    if balance < 0.0 or lot <= 0.0:
        raise argparse.ArgumentTypeError("lot tier balance/lot is invalid")
    return balance, lot


def _position(
    mt5,
    info,
    outcome,
    *,
    side: str,
    lot: float,
    leg: str = "FULL",
    outcome_r: float | None = None,
    closed_at: datetime | None = None,
    result: str | None = None,
    round_trip_spread_usd: float = 0.0,
    slippage_per_side_usd: float = 0.0,
    commission_per_lot_side_usd: float = 0.0,
):
    entry = float(outcome["entry"])
    stop = float(outcome["stop"])
    risk = abs(entry - stop)
    resolved_outcome_r = (
        float(outcome["outcome_r"]) if outcome_r is None else float(outcome_r)
    )
    exit_price = (
        entry + resolved_outcome_r * risk
        if side == "BUY"
        else entry - resolved_outcome_r * risk
    )
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    gross_profit = mt5.order_calc_profit(order_type, info.name, lot, entry, exit_price)
    margin = mt5.order_calc_margin(order_type, info.name, lot, entry)
    if gross_profit is None or margin is None:
        raise RuntimeError(f"MT5 portfolio calculation failed: {mt5.last_error()}")
    exposure_ounces = float(getattr(info, "trade_contract_size", 1.0)) * lot
    entry_cost = (
        (round_trip_spread_usd + slippage_per_side_usd) * exposure_ounces
        + commission_per_lot_side_usd * lot
    )
    exit_cost = (
        slippage_per_side_usd * exposure_ounces
        + commission_per_lot_side_usd * lot
    )
    return {
        "id": f"{side}:{outcome['opened_at']}:{entry}:{leg}",
        "strategy": "GOLDM_REVISED" if side == "BUY" else "GOLDM_BEAR_V4",
        "side": side,
        "lot": lot,
        "opened_at": datetime.fromisoformat(outcome["opened_at"]),
        "closed_at": closed_at or datetime.fromisoformat(outcome["closed_at"]),
        "entry": entry,
        "exit_price": exit_price,
        "gross_profit": float(gross_profit),
        "entry_cost": entry_cost,
        "exit_cost": exit_cost,
        "close_profit": float(gross_profit) - exit_cost,
        "profit": float(gross_profit) - entry_cost - exit_cost,
        "margin": float(margin),
        "result": result or outcome["result"],
        "outcome_r": resolved_outcome_r,
        "leg": leg,
    }


def _positions(
    mt5,
    info,
    outcome,
    *,
    side: str,
    lot: float,
    round_trip_spread_usd: float = 0.0,
    slippage_per_side_usd: float = 0.0,
    commission_per_lot_side_usd: float = 0.0,
):
    """Expand a dual-TP outcome into margin-accurate executable legs."""

    tp1_fraction = float(outcome.get("tp1_fraction", 0.0))
    runner_fraction = float(outcome.get("runner_fraction", 1.0))
    is_split = 0.0 < tp1_fraction < 1.0 and 0.0 < runner_fraction < 1.0
    if not is_split:
        return [
            _position(
                mt5,
                info,
                outcome,
                side=side,
                lot=lot,
                round_trip_spread_usd=round_trip_spread_usd,
                slippage_per_side_usd=slippage_per_side_usd,
                commission_per_lot_side_usd=commission_per_lot_side_usd,
            )
        ]

    volume_step = float(getattr(info, "volume_step", 0.01) or 0.01)
    volume_min = float(getattr(info, "volume_min", volume_step) or volume_step)
    raw_tp1_lot = lot * tp1_fraction
    raw_runner_lot = lot * runner_fraction
    executable_split = bool(
        raw_tp1_lot + 1e-12 >= volume_min
        and raw_runner_lot + 1e-12 >= volume_min
        and abs(round(raw_tp1_lot / volume_step) * volume_step - raw_tp1_lot)
        < 1e-9
        and abs(round(raw_runner_lot / volume_step) * volume_step - raw_runner_lot)
        < 1e-9
    )
    if not executable_split:
        full_outcome_r = float(outcome["outcome_r"])
        if bool(outcome.get("tp1_taken")):
            tp1_r = float(outcome["tp1_r"])
            full_outcome_r = (
                full_outcome_r - tp1_fraction * tp1_r
            ) / runner_fraction
        return [
            _position(
                mt5,
                info,
                outcome,
                side=side,
                lot=lot,
                leg="PARTIAL_FALLBACK_FULL_RUNNER",
                outcome_r=full_outcome_r,
                round_trip_spread_usd=round_trip_spread_usd,
                slippage_per_side_usd=slippage_per_side_usd,
                commission_per_lot_side_usd=commission_per_lot_side_usd,
            )
        ]

    tp1_lot = round(raw_tp1_lot / volume_step) * volume_step
    runner_lot = round(raw_runner_lot / volume_step) * volume_step

    if not bool(outcome.get("tp1_taken")):
        shared_outcome_r = float(outcome["outcome_r"])
        return [
            _position(
                mt5,
                info,
                outcome,
                side=side,
                lot=tp1_lot,
                leg="TP1_UNFILLED",
                outcome_r=shared_outcome_r,
                round_trip_spread_usd=round_trip_spread_usd,
                slippage_per_side_usd=slippage_per_side_usd,
                commission_per_lot_side_usd=commission_per_lot_side_usd,
            ),
            _position(
                mt5,
                info,
                outcome,
                side=side,
                lot=runner_lot,
                leg="RUNNER",
                outcome_r=shared_outcome_r,
                round_trip_spread_usd=round_trip_spread_usd,
                slippage_per_side_usd=slippage_per_side_usd,
                commission_per_lot_side_usd=commission_per_lot_side_usd,
            ),
        ]

    tp1_taken_at = outcome.get("tp1_taken_at")
    if not tp1_taken_at:
        raise ValueError("partial outcome is missing causal tp1_taken_at")
    tp1_r = float(outcome["tp1_r"])
    total_outcome_r = float(outcome["outcome_r"])
    runner_outcome_r = (
        total_outcome_r - tp1_fraction * tp1_r
    ) / runner_fraction
    return [
        _position(
            mt5,
            info,
            outcome,
            side=side,
            lot=tp1_lot,
            leg="TP1",
            outcome_r=tp1_r,
            closed_at=datetime.fromisoformat(tp1_taken_at),
            result="TP1_PARTIAL",
            round_trip_spread_usd=round_trip_spread_usd,
            slippage_per_side_usd=slippage_per_side_usd,
            commission_per_lot_side_usd=commission_per_lot_side_usd,
        ),
        _position(
            mt5,
            info,
            outcome,
            side=side,
            lot=runner_lot,
            leg="RUNNER",
            outcome_r=runner_outcome_r,
            round_trip_spread_usd=round_trip_spread_usd,
            slippage_per_side_usd=slippage_per_side_usd,
            commission_per_lot_side_usd=commission_per_lot_side_usd,
        ),
    ]


def _floating_profit(position, price: float, contract_size: float) -> float:
    direction = 1.0 if position["side"] == "BUY" else -1.0
    return (
        direction
        * (price - position["entry"])
        * contract_size
        * position["lot"]
    )


def _select_trade_lot(
    balance: float,
    threshold: float | None,
    low_lot: float,
    high_lot: float,
    static_lot: float,
    lot_tiers: tuple[tuple[float, float], ...] = (),
) -> float:
    if lot_tiers:
        selected = lot_tiers[0][1]
        for tier_balance, tier_lot in lot_tiers:
            if balance + 1e-12 < tier_balance:
                break
            selected = tier_lot
        return selected
    if threshold is None:
        return static_lot
    return high_lot if balance >= threshold else low_lot


def main() -> int:
    args = parse_args()
    buy_report = json.loads(args.buy_report.read_text(encoding="utf-8"))
    sell_report = json.loads(args.sell_report.read_text(encoding="utf-8"))
    start = args.from_time or min(
        datetime.fromisoformat(buy_report["from_time"]),
        datetime.fromisoformat(sell_report["from_time"]),
    )
    end = args.to_time or max(
        datetime.fromisoformat(buy_report["to_time"]),
        datetime.fromisoformat(sell_report["to_time"]),
    )
    if end <= start:
        raise ValueError("to-time must be after from-time")
    costs = (
        args.round_trip_spread_usd,
        args.slippage_per_side_usd,
        args.commission_per_lot_side_usd,
    )
    if any(value < 0.0 for value in costs):
        raise ValueError("execution stress costs cannot be negative")
    if args.adaptive_lot_balance is not None:
        if args.adaptive_lot_balance <= 0.0:
            raise ValueError("adaptive lot balance must be positive")
        if not 0.0 < args.adaptive_low_lot <= args.adaptive_high_lot:
            raise ValueError("adaptive lot sizes are invalid")
    lot_tiers = tuple(sorted(args.adaptive_lot_tier))
    if lot_tiers and args.adaptive_lot_balance is not None:
        raise ValueError("use adaptive lot tiers or one balance threshold, not both")
    if lot_tiers:
        if lot_tiers[0][0] != 0.0:
            raise ValueError("adaptive lot tiers must define a zero-balance fallback")
        if len({balance for balance, _ in lot_tiers}) != len(lot_tiers):
            raise ValueError("adaptive lot tier balances must be unique")
    buy_outcomes = [
        outcome
        for outcome in buy_report["outcomes"]
        if start <= datetime.fromisoformat(outcome["opened_at"]) < end
    ]
    sell_outcomes = [
        outcome
        for outcome in sell_report["outcomes"]
        if start <= datetime.fromisoformat(outcome["opened_at"]) < end
    ]
    import MetaTrader5 as mt5

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        info = mt5.symbol_info(args.symbol)
        account = mt5.account_info()
        if info is None or account is None:
            raise RuntimeError(f"MT5 metadata unavailable: {mt5.last_error()}")
        trade_groups = []
        for side, outcomes, static_lot in (
            ("BUY", buy_outcomes, args.buy_lot),
            ("SELL", sell_outcomes, args.sell_lot),
        ):
            variant_lots = (
                {
                    f"TIER_{index}": lot
                    for index, (_, lot) in enumerate(lot_tiers)
                }
                if lot_tiers
                else
                {
                    "LOW": args.adaptive_low_lot,
                    "HIGH": args.adaptive_high_lot,
                }
                if args.adaptive_lot_balance is not None
                else {"STATIC": static_lot}
            )
            for outcome in outcomes:
                variants = {
                    name: _positions(
                        mt5,
                        info,
                        outcome,
                        side=side,
                        lot=lot,
                        round_trip_spread_usd=args.round_trip_spread_usd,
                        slippage_per_side_usd=args.slippage_per_side_usd,
                        commission_per_lot_side_usd=args.commission_per_lot_side_usd,
                    )
                    for name, lot in variant_lots.items()
                }
                trade_groups.append(
                    {
                        "side": side,
                        "opened_at": datetime.fromisoformat(outcome["opened_at"]),
                        "static_lot": static_lot,
                        "variants": variants,
                        "variant_lots": variant_lots,
                    }
                )
        contract_size = float(info.trade_contract_size)
        stop_out_level = float(getattr(account, "margin_so_so", 0.0) or 0.0)
    finally:
        mt5.shutdown()

    loader = RevisedMt5HistoryLoader()
    loader.connect()
    try:
        module = loader._module()
        symbol_info = module.symbol_info(args.symbol)
        if symbol_info is None:
            raise RuntimeError(f"MT5 symbol info unavailable: {module.last_error()}")
        bars = loader._rates(
            args.symbol,
            module.TIMEFRAME_M1,
            start,
            end,
            start.tzinfo,
            float(symbol_info.point),
        )
    finally:
        loader.close()

    opens = defaultdict(list)
    closes = defaultdict(list)
    possible_close_times = set()
    for group in trade_groups:
        opens[group["opened_at"]].append(group)
        for positions in group["variants"].values():
            possible_close_times.update(position["closed_at"] for position in positions)
    active = {}
    selected_positions = []
    balance = args.balance
    peak_balance = balance
    peak_equity = balance
    minimum_balance = balance
    minimum_equity = balance
    maximum_realized_drawdown = 0.0
    maximum_floating_drawdown = 0.0
    minimum_margin_level = float("inf")
    maximum_margin = 0.0
    maximum_concurrent = 0
    failure = None
    ledger = []
    realized_buy_net = 0.0
    realized_sell_net = 0.0
    total_entry_cost = 0.0
    total_exit_cost = 0.0
    low_lot_trades = 0
    high_lot_trades = 0
    static_lot_trades = 0
    first_high_lot_time = None
    lot_trade_counts: dict[str, int] = defaultdict(int)

    def close_positions(timestamp):
        nonlocal balance, peak_balance, minimum_balance, maximum_realized_drawdown
        nonlocal realized_buy_net, realized_sell_net
        for position in closes.get(timestamp, []):
            if position["id"] not in active:
                continue
            balance += position["close_profit"]
            if position["side"] == "BUY":
                realized_buy_net += position["close_profit"]
            else:
                realized_sell_net += position["close_profit"]
            peak_balance = max(peak_balance, balance)
            minimum_balance = min(minimum_balance, balance)
            maximum_realized_drawdown = max(
                maximum_realized_drawdown,
                peak_balance - balance,
            )
            active.pop(position["id"], None)
            ledger.append(
                {
                    "time": timestamp.isoformat(),
                    "event": "CLOSE",
                    "strategy": position["strategy"],
                    "side": position["side"],
                    "profit": position["close_profit"],
                    "exit_cost": position["exit_cost"],
                    "balance": balance,
                    "result": position["result"],
                    "leg": position["leg"],
                }
            )

    def open_positions(timestamp):
        nonlocal maximum_concurrent, maximum_margin, failure
        nonlocal balance, peak_balance, minimum_balance, maximum_realized_drawdown
        nonlocal realized_buy_net, realized_sell_net
        nonlocal total_entry_cost, total_exit_cost
        nonlocal low_lot_trades, high_lot_trades, static_lot_trades
        nonlocal first_high_lot_time
        candidates = []
        selected_groups = []
        for group in opens.get(timestamp, []):
            lot = _select_trade_lot(
                balance,
                args.adaptive_lot_balance,
                args.adaptive_low_lot,
                args.adaptive_high_lot,
                group["static_lot"],
                lot_tiers,
            )
            if lot_tiers:
                variant_name = next(
                    name
                    for name, candidate_lot in group["variant_lots"].items()
                    if isclose(candidate_lot, lot, abs_tol=1e-12)
                )
            elif args.adaptive_lot_balance is None:
                variant_name = "STATIC"
            elif lot == args.adaptive_high_lot:
                variant_name = "HIGH"
            else:
                variant_name = "LOW"
            positions = group["variants"][variant_name]
            candidates.extend(positions)
            selected_groups.append((variant_name, lot, positions))
        entry_cost = sum(position["entry_cost"] for position in candidates)
        projected_margin = sum(item["margin"] for item in active.values()) + sum(
            position["margin"] for position in candidates
        )
        if projected_margin > balance - entry_cost:
            failure = {
                "reason": "INSUFFICIENT_SHARED_MARGIN_AT_ENTRY",
                "time": timestamp.isoformat(),
                "balance": balance,
                "required_margin": projected_margin,
            }
            return
        balance -= entry_cost
        total_entry_cost += entry_cost
        total_exit_cost += sum(position["exit_cost"] for position in candidates)
        for position in candidates:
            if position["side"] == "BUY":
                realized_buy_net -= position["entry_cost"]
            else:
                realized_sell_net -= position["entry_cost"]
        minimum_balance = min(minimum_balance, balance)
        maximum_realized_drawdown = max(
            maximum_realized_drawdown,
            peak_balance - balance,
        )
        for variant_name, lot, positions in selected_groups:
            lot_trade_counts[f"{lot:.8f}".rstrip("0").rstrip(".")] += 1
            dynamic_lots = (
                tuple(lot for _, lot in lot_tiers)
                if lot_tiers
                else (args.adaptive_low_lot, args.adaptive_high_lot)
            )
            if variant_name == "LOW" or (
                lot_tiers and isclose(lot, min(dynamic_lots), abs_tol=1e-12)
            ):
                low_lot_trades += 1
            elif variant_name == "HIGH" or (
                lot_tiers and isclose(lot, max(dynamic_lots), abs_tol=1e-12)
            ):
                high_lot_trades += 1
                if first_high_lot_time is None:
                    first_high_lot_time = timestamp
            else:
                static_lot_trades += 1
            for position in positions:
                position["trade_lot"] = lot
                selected_positions.append(position)
                closes[position["closed_at"]].append(position)
        for position in candidates:
            active[position["id"]] = position
            maximum_concurrent = max(maximum_concurrent, len(active))
            maximum_margin = max(
                maximum_margin,
                sum(item["margin"] for item in active.values()),
            )
            ledger.append(
                {
                    "time": timestamp.isoformat(),
                    "event": "OPEN",
                    "strategy": position["strategy"],
                    "side": position["side"],
                    "lot": position["lot"],
                    "leg": position["leg"],
                    "balance": balance,
                    "entry_cost": position["entry_cost"],
                }
            )

    all_event_times = sorted(set(opens) | possible_close_times)
    event_index = 0
    for bar in bars:
        while event_index < len(all_event_times) and all_event_times[event_index] <= bar.time:
            timestamp = all_event_times[event_index]
            close_positions(timestamp)
            open_positions(timestamp)
            event_index += 1
            if failure:
                break
        if failure:
            break
        if active:
            total_margin = sum(item["margin"] for item in active.values())
            equities = []
            for price in (bar.low, bar.high, bar.close):
                equities.append(
                    balance
                    + sum(
                        _floating_profit(position, price, contract_size)
                        for position in active.values()
                    )
                )
            adverse_equity = min(equities)
            close_equity = equities[-1]
            minimum_equity = min(minimum_equity, adverse_equity)
            peak_equity = max(peak_equity, close_equity)
            maximum_floating_drawdown = max(
                maximum_floating_drawdown,
                peak_equity - adverse_equity,
            )
            margin_level = (
                adverse_equity / total_margin * 100.0
                if total_margin > 0
                else float("inf")
            )
            minimum_margin_level = min(minimum_margin_level, margin_level)
            if adverse_equity <= 0 or (
                stop_out_level > 0 and margin_level <= stop_out_level
            ):
                failure = {
                    "reason": "SHARED_PORTFOLIO_STOP_OUT",
                    "time": bar.time.isoformat(),
                    "adverse_equity": adverse_equity,
                    "margin_level_percent": margin_level,
                    "active_positions": len(active),
                }
                balance = max(0.0, total_margin * stop_out_level / 100.0)
                minimum_balance = min(minimum_balance, balance)
                break
        close_time = bar.time + timedelta(minutes=1)
        while event_index < len(all_event_times) and all_event_times[event_index] <= close_time:
            timestamp = all_event_times[event_index]
            close_positions(timestamp)
            open_positions(timestamp)
            event_index += 1
            if failure:
                break
        if failure:
            break

    if not failure:
        while event_index < len(all_event_times):
            timestamp = all_event_times[event_index]
            close_positions(timestamp)
            open_positions(timestamp)
            event_index += 1

    requested_buy_net = sum(
        position["profit"]
        for position in selected_positions
        if position["side"] == "BUY"
    )
    requested_sell_net = sum(
        position["profit"]
        for position in selected_positions
        if position["side"] == "SELL"
    )
    payload = {
        "starting_balance": args.balance,
        "ending_balance": balance,
        "net_profit": balance - args.balance,
        "buy_net_attribution": realized_buy_net,
        "sell_net_attribution": realized_sell_net,
        "requested_buy_net_if_all_closed": requested_buy_net,
        "requested_sell_net_if_all_closed": requested_sell_net,
        "buy_lot": args.buy_lot,
        "sell_lot": args.sell_lot,
        "positions_requested": len(selected_positions),
        "positions_closed": sum(item["event"] == "CLOSE" for item in ledger),
        "partial_fallback_positions": sum(
            position["leg"] == "PARTIAL_FALLBACK_FULL_RUNNER"
            for position in selected_positions
        ),
        "adaptive_lot_balance": args.adaptive_lot_balance,
        "adaptive_low_lot": args.adaptive_low_lot,
        "adaptive_high_lot": args.adaptive_high_lot,
        "adaptive_lot_tiers": [list(item) for item in lot_tiers],
        "lot_trade_counts": dict(lot_trade_counts),
        "low_lot_trades": low_lot_trades,
        "high_lot_trades": high_lot_trades,
        "static_lot_trades": static_lot_trades,
        "first_high_lot_time": (
            first_high_lot_time.isoformat() if first_high_lot_time else None
        ),
        "maximum_concurrent_positions": maximum_concurrent,
        "maximum_shared_margin": maximum_margin,
        "minimum_margin_level_percent": (
            minimum_margin_level if minimum_margin_level != float("inf") else None
        ),
        "minimum_realized_balance": minimum_balance,
        "minimum_floating_equity": minimum_equity,
        "maximum_realized_drawdown_usd": maximum_realized_drawdown,
        "maximum_floating_drawdown_usd": maximum_floating_drawdown,
        "maximum_floating_drawdown_percent_of_peak": (
            maximum_floating_drawdown / peak_equity * 100.0
            if peak_equity > 0
            else 0.0
        ),
        "failure": failure,
        "commission_swap_slippage_included": any(value > 0.0 for value in costs),
        "round_trip_spread_usd": args.round_trip_spread_usd,
        "slippage_per_side_usd": args.slippage_per_side_usd,
        "commission_per_lot_side_usd": args.commission_per_lot_side_usd,
        "total_entry_cost": total_entry_cost,
        "total_exit_cost": total_exit_cost,
        "total_execution_cost": total_entry_cost + total_exit_cost,
        "swap_modeled": False,
        "ledger": ledger,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "ledger"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
