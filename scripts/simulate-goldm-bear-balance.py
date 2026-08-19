from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--lot", type=float, default=0.02)
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    import MetaTrader5 as mt5

    report = json.loads(args.report.read_text(encoding="utf-8"))
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        info = mt5.symbol_info(args.symbol)
        account = mt5.account_info()
        if info is None or account is None:
            raise RuntimeError(f"MT5 metadata unavailable: {mt5.last_error()}")
        balance = args.balance
        peak = balance
        minimum_balance = balance
        minimum_adverse_equity = balance
        maximum_drawdown = 0.0
        maximum_drawdown_percent = 0.0
        maximum_margin = 0.0
        minimum_margin_level = float("inf")
        gross_profit = 0.0
        gross_loss = 0.0
        completed = 0
        failure = None
        stop_out_level = float(getattr(account, "margin_so_so", 0.0) or 0.0)
        ledger = []
        for outcome in sorted(report["outcomes"], key=lambda item: item["opened_at"]):
            entry = float(outcome["entry"])
            stop = float(outcome["stop"])
            risk = stop - entry
            margin = mt5.order_calc_margin(
                mt5.ORDER_TYPE_SELL,
                args.symbol,
                args.lot,
                entry,
            )
            if margin is None:
                failure = {"reason": "MARGIN_CALC_FAILED", "mt5_error": mt5.last_error()}
                break
            margin = float(margin)
            maximum_margin = max(maximum_margin, margin)
            if margin > balance:
                failure = {
                    "reason": "INSUFFICIENT_MARGIN_AT_ENTRY",
                    "opened_at": outcome["opened_at"],
                    "balance": balance,
                    "required_margin": margin,
                }
                break
            adverse_price = entry - float(outcome["mae_r"]) * risk
            adverse_profit = mt5.order_calc_profit(
                mt5.ORDER_TYPE_SELL,
                args.symbol,
                args.lot,
                entry,
                adverse_price,
            )
            if adverse_profit is None:
                failure = {"reason": "ADVERSE_CALC_FAILED", "mt5_error": mt5.last_error()}
                break
            adverse_equity = balance + float(adverse_profit)
            minimum_adverse_equity = min(minimum_adverse_equity, adverse_equity)
            margin_level = adverse_equity / margin * 100.0 if margin > 0 else float("inf")
            minimum_margin_level = min(minimum_margin_level, margin_level)
            if adverse_equity <= 0 or (
                stop_out_level > 0 and margin_level <= stop_out_level
            ):
                failure = {
                    "reason": "STOP_OUT_DURING_TRADE",
                    "opened_at": outcome["opened_at"],
                    "balance_before": balance,
                    "adverse_equity": adverse_equity,
                    "margin_level_percent": margin_level,
                }
                balance = max(0.0, margin * stop_out_level / 100.0)
                break
            exit_price = entry - float(outcome["outcome_r"]) * risk
            profit = mt5.order_calc_profit(
                mt5.ORDER_TYPE_SELL,
                args.symbol,
                args.lot,
                entry,
                exit_price,
            )
            if profit is None:
                failure = {"reason": "PROFIT_CALC_FAILED", "mt5_error": mt5.last_error()}
                break
            profit = float(profit)
            balance += profit
            completed += 1
            if profit >= 0:
                gross_profit += profit
            else:
                gross_loss += abs(profit)
            peak = max(peak, balance)
            minimum_balance = min(minimum_balance, balance)
            maximum_drawdown = max(maximum_drawdown, peak - balance)
            maximum_drawdown_percent = max(
                maximum_drawdown_percent,
                (peak - balance) / peak * 100.0,
            )
            ledger.append(
                {
                    "opened_at": outcome["opened_at"],
                    "closed_at": outcome["closed_at"],
                    "result": outcome["result"],
                    "profit_usd": profit,
                    "balance_after": balance,
                }
            )
        payload = {
            "symbol": args.symbol,
            "starting_balance": args.balance,
            "lot": args.lot,
            "requested_trades": len(report["outcomes"]),
            "completed_trades": completed,
            "ending_balance": balance,
            "net_profit": balance - args.balance,
            "return_percent": (balance / args.balance - 1.0) * 100.0,
            "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
            "maximum_drawdown_usd": maximum_drawdown,
            "maximum_drawdown_percent_of_peak": maximum_drawdown_percent,
            "minimum_realized_balance": minimum_balance,
            "minimum_adverse_equity": minimum_adverse_equity,
            "maximum_required_margin": maximum_margin,
            "minimum_margin_level_percent": (
                minimum_margin_level if minimum_margin_level != float("inf") else None
            ),
            "failure": failure,
            "commission_and_swap_included": False,
            "ledger": ledger,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({key: payload[key] for key in payload if key != "ledger"}, sort_keys=True))
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
