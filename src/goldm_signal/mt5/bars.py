from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Timeframe(str, Enum):
    M5 = "M5"
    M15 = "M15"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"


@dataclass(frozen=True, slots=True)
class ClosedBar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: float
    spread_points: float
    real_volume: float

    @property
    def full_range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)
