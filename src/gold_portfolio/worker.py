from __future__ import annotations

import json
import os
import time
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from gold_engine_core import ProfileConfig, load_named_profile
from gold_engine_core.rules.bear_incremental import (
    BearIncrementalMachine,
    BearIncrementalOutput,
    BearIncrementalPhase,
)
from goldm_bear.engine import BearBar
from goldm_bear.multitimeframe import BearMultiTimeframeReplay, BearV4Config, BearV4Report
from goldm_revised.engine import (
    RevisedEngine,
    RevisedEngineConfig,
    RevisedSide,
    RevisedSnapshot,
    RevisedState,
)
from goldm_revised.setup import RevisedSetupDetector
from goldm_signal.notify.telegram import TelegramBotClient

from .config import PortfolioWorkerConfig, TelegramConfig
from .models import SignalPlan, WatchEvent
from .mt5_session import BoundMt5Session

ROOT = Path(__file__).resolve().parents[2]
AUDIT_MAX_BYTES = 5 * 1024 * 1024
AUDIT_BACKUPS = 3


def _json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"config must be an object: {resolved}")
    return payload


class TelegramBroadcast:
    def __init__(self, config: TelegramConfig) -> None:
        self.config = config
        self.chat_ids = config.chat_ids
        self.client = (
            TelegramBotClient(bot_token=config.bot_token)
            if config.bot_token and config.chat_ids
            else None
        )

    @property
    def configured(self) -> bool:
        return self.client is not None

    def send(self, text: str, *, include_subscribers: bool = False) -> None:
        if self.client is None:
            return
        recipients = set(self.chat_ids)
        if include_subscribers and self.config.audience == "goldi_approved":
            recipients.update(self._approved_goldi_subscribers())
        for chat_id in sorted(recipients):
            self.client.send_message(chat_id=chat_id, text=text)

    def _approved_goldi_subscribers(self) -> set[str]:
        path = self.config.subscriber_state_path
        if path is None:
            return set()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        values = payload.get("goldi_subscribers") if isinstance(payload, dict) else []
        normalized: set[str] = set()
        for item in values or []:
            text = str(item).strip()
            digits = text[1:] if text.startswith("-") else text
            if text.isascii() and digits.isdecimal() and int(text) != 0:
                normalized.add(str(int(text)))
        return normalized


class CompositePortfolioWorker:
    def __init__(
        self,
        config: PortfolioWorkerConfig,
        *,
        mt5_module: Any | None = None,
        telegram: TelegramBroadcast | None = None,
    ) -> None:
        self.config = config
        self.session = BoundMt5Session(config, mt5_module=mt5_module)
        self.telegram = telegram or TelegramBroadcast(config.telegram)
        self.revised_engine = RevisedEngine(self._revised_engine_config())
        self.revised_detector = RevisedSetupDetector(
            maximum_m1_bars=self.revised_engine.config.watch_max_m1_bars
        )
        bear_values = dict(config.bear.get("config") or {})
        bear_values.update(
            fixed_target_r=float(config.bear.get("fixed_target_r") or 2.0),
            stop_multiplier=float(config.bear.get("stop_multiplier") or 1.0),
            target_multiplier=float(config.bear.get("target_multiplier") or 1.0),
        )
        self.bear_replay = BearMultiTimeframeReplay(BearV4Config(**bear_values))
        profile_id = {"goldi": "GOLDI", "goldm": "GOLDM"}.get(config.group)
        if profile_id is None:
            raise ValueError(f"unsupported final worker group: {config.group!r}")
        profile = ProfileConfig.from_manifest(
            load_named_profile(ROOT, profile_id),
            tick_size=Decimal(str(self.bear_replay.config.price_tick)),
        )
        self.bear_incremental = BearIncrementalMachine(profile, self.bear_replay)
        self.bear_incremental_state = self.bear_incremental.initial_state(
            datetime(1970, 1, 1, tzinfo=self.session.server_timezone)
        )
        self.state = self._load_state()
        self.health_path = self.config.state_path.with_name("health.json")
        self._last_error_key = ""
        self._last_error_notification_at = 0.0
        self._revised_detector_warmed = False

    def _revised_engine_config(self) -> RevisedEngineConfig:
        source = _json(str(self.config.revised["engine_config_path"]))
        values = dict(source.get("engine") or {})
        values["symbol"] = self.config.symbol
        if "psychological_steps" in values:
            values["psychological_steps"] = tuple(values["psychological_steps"])
        if "strong_m5_patterns" in values:
            values["strong_m5_patterns"] = tuple(values["strong_m5_patterns"])
        return RevisedEngineConfig(**values)

    def run_once(self) -> dict[str, Any]:
        self.session.connect()
        closed_events = self._deliver_closed_positions()
        latest = self._revised_snapshot()
        latest_m1 = latest.m1_bars[-1].time
        if self.state.get("last_m1") == latest_m1.isoformat():
            self._save_state()
            return {
                "group": self.config.group,
                "symbol": self.config.symbol,
                "latest_m1": latest_m1,
                "signals": [],
                "watches": [],
                "watch_events": [],
                "events": [],
                "closed_events": closed_events,
                "new_bar": False,
            }
        signals: list[SignalPlan] = []
        watches: list[WatchEvent] = []
        revised, revised_watch = self._evaluate_revised(latest)
        if revised is not None:
            signals.append(revised)
        if revised_watch is not None:
            watches.append(revised_watch)
        bear, bear_watch = self._evaluate_bear(latest_m1)
        if bear is not None:
            signals.append(bear)
        if bear_watch is not None:
            watches.append(bear_watch)
        watch_events = [
            event for watch in watches if (event := self._process_watch(watch)) is not None
        ]
        events = []
        for signal in signals:
            if self._seen(signal.event_id):
                continue
            self._remember(signal.event_id)
            execution = self.session.execute(signal)
            event = {
                "time": datetime.now(tz=self.session.server_timezone).isoformat(),
                "group": self.config.group,
                "signal": asdict(signal),
                "execution": execution,
            }
            self._audit(event)
            events.append(event)
            if execution.get("status") == "EXECUTED":
                self._track_open_position(signal, execution)
            notification = (
                self._format_signal(signal)
                if execution.get("status") == "SIGNAL_ONLY"
                else self._format_execution(signal, execution)
            )
            self.telegram.send(notification, include_subscribers=True)
        self.state["last_m1"] = latest_m1.isoformat()
        self._save_state()
        return {
            "group": self.config.group,
            "symbol": self.config.symbol,
            "latest_m1": latest_m1,
            "signals": signals,
            "watches": watches,
            "watch_events": watch_events,
            "events": events,
            "closed_events": closed_events,
            "new_bar": True,
        }

    def run_forever(self) -> None:
        started_notified = False
        try:
            while True:
                try:
                    result = self.run_once()
                    self._last_error_key = ""
                    self._write_health(
                        "RUNNING",
                        "new bar" if result.get("new_bar") else "waiting for closed M1",
                    )
                    if not started_notified and self.config.telegram.send_health:
                        account = self.session.account_info()
                        self.telegram.send(
                            f"{self.config.portfolio_id} STARTED\n"
                            f"symbol={self.config.symbol} mode={self.config.execution_mode}\n"
                            f"login={account.login} server={account.server} "
                            f"balance={account.balance:.2f}"
                        )
                        started_notified = True
                except Exception as exc:
                    self._audit(
                        {
                            "time": datetime.now(tz=self.session.server_timezone).isoformat(),
                            "group": self.config.group,
                            "error": str(exc),
                        }
                    )
                    self._write_health("ERROR", str(exc))
                    now = time.monotonic()
                    error_key = f"{type(exc).__name__}:{exc}"
                    should_notify = (
                        error_key != self._last_error_key
                        or now - self._last_error_notification_at >= 300.0
                    )
                    if self.config.telegram.send_health and should_notify:
                        self.telegram.send(f"{self.config.portfolio_id} ERROR\n{exc}")
                        self._last_error_key = error_key
                        self._last_error_notification_at = now
                    self.session.close()
                time.sleep(self.config.poll_seconds)
        finally:
            self._write_health("STOPPED", "worker stopped")
            self.session.close()

    def _revised_snapshot(self) -> RevisedSnapshot:
        m1 = self.session.closed_revised_bars("TIMEFRAME_M1", 180)
        m5 = self.session.closed_revised_bars("TIMEFRAME_M5", 140)
        h1 = self.session.closed_revised_bars("TIMEFRAME_H1", 140)
        d1 = self.session.closed_revised_bars("TIMEFRAME_D1", 140)
        if not m1 or not m5:
            raise RuntimeError("MT5 returned no closed M1/M5 bars")
        return RevisedSnapshot(
            symbol=self.config.symbol,
            side=RevisedSide.BUY,
            current_time=m1[-1].time,
            m1_bars=m1,
            m5_bars=m5,
            h1_bars=h1,
            d1_bars=d1,
        )

    def _evaluate_revised(
        self,
        latest: RevisedSnapshot,
    ) -> tuple[SignalPlan | None, WatchEvent | None]:
        self._warm_revised_detector(latest)
        setup = self.revised_detector.update(
            latest.m5_bars,
            current_m1_time=latest.m1_bars[-1].time,
            side=RevisedSide.BUY,
        )
        if setup is None:
            termination = self.revised_detector.pop_termination(RevisedSide.BUY)
            if termination is None:
                return None, None
            terminated_setup, reason = termination
            state = "EXPIRED" if reason == "WATCH_WINDOW_EXPIRED" else "CANCELLED"
            return None, WatchEvent(
                watch_id=self._revised_watch_id(terminated_setup.trigger_time),
                component="revised",
                symbol=self.config.symbol,
                side="BUY",
                state=state,
                stage="M1_CONFIRMATION",
                time=latest.m1_bars[-1].time,
                trigger_time=terminated_setup.trigger_time,
                reason=reason,
                level=terminated_setup.level,
                invalidation=terminated_setup.invalidation,
            )
        snapshot = replace(
            latest,
            m5_trigger_time=setup.trigger_time,
            m5_pattern=setup.pattern,
            m5_votes=setup.votes,
            confidence=setup.confidence,
            level=setup.level,
            invalidation=setup.invalidation,
        )
        decision = self.revised_engine.evaluate(snapshot)
        watch = WatchEvent(
            watch_id=self._revised_watch_id(setup.trigger_time),
            component="revised",
            symbol=self.config.symbol,
            side="BUY",
            state=(
                "ENTRY_READY"
                if decision.state is RevisedState.ENTRY_READY
                else "CANCELLED"
                if decision.state is RevisedState.CANCELLED
                else "WATCH"
            ),
            stage="M1_CONFIRMATION",
            time=decision.time,
            trigger_time=setup.trigger_time,
            reason=decision.reason,
            level=setup.level,
            invalidation=setup.invalidation,
            entry=decision.entry,
            stop=decision.stop,
            target=decision.target,
            mode=decision.mode.value if decision.mode is not None else None,
            touch_count=decision.touch_count,
            rejection_count=decision.rejection_count,
            evidence={
                "validation_status": decision.validation_status,
                "confidence": decision.confidence,
                "m1_votes": decision.m1_votes,
                "acceptance_count": decision.acceptance_count,
                "exhausted": decision.exhausted,
                "first_obstacle": decision.first_obstacle,
                "first_obstacle_kind": decision.first_obstacle_kind,
                "first_obstacle_r": decision.first_obstacle_r,
            },
        )
        if decision.state is not RevisedState.ENTRY_READY:
            if decision.state is RevisedState.CANCELLED:
                self.revised_detector.consume(RevisedSide.BUY, setup.trigger_time)
            return None, watch
        if decision.entry is None or decision.stop is None or decision.target is None:
            return None, watch
        self.revised_detector.consume(RevisedSide.BUY, setup.trigger_time)
        risk = abs(decision.entry - decision.stop)
        reward = abs(decision.target - decision.entry)
        stop_multiplier = float(self.config.revised.get("stop_multiplier") or 1.0)
        target_multiplier = float(self.config.revised.get("target_multiplier") or 1.0)
        stop = decision.entry - risk * stop_multiplier
        target = decision.entry + reward * target_multiplier
        return SignalPlan(
            event_id=f"revised:{decision.time.isoformat()}:{decision.entry:.2f}",
            component="revised",
            symbol=self.config.symbol,
            side="BUY",
            time=decision.time,
            entry=decision.entry,
            stop=round(stop, 2),
            target=round(target, 2),
            reason=decision.reason,
        ), watch

    def _warm_revised_detector(self, latest: RevisedSnapshot) -> None:
        if self._revised_detector_warmed:
            return
        bars = latest.m5_bars
        start = max(2, len(bars) - 24)
        for end in range(start, len(bars) + 1):
            bar_close = bars[end - 1].time + timedelta(minutes=5)
            causal_m1_time = min(
                latest.m1_bars[-1].time,
                bar_close + timedelta(minutes=1),
            )
            self.revised_detector.update(
                bars[:end],
                current_m1_time=causal_m1_time,
                side=RevisedSide.BUY,
            )
        self._revised_detector_warmed = True

    @staticmethod
    def _revised_watch_id(trigger_time: datetime) -> str:
        return f"revised:BUY:{trigger_time.isoformat()}"

    def _evaluate_bear(
        self,
        latest_m1: datetime,
    ) -> tuple[SignalPlan | None, WatchEvent | None]:
        end = latest_m1 + timedelta(minutes=1)
        start = end - self.bear_incremental.maximum_warmup_span
        m1_bars = self.session.bear_bars_range("TIMEFRAME_M1", start, end)
        m5_bars = self.session.bear_bars_range("TIMEFRAME_M5", start, end)
        m15_bars = self.session.bear_bars_range("TIMEFRAME_M15", start, end)
        h1_bars = self.session.bear_bars_range("TIMEFRAME_H1", start, end)
        output = self.bear_incremental.feed_closed_batches(
            self.bear_incremental_state,
            m1_bars=tuple(m1_bars),
            m5_bars=tuple(m5_bars),
            m15_bars=tuple(m15_bars),
            h1_bars=tuple(h1_bars),
            available_at=end,
            emit_after=latest_m1,
        )
        self.bear_incremental_state = output.next_state
        signal = None
        if output.signal is not None:
            candidate = output.signal
            signal = SignalPlan(
                event_id=candidate.signal_id,
                component="bear",
                symbol=self.config.symbol,
                side="SELL",
                time=candidate.opened_at,
                entry=candidate.entry,
                stop=candidate.stop,
                target=candidate.target,
                reason=candidate.reason,
            )
        watch = self._bear_incremental_watch(latest_m1, output)
        return signal, watch

    def _bear_incremental_watch(
        self,
        latest_m1: datetime,
        output: BearIncrementalOutput,
    ) -> WatchEvent | None:
        state = output.next_state
        candidate = output.signal or state.signal
        if candidate is not None:
            return WatchEvent(
                watch_id=candidate.setup_id,
                component="bear",
                symbol=self.config.symbol,
                side="SELL",
                state="ENTRY_READY",
                stage="M1_CONFIRMATION",
                time=candidate.opened_at,
                trigger_time=candidate.setup_time + timedelta(minutes=15),
                reason=candidate.reason,
                level=state.level,
                invalidation=candidate.stop,
                entry=candidate.entry,
                stop=candidate.stop,
                target=candidate.target,
                mode="RANGE",
                touch_count=candidate.m5_touches,
                rejection_count=candidate.m5_rejections,
                evidence={"m1_touches": candidate.m1_touches},
            )
        if state.phase is BearIncrementalPhase.IDLE or state.setup_id is None:
            return None
        stage, default_reason = {
            BearIncrementalPhase.WATCH_H1: (
                "H1_CONTEXT",
                "H1_BEARISH_CONTEXT_PENDING",
            ),
            BearIncrementalPhase.WATCH_M5: (
                "M5_VALIDATION",
                "M5_RETEST_CONFIRMATION_PENDING",
            ),
            BearIncrementalPhase.WATCH_M1: (
                "M1_CONFIRMATION",
                "M1_RETEST_CONFIRMATION_PENDING",
            ),
            BearIncrementalPhase.CANCELLED: (
                "TERMINAL",
                "BEAR_INCREMENTAL_CANCELLED",
            ),
            BearIncrementalPhase.ENTRY_READY: (
                "M1_CONFIRMATION",
                "M1_ENTRY_CONFIRMATION_READY",
            ),
        }[state.phase]
        reason = output.events[-1].reason if output.events else default_reason
        evidence = {item.name: item.value for item in state.evidence}
        return WatchEvent(
            watch_id=state.setup_id,
            component="bear",
            symbol=self.config.symbol,
            side="SELL",
            state=("CANCELLED" if state.phase is BearIncrementalPhase.CANCELLED else "WATCH"),
            stage=stage,
            time=latest_m1,
            trigger_time=(state.setup_time or latest_m1) + timedelta(minutes=15),
            reason=reason,
            level=state.level,
            invalidation=state.invalidation,
            entry=(state.entry_zone[0] if state.entry_zone is not None else None),
            stop=state.invalidation,
            target=(state.setup.take_profit if state.setup is not None else None),
            mode="RANGE",
            touch_count=state.touches,
            rejection_count=state.rejections,
            evidence={**evidence, "acceptance": state.acceptance},
        )

    def _bear_watch_event(
        self,
        *,
        latest_m1: datetime,
        end: datetime,
        start: datetime,
        m1_bars: Sequence[BearBar],
        m5_bars: Sequence[BearBar],
        m15_bars: Sequence[BearBar],
        h1_bars: Sequence[BearBar],
        report: BearV4Report,
        signal: SignalPlan | None,
    ) -> WatchEvent | None:
        setups = [
            setup
            for setup in self.bear_replay.setup_engine.scan(m15_bars)
            if start <= setup.time < end
        ]
        if not setups:
            return None
        setup = max(setups, key=lambda item: item.time)
        watch_id = f"bear:SELL:{setup.time.isoformat()}"
        setup_available = setup.time + timedelta(minutes=15)
        matching_outcomes = [
            outcome for outcome in report.outcomes if outcome.setup_time == setup.time
        ]
        if matching_outcomes:
            if signal is not None and signal.time == matching_outcomes[-1].opened_at:
                return WatchEvent(
                    watch_id=watch_id,
                    component="bear",
                    symbol=self.config.symbol,
                    side="SELL",
                    state="ENTRY_READY",
                    stage="M1_CONFIRMATION",
                    time=signal.time,
                    trigger_time=setup_available,
                    reason=signal.reason,
                    level=setup.resistance,
                    invalidation=signal.stop,
                    entry=signal.entry,
                    stop=signal.stop,
                    target=signal.target,
                )
            return None
        h1_close_times = [bar.time + timedelta(hours=1) for bar in h1_bars]
        h1_index = bisect_right(h1_close_times, setup_available)
        h1_history = h1_bars[
            max(0, h1_index - self.bear_replay.config.h1_sma_period - 2) : h1_index
        ]
        base = {
            "watch_id": watch_id,
            "component": "bear",
            "symbol": self.config.symbol,
            "side": "SELL",
            "time": latest_m1,
            "trigger_time": setup_available,
            "level": setup.resistance,
            "invalidation": setup.stop,
            "entry": setup.entry,
            "stop": setup.stop,
            "target": setup.take_profit,
            "mode": "RANGE",
        }
        if latest_m1 < setup_available:
            return WatchEvent(
                **base,
                state="WATCH",
                stage="M15_CLOSE",
                reason="M15_SETUP_AWAITING_CAUSAL_CLOSE",
            )
        if not self.bear_replay._h1_bearish(h1_history):
            return WatchEvent(
                **base,
                state="CANCELLED",
                stage="H1_CONTEXT",
                reason="H1_BEARISH_CONTEXT_REJECTED",
            )
        m5_times = [bar.time for bar in m5_bars]
        m5_index = bisect_left(m5_times, setup_available)
        validation_start = max(0, m5_index - 3)
        m5_candidates = m5_bars[
            validation_start : validation_start + self.bear_replay.config.m5_watch_bars
        ]
        m5_result = self.bear_replay._arm_on_m5(
            setup,
            m5_bars[max(0, validation_start - 20) : validation_start],
            m5_candidates,
            setup_available,
        )
        m5_state = str(m5_result.get("state") or "EXPIRED")
        touches = int(m5_result.get("touches") or 0)
        rejections = int(m5_result.get("rejections") or 0)
        if m5_state == "CANCELLED":
            return WatchEvent(
                **base,
                state="CANCELLED",
                stage="M5_VALIDATION",
                reason=str(m5_result.get("reason") or "M5_VALIDATION_CANCELLED"),
                touch_count=touches,
                rejection_count=rejections,
            )
        if m5_state != "ARMED":
            complete_window = len(m5_candidates) >= self.bear_replay.config.m5_watch_bars
            return WatchEvent(
                **base,
                state="EXPIRED" if complete_window else "WATCH",
                stage="M5_VALIDATION",
                reason=(
                    "M5_WATCH_WINDOW_EXPIRED"
                    if complete_window
                    else "M5_RETEST_CONFIRMATION_PENDING"
                ),
                touch_count=touches,
                rejection_count=rejections,
                evidence={"observed_m5_bars": len(m5_candidates)},
            )
        armed_at = m5_result["armed_at"]
        m1_times = [bar.time for bar in m1_bars]
        m1_index = bisect_left(m1_times, armed_at)
        m1_candidates = m1_bars[m1_index : m1_index + self.bear_replay.config.m1_entry_bars]
        entry_plan = self.bear_replay._entry_on_m1(
            setup,
            m5_result,
            m1_bars[max(0, m1_index - 20) : m1_index],
            m1_candidates,
        )
        if entry_plan is not None:
            ready_fields = dict(base)
            ready_fields.update(
                time=entry_plan["opened_at"],
                entry=float(entry_plan["entry"]),
                stop=float(entry_plan["stop"]),
                target=float(entry_plan["target"]),
            )
            return WatchEvent(
                **ready_fields,
                state="ENTRY_READY",
                stage="M1_CONFIRMATION",
                reason="M1_ENTRY_CONFIRMATION_READY",
                touch_count=touches,
                rejection_count=rejections,
            )
        complete_m1_window = len(m1_candidates) >= self.bear_replay.config.m1_entry_bars
        return WatchEvent(
            **base,
            state="EXPIRED" if complete_m1_window else "WATCH",
            stage="M1_CONFIRMATION",
            reason=(
                "M1_WATCH_WINDOW_EXPIRED_OR_INVALIDATED"
                if complete_m1_window
                else "M1_RETEST_CONFIRMATION_PENDING"
            ),
            touch_count=touches,
            rejection_count=rejections,
            evidence={
                "armed_at": armed_at.isoformat(),
                "observed_m1_bars": len(m1_candidates),
            },
        )

    def _process_watch(self, watch: WatchEvent) -> dict[str, Any] | None:
        active = dict(self.state.get("active_watches") or {})
        key = f"{watch.component}:{watch.side}"
        if watch.state in {"ENTRY_READY", "CANCELLED", "EXPIRED"}:
            active.pop(key, None)
            self.state["active_watches"] = active
            return None
        active[key] = {
            "watch_id": watch.watch_id,
            "stage": watch.stage,
            "reason": watch.reason,
            "server_time": watch.time.isoformat(),
            "level": watch.level,
            "invalidation": watch.invalidation,
            "mode": watch.mode,
            "touches": watch.touch_count,
            "rejections": watch.rejection_count,
        }
        self.state["active_watches"] = active
        return None

    def _format_signal(self, signal: SignalPlan) -> str:
        account = self.session.account_info()
        vm_time = datetime.now().astimezone()
        return (
            f"🟡 ENTRY SIAP — {signal.symbol} {signal.side}\n"
            f"Engine: {signal.component.title()}\n"
            f"Akun: {account.login} ({self.config.execution_mode.upper()})\n\n"
            f"Rencana transaksi\n"
            f"• Entry: {signal.entry:.2f}\n"
            f"• Stop Loss: {signal.stop:.2f}\n"
            f"• Take Profit: {signal.target:.2f}\n\n"
            f"Identitas\n"
            f"• ID sinyal: {signal.event_id}\n"
            f"• Instrumen: {signal.symbol}\n\n"
            f"Waktu\n"
            f"• Server broker: {self._human_time(signal.time)}\n"
            f"• VM: {self._human_time(vm_time)}\n\n"
            f"Alasan: {self._human_reason(signal.reason)}\n"
            f"Kode: {signal.reason}"
        )

    def _format_execution(self, signal: SignalPlan, execution: dict[str, Any]) -> str:
        account = self.session.account_info()
        status = str(execution.get("status") or "UNKNOWN")
        if status == "EXECUTED":
            heading = f"✅ ENTRY DIBUKA — {self.config.execution_mode.upper()}"
        elif status == "BLOCKED":
            heading = "⛔ ENTRY DIBLOKIR"
        else:
            heading = "❌ ENTRY DITOLAK"
        return (
            f"{heading}\n"
            f"{signal.symbol} • {signal.side} • {signal.component.title()}\n"
            f"Akun: {account.login}\n\n"
            f"Eksekusi\n"
            f"• Volume: {execution.get('volume', '-')} lot\n"
            f"• Harga: {execution.get('price', '-')}\n"
            f"• Stop Loss: {execution.get('sl', '-')}\n"
            f"• Take Profit: {execution.get('tp', '-')}\n"
            f"• Saldo setelah entry: {execution.get('balance', '-')} USD\n\n"
            f"Identitas\n"
            f"• ID sinyal: {signal.event_id}\n"
            f"• ID order: {execution.get('order', '-')}\n"
            f"• ID deal: {execution.get('deal', '-')}\n"
            f"• ID request: {execution.get('request_id', '-')}\n"
            f"• Instrumen: {signal.symbol}\n\n"
            f"Waktu\n"
            f"• Server broker: {self._human_time(execution.get('server_time'))}\n"
            f"• VM: {self._human_time(execution.get('vm_time'))}\n\n"
            f"Keputusan: {self._human_reason(signal.reason)}\n"
            f"Status broker: {status} • retcode {execution.get('retcode', '-')}\n"
            f"Catatan: {execution.get('comment', execution.get('reason', '-'))}"
        )

    def _track_open_position(
        self,
        signal: SignalPlan,
        execution: dict[str, Any],
    ) -> None:
        ticket = int(execution.get("order") or 0)
        if ticket <= 0:
            return
        positions = dict(self.state.get("open_positions") or {})
        opened_at = (
            execution.get("server_time")
            or datetime.now(tz=self.session.server_timezone).isoformat()
        )
        positions[str(ticket)] = {
            "signal": asdict(signal),
            "opened_at": opened_at,
            "order_id": ticket,
            "deal_id": int(execution.get("deal") or 0),
            "request_id": int(execution.get("request_id") or 0),
            "fill_price": float(execution.get("price") or signal.entry),
            "volume": float(execution.get("volume") or 0.0),
            "sl": float(execution.get("sl") or signal.stop),
            "tp": float(execution.get("tp") or signal.target),
            "balance_after_entry": float(execution.get("balance") or 0.0),
        }
        self.state["open_positions"] = positions

    def _deliver_closed_positions(self) -> list[dict[str, Any]]:
        positions = dict(self.state.get("open_positions") or {})
        delivered: list[dict[str, Any]] = []
        for ticket_text, tracked in list(positions.items()):
            ticket = int(ticket_text)
            result = self.session.closed_position_result(ticket)
            if result is None:
                continue
            opened_at = datetime.fromisoformat(str(tracked["opened_at"]))
            close_time = result["close_time"]
            duration_seconds = max(0, int((close_time - opened_at).total_seconds()))
            fill = float(tracked["fill_price"])
            sl = float(tracked["sl"])
            tp = float(tracked["tp"])
            volume = float(tracked["volume"])
            info = self.session.mt5.symbol_info(self.config.symbol)
            risk_price = abs(fill - sl)
            reward_price = abs(tp - fill)
            planned_rr = reward_price / risk_price if risk_price > 0 else 0.0
            risk_cash = risk_price * float(info.trade_contract_size) * volume
            realized_r = float(result["profit_loss"]) / risk_cash if risk_cash > 0 else 0.0
            signal = dict(tracked.get("signal") or {})
            close_event = {
                **result,
                "component": signal.get("component"),
                "side": signal.get("side"),
                "reason": signal.get("reason"),
                "event_id": signal.get("event_id"),
                "opened_at": opened_at,
                "duration_seconds": duration_seconds,
                "planned_rr": planned_rr,
                "realized_r": realized_r,
                "entry_price": fill,
                "sl": sl,
                "tp": tp,
                "volume": volume,
            }
            self.telegram.send(
                self._format_close(close_event),
                include_subscribers=True,
            )
            self._audit(
                {
                    "time": close_time.isoformat(),
                    "group": self.config.group,
                    "close": close_event,
                }
            )
            delivered.append(close_event)
            positions.pop(ticket_text, None)
        self.state["open_positions"] = positions
        return delivered

    def _format_close(self, event: dict[str, Any]) -> str:
        duration = int(event["duration_seconds"])
        hours, remainder = divmod(duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        account = self.session.account_info()
        vm_time = datetime.now().astimezone()
        profit_loss = float(event["profit_loss"])
        result_label = "PROFIT" if profit_loss >= 0 else "LOSS"
        icon = "✅" if profit_loss >= 0 else "🔻"
        return (
            f"{icon} POSISI DITUTUP — {result_label}\n"
            f"{self.config.symbol} • {event.get('side')} • "
            f"{str(event.get('component') or '-').title()}\n"
            f"Akun: {account.login} ({self.config.execution_mode.upper()})\n\n"
            f"Hasil transaksi\n"
            f"• Entry: {event['entry_price']:.2f}\n"
            f"• Close: {event['close_price']:.2f}\n"
            f"• Volume: {event['volume']:.2f} lot\n"
            f"• P/L: {profit_loss:+.2f} USD\n"
            f"• Realized R: {event['realized_r']:+.2f}R\n"
            f"• R:R rencana: {event['planned_rr']:.2f}\n"
            f"• Durasi: {hours:02d}:{minutes:02d}:{seconds:02d}\n"
            f"• Saldo: {event['balance']:.2f} USD\n"
            f"• Equity: {event['equity']:.2f} USD\n\n"
            f"Identitas\n"
            f"• ID sinyal: {event.get('event_id', '-')}\n"
            f"• ID posisi: {event.get('position_ticket', '-')}\n"
            f"• Instrumen: {self.config.symbol}\n\n"
            f"Waktu\n"
            f"• Server broker: {self._human_time(event['close_time'])}\n"
            f"• VM: {self._human_time(vm_time)}\n\n"
            f"Keputusan awal: {self._human_reason(str(event.get('reason') or '-'))}"
        )

    @staticmethod
    def _human_reason(reason: str) -> str:
        return reason.replace("_", " ").strip().capitalize()

    @staticmethod
    def _human_time(value: object) -> str:
        if value in {None, "", "-"}:
            return "-"
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value))
            except ValueError:
                return str(value)
        months = (
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "Mei",
            "Jun",
            "Jul",
            "Agu",
            "Sep",
            "Okt",
            "Nov",
            "Des",
        )
        offset = parsed.utcoffset()
        if offset is None:
            zone = str(parsed.tzname() or "tanpa timezone")
        else:
            total_minutes = int(offset.total_seconds() // 60)
            sign = "+" if total_minutes >= 0 else "-"
            absolute = abs(total_minutes)
            zone = f"GMT{sign}{absolute // 60}"
            if absolute % 60:
                zone += f":{absolute % 60:02d}"
        return f"{parsed.day:02d} {months[parsed.month - 1]} {parsed.year} {parsed:%H:%M:%S} {zone}"

    def _load_state(self) -> dict[str, Any]:
        if not self.config.state_path.exists():
            return {"seen": []}
        payload = json.loads(self.config.state_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"seen": []}

    def _save_state(self) -> None:
        self.config.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.state, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.config.state_path)

    def _seen(self, event_id: str) -> bool:
        return event_id in set(self.state.get("seen") or [])

    def _remember(self, event_id: str) -> None:
        seen = list(self.state.get("seen") or [])
        seen.append(event_id)
        self.state["seen"] = seen[-500:]

    def _audit(self, payload: dict[str, Any]) -> None:
        self.config.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._rotate_audit()
        with self.config.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")

    def _rotate_audit(self) -> None:
        path = self.config.audit_path
        try:
            if path.stat().st_size < AUDIT_MAX_BYTES:
                return
        except FileNotFoundError:
            return
        oldest = Path(f"{path}.{AUDIT_BACKUPS}")
        if oldest.exists():
            oldest.unlink()
        for index in range(AUDIT_BACKUPS - 1, 0, -1):
            source = Path(f"{path}.{index}")
            if source.exists():
                os.replace(source, Path(f"{path}.{index + 1}"))
        os.replace(path, Path(f"{path}.1"))

    def _write_health(self, status: str, detail: str) -> None:
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        account_fields: dict[str, Any] = {}
        if self.session.connected:
            try:
                account = self.session.mt5.account_info()
            except Exception:
                account = None
            if account is not None:
                account_fields = {
                    "login": int(account.login),
                    "server": str(account.server),
                    "balance": float(account.balance),
                    "equity": float(account.equity),
                }
        temporary = self.health_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "group": self.config.group,
                    "portfolio_id": self.config.portfolio_id,
                    "symbol": self.config.symbol,
                    "execution_mode": self.config.execution_mode,
                    "status": status,
                    "detail": detail,
                    **account_fields,
                    "updated_at": datetime.now(tz=self.session.server_timezone).isoformat(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.health_path)
