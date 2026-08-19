from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goldm_revised.risk import AdaptiveCompoundSizer, AdaptiveRiskConfig  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--balances", type=float, nargs="+", default=[50.0, 100.0])
    parser.add_argument("--risk-percents", type=float, nargs="+", default=[1.0, 2.0, 3.0, 5.0])
    parser.add_argument(
        "--minimum-lot-risk-cap-percents",
        type=float,
        nargs="+",
        default=[0.0],
    )
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def structural_outcomes(outcomes):
    eligible = []
    skipped = {
        "invalid_direction": 0,
        "target_below_one_r": 0,
        "first_obstacle_below_one_r": 0,
        "target_beyond_first_obstacle": 0,
    }
    for outcome in outcomes:
        entry = float(outcome["entry"])
        stop = float(outcome["stop"])
        target = float(outcome["target"])
        risk = abs(entry - stop)
        target_r = (target - entry) / risk if risk > 0 else float("-inf")
        obstacle_r = float(outcome["first_obstacle_r"])
        if target <= entry or risk <= 0:
            skipped["invalid_direction"] += 1
        elif target_r < 1.0:
            skipped["target_below_one_r"] += 1
        elif obstacle_r < 1.0:
            skipped["first_obstacle_below_one_r"] += 1
        elif target_r > obstacle_r:
            skipped["target_beyond_first_obstacle"] += 1
        else:
            eligible.append(outcome)
    return eligible, skipped


def simulate(
    mt5,
    outcomes,
    info,
    account,
    *,
    balance: float,
    risk_percent: float,
    minimum_lot_risk_cap_percent: float,
):
    config = AdaptiveRiskConfig(
        risk_fraction=risk_percent / 100.0,
        volume_min=float(info.volume_min),
        volume_max=float(info.volume_max),
        volume_step=float(info.volume_step),
        minimum_lot_risk_cap_fraction=minimum_lot_risk_cap_percent / 100.0,
    )
    sizer = AdaptiveCompoundSizer(config)
    starting_balance = balance
    peak_balance = balance
    minimum_balance = balance
    minimum_adverse_equity = balance
    maximum_drawdown = 0.0
    maximum_drawdown_percent = 0.0
    minimum_margin_level = float("inf")
    maximum_required_margin = 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    executed = 0
    skipped_minimum_volume = 0
    minimum_lot_bridge_trades = 0
    minimum_volume: float | None = None
    maximum_volume = 0.0
    volume_sum = 0.0
    projected_risk_sum = 0.0
    failure = None
    stop_out_level = float(getattr(account, "margin_so_so", 0.0) or 0.0)
    ledger: list[dict[str, object]] = []
    for outcome in sorted(outcomes, key=lambda item: item["opened_at"]):
        entry = float(outcome["entry"])
        stop = float(outcome["stop"])
        risk = abs(entry - stop)
        loss_one_lot = mt5.order_calc_profit(
            mt5.ORDER_TYPE_BUY,
            info.name,
            1.0,
            entry,
            stop,
        )
        margin_one_lot = mt5.order_calc_margin(
            mt5.ORDER_TYPE_BUY,
            info.name,
            1.0,
            entry,
        )
        if loss_one_lot is None or margin_one_lot is None:
            failure = {
                "reason": "MT5_RISK_CALCULATION_FAILED",
                "opened_at": outcome["opened_at"],
                "mt5_error": mt5.last_error(),
            }
            break
        sizing = sizer.size(
            equity=balance,
            high_water_equity=peak_balance,
            loss_per_lot=abs(float(loss_one_lot)),
            margin_per_lot=float(margin_one_lot),
        )
        if not sizing.executable:
            if sizing.reason == "HARD_DRAWDOWN_PAUSE":
                failure = {
                    "reason": sizing.reason,
                    "opened_at": outcome["opened_at"],
                    "balance": balance,
                    "drawdown_fraction": sizing.drawdown_fraction,
                }
                break
            skipped_minimum_volume += 1
            continue
        lot = sizing.volume
        if sizing.reason == "MINIMUM_LOT_BRIDGE":
            minimum_lot_bridge_trades += 1
        margin = sizing.projected_margin
        maximum_required_margin = max(maximum_required_margin, margin)
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
                "reason": "MT5_ADVERSE_PROFIT_CALCULATION_FAILED",
                "opened_at": outcome["opened_at"],
                "mt5_error": mt5.last_error(),
            }
            break
        adverse_equity = balance + float(adverse_profit)
        minimum_adverse_equity = min(minimum_adverse_equity, adverse_equity)
        maximum_drawdown = max(maximum_drawdown, peak_balance - adverse_equity)
        maximum_drawdown_percent = max(
            maximum_drawdown_percent,
            (peak_balance - adverse_equity) / peak_balance * 100.0,
        )
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
                "reason": "MT5_EXIT_PROFIT_CALCULATION_FAILED",
                "opened_at": outcome["opened_at"],
                "mt5_error": mt5.last_error(),
            }
            break
        profit = float(profit)
        balance += profit
        executed += 1
        volume_sum += lot
        projected_risk_sum += sizing.projected_risk_fraction
        minimum_volume = lot if minimum_volume is None else min(minimum_volume, lot)
        maximum_volume = max(maximum_volume, lot)
        if profit >= 0:
            gross_profit += profit
        else:
            gross_loss += abs(profit)
        peak_balance = max(peak_balance, balance)
        minimum_balance = min(minimum_balance, balance)
        maximum_drawdown = max(maximum_drawdown, peak_balance - balance)
        maximum_drawdown_percent = max(
            maximum_drawdown_percent,
            (peak_balance - balance) / peak_balance * 100.0,
        )
        ledger.append(
            {
                "opened_at": outcome["opened_at"],
                "closed_at": outcome["closed_at"],
                "result": outcome["result"],
                "balance_before": balance - profit,
                "balance_after": balance,
                "volume": lot,
                "profit_usd": profit,
                "projected_loss": sizing.projected_loss,
                "projected_risk_fraction": sizing.projected_risk_fraction,
                "effective_risk_fraction": sizing.effective_risk_fraction,
                "drawdown_fraction_before": sizing.drawdown_fraction,
            }
        )
    return {
        "starting_balance": starting_balance,
        "ending_balance": balance,
        "net_profit": balance - starting_balance,
        "return_percent": (balance / starting_balance - 1.0) * 100.0,
        "configured_risk_percent": risk_percent,
        "minimum_lot_risk_cap_percent": minimum_lot_risk_cap_percent,
        "requested_trades": len(outcomes),
        "executed_trades": executed,
        "skipped_minimum_volume": skipped_minimum_volume,
        "minimum_lot_bridge_trades": minimum_lot_bridge_trades,
        "minimum_volume": minimum_volume,
        "maximum_volume": maximum_volume,
        "average_volume": volume_sum / executed if executed else None,
        "average_projected_risk_percent": (
            projected_risk_sum / executed * 100.0 if executed else None
        ),
        "ending_to_start_multiple": balance / starting_balance,
        "maximum_drawdown_usd": maximum_drawdown,
        "maximum_drawdown_percent_of_peak": maximum_drawdown_percent,
        "peak_balance": peak_balance,
        "minimum_realized_balance": minimum_balance,
        "minimum_adverse_equity": minimum_adverse_equity,
        "maximum_required_margin": maximum_required_margin,
        "minimum_margin_level_percent": (
            minimum_margin_level if minimum_margin_level != float("inf") else None
        ),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "failure": failure,
        "ledger": ledger,
    }


def main() -> int:
    args = parse_args()
    import MetaTrader5 as mt5

    report = json.loads(args.report.read_text(encoding="utf-8"))
    eligible_outcomes, structural_skips = structural_outcomes(report["outcomes"])
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        info = mt5.symbol_info(args.symbol)
        account = mt5.account_info()
        if info is None or account is None:
            raise RuntimeError(f"MT5 metadata unavailable: {mt5.last_error()}")
        scenarios = [
            simulate(
                mt5,
                eligible_outcomes,
                info,
                account,
                balance=balance,
                risk_percent=risk_percent,
                minimum_lot_risk_cap_percent=minimum_lot_risk_cap_percent,
            )
            for balance in args.balances
            for risk_percent in args.risk_percents
            for minimum_lot_risk_cap_percent in args.minimum_lot_risk_cap_percents
        ]
        payload = {
            "symbol": args.symbol,
            "period": {"from": report["from_time"], "to": report["to_time"]},
            "source_report": str(args.report),
            "volume_min": float(info.volume_min),
            "volume_max": float(info.volume_max),
            "volume_step": float(info.volume_step),
            "commission_and_swap_included": False,
            "source_outcomes": len(report["outcomes"]),
            "structural_eligible_outcomes": len(eligible_outcomes),
            "structural_skips": structural_skips,
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
