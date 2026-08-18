from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from .engine import RevisedBar, RevisedSide
from .storage import RevisedStore


class RevisedShadowTracker:
    """Tracks shadow TP/SL, MFE and MAE without touching broker positions."""

    def update(self, store: RevisedStore, bars: Sequence[RevisedBar]) -> int:
        if not bars:
            return 0
        latest = bars[-1]
        closed = 0
        for position in store.open_positions():
            side = RevisedSide(str(position["side"]))
            entry = float(position["entry"])
            stop = float(position["stop"])
            target = float(position["target"])
            risk = abs(entry - stop)
            if risk <= 0:
                continue
            if side is RevisedSide.BUY:
                mfe = (latest.high - entry) / risk
                mae = (latest.low - entry) / risk
                stop_hit = latest.low <= stop
                target_hit = latest.high >= target
            else:
                mfe = (entry - latest.low) / risk
                mae = (entry - latest.high) / risk
                stop_hit = latest.high >= stop
                target_hit = latest.low <= target
            store.update_position_marks(str(position["setup_id"]), mfe=mfe, mae=mae)
            if not stop_hit and not target_hit:
                continue
            if stop_hit and target_hit:
                reason = "AMBIGUOUS_SAME_BAR"
                status = "AMBIGUOUS"
                exit_price = None
            elif target_hit:
                reason = "TARGET"
                status = "TARGET"
                exit_price = target
            else:
                reason = "STOP"
                status = "STOP"
                exit_price = stop
            store.record_outcome(
                setup_id=str(position["setup_id"]),
                status=status,
                close_reason=reason,
                exit_price=exit_price,
                mfe=max(float(position["mfe"]), mfe),
                mae=min(float(position["mae"]), mae),
                closed_at=latest.time if latest.time.tzinfo else latest.time.replace(tzinfo=timezone.utc),
            )
            closed += 1
        return closed
