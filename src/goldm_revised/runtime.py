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
from .setup import RevisedSetupDetector
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
        self.detector = RevisedSetupDetector(
            maximum_m1_bars=self.engine.config.watch_max_m1_bars
        )
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
            setup = self.detector.update(
                latest.m5_bars,
                current_m1_time=latest_m1,
                side=side,
            )
            if setup is None:
                termination = self.detector.pop_termination(side)
                if termination is None:
                    continue
                ended, reason = termination
                snapshot = replace(
                    latest,
                    side=side,
                    m5_trigger_time=ended.trigger_time,
                    m5_pattern=ended.pattern,
                    m5_votes=ended.votes,
                    confidence=ended.confidence,
                    level=ended.level,
                    invalidation=ended.invalidation,
                )
                decision = self.engine.terminal_decision(snapshot, reason)
            else:
                snapshot = replace(
                    latest,
                    side=side,
                    m5_trigger_time=setup.trigger_time,
                    m5_pattern=setup.pattern,
                    m5_votes=setup.votes,
                    confidence=setup.confidence,
                    level=setup.level,
                    invalidation=setup.invalidation,
                )
                decision = self.engine.evaluate(snapshot)
            self.store.record_decision(decision)
            decisions.append(decision)
            if setup is not None and decision.state.value in {"ENTRY_READY", "CANCELLED"}:
                self.detector.consume(side, setup.trigger_time)
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
