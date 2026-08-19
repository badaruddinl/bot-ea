from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--balance", type=float, default=100.0)
    parser.add_argument("--lots", type=float, nargs="+", default=[0.20, 0.02])
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def simulate(mt5, outcomes, info, account, *, balance: float, lot: float):
    starting_balance = balance
    peak = balance
    peak_balance = balance
    minimum_balance = balance
    minimum_adverse_equity = balance
    maximum_drawdown = 0.0
    maximum_drawdown_percent = 0.0
    maximum_required_margin = 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    completed = 0
    failure = None
    minimum_margin_level = float("inf")
    ledger: list[dict[str, object]] = []
    stop_out_level = float(getattr(account, "margin_so_so", 0.0) or 0.0)
    margin_call_level = float(getattr(account, "margin_so_call", 0.0) or 0.0)
    for outcome in sorted(outcomes, key=lambda item: item["opened_at"]):
        entry = float(outcome["entry"])
        stop = float(outcome["stop"])
        risk = abs(entry - stop)
        margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, info.name, lot, entry)
        if margin is None:
            failure = {
                "reason": "MARGIN_CALC_FAILED",
                "opened_at": outcome["opened_at"],
                "mt5_error": mt5.last_error(),
            }
            break
        margin = float(margin)
        maximum_required_margin = max(maximum_required_margin, margin)
        if margin > balance:
            failure = {
                "reason": "INSUFFICIENT_MARGIN_AT_ENTRY",
                "opened_at": outcome["opened_at"],
                "balance": balance,
                "required_margin": margin,
            }
            break
        mae_price = entry + float(outcome["mae"]) * risk
        adverse_profit = mt5.order_calc_profit(
            mt5.ORDER_TYPE_BUY,
            info.name,
            lot,
            entry,
            mae_price,
        )
        if adverse_profit is None:
            failure = {
                "reason": "PROFIT_CALC_FAILED",
                "opened_at": outcome["opened_at"],
                "mt5_error": mt5.last_error(),
            }
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
                "margin": margin,
                "margin_level_percent": margin_level,
                "stop_out_level_percent": stop_out_level,
            }
            balance = max(0.0, margin * stop_out_level / 100.0)
            minimum_balance = min(minimum_balance, balance)
            maximum_drawdown = max(maximum_drawdown, peak - balance)
            maximum_drawdown_percent = max(
                maximum_drawdown_percent,
                (peak - balance) / peak * 100.0 if peak > 0 else 0.0,
            )
            break
        exit_price = entry + float(outcome["outcome_r"]) * risk
        profit = mt5.order_calc_profit(
            mt5.ORDER_TYPE_BUY,
            info.name,
            lot,
            entry,
            exit_price,
        )
        if profit is None:
            failure = {
                "reason": "PROFIT_CALC_FAILED",
                "opened_at": outcome["opened_at"],
                "mt5_error": mt5.last_error(),
            }
            break
        profit = float(profit)
        balance += profit
        completed += 1
        if profit >= 0:
            gross_profit += profit
        else:
            gross_loss += abs(profit)
        peak = max(peak, balance)
        peak_balance = max(peak_balance, balance)
        minimum_balance = min(minimum_balance, balance)
        maximum_drawdown = max(maximum_drawdown, peak - balance)
        maximum_drawdown_percent = max(
            maximum_drawdown_percent,
            (peak - balance) / peak * 100.0 if peak > 0 else 0.0,
        )
        ledger.append(
            {
                "opened_at": outcome["opened_at"],
                "closed_at": outcome["closed_at"],
                "result": outcome["result"],
                "entry_profile": outcome.get("entry_profile"),
                "entry": entry,
                "exit_price": exit_price,
                "outcome_r": float(outcome["outcome_r"]),
                "profit_usd": profit,
                "balance_after": balance,
                "required_margin": margin,
                "worst_margin_level_percent": margin_level,
            }
        )
        if balance <= 0:
            failure = {
                "reason": "BALANCE_DEPLETED",
                "opened_at": outcome["opened_at"],
                "balance": balance,
            }
            break
    return {
        "lot": lot,
        "starting_balance": starting_balance,
        "ending_balance": balance,
        "net_profit": balance - starting_balance,
        "return_percent": (balance / starting_balance - 1.0) * 100.0,
        "completed_trades": completed,
        "requested_trades": len(outcomes),
        "maximum_drawdown_usd": maximum_drawdown,
        "maximum_drawdown_percent_of_start": maximum_drawdown / starting_balance * 100.0,
        "maximum_drawdown_percent_of_peak": maximum_drawdown_percent,
        "maximum_required_margin": maximum_required_margin,
        "peak_balance": peak_balance,
        "minimum_realized_balance": minimum_balance,
        "minimum_adverse_equity": minimum_adverse_equity,
        "minimum_margin_level_percent": (
            minimum_margin_level if minimum_margin_level != float("inf") else None
        ),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "margin_call_level_percent": margin_call_level,
        "stop_out_level_percent": stop_out_level,
        "failure": failure,
        "ledger": ledger,
    }


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
        if not mt5.symbol_select(args.symbol, True):
            raise RuntimeError(f"MT5 symbol select failed: {mt5.last_error()}")
        scenarios = [
            simulate(
                mt5,
                report["outcomes"],
                info,
                account,
                balance=args.balance,
                lot=lot,
            )
            for lot in args.lots
        ]
        payload = {
            "symbol": args.symbol,
            "period": {"from": report["from_time"], "to": report["to_time"]},
            "contract_size": float(info.trade_contract_size),
            "volume_min": float(info.volume_min),
            "volume_step": float(info.volume_step),
            "leverage": int(account.leverage),
            "currency": str(account.currency),
            "commission_and_swap_included": False,
            "scenarios": scenarios,
        }
        rendered = json.dumps(payload, indent=2, sort_keys=True)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
