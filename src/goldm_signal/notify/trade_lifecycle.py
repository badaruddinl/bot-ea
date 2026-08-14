from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from bot_ea.models import PositionSizeRequest, RiskPolicy, TradingStyle
from bot_ea.mt5_adapter import MT5Adapter
from bot_ea.mt5_execution_runtime import MT5ExecutionRuntime
from bot_ea.polling_runtime import AIIntent, DecisionAction, MT5SnapshotProvider
from bot_ea.risk_engine import RiskEngine

from ..storage.database import SignalStore
from .mt5_log import render_stored_event


@dataclass(frozen=True, slots=True)
class TradeLifecycleConfig:
    enabled: bool = False
    execution_mode: str = "off"
    risk_pct: float = 0.5
    max_total_open_risk_pct: float = 1.0
    daily_loss_limit_pct: float = 2.0
    signal_ttl_minutes: int = 5
    max_entry_drift_r: float = 0.15
    magic: int = 260814
    expected_login: str = ""
    expected_server: str = ""
    live_consent: str = ""

    @classmethod
    def from_env(cls) -> "TradeLifecycleConfig":
        mode = os.environ.get("GOLDM_EXECUTION_MODE", "off").strip().lower()
        if mode not in {"off", "demo", "live"}:
            raise ValueError("GOLDM_EXECUTION_MODE must be off, demo, or live")
        return cls(
            enabled=_bool_env("GOLDM_TRADE_LIFECYCLE_ENABLED", False),
            execution_mode=mode,
            risk_pct=float(os.environ.get("GOLDM_RISK_PCT", "0.5")),
            max_total_open_risk_pct=float(os.environ.get("GOLDM_MAX_OPEN_RISK_PCT", "1.0")),
            daily_loss_limit_pct=float(os.environ.get("GOLDM_DAILY_LOSS_LIMIT_PCT", "2.0")),
            signal_ttl_minutes=int(os.environ.get("GOLDM_SIGNAL_TTL_MINUTES", "5")),
            max_entry_drift_r=float(os.environ.get("GOLDM_MAX_ENTRY_DRIFT_R", "0.15")),
            magic=int(os.environ.get("GOLDM_MAGIC", "260814")),
            expected_login=os.environ.get("GOLDM_EXPECTED_MT5_LOGIN", "").strip(),
            expected_server=os.environ.get("GOLDM_EXPECTED_MT5_SERVER", "").strip(),
            live_consent=os.environ.get("GOLDM_LIVE_ORDER_CONSENT", "").strip(),
        )

    @classmethod
    def from_sources(
        cls,
        store: SignalStore,
        *,
        fallback: "TradeLifecycleConfig | None" = None,
    ) -> "TradeLifecycleConfig":
        base = fallback or cls.from_env()
        values = store.runtime_settings(prefix="trade.")
        mode = str(values.get("trade.execution_mode", base.execution_mode)).lower()
        if mode not in {"off", "demo", "live"}:
            mode = "off"
        return cls(
            enabled=base.enabled,
            execution_mode=mode,
            risk_pct=float(values.get("trade.risk_pct", base.risk_pct)),
            max_total_open_risk_pct=float(
                values.get("trade.max_open_risk_pct", base.max_total_open_risk_pct)
            ),
            daily_loss_limit_pct=float(
                values.get("trade.daily_loss_limit_pct", base.daily_loss_limit_pct)
            ),
            signal_ttl_minutes=int(
                values.get("trade.signal_ttl_minutes", base.signal_ttl_minutes)
            ),
            max_entry_drift_r=float(
                values.get("trade.max_entry_drift_r", base.max_entry_drift_r)
            ),
            magic=int(values.get("trade.magic", base.magic)),
            expected_login=str(values.get("trade.expected_login", base.expected_login)),
            expected_server=str(values.get("trade.expected_server", base.expected_server)),
            live_consent=str(values.get("trade.live_consent", base.live_consent)),
        )


class TradeLifecycleWorker:
    """Size, gate, execute, and reconcile GoldM signals against the broker account.

    Telegram subscriber approval is deliberately absent from this class. Trading
    authority comes from the execution mode, account pin, and live-consent gates;
    their runtime overrides are written only by a root-admin control action.
    """

    def __init__(
        self,
        *,
        store: SignalStore,
        adapter: MT5Adapter,
        config: TradeLifecycleConfig,
        now_fn=None,
    ) -> None:
        self.store = store
        self.adapter = adapter
        self.config = config
        self.risk_engine = RiskEngine()
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def run_once(self) -> tuple[int, int, int]:
        self.config = TradeLifecycleConfig.from_sources(self.store, fallback=self.config)
        planned = sum(self._process_signal(row) for row in self.store.execution_candidates())
        outcomes = sum(
            self._process_model_outcome(row)
            for row in self.store.execution_candidates(event_type="SNIPER_OUTCOME")
        )
        closed = self._reconcile_positions()
        return planned, outcomes, closed

    def _process_signal(self, row: dict[str, Any]) -> int:
        payload = dict(row["payload"])
        fields = {str(key): str(value) for key, value in payload.get("fields", {}).items()}
        setup_id = str(row["setup_id"])
        symbol = str(row["symbol"])
        side = str(row["side"]).lower()
        entry = _float(fields, "entry")
        stop = _float(fields, "stop")
        target = _float(fields, "target")
        generated_at = _parse_iso(payload.get("generated_at_utc")) or self.now_fn()
        valid_until = _epoch_datetime(fields.get("validUntilUtcEpoch")) or (
            generated_at + timedelta(minutes=self.config.signal_ttl_minutes)
        )
        client_tag = hashlib.sha256(setup_id.encode("utf-8")).hexdigest()[:10]
        record = _execution_record(
            row=row,
            mode=self.config.execution_mode,
            entry=entry,
            stop=stop,
            target=target,
            valid_until=valid_until,
            client_tag=client_tag,
        )

        if min(entry, stop, target) <= 0 or side not in {"buy", "sell"}:
            return self._reject_signal(row, payload, fields, record, "RISK_REJECTED", "invalid entry/stop/target/side")
        if self.now_fn() > valid_until:
            return self._reject_signal(row, payload, fields, record, "EXPIRED", "masa berlaku sinyal sudah habis")

        try:
            point_snapshot = self.adapter.load_symbol_snapshot(symbol)
            point = float(point_snapshot.point or 0.0)
            if point <= 0:
                raise ValueError("MT5 symbol point is unavailable")
            stop_points = abs(entry - stop) / point
            policy = RiskPolicy(
                base_risk_pct=self.config.risk_pct,
                max_total_open_risk_pct=self.config.max_total_open_risk_pct,
                daily_loss_limit_pct=self.config.daily_loss_limit_pct,
            )
            snapshot = MT5SnapshotProvider(
                adapter=self.adapter,
                symbol=symbol,
                timeframe="M15",
                risk_policy=policy,
                trading_style=TradingStyle.INTRADAY,
                stop_distance_points=stop_points,
            ).get_snapshot()
            size = self.risk_engine.compute_position_size(
                PositionSizeRequest(
                    account=snapshot.account,
                    symbol=snapshot.symbol_snapshot,
                    policy=policy,
                    stop_distance_points=stop_points,
                    trading_style=TradingStyle.INTRADAY,
                    force_symbol=True,
                )
            )
            if not size.accepted:
                return self._reject_signal(
                    row, payload, fields, record, "RISK_REJECTED", size.rejection_reason or "risk sizing rejected"
                )

            live_price = snapshot.ask if side == "buy" else snapshot.bid
            risk_distance = abs(entry - stop)
            if risk_distance <= 0 or abs(live_price - entry) / risk_distance > self.config.max_entry_drift_r:
                return self._reject_signal(
                    row, payload, fields, record, "PRECHECK_REJECTED", "harga bergerak melewati batas entry drift"
                )

            projected_r = float(fields.get("projectedR", 0.0) or 0.0)
            record.update(
                volume=size.normalized_volume,
                risk_cash=size.estimated_loss_cash,
                expected_profit_cash=size.estimated_loss_cash * projected_r,
            )
            intent = AIIntent(
                action=DecisionAction.OPEN,
                side=side,
                reason=client_tag,
                stop_distance_points=stop_points,
                entry_price=entry,
                payload={"sl": stop, "tp": target},
            )
            runtime = MT5ExecutionRuntime(
                adapter=self.adapter,
                allow_live_orders=self.config.execution_mode in {"demo", "live"},
                magic=self.config.magic,
                comment_prefix="GMS",
            )
            gate_error = self._account_gate(snapshot)
            if gate_error:
                return self._reject_signal(row, payload, fields, record, "GUARD_REJECTED", gate_error)
            preflight = runtime.preflight(snapshot, intent, size)
            if preflight["status"] != "PRECHECK_OK":
                return self._reject_signal(
                    row, payload, fields, record, str(preflight["status"]), str(preflight.get("detail", "precheck rejected"))
                )
            if self.config.execution_mode == "off":
                record["status"] = "READY_MANUAL"
                self.store.save_trade_execution(record)
                self._enrich_signal(row, payload, fields, record, "READY_MANUAL", "execution mode off")
                return 1

            result = runtime.execute(snapshot, intent, size, preflight)
            status = str(result["status"])
            record.update(
                status=status,
                order_ticket=result.get("order"),
                deal_ticket=result.get("deal"),
                actual_entry=result.get("realized_price") or result.get("price"),
                opened_at=self.now_fn().isoformat() if status == "FILLED" else None,
                last_error=None if status == "FILLED" else str(result.get("detail", "execution rejected")),
            )
            if status == "FILLED":
                position = self._find_position(record)
                if position is not None:
                    record["position_ticket"] = position.ticket
                    record["actual_entry"] = position.price_open
                    record["opened_at"] = position.opened_at or record["opened_at"]
            self.store.save_trade_execution(record)
            self._enrich_signal(row, payload, fields, record, status, str(result.get("detail", "")))
            if status == "FILLED":
                self._enqueue_position_opened(record)
            return 1
        except Exception as exc:
            return self._reject_signal(row, payload, fields, record, "PRECHECK_REJECTED", str(exc))

    def _account_gate(self, snapshot) -> str | None:
        if self.config.execution_mode == "off":
            return None
        fingerprint = snapshot.context.get("account_fingerprint", {})
        is_live = fingerprint.get("is_live")
        if self.config.execution_mode == "demo" and is_live is not False:
            return "mode demo menolak akun live atau akun yang tidak dapat diidentifikasi"
        if self.config.execution_mode == "live":
            if self.config.live_consent != "I_UNDERSTAND_LIVE_ORDERS":
                return "live order consent belum eksplisit"
            if not self.config.expected_login or not self.config.expected_server:
                return "expected login dan server wajib untuk mode live"
        if self.config.expected_login and str(fingerprint.get("login")) != self.config.expected_login:
            return "MT5 login tidak cocok dengan konfigurasi"
        if self.config.expected_server and str(fingerprint.get("server")) != self.config.expected_server:
            return "MT5 server tidak cocok dengan konfigurasi"
        return None

    def _reject_signal(self, row, payload, fields, record, status: str, detail: str) -> int:
        record.update(status=status, last_error=detail)
        self.store.save_trade_execution(record)
        self._enrich_signal(row, payload, fields, record, status, detail)
        return 1

    def _enrich_signal(self, row, payload, fields, record, status: str, detail: str) -> None:
        fields.update(
            volume=f"{float(record['volume']):.2f}" if record["volume"] else "0",
            expectedLossCash=f"{float(record['risk_cash']):.2f}" if record["risk_cash"] else "0",
            expectedProfitCash=f"{float(record['expected_profit_cash']):.2f}" if record["expected_profit_cash"] else "0",
            executionStatus=status,
            executionDetail=detail,
            orderTicket=str(record.get("order_ticket") or ""),
            positionTicket=str(record.get("position_ticket") or ""),
            actualEntry=str(record.get("actual_entry") or ""),
        )
        payload["fields"] = fields
        setup_at = _parse_iso(payload.get("setup_at_utc")) or _parse_iso(row.get("breakout_at")) or self.now_fn()
        generated_at = _parse_iso(payload.get("generated_at_utc")) or setup_at
        payload["text"] = render_stored_event(
            event_type="SNIPER_SIGNAL",
            setup_id=str(row["setup_id"]),
            symbol=str(row["symbol"]),
            side=str(row["side"]),
            level=float(row["level"]),
            setup_at=setup_at,
            generated_at=generated_at,
            fields=fields,
        )
        self.store.update_outbox_payload(int(row["id"]), payload)

    def _process_model_outcome(self, row: dict[str, Any]) -> int:
        execution = self.store.trade_execution(str(row["setup_id"]))
        result_name = str(row["payload"].get("fields", {}).get("result", ""))
        if execution is None or execution["status"] not in {"FILLED", "CLOSE_SUBMITTED"}:
            self.store.mark_trade_event_processed(
                outbox_id=int(row["id"]), event_type="SNIPER_OUTCOME", result="no active broker execution"
            )
            return 1
        if result_name not in {"M1_DEFENSIVE", "M1_MANAGEMENT", "TIMEOUT"}:
            self.store.mark_trade_event_processed(
                outbox_id=int(row["id"]), event_type="SNIPER_OUTCOME", result="broker SL/TP or observation only"
            )
            return 1
        position = self._find_position(execution)
        if position is None:
            self.store.mark_trade_event_processed(
                outbox_id=int(row["id"]), event_type="SNIPER_OUTCOME", result="position already absent"
            )
            return 1
        if self.config.execution_mode not in {"demo", "live"}:
            self.store.mark_trade_event_processed(
                outbox_id=int(row["id"]), event_type="SNIPER_OUTCOME", result="execution mode off"
            )
            return 1

        symbol = str(execution["symbol"])
        side = str(execution["side"]).lower()
        point = self.adapter.load_symbol_snapshot(symbol).point
        policy = RiskPolicy(
            base_risk_pct=self.config.risk_pct,
            max_total_open_risk_pct=self.config.max_total_open_risk_pct,
            daily_loss_limit_pct=self.config.daily_loss_limit_pct,
        )
        snapshot = MT5SnapshotProvider(
            adapter=self.adapter, symbol=symbol, timeframe="M1", risk_policy=policy,
            trading_style=TradingStyle.INTRADAY, stop_distance_points=max(1.0, abs(execution["requested_entry"] - execution["stop_price"]) / point),
        ).get_snapshot()
        runtime = MT5ExecutionRuntime(
            adapter=self.adapter, allow_live_orders=True, magic=self.config.magic, comment_prefix="GMS"
        )
        intent = AIIntent(
            action=DecisionAction.CLOSE,
            side=side,
            reason=f"auto-{result_name.lower()}",
            payload={"position_ticket": position.ticket, "volume": position.volume},
        )
        size = SimpleNamespace(normalized_volume=position.volume)
        close_result = runtime.execute(snapshot, intent, size)
        execution.update(
            status="CLOSE_SUBMITTED" if close_result["status"] == "FILLED" else "CLOSE_REJECTED",
            close_reason=result_name,
            closed_by="strategy_auto",
            last_error=None if close_result["status"] == "FILLED" else str(close_result.get("detail", "close rejected")),
        )
        self.store.save_trade_execution(execution)
        event_type = "AUTO_CLOSE_SUBMITTED" if close_result["status"] == "FILLED" else "AUTO_CLOSE_REJECTED"
        self.store.enqueue(
            setup_id=str(execution["setup_id"]),
            event_type=event_type,
            event_key=f"{event_type}:{row['id']}",
            payload={
                "text": "\n".join(
                    [
                        "🔄 AUTO CLOSE STRATEGI" if close_result["status"] == "FILLED" else "🚨 AUTO CLOSE DITOLAK",
                        f"{execution['symbol']}  •  {execution['side']}",
                        f"• Pemicu: {result_name}",
                        f"• Status broker: {close_result['status']}",
                        f"• Detail: {close_result.get('detail', '-')}",
                        "Status final dan P/L aktual menyusul dari history broker.",
                        f"🆔 {execution['setup_id']}",
                    ]
                ),
                "setup_id": execution["setup_id"],
                "event_type": event_type,
                "source": "mt5_broker_execution",
            },
        )
        self.store.mark_trade_event_processed(
            outbox_id=int(row["id"]), event_type="SNIPER_OUTCOME", result=str(close_result)
        )
        return 1

    def _enqueue_position_opened(self, record: dict[str, Any]) -> None:
        self.store.enqueue(
            setup_id=str(record["setup_id"]),
            event_type="POSITION_OPENED",
            event_key=f"POSITION_OPENED:{record.get('deal_ticket') or record.get('order_ticket')}",
            payload={
                "text": "\n".join(
                    [
                        "✅ POSISI BROKER TERBUKA",
                        f"{record['symbol']}  •  {record['side']}",
                        f"• Lot aktual: {float(record['volume']):.2f}",
                        f"• Entry aktual: {record.get('actual_entry') or record['requested_entry']}",
                        f"• Stop Loss: {record['stop_price']}",
                        f"• Take Profit: {record['target_price']}",
                        f"• Risiko estimasi: {float(record['risk_cash']):.2f} (mata uang akun)",
                        f"• Profit estimasi: {float(record['expected_profit_cash']):.2f} (mata uang akun)",
                        f"• Ticket: {record.get('position_ticket') or record.get('order_ticket') or '?'}",
                        f"🆔 {record['setup_id']}",
                    ]
                ),
                "setup_id": record["setup_id"],
                "event_type": "POSITION_OPENED",
                "source": "mt5_broker_execution",
            },
        )

    def _reconcile_positions(self) -> int:
        closed_count = 0
        for record in self.store.active_trade_executions():
            position = self._find_position(record)
            if position is not None:
                if not record.get("position_ticket"):
                    record.update(position_ticket=position.ticket, actual_entry=position.price_open, opened_at=position.opened_at)
                    self.store.save_trade_execution(record)
                continue
            since = _parse_iso(record.get("opened_at")) or (self.now_fn() - timedelta(days=2))
            deals = self.adapter.load_deals(since=since, symbol=str(record["symbol"]))
            position_ticket = int(record["position_ticket"]) if record.get("position_ticket") else 0
            if not position_ticket:
                entry_deals = [
                    deal for deal in deals
                    if deal.entry == "in"
                    and (
                        (record.get("deal_ticket") and deal.ticket == int(record["deal_ticket"]))
                        or record["client_tag"] in deal.comment
                    )
                ]
                if entry_deals:
                    position_ticket = max(entry_deals, key=lambda deal: deal.occurred_at or "").position_ticket
            matching = [
                deal for deal in deals
                if deal.entry in {"out", "inout", "out_by"}
                and (
                    (position_ticket and deal.position_ticket == position_ticket)
                    or record["client_tag"] in deal.comment
                )
            ]
            if not matching:
                continue
            last = max(matching, key=lambda deal: deal.occurred_at or "")
            related = [deal for deal in deals if deal.position_ticket == last.position_ticket]
            profit = sum(deal.profit + deal.commission + deal.swap for deal in related)
            opened_at = _parse_iso(record.get("opened_at")) or since
            closed_at = _parse_iso(last.occurred_at) or self.now_fn()
            duration = max(0, int((closed_at - opened_at).total_seconds() // 60))
            closed_by = _closed_by(last.reason, record.get("closed_by"))
            record.update(
                status="CLOSED", position_ticket=last.position_ticket, closed_at=closed_at.isoformat(),
                exit_price=last.price, profit_cash=profit, close_reason=last.reason,
                closed_by=closed_by, last_error=None,
            )
            self.store.save_trade_execution(record)
            predicted = _prediction_label(last.reason, float(record["target_price"]), float(record["stop_price"]), last.price)
            self.store.enqueue(
                setup_id=str(record["setup_id"]),
                event_type="POSITION_CLOSED",
                event_key=f"POSITION_CLOSED:{last.ticket}",
                payload={
                    "text": "\n".join(
                        [
                            "🏁 POSISI BROKER DITUTUP",
                            f"{record['symbol']}  •  {record['side']}",
                            f"• Ditutup oleh: {closed_by}",
                            f"• Alasan broker: {last.reason}",
                            f"• Entry aktual: {record.get('actual_entry') or record['requested_entry']}",
                            f"• Exit aktual: {last.price}",
                            f"• P/L aktual: {profit:.2f} (mata uang akun)",
                            f"• Durasi aktual: {duration} menit",
                            f"• Hasil vs rencana: {predicted}",
                            f"🆔 {record['setup_id']}",
                        ]
                    ),
                    "setup_id": record["setup_id"],
                    "event_type": "POSITION_CLOSED",
                    "source": "mt5_broker_history",
                },
            )
            closed_count += 1
        return closed_count

    def _find_position(self, record: dict[str, Any]):
        positions = self.adapter.load_open_positions(symbol=str(record["symbol"]))
        if record.get("position_ticket"):
            for position in positions:
                if position.ticket == int(record["position_ticket"]):
                    return position
        for position in positions:
            if position.magic == self.config.magic and str(record["client_tag"]) in position.comment:
                return position
        return None


def _execution_record(*, row, mode, entry, stop, target, valid_until, client_tag) -> dict[str, Any]:
    return {
        "setup_id": str(row["setup_id"]), "signal_outbox_id": int(row["id"]),
        "execution_mode": mode, "status": "PLANNING", "symbol": str(row["symbol"]),
        "side": str(row["side"]), "requested_entry": entry, "stop_price": stop,
        "target_price": target, "volume": 0.0, "risk_cash": 0.0,
        "expected_profit_cash": 0.0, "valid_until": valid_until.isoformat(),
        "client_tag": client_tag, "order_ticket": None, "deal_ticket": None,
        "position_ticket": None, "actual_entry": None, "opened_at": None,
        "closed_at": None, "exit_price": None, "profit_cash": None,
        "close_reason": None, "closed_by": None, "last_error": None,
    }


def _float(fields: dict[str, str], key: str) -> float:
    try:
        return float(fields.get(key, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _epoch_datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc) if value not in {None, ""} else None
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def _closed_by(reason: str, previous: str | None) -> str:
    if previous == "strategy_auto":
        return previous
    if reason == "stop_loss":
        return "broker_stop_loss"
    if reason == "take_profit":
        return "broker_take_profit"
    if reason.startswith("manual_"):
        return reason
    if reason == "expert":
        return "expert_or_automation"
    return "broker_or_external"


def _prediction_label(reason: str, target: float, stop: float, exit_price: float) -> str:
    if reason == "take_profit" or abs(exit_price - target) <= 1e-6:
        return "sesuai target (predicted)"
    if reason == "stop_loss" or abs(exit_price - stop) <= 1e-6:
        return "sesuai batas risiko (predicted stop)"
    return "keluar di luar TP/SL awal (not predicted)"
