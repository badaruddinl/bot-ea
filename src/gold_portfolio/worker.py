from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from goldm_bear.multitimeframe import BearMultiTimeframeReplay, BearV4Config
from goldm_revised.engine import (
    RevisedEngine,
    RevisedEngineConfig,
    RevisedSide,
    RevisedSnapshot,
    RevisedState,
)
from goldm_revised.setup import RevisedSetupDetector
from goldm_signal.notify.telegram import TelegramBotClient

from .config import PortfolioWorkerConfig
from .models import SignalPlan
from .mt5_session import BoundMt5Session


ROOT = Path(__file__).resolve().parents[2]


def _json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"config must be an object: {resolved}")
    return payload


class TelegramBroadcast:
    def __init__(self, config) -> None:
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
        return {
            str(int(item))
            for item in (values or [])
            if str(item).isascii()
            and str(item).isdecimal()
            and int(str(item)) > 0
        }


class CompositePortfolioWorker:
    def __init__(
        self,
        config: PortfolioWorkerConfig,
        *,
        mt5_module=None,
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
        self.state = self._load_state()
        self.health_path = self.config.state_path.with_name("health.json")
        self._last_error_key = ""
        self._last_error_notification_at = 0.0

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
                "events": [],
                "closed_events": closed_events,
                "new_bar": False,
            }
        signals: list[SignalPlan] = []
        revised = self._evaluate_revised(latest)
        if revised is not None:
            signals.append(revised)
        bear = self._evaluate_bear(latest_m1)
        if bear is not None:
            signals.append(bear)
        events = []
        for signal in signals:
            if self._seen(signal.event_id):
                continue
            self._remember(signal.event_id)
            self.telegram.send(
                self._format_signal(signal),
                include_subscribers=True,
            )
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
            if execution.get("status") not in {"SIGNAL_ONLY"}:
                self.telegram.send(
                    self._format_execution(signal, execution),
                    include_subscribers=True,
                )
        self.state["last_m1"] = latest_m1.isoformat()
        self._save_state()
        return {
            "group": self.config.group,
            "symbol": self.config.symbol,
            "latest_m1": latest_m1,
            "signals": signals,
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

    def _evaluate_revised(self, latest: RevisedSnapshot) -> SignalPlan | None:
        setup = self.revised_detector.update(
            latest.m5_bars,
            current_m1_time=latest.m1_bars[-1].time,
            side=RevisedSide.BUY,
        )
        if setup is None:
            self.revised_detector.pop_termination(RevisedSide.BUY)
            return None
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
        if decision.state is not RevisedState.ENTRY_READY:
            return None
        if decision.entry is None or decision.stop is None or decision.target is None:
            return None
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
        )

    def _evaluate_bear(self, latest_m1: datetime) -> SignalPlan | None:
        lookback_days = int(self.config.bear.get("lookback_days") or 30)
        end = latest_m1 + timedelta(minutes=1)
        start = end - timedelta(days=lookback_days)
        report = self.bear_replay.run(
            m1_bars=self.session.bear_bars_range("TIMEFRAME_M1", start, end),
            m5_bars=self.session.bear_bars_range("TIMEFRAME_M5", start, end),
            m15_bars=self.session.bear_bars_range("TIMEFRAME_M15", start, end),
            h1_bars=self.session.bear_bars_range("TIMEFRAME_H1", start, end),
            from_time=start,
            to_time=end,
        )
        candidates = [
            outcome
            for outcome in report.outcomes
            if outcome.opened_at >= latest_m1
            and outcome.result == "END_OF_TEST"
        ]
        if not candidates:
            return None
        outcome = max(candidates, key=lambda item: item.opened_at)
        return SignalPlan(
            event_id=f"bear:{outcome.opened_at.isoformat()}:{outcome.entry:.2f}",
            component="bear",
            symbol=self.config.symbol,
            side="SELL",
            time=outcome.opened_at,
            entry=outcome.entry,
            stop=outcome.stop,
            target=outcome.target,
            reason=outcome.setup_reason,
        )

    def _format_signal(self, signal: SignalPlan) -> str:
        account = self.session.account_info()
        vm_time = datetime.now().astimezone()
        return (
            f"{self.config.portfolio_id} SIGNAL\n"
            f"instrument={signal.symbol} engine={signal.component} side={signal.side}\n"
            f"signal_id={signal.event_id} account_id={account.login}\n"
            f"entry={signal.entry:.2f} sl={signal.stop:.2f} tp={signal.target:.2f}\n"
            f"balance={float(account.balance):.2f} equity={float(account.equity):.2f}\n"
            f"server_time={signal.time.astimezone(self.session.server_timezone).isoformat()}\n"
            f"vm_time={vm_time.isoformat()} vm_timezone={vm_time.tzname()}\n"
            f"reason={signal.reason}"
        )

    def _format_execution(self, signal: SignalPlan, execution: dict[str, Any]) -> str:
        account = self.session.account_info()
        return (
            f"{self.config.portfolio_id} ENTRY {execution.get('status')}\n"
            f"instrument={signal.symbol} engine={signal.component} side={signal.side}\n"
            f"signal_id={signal.event_id} account_id={account.login}\n"
            f"order_id={execution.get('order', '-')} deal_id={execution.get('deal', '-')} "
            f"request_id={execution.get('request_id', '-')}\n"
            f"volume={execution.get('volume', '-')} price={execution.get('price', '-')}\n"
            f"sl={execution.get('sl', '-')} tp={execution.get('tp', '-')}\n"
            f"balance={execution.get('balance', '-')}\n"
            f"server_time={execution.get('server_time') or '-'}\n"
            f"vm_time={execution.get('vm_time') or '-'}\n"
            f"retcode={execution.get('retcode', '-')} {execution.get('comment', execution.get('reason', ''))}"
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
        opened_at = execution.get("server_time") or datetime.now(
            tz=self.session.server_timezone
        ).isoformat()
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
            realized_r = (
                float(result["profit_loss"]) / risk_cash if risk_cash > 0 else 0.0
            )
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
        return (
            f"{self.config.portfolio_id} CLOSED\n"
            f"instrument={self.config.symbol} engine={event.get('component')} "
            f"side={event.get('side')}\n"
            f"signal_id={event.get('event_id', '-')} account_id={account.login} "
            f"position_id={event.get('position_ticket', '-')}\n"
            f"entry={event['entry_price']:.2f} close={event['close_price']:.2f} "
            f"volume={event['volume']:.2f}\n"
            f"P/L={event['profit_loss']:+.2f} USD realized_R={event['realized_r']:+.2f} "
            f"planned_RR={event['planned_rr']:.2f}\n"
            f"duration={hours:02d}:{minutes:02d}:{seconds:02d} "
            f"balance={event['balance']:.2f} equity={event['equity']:.2f}\n"
            f"server_time={event['close_time'].isoformat()}\n"
            f"vm_time={vm_time.isoformat()} vm_timezone={vm_time.tzname()}\n"
            f"decision={event.get('reason', '-') }"
        )

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
        with self.config.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")

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
                    "updated_at": datetime.now(
                        tz=self.session.server_timezone
                    ).isoformat(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.health_path)
