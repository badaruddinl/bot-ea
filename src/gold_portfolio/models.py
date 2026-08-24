from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from gold_engine_core import SignalPlan as SignalPlan


@dataclass(frozen=True, slots=True)
class WatchEvent:
    watch_id: str
    component: str
    symbol: str
    side: str
    state: str
    stage: str
    time: datetime
    trigger_time: datetime
    reason: str
    level: float | None = None
    invalidation: float | None = None
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    mode: str | None = None
    touch_count: int = 0
    rejection_count: int = 0
    evidence: dict[str, Any] | None = None
