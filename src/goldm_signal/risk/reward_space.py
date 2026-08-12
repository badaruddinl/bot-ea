from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RewardSpace:
    passed: bool
    projected_r: float
    reason: str


@dataclass(frozen=True, slots=True)
class M15RiskGeometry:
    passed: bool
    stop: float
    risk: float
    entry_distance_atr: float
    reason: str


def evaluate_m15_risk_geometry(
    *,
    side: str,
    entry: float,
    level: float,
    retest_extreme: float,
    atr_m15: float,
    maximum_entry_distance_atr: float = 0.30,
    maximum_retest_penetration_atr: float = 0.25,
    structural_stop_buffer_atr: float = 0.10,
) -> M15RiskGeometry:
    """Mirror the EA's M15-native entry-distance and structural-stop calculation."""
    direction = side.strip().upper()
    if direction not in {"BUY", "SELL"}:
        return M15RiskGeometry(False, 0.0, 0.0, 0.0, "side must be BUY or SELL")
    if atr_m15 <= 0 or maximum_entry_distance_atr <= 0:
        return M15RiskGeometry(False, 0.0, 0.0, 0.0, "M15 ATR and entry-distance limit must be positive")
    if maximum_retest_penetration_atr < 0 or structural_stop_buffer_atr < 0:
        return M15RiskGeometry(False, 0.0, 0.0, 0.0, "M15 structural ATR limits cannot be negative")

    if direction == "BUY":
        entry_distance_atr = (entry - level) / atr_m15
        invalidation = level - maximum_retest_penetration_atr * atr_m15
        stop = min(retest_extreme, invalidation) - structural_stop_buffer_atr * atr_m15
        risk = entry - stop
    else:
        entry_distance_atr = (level - entry) / atr_m15
        invalidation = level + maximum_retest_penetration_atr * atr_m15
        stop = max(retest_extreme, invalidation) + structural_stop_buffer_atr * atr_m15
        risk = stop - entry

    if entry_distance_atr < 0:
        return M15RiskGeometry(False, stop, risk, entry_distance_atr, "entry is back across the M15 breakout level")
    if entry_distance_atr > maximum_entry_distance_atr:
        return M15RiskGeometry(False, stop, risk, entry_distance_atr, "entry is chasing too far from the M15 breakout level")
    if risk <= 0:
        return M15RiskGeometry(False, stop, risk, entry_distance_atr, "M15 structural stop does not define positive risk")
    return M15RiskGeometry(True, stop, risk, entry_distance_atr, "M15 structural risk gate passed")


def evaluate_reward_space(
    *,
    side: str,
    entry: float,
    stop: float,
    target: float,
    minimum_r: float = 3.0,
) -> RewardSpace:
    direction = side.strip().upper()
    if direction == "BUY":
        risk = entry - stop
        reward = target - entry
    elif direction == "SELL":
        risk = stop - entry
        reward = entry - target
    else:
        return RewardSpace(False, 0.0, "side must be BUY or SELL")
    if risk <= 0 or reward <= 0:
        return RewardSpace(False, 0.0, "entry, stop, and target are not structurally ordered")
    projected_r = reward / risk
    return RewardSpace(
        projected_r >= minimum_r,
        projected_r,
        "room-to-profit gate passed" if projected_r >= minimum_r else "projected room is below the minimum",
    )
