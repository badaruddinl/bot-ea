from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class SetupState(str, Enum):
    SCANNING = "SCANNING"
    LEVEL_APPROACH = "LEVEL_APPROACH"
    BREAKOUT_DETECTED = "BREAKOUT_DETECTED"
    WAITING_RETEST = "WAITING_RETEST"
    RETEST_VALID = "RETEST_VALID"
    WAITING_M5_TRIGGER = "WAITING_M5_TRIGGER"
    EARLY_CANDIDATE = "EARLY_CANDIDATE"
    CONFIRMED_A_PLUS = "CONFIRMED_A_PLUS"
    TELEGRAM_SENT = "TELEGRAM_SENT"
    ACTIVE_SIGNAL = "ACTIVE_SIGNAL"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    MANUALLY_ENTERED = "MANUALLY_ENTERED"
    MISSED = "MISSED"
    CLOSED = "CLOSED"


TERMINAL_STATES = frozenset(
    {
        SetupState.EXPIRED,
        SetupState.CANCELLED,
        SetupState.MANUALLY_ENTERED,
        SetupState.MISSED,
        SetupState.CLOSED,
    }
)

_TRANSITIONS: dict[SetupState, frozenset[SetupState]] = {
    SetupState.SCANNING: frozenset({SetupState.LEVEL_APPROACH}),
    SetupState.LEVEL_APPROACH: frozenset(
        {SetupState.BREAKOUT_DETECTED, SetupState.EXPIRED, SetupState.CANCELLED}
    ),
    SetupState.BREAKOUT_DETECTED: frozenset(
        {SetupState.WAITING_RETEST, SetupState.EXPIRED, SetupState.CANCELLED}
    ),
    SetupState.WAITING_RETEST: frozenset(
        {SetupState.RETEST_VALID, SetupState.EXPIRED, SetupState.CANCELLED}
    ),
    SetupState.RETEST_VALID: frozenset(
        {SetupState.WAITING_M5_TRIGGER, SetupState.EXPIRED, SetupState.CANCELLED}
    ),
    SetupState.WAITING_M5_TRIGGER: frozenset(
        {
            SetupState.EARLY_CANDIDATE,
            SetupState.CONFIRMED_A_PLUS,
            SetupState.EXPIRED,
            SetupState.CANCELLED,
        }
    ),
    SetupState.EARLY_CANDIDATE: frozenset(
        {SetupState.CONFIRMED_A_PLUS, SetupState.EXPIRED, SetupState.CANCELLED, SetupState.MISSED}
    ),
    SetupState.CONFIRMED_A_PLUS: frozenset(
        {SetupState.TELEGRAM_SENT, SetupState.EXPIRED, SetupState.CANCELLED, SetupState.MISSED}
    ),
    SetupState.TELEGRAM_SENT: frozenset(
        {SetupState.ACTIVE_SIGNAL, SetupState.CANCELLED, SetupState.MANUALLY_ENTERED, SetupState.MISSED}
    ),
    SetupState.ACTIVE_SIGNAL: frozenset(
        {SetupState.CANCELLED, SetupState.MANUALLY_ENTERED, SetupState.MISSED, SetupState.CLOSED}
    ),
}


@dataclass(slots=True)
class SetupRecord:
    setup_id: str
    symbol: str
    side: str
    level: float
    breakout_at: datetime
    state: SetupState = SetupState.SCANNING
    retest_bars_elapsed: int = 0
    reason: str = ""


class SetupStateMachine:
    def __init__(self, record: SetupRecord, *, maximum_retest_bars: int = 10) -> None:
        if maximum_retest_bars <= 0:
            raise ValueError("maximum_retest_bars must be positive")
        self.record = record
        self.maximum_retest_bars = maximum_retest_bars

    def transition(self, target: SetupState, *, reason: str) -> SetupRecord:
        if not reason.strip():
            raise ValueError("state transition reason is required")
        if self.record.state in TERMINAL_STATES:
            raise ValueError(f"cannot transition terminal state {self.record.state.value}")
        allowed = _TRANSITIONS.get(self.record.state, frozenset())
        if target not in allowed:
            raise ValueError(f"invalid transition {self.record.state.value} -> {target.value}")
        self.record.state = target
        self.record.reason = reason.strip()
        return self.record

    def record_retest_bar(self) -> SetupRecord:
        if self.record.state is not SetupState.WAITING_RETEST:
            raise ValueError("retest bars can only be counted while waiting for retest")
        self.record.retest_bars_elapsed += 1
        if self.record.retest_bars_elapsed >= self.maximum_retest_bars:
            return self.transition(SetupState.EXPIRED, reason="retest did not occur within the bar limit")
        return self.record


def build_setup_id(symbol: str, side: str, level: float, breakout_at: datetime) -> str:
    clean_symbol = re.sub(r"[^A-Za-z0-9._#-]", "_", symbol.strip())
    clean_side = side.strip().upper()
    if not clean_symbol:
        raise ValueError("symbol is required")
    if clean_side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    if level <= 0:
        raise ValueError("level must be positive")
    aware = breakout_at if breakout_at.tzinfo else breakout_at.replace(tzinfo=timezone.utc)
    utc_time = aware.astimezone(timezone.utc)
    level_text = f"{level:.2f}".rstrip("0").rstrip(".")
    return f"{clean_symbol}-{clean_side}-{level_text}-{utc_time:%Y%m%dT%H%M}"
