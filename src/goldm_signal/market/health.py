from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..config import GoldSymbolProfile, SignalPolicy


@dataclass(frozen=True, slots=True)
class DataHealthInput:
    now: datetime
    last_tick_at: datetime | None
    server_time: datetime | None
    available_timeframes: frozenset[str]
    terminal_connected: bool
    quote_session_active: bool
    trade_session_active: bool
    spread_price: float
    atr_m15: float


@dataclass(slots=True)
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_data_health(
    snapshot: DataHealthInput,
    profile: GoldSymbolProfile,
    policy: SignalPolicy,
) -> GateResult:
    reasons: list[str] = []
    if not snapshot.terminal_connected:
        reasons.append("MT5 terminal is disconnected")
    missing = sorted(set(policy.required_timeframes) - set(snapshot.available_timeframes))
    if missing:
        reasons.append(f"closed-bar data incomplete: {', '.join(missing)}")
    if snapshot.last_tick_at is None:
        reasons.append("last tick is unavailable")
    else:
        tick_age = (snapshot.now - snapshot.last_tick_at).total_seconds()
        if tick_age < 0:
            reasons.append("last tick is in the future")
        elif tick_age > policy.max_tick_age_seconds:
            reasons.append(f"price is stale ({tick_age:.0f}s old)")
    if not snapshot.quote_session_active:
        reasons.append("broker quote session is inactive")
    if not snapshot.trade_session_active:
        reasons.append("broker trade session is inactive")
    if snapshot.server_time is None:
        reasons.append("broker server time is unavailable")
    else:
        server_clock = snapshot.server_time.time().replace(tzinfo=None)
        if not profile.quote_window.contains(server_clock):
            reasons.append("outside configured quote window")
        if not profile.trade_window.contains(server_clock):
            reasons.append("outside configured trade window")
    if snapshot.atr_m15 <= 0:
        reasons.append("M15 ATR is unavailable or invalid")
    elif snapshot.spread_price < 0:
        reasons.append("spread is invalid")
    elif snapshot.spread_price / snapshot.atr_m15 > policy.max_spread_to_atr:
        reasons.append("spread is too wide relative to M15 ATR")
    return GateResult(passed=not reasons, reasons=reasons)
