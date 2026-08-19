from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SignalPlan:
    event_id: str
    component: str
    symbol: str
    side: str
    time: datetime
    entry: float
    stop: float
    target: float
    reason: str

