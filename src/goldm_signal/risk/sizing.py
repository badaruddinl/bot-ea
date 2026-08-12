from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

from ..config import GoldSymbolProfile, SignalPolicy


@dataclass(frozen=True, slots=True)
class PositionSizeSuggestion:
    safe: bool
    volume: float
    risk_cash: float
    estimated_loss_cash: float
    reason: str


def suggest_position_size(
    *,
    equity: float,
    risk_pct: float,
    stop_distance_price: float,
    tick_size: float,
    tick_value_loss: float,
    volume_step: float,
    profile: GoldSymbolProfile,
    policy: SignalPolicy,
) -> PositionSizeSuggestion:
    if equity <= 0 or stop_distance_price <= 0 or tick_size <= 0 or tick_value_loss <= 0:
        return PositionSizeSuggestion(False, 0.0, 0.0, 0.0, "invalid sizing input")
    if volume_step <= 0:
        return PositionSizeSuggestion(False, 0.0, 0.0, 0.0, "broker volume step is unavailable")
    if risk_pct <= 0 or risk_pct > policy.absolute_manual_risk_cap_pct:
        return PositionSizeSuggestion(False, 0.0, 0.0, 0.0, "risk percentage is outside the manual cap")

    risk_cash = equity * risk_pct
    loss_per_lot = (stop_distance_price / tick_size) * tick_value_loss
    raw_volume = risk_cash / loss_per_lot
    step = Decimal(str(volume_step))
    normalized = float((Decimal(str(raw_volume)) / step).to_integral_value(rounding=ROUND_DOWN) * step)
    normalized = min(normalized, profile.volume_max)
    minimum_loss = profile.volume_min * loss_per_lot
    if normalized < profile.volume_min:
        return PositionSizeSuggestion(
            False,
            0.0,
            risk_cash,
            minimum_loss,
            "NO SAFE POSITION SIZE: broker minimum lot exceeds the risk budget",
        )
    estimated_loss = normalized * loss_per_lot
    return PositionSizeSuggestion(True, normalized, risk_cash, estimated_loss, "informational sizing only")
