from __future__ import annotations

from enum import Enum


class StrategyFamily(str, Enum):
    SESSION_BREAKOUT = "session_breakout"
    PULLBACK_CONTINUATION = "pullback_continuation"
    VOLATILITY_EXPANSION = "volatility_contraction_expansion"
    FAILED_BREAKOUT = "failed_breakout_range_reversion"


def choose_family(global_gate_pass: bool, session_active: bool, trend_active: bool, compression_present: bool) -> StrategyFamily | None:
    """Minimal placeholder matching the stage-3 decision priority."""
    if not global_gate_pass:
        return None
    if session_active:
        return StrategyFamily.SESSION_BREAKOUT
    if trend_active:
        return StrategyFamily.PULLBACK_CONTINUATION
    if compression_present:
        return StrategyFamily.VOLATILITY_EXPANSION
    return StrategyFamily.FAILED_BREAKOUT
