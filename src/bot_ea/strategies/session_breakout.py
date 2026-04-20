from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..models import Bar, SymbolSnapshot


class SignalSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(slots=True)
class SessionBreakoutConfig:
    opening_range_bars: int = 4
    min_range_points: float = 20.0
    max_range_points: float = 400.0
    breakout_buffer_points: float = 5.0
    min_body_fraction: float = 0.55
    max_spread_to_volatility_ratio: float = 0.10


@dataclass(slots=True)
class SessionBreakoutSignal:
    valid: bool
    side: SignalSide | None = None
    entry_reference: float | None = None
    stop_reference: float | None = None
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def evaluate_session_breakout(
    bars: list[Bar],
    symbol: SymbolSnapshot,
    config: SessionBreakoutConfig,
    *,
    session_active: bool,
    news_blocked: bool,
) -> SessionBreakoutSignal:
    reasons: list[str] = []
    warnings: list[str] = []

    minimum_bars = config.opening_range_bars + 1
    if len(bars) < minimum_bars:
        return SessionBreakoutSignal(valid=False, reasons=["not enough closed bars"])

    if not session_active:
        return SessionBreakoutSignal(valid=False, reasons=["session inactive"])

    if not symbol.quote_session_active or not symbol.trade_session_active:
        return SessionBreakoutSignal(valid=False, reasons=["symbol quote or trade session inactive"])

    if news_blocked:
        return SessionBreakoutSignal(valid=False, reasons=["news blackout active"])

    if symbol.volatility_points and symbol.volatility_points > 0:
        spread_ratio = symbol.spread_points / symbol.volatility_points
        if spread_ratio > config.max_spread_to_volatility_ratio:
            return SessionBreakoutSignal(valid=False, reasons=["spread too wide relative to volatility"])

    opening_range = bars[: config.opening_range_bars]
    trigger_bar = bars[config.opening_range_bars]

    range_high = max(bar.high for bar in opening_range)
    range_low = min(bar.low for bar in opening_range)
    range_points = range_high - range_low

    if range_points < config.min_range_points:
        return SessionBreakoutSignal(valid=False, reasons=["opening range too narrow"])
    if range_points > config.max_range_points:
        return SessionBreakoutSignal(valid=False, reasons=["opening range too wide"])

    if trigger_bar.range_points <= 0:
        return SessionBreakoutSignal(valid=False, reasons=["trigger bar has zero range"])

    body_fraction = trigger_bar.body_points / trigger_bar.range_points
    if body_fraction < config.min_body_fraction:
        return SessionBreakoutSignal(valid=False, reasons=["trigger body too weak"])

    upper_breakout = range_high + config.breakout_buffer_points
    lower_breakout = range_low - config.breakout_buffer_points

    if trigger_bar.close > upper_breakout:
        warnings.append("closed-bar breakout detected")
        return SessionBreakoutSignal(
            valid=True,
            side=SignalSide.BUY,
            entry_reference=trigger_bar.close,
            stop_reference=range_low,
            reasons=["close broke above opening range"],
            warnings=warnings,
        )

    if trigger_bar.close < lower_breakout:
        warnings.append("closed-bar breakout detected")
        return SessionBreakoutSignal(
            valid=True,
            side=SignalSide.SELL,
            entry_reference=trigger_bar.close,
            stop_reference=range_high,
            reasons=["close broke below opening range"],
            warnings=warnings,
        )

    reasons.append("no breakout close beyond opening range")
    return SessionBreakoutSignal(valid=False, reasons=reasons, warnings=warnings)
