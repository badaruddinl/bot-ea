from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
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
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _position(mt5, info, outcome, *, side: str, lot: float):
    entry = float(outcome["entry"])
    stop = float(outcome["stop"])
    risk = abs(entry - stop)
    outcome_r = float(outcome["outcome_r"])
    exit_price = (
        entry + outcome_r * risk if side == "BUY" else entry - outcome_r * risk
    )
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    profit = mt5.order_calc_profit(order_type, info.name, lot, entry, exit_price)
    margin = mt5.order_calc_margin(order_type, info.name, lot, entry)
    if profit is None or margin is None:
        raise RuntimeError(f"MT5 portfolio calculation failed: {mt5.last_error()}")
    return {
        "id": f"{side}:{outcome['opened_at']}:{entry}",
        "strategy": "GOLDM_REVISED" if side == "BUY" else "GOLDM_BEAR_V4",
        "side": side,
        "lot": lot,
        "opened_at": datetime.fromisoformat(outcome["opened_at"]),
        "closed_at": datetime.fromisoformat(outcome["closed_at"]),
        "entry": entry,
        "exit_price": exit_price,
        "profit": float(profit),
        "margin": float(margin),
        "result": outcome["result"],
        "outcome_r": outcome_r,
    }


def _floating_profit(position, price: float, contract_size: float) -> float:
    direction = 1.0 if position["side"] == "BUY" else -1.0
    return (
        direction
        * (price - position["entry"])
        * contract_size
        * position["lot"]
    )


def main() -> int:
    args = parse_args()
    buy_report = json.loads(args.buy_report.read_text(encoding="utf-8"))
    sell_report = json.loads(args.sell_report.read_text(encoding="utf-8"))
    import MetaTrader5 as mt5

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        info = mt5.symbol_info(args.symbol)
        account = mt5.account_info()
        if info is None or account is None:
            raise RuntimeError(f"MT5 metadata unavailable: {mt5.last_error()}")
        positions = [
            _position(mt5, info, outcome, side="BUY", lot=args.buy_lot)
            for outcome in buy_report["outcomes"]
        ] + [
            _position(mt5, info, outcome, side="SELL", lot=args.sell_lot)
            for outcome in sell_report["outcomes"]
        ]
        contract_size = float(info.trade_contract_size)
        stop_out_level = float(getattr(account, "margin_so_so", 0.0) or 0.0)
    finally:
        mt5.shutdown()

    start = min(
        datetime.fromisoformat(buy_report["from_time"]),
        datetime.fromisoformat(sell_report["from_time"]),
    )
    end = max(
        datetime.fromisoformat(buy_report["to_time"]),
        datetime.fromisoformat(sell_report["to_time"]),
    )
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
    for position in positions:
        opens[position["opened_at"]].append(position)
        closes[position["closed_at"]].append(position)
    active = {}
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

    def close_positions(timestamp):
        nonlocal balance, peak_balance, minimum_balance, maximum_realized_drawdown
        nonlocal realized_buy_net, realized_sell_net
        for position in closes.get(timestamp, []):
            if position["id"] not in active:
                continue
            balance += position["profit"]
            if position["side"] == "BUY":
                realized_buy_net += position["profit"]
            else:
                realized_sell_net += position["profit"]
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
                    "profit": position["profit"],
                    "balance": balance,
                    "result": position["result"],
                }
            )

    def open_positions(timestamp):
        nonlocal maximum_concurrent, maximum_margin, failure
        for position in opens.get(timestamp, []):
            projected_margin = sum(item["margin"] for item in active.values()) + position["margin"]
            if projected_margin > balance:
                failure = {
                    "reason": "INSUFFICIENT_SHARED_MARGIN_AT_ENTRY",
                    "time": timestamp.isoformat(),
                    "balance": balance,
                    "required_margin": projected_margin,
                }
                return
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
                    "balance": balance,
                }
            )

    all_event_times = sorted(set(opens) | set(closes))
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
        position["profit"] for position in positions if position["side"] == "BUY"
    )
    requested_sell_net = sum(
        position["profit"] for position in positions if position["side"] == "SELL"
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
        "positions_requested": len(positions),
        "positions_closed": sum(item["event"] == "CLOSE" for item in ledger),
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
        "commission_swap_slippage_included": False,
        "ledger": ledger,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "ledger"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
