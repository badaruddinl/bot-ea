from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .engine import RevisedEngine, RevisedEngineConfig, RevisedSide
from .mt5_source import RevisedMt5Config, RevisedMt5ReadOnlySource
from .storage import RevisedStore
from .telegram import RevisedAdminNotifier
from .tracker import RevisedShadowTracker


def load_runtime_config(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("REVISED runtime config must be an object")
    return payload


class RevisedShadowRuntime:
    def __init__(self, config: dict[str, Any]) -> None:
        engine_config = dict(config.get("engine", {}))
        if "psychological_steps" in engine_config:
            engine_config["psychological_steps"] = tuple(engine_config["psychological_steps"])
        if "strong_m5_patterns" in engine_config:
            engine_config["strong_m5_patterns"] = tuple(engine_config["strong_m5_patterns"])
        self.engine = RevisedEngine(RevisedEngineConfig(**engine_config))
        mt5_config = dict(config.get("mt5", {}))
        offset = int(mt5_config.pop("server_utc_offset_minutes", 180))
        mt5_config["server_timezone"] = timezone(timedelta(minutes=offset))
        self.source = RevisedMt5ReadOnlySource(RevisedMt5Config(**mt5_config))
        storage_config = config.get("storage", {})
        self.store = RevisedStore(
            storage_config.get("db_path", "runtime_data/goldm_revised_shadow.db"),
            audit_path=storage_config.get("audit_path"),
        )
        self.notifier = RevisedAdminNotifier()
        self.tracker = RevisedShadowTracker()
        self.poll_seconds = float(config.get("runtime", {}).get("poll_seconds", 30.0))
        self._last_m1_time: datetime | None = None

    def run_once(self) -> dict[str, object]:
        health = self.source.health()
        self.store.record_health("OK", json.dumps(health, sort_keys=True))
        latest = self.source.snapshot_with_retry(side=RevisedSide.BUY)
        latest_m1 = latest.m1_bars[-1].time
        closed = self.tracker.update(self.store, latest.m1_bars)
        if self._last_m1_time == latest_m1:
            self._deliver_pending()
            return {"new_bar": False, "latest_m1": latest_m1, "closed": closed}
        self._last_m1_time = latest_m1
        decisions = []
        for side in (RevisedSide.BUY, RevisedSide.SELL):
            snapshot = self._with_m5_trigger(replace(latest, side=side), side)
            decision = self.engine.evaluate(snapshot)
            self.store.record_decision(decision)
            decisions.append(decision)
        self._deliver_pending()
        return {"new_bar": True, "latest_m1": latest_m1, "closed": closed, "decisions": decisions}

    def run_forever(self) -> None:
        self.store.record_health("STARTING", "GOLDM_REVISED shadow runtime started")
        try:
            while True:
                try:
                    self.run_once()
                except Exception as exc:
                    self.store.record_health("ERROR", str(exc))
                time.sleep(self.poll_seconds)
        finally:
            self.source.close()

    def _with_m5_trigger(self, snapshot, side: RevisedSide):
        bars = snapshot.m5_bars
        latest = bars[-1]
        previous = bars[-2] if len(bars) >= 2 else latest
        if side is RevisedSide.BUY:
            directional = latest.close > latest.open
            micro = latest.close > previous.high
            level = previous.high
            invalidation = previous.low
        else:
            directional = latest.close < latest.open
            micro = latest.close < previous.low
            level = previous.low
            invalidation = previous.high
        pattern = (
            "BULL_ENGULFING" if side is RevisedSide.BUY and directional and latest.open <= previous.close and latest.close >= previous.open
            else "BEAR_ENGULFING" if side is RevisedSide.SELL and directional and latest.open >= previous.close and latest.close <= previous.open
            else "BULL_MICRO_BREAK" if side is RevisedSide.BUY and directional and micro
            else "BEAR_MICRO_BREAK" if side is RevisedSide.SELL and directional and micro
            else "NONE"
        )
        votes = int(directional) + int(micro)
        return replace(
            snapshot,
            m5_trigger_time=latest.time,
            m5_pattern=pattern,
            m5_votes=votes,
            confidence=60.0 + votes * 10.0,
            level=level,
            invalidation=invalidation,
        )

    def _deliver_pending(self) -> None:
        if not self.notifier.configured:
            return
        for event in self.store.pending_notifications():
            payload = json.loads(event["payload_json"])
            if event["event_type"] == "REVISED_ENTRY_READY" and payload.get("observation_only"):
                self.store.mark_delivered(int(event["id"]))
                continue
            text = self.notifier.format_event(event["event_type"], payload)
            self.notifier.send(text)
            self.store.mark_delivered(int(event["id"]))
