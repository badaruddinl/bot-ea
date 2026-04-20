from __future__ import annotations

from .models import ExecutionGateResult, GateCheck, OperatingMode, RiskPolicy


def evaluate_execution_guards(account, symbol, policy: RiskPolicy, mode: OperatingMode, stop_distance_points: float) -> ExecutionGateResult:
    checks: list[GateCheck] = []

    checks.append(
        GateCheck(
            name="trade_allowed",
            passed=symbol.trade_allowed,
            detail="symbol is trade-allowed" if symbol.trade_allowed else "symbol trading disabled",
        )
    )
    checks.append(
        GateCheck(
            name="session_active",
            passed=symbol.quote_session_active and symbol.trade_session_active,
            detail="quote and trade sessions active"
            if symbol.quote_session_active and symbol.trade_session_active
            else "quote or trade session inactive",
        )
    )
    checks.append(
        GateCheck(
            name="stop_level",
            passed=stop_distance_points >= symbol.stops_level_points,
            detail="stop distance satisfies broker stop level"
            if stop_distance_points >= symbol.stops_level_points
            else "stop distance below broker stop level",
        )
    )
    checks.append(
        GateCheck(
            name="daily_loss",
            passed=account.daily_realized_loss_pct < policy.daily_loss_limit_pct,
            detail="daily loss below limit"
            if account.daily_realized_loss_pct < policy.daily_loss_limit_pct
            else "daily loss limit hit",
        )
    )
    checks.append(
        GateCheck(
            name="open_risk",
            passed=account.current_open_risk_pct < policy.max_total_open_risk_pct,
            detail="open risk below cap"
            if account.current_open_risk_pct < policy.max_total_open_risk_pct
            else "open risk cap hit",
        )
    )

    if symbol.volatility_points and symbol.volatility_points > 0:
        spread_ratio = symbol.spread_points / symbol.volatility_points
        allowed_ratio = (
            policy.strict_spread_to_volatility_ratio
            if mode is OperatingMode.STRICT
            else policy.caution_spread_to_volatility_ratio
            if mode is OperatingMode.CAUTION
            else policy.strict_spread_to_volatility_ratio
        )
        checks.append(
            GateCheck(
                name="spread_efficiency",
                passed=spread_ratio <= allowed_ratio,
                detail=f"spread ratio {spread_ratio:.3f} within cap {allowed_ratio:.3f}"
                if spread_ratio <= allowed_ratio
                else f"spread ratio {spread_ratio:.3f} exceeds cap {allowed_ratio:.3f}",
            )
        )

    return ExecutionGateResult(allowed=all(check.passed for check in checks), checks=checks)
