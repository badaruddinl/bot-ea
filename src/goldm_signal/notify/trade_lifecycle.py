from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any

from bot_ea.models import PositionSizeRequest, RiskPolicy, TradingStyle
from bot_ea.mt5_adapter import MT5Adapter
from bot_ea.mt5_execution_runtime import MT5ExecutionRuntime
from bot_ea.polling_runtime import AIIntent, DecisionAction, MT5SnapshotProvider
from bot_ea.risk_engine import RiskEngine

from ..config import (
    EntrySidePolicy,
    NotificationSideFilter,
    StrategyEngine,
    gold_i_profile,
)
from ..position_management import PositionManagementPolicy
from ..storage.database import SignalStore
from .mt5_log import render_stored_event
from .position_manager import BrokerPositionManager, PositionManagementCycle


_EXECUTABLE_STRATEGY_ID = "GOLDM_SNIPER_PARITY"
_SUPPORTED_EXECUTABLE_STRATEGY_VERSIONS = frozenset({"1.72"})
_MAX_EXECUTABLE_HOLDING_MINUTES = 7 * 24 * 60


@dataclass(frozen=True, slots=True)
class TradeLifecycleConfig:
    enabled: bool = False
    execution_mode: str = "off"
    strategy_engine: StrategyEngine = StrategyEngine.D7_CHANNEL_CONTINUATION
    entry_side_policy: EntrySidePolicy | None = EntrySidePolicy.ALL
    notification_side_filter: NotificationSideFilter | None = (
        NotificationSideFilter.ALL
    )
    risk_pct: float = 0.5
    max_total_open_risk_pct: float = 1.0
    daily_loss_limit_pct: float = 2.0
    signal_ttl_minutes: int = 5
    max_entry_drift_r: float = 0.15
    r1_protection_enabled: bool = True
    r2_protection_enabled: bool = True
    r3_close_enabled: bool = True
    magic: int = 260814
    expected_login: str = ""
    expected_server: str = ""
    live_consent: str = ""
    allow_live_activation: bool = False

    @classmethod
    def from_env(cls) -> "TradeLifecycleConfig":
        legacy_keys = {
            "GOLDM_DIRECTION_PROFILE",
            "GOLDM_NOTIFICATION_DIRECTION_PROFILE",
        }.intersection(os.environ)
        if legacy_keys:
            raise ValueError(
                "legacy direction-profile environment keys are ambiguous and "
                f"must be removed: {sorted(legacy_keys)!r}"
            )
        mode = os.environ.get("GOLDM_EXECUTION_MODE", "off").strip().lower()
        if mode not in {"off", "demo", "live"}:
            raise ValueError("GOLDM_EXECUTION_MODE must be off, demo, or live")
        return cls(
            enabled=_bool_env("GOLDM_TRADE_LIFECYCLE_ENABLED", False),
            execution_mode=mode,
            strategy_engine=StrategyEngine.parse(
                os.environ.get(
                    "GOLDM_STRATEGY_ENGINE",
                    StrategyEngine.D7_CHANNEL_CONTINUATION.value,
                )
            ),
            entry_side_policy=EntrySidePolicy.parse(
                os.environ.get("GOLDM_ENTRY_SIDE_POLICY", EntrySidePolicy.ALL.value)
            ),
            notification_side_filter=NotificationSideFilter.parse(
                os.environ.get(
                    "GOLDM_NOTIFICATION_SIDE_FILTER",
                    NotificationSideFilter.ALL.value,
                )
            ),
            risk_pct=float(os.environ.get("GOLDM_RISK_PCT", "0.5")),
            max_total_open_risk_pct=float(os.environ.get("GOLDM_MAX_OPEN_RISK_PCT", "1.0")),
            daily_loss_limit_pct=float(os.environ.get("GOLDM_DAILY_LOSS_LIMIT_PCT", "2.0")),
            signal_ttl_minutes=int(os.environ.get("GOLDM_SIGNAL_TTL_MINUTES", "5")),
            max_entry_drift_r=float(os.environ.get("GOLDM_MAX_ENTRY_DRIFT_R", "0.15")),
            r1_protection_enabled=_bool_env("GOLDM_R1_PROTECTION_ENABLED", True),
            r2_protection_enabled=_bool_env("GOLDM_R2_PROTECTION_ENABLED", True),
            r3_close_enabled=_bool_env("GOLDM_R3_CLOSE_ENABLED", True),
            magic=int(os.environ.get("GOLDM_MAGIC", "260814")),
            expected_login=os.environ.get("GOLDM_EXPECTED_MT5_LOGIN", "").strip(),
            expected_server=os.environ.get("GOLDM_EXPECTED_MT5_SERVER", "").strip(),
            live_consent=os.environ.get("GOLDM_LIVE_ORDER_CONSENT", "").strip(),
            allow_live_activation=_bool_env("GOLDM_ALLOW_LIVE_ACTIVATION", False),
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
        try:
            if "trade.direction_profile" in values:
                raise ValueError("legacy ambiguous runtime key")
            entry_side_policy = EntrySidePolicy.parse(
                values.get("trade.entry_side_policy", base.entry_side_policy)
            )
        except ValueError:
            # A corrupted/manual runtime setting must never widen permissions.
            # None is an explicit fail-closed state at entry time.
            entry_side_policy = None
        try:
            if "trade.notification_direction_profile" in values:
                raise ValueError("legacy ambiguous runtime key")
            notification_side_filter = NotificationSideFilter.parse(
                values.get(
                    "trade.notification_side_filter",
                    base.notification_side_filter,
                )
            )
        except ValueError:
            notification_side_filter = None
        return cls(
            enabled=base.enabled,
            execution_mode=mode,
            strategy_engine=base.strategy_engine,
            entry_side_policy=entry_side_policy,
            notification_side_filter=notification_side_filter,
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
            r1_protection_enabled=_bool_value(
                values.get("trade.r1_protection_enabled"),
                base.r1_protection_enabled,
            ),
            r2_protection_enabled=_bool_value(
                values.get("trade.r2_protection_enabled"),
                base.r2_protection_enabled,
            ),
            r3_close_enabled=_bool_value(
                values.get("trade.r3_close_enabled"), base.r3_close_enabled
            ),
            magic=int(values.get("trade.magic", base.magic)),
            expected_login=str(values.get("trade.expected_login", base.expected_login)),
            expected_server=str(values.get("trade.expected_server", base.expected_server)),
            live_consent=str(values.get("trade.live_consent", base.live_consent)),
            # Deployment kill switch is intentionally immutable at runtime and
            # cannot be enabled from Telegram/runtime_settings.
            allow_live_activation=base.allow_live_activation,
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
        self.position_manager = BrokerPositionManager(
            store=store,
            adapter=adapter,
            now_fn=self.now_fn,
        )

    def run_once(self) -> tuple[int, int, int]:
        self.config = TradeLifecycleConfig.from_sources(self.store, fallback=self.config)
        terminal_rows = sorted(
            [
                *self.store.execution_candidates(
                    event_type="SNIPER_EARLY_CANCELLED"
                ),
                *self.store.execution_candidates(event_type="SNIPER_OUTCOME"),
            ],
            key=lambda row: int(row["id"]),
        )
        outcomes = sum(self._process_terminal_event(row) for row in terminal_rows)
        planned = sum(
            self._process_signal(row) for row in self.store.execution_candidates()
        )
        management = self.position_manager.run_once(
            current_entry_mode=self._effective_entry_mode(),
            allow_live_open=self.config.allow_live_activation,
        )
        return planned, outcomes, management.closed_positions

    def manage_positions_once(self) -> PositionManagementCycle:
        """Run broker reconciliation/protection independently of new-entry mode.

        This method is intentionally safe to schedule at a higher cadence than
        Telegram polling. Turning entry OFF only prevents an unfenced OPEN from
        being sent; existing/ambiguous positions continue to be reconciled and
        managed from their immutable snapshots.
        """

        self.config = TradeLifecycleConfig.from_sources(
            self.store, fallback=self.config
        )
        return self.position_manager.run_once(
            current_entry_mode=self._effective_entry_mode(),
            allow_live_open=self.config.allow_live_activation,
        )

    def _effective_entry_mode(self) -> str:
        if not self.config.enabled:
            return "off"
        if (
            self.config.execution_mode == "live"
            and not self.config.allow_live_activation
        ):
            return "off"
        return self.config.execution_mode

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
        record.update(_account_context_from_payload(payload))

        if str(row.get("state") or "").upper() != "ACTIVE_SIGNAL":
            return self._reject_signal(
                row,
                payload,
                fields,
                record,
                "CANCELLED",
                "setup generation is no longer ACTIVE_SIGNAL",
            )
        if symbol != gold_i_profile().symbol:
            return self._reject_signal(
                row,
                payload,
                fields,
                record,
                "PRECHECK_REJECTED",
                "symbol sinyal bukan canonical GOLD.i#; broker entry diblokir",
            )
        if min(entry, stop, target) <= 0 or side not in {"buy", "sell"}:
            return self._reject_signal(row, payload, fields, record, "RISK_REJECTED", "invalid entry/stop/target/side")
        metadata_error = _executable_signal_metadata_error(row, fields)
        if metadata_error:
            return self._reject_signal(
                row,
                payload,
                fields,
                record,
                "PRECHECK_REJECTED",
                metadata_error,
            )
        account_binding_error = _event_account_binding_error(payload)
        if account_binding_error:
            _append_account_context_error(payload, account_binding_error)
            return self._reject_signal(
                row,
                payload,
                fields,
                record,
                "PRECHECK_REJECTED",
                account_binding_error,
            )
        record["entry_side_policy"] = _entry_side_policy_name(
            self.config.entry_side_policy
        )
        if self.now_fn() > valid_until:
            return self._reject_signal(row, payload, fields, record, "EXPIRED", "masa berlaku sinyal sudah habis")
        side_policy_error = _entry_side_gate(self.config.entry_side_policy, side)
        if side_policy_error:
            return self._reject_signal(
                row,
                payload,
                fields,
                record,
                "SIDE_POLICY_REJECTED",
                side_policy_error,
            )
        if fields["directionProfile"] != "ALL":
            return self._reject_signal(
                row,
                payload,
                fields,
                record,
                "ENGINE_LINEAGE_REJECTED",
                "production D7 engine requires immutable directionProfile=ALL lineage",
            )

        try:
            point_snapshot = self.adapter.load_symbol_snapshot(symbol)
            point = float(point_snapshot.point or 0.0)
            if point <= 0:
                raise ValueError("MT5 symbol point is unavailable")
            stop, target = _normalize_initial_levels(
                side=side,
                stop=stop,
                target=target,
                tick_size=float(point_snapshot.tick_size or point),
            )
            if (side == "buy" and not stop < entry < target) or (
                side == "sell" and not target < entry < stop
            ):
                raise ValueError(
                    "tick-normalized SL/TP are on an invalid side of requested entry"
                )
            record.update(stop_price=stop, target_price=target)
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
            fingerprint = dict(snapshot.context.get("account_fingerprint") or {})
            record["account_margin_mode"] = str(
                fingerprint.get("margin_mode") or "UNKNOWN"
            ).upper()
            account_binding_error = _event_account_binding_error(
                payload,
                current_fingerprint=fingerprint,
            )
            if account_binding_error:
                _append_account_context_error(payload, account_binding_error)
                return self._reject_signal(
                    row,
                    payload,
                    fields,
                    record,
                    "PRECHECK_REJECTED",
                    account_binding_error,
                )
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

            projected_r = abs(target - entry) / abs(entry - stop)
            management_policy = PositionManagementPolicy(
                r1_protection_enabled=self.config.r1_protection_enabled,
                r2_protection_enabled=self.config.r2_protection_enabled,
                r3_close_enabled=self.config.r3_close_enabled,
            )
            record.update(
                volume=size.normalized_volume,
                risk_cash=size.estimated_loss_cash,
                expected_profit_cash=size.estimated_loss_cash * projected_r,
                strategy_id=fields["strategy"],
                strategy_version=fields["strategyVersion"],
                direction_profile=fields["directionProfile"],
                entry_side_policy=_entry_side_policy_name(
                    self.config.entry_side_policy
                ),
                execution_profile=fields.get("executionProfile")
                or "MT5_MARKET_V1",
                magic=self.config.magic,
                position_identifier=None,
                initial_volume=None,
                remaining_volume=None,
                initial_stop_price=None,
                current_stop_price=None,
                initial_risk_distance=None,
                management_policy=management_policy.policy_id,
                management_policy_version=str(management_policy.version),
                management_policy_json=asdict(management_policy),
                max_holding_minutes=_positive_int(fields.get("maxHoldingMinutes")),
                highest_observed_r=None,
                r1_reached_at=None,
                r2_reached_at=None,
                r3_reached_at=None,
                r1_protection_status=None,
                r2_protection_status=None,
                r3_close_status=None,
                last_broker_sync_at=None,
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

            record["status"] = "OPEN_PENDING"
            action_key = f"OPEN:{setup_id}"
            stored, _, _, disposition = (
                self.store.create_open_execution_intent_if_setup_current(
                    record,
                    action_idempotency_key=action_key,
                    action_payload={
                        "risk_policy": asdict(policy),
                        "operating_mode": size.mode.value,
                        "requested_volume": float(size.normalized_volume),
                        "requested_stop": stop,
                        "requested_target": target,
                    },
                    expected_setup_state="ACTIVE_SIGNAL",
                    expected_signal_outbox_id=int(row["id"]),
                )
            )
            if stored is None:
                terminal = disposition == "TERMINAL_EVENT"
                return self._reject_signal(
                    row,
                    payload,
                    fields,
                    record,
                    "CANCELLED" if terminal else "PRECHECK_REJECTED",
                    (
                        "terminal event already exists for this setup generation"
                        if terminal
                        else "setup state changed before OPEN intent could be fenced"
                    ),
                )
            self._enrich_signal(
                row,
                payload,
                fields,
                stored,
                "OPEN_PENDING",
                "broker OPEN intent tersimpan; menunggu fenced execution",
            )
            return 1
        except Exception as exc:
            return self._reject_signal(row, payload, fields, record, "PRECHECK_REJECTED", str(exc))

    def _account_gate(self, snapshot) -> str | None:
        if self.config.execution_mode == "off":
            return None
        fingerprint = snapshot.context.get("account_fingerprint", {})
        is_live = fingerprint.get("is_live")
        if not str(fingerprint.get("login") or "") or not str(
            fingerprint.get("server") or ""
        ):
            return "identitas login/server MT5 tidak lengkap"
        if str(fingerprint.get("margin_mode") or "UNKNOWN").upper() != "HEDGING":
            return "auto-entry hanya diizinkan pada akun MT5 HEDGING"
        if self.config.execution_mode == "demo" and is_live is not False:
            return "mode demo menolak akun live atau akun yang tidak dapat diidentifikasi"
        if self.config.execution_mode == "live":
            if not self.config.allow_live_activation:
                return "deployment kill switch GOLDM_ALLOW_LIVE_ACTIVATION belum aktif"
            if self.config.live_consent != "I_UNDERSTAND_LIVE_ORDERS":
                return "live order consent belum eksplisit"
            if not self.config.expected_login or not self.config.expected_server:
                return "expected login dan server wajib untuk mode live"
            if is_live is not True:
                return "mode live menolak akun demo atau akun yang tidak dapat diidentifikasi"
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
            executionEntrySidePolicy=_entry_side_policy_name(
                self.config.entry_side_policy
            ),
        )
        payload["fields"] = fields
        immutable_scope = str(record.get("account_scope") or "unknown").lower()
        source_was_approved = str(payload.get("audience") or "").lower() == "approved"
        binding_verified = payload.get("event_account_binding_verified") is True
        payload["account_scope"] = (
            immutable_scope if immutable_scope in {"demo", "live"} else "unknown"
        )
        payload["audience"] = (
            "approved"
            if (
                source_was_approved
                and binding_verified
                and payload["account_scope"] == "demo"
            )
            else "admin_only"
        )
        payload["account_login"] = str(record.get("account_login") or "")
        payload["account_server"] = str(record.get("account_server") or "")
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
        return self._process_terminal_event(row)

    def _process_terminal_event(self, row: dict[str, Any]) -> int:
        payload = dict(row.get("payload") or {})
        fields = dict(payload.get("fields") or {})
        reason = str(
            fields.get("result")
            or fields.get("reason")
            or row.get("event_type")
            or "TERMINAL_EVENT"
        )
        setup_id = str(row["setup_id"])
        execution = self.store.trade_execution(setup_id)
        if execution is None:
            # There is no broker lifecycle to mutate. Persist an idempotent
            # receipt so a terminal-before-signal batch remains a no-op here;
            # the setup state fence independently prevents a later OPEN.
            self.store.mark_trade_event_processed(
                outbox_id=int(row["id"]),
                event_type=str(row.get("event_type") or "TERMINAL_EVENT"),
                result=json.dumps(
                    {
                        "kind": "TERMINAL_NO_EXECUTION_V1",
                        "setup_id": setup_id,
                        "terminal_outbox_id": int(row["id"]),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            return 1

        binding_error = _terminal_event_account_binding_error(
            payload,
            execution,
            setup_symbol=str(row.get("symbol") or ""),
        )
        if binding_error:
            return self._reject_terminal_event_account_binding(
                row=row,
                payload=payload,
                execution=execution,
                detail=binding_error,
            )

        snapshot = self.store.cancel_pending_open_for_terminal_event(
            setup_id,
            terminal_outbox_id=int(row["id"]),
            reason=reason,
        )
        execution = snapshot.get("execution")
        if (
            snapshot.get("disposition") == "DEFERRED_CLOSE"
            and isinstance(execution, dict)
            and str(execution.get("status")) == "FILLED"
        ):
            self.position_manager.queue_close(
                execution,
                reason=str(snapshot.get("deferred_close_reason") or reason),
                closed_by="strategy_auto",
            )
        return 1

    def _reject_terminal_event_account_binding(
        self,
        *,
        row: dict[str, Any],
        payload: dict[str, Any],
        execution: dict[str, Any],
        detail: str,
    ) -> int:
        setup_id = str(row["setup_id"])
        terminal_id = int(row["id"])
        event_type = str(row.get("event_type") or "TERMINAL_EVENT").upper()
        _append_account_context_error(payload, detail)
        payload["terminal_execution_binding_verified"] = False
        original_text = str(payload.get("text") or "").strip()
        payload["text"] = (
            "🚨 TERMINAL EVENT DIBLOKIR\n"
            "Event tidak cocok dengan akun immutable milik eksekusi dan tidak "
            "boleh membatalkan OPEN atau menutup posisi.\n"
            f"• Alasan: {detail}"
            + (f"\n\n{original_text}" if original_text else "")
        )
        # If the original notification is still pending, restrict it before
        # delivery. A separate deduplicated audit remains durable even when the
        # original event had already been sent before this lifecycle pass.
        self.store.update_outbox_payload(terminal_id, payload)

        expected = {
            "scope": str(execution.get("account_scope") or "unknown"),
            "login": str(execution.get("account_login") or ""),
            "server": str(execution.get("account_server") or ""),
        }
        observed = {
            "scope": str(payload.get("event_origin_account_scope") or "unknown"),
            "login": str(payload.get("event_origin_account_login") or ""),
            "server": str(payload.get("event_origin_account_server") or ""),
        }
        self.store.enqueue(
            setup_id=setup_id,
            event_type="TERMINAL_ACCOUNT_BINDING_REJECTED",
            event_key=f"TERMINAL_ACCOUNT_BINDING_REJECTED:{terminal_id}",
            payload={
                "text": (
                    "🚨 TERMINAL ACCOUNT BINDING DITOLAK\n"
                    f"• Setup: {setup_id}\n"
                    f"• Event: {event_type} #{terminal_id}\n"
                    f"• Alasan: {detail}\n"
                    "Tidak ada pembatalan OPEN, deferred close, atau broker close."
                ),
                "setup_id": setup_id,
                "event_type": event_type,
                "terminal_outbox_id": terminal_id,
                "source": "trade_lifecycle_guard",
                "account_scope": "unknown",
                "account_login": "",
                "account_server": "",
                "event_origin_account_scope": observed["scope"],
                "event_origin_account_login": observed["login"],
                "event_origin_account_server": observed["server"],
                "current_account_scope": "unknown",
                "current_account_login": "",
                "current_account_server": "",
                "event_account_binding_verified": False,
                "terminal_execution_binding_verified": False,
                "audience": "admin_only",
                "account_context_error": detail,
                "expected_execution_account": expected,
                "observed_terminal_origin": observed,
            },
        )
        self.store.mark_trade_event_processed(
            outbox_id=terminal_id,
            event_type=event_type,
            result=json.dumps(
                {
                    "kind": "TERMINAL_ACCOUNT_REJECTED_V1",
                    "setup_id": setup_id,
                    "terminal_outbox_id": terminal_id,
                    "reason": detail,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        return 1

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


def _execution_audience(mode: Any) -> dict[str, str]:
    requested_scope = str(mode or "unknown").strip().lower()
    account_scope = requested_scope if requested_scope in {"demo", "live"} else "unknown"
    return {
        "account_scope": account_scope,
        "audience": "approved" if account_scope == "demo" else "admin_only",
    }


def _account_context_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    scope = str(payload.get("account_scope") or "unknown").strip().lower()
    if scope not in {"demo", "live"}:
        scope = "unknown"
    return {
        "account_login": str(payload.get("account_login") or "").strip(),
        "account_server": str(payload.get("account_server") or "").strip(),
        "account_scope": scope,
    }


def _account_scope_from_fingerprint(fingerprint: dict[str, Any]) -> str:
    is_live = fingerprint.get("is_live")
    if is_live is True:
        return "live"
    if is_live is False:
        return "demo"
    return "unknown"


def _entry_side_policy_name(policy: EntrySidePolicy | object | None) -> str:
    try:
        return EntrySidePolicy.parse(policy).value
    except ValueError:
        return "INVALID"


def _entry_side_gate(
    policy: EntrySidePolicy | object | None, side: object
) -> str | None:
    try:
        parsed = EntrySidePolicy.parse(policy)
    except ValueError:
        return "entry side policy tidak valid; entry diblokir fail-closed"
    if parsed.allows(side):
        return None
    return f"side {str(side).upper()} diblokir oleh policy {parsed.value}"


def _executable_signal_metadata_error(
    row: dict[str, Any], fields: dict[str, str]
) -> str | None:
    duplicates = str(fields.get("_duplicateFields") or "").strip()
    if duplicates:
        return f"metadata sinyal ambigu; field duplikat: {duplicates}"
    setup_side = str(row.get("side") or "").strip().lower()
    field_side = str(fields.get("side") or "").strip().lower()
    if field_side not in {"buy", "sell"} or field_side != setup_side:
        return (
            "metadata side tidak cocok dengan setup id "
            f"({field_side or 'missing'} != {setup_side or 'missing'})"
        )
    if str(fields.get("strategy") or "") != _EXECUTABLE_STRATEGY_ID:
        return (
            "strategy executable wajib exact "
            f"{_EXECUTABLE_STRATEGY_ID}; legacy/unknown marker hanya notifikasi"
        )
    version = str(fields.get("strategyVersion") or "")
    if version not in _SUPPORTED_EXECUTABLE_STRATEGY_VERSIONS:
        return f"strategyVersion tidak didukung untuk entry: {version or 'missing'}"
    if str(fields.get("autoEntryEligible") or "").strip().lower() != "true":
        return "autoEntryEligible=true wajib eksplisit untuk broker entry"
    max_holding_minutes = _positive_int(fields.get("maxHoldingMinutes"))
    if max_holding_minutes is None:
        return "maxHoldingMinutes wajib berupa integer positif untuk broker entry"
    if max_holding_minutes > _MAX_EXECUTABLE_HOLDING_MINUTES:
        return (
            "maxHoldingMinutes melampaui batas aman "
            f"{_MAX_EXECUTABLE_HOLDING_MINUTES} menit"
        )
    if not str(fields.get("directionProfile") or "").strip():
        return "directionProfile lineage wajib tersedia untuk broker entry"
    setup_at = _strict_positive_epoch(fields.get("setupUtcEpoch"))
    generated_at = _strict_positive_epoch(fields.get("generatedUtcEpoch"))
    if setup_at is None or generated_at is None:
        return "setupUtcEpoch dan generatedUtcEpoch valid wajib untuk broker entry"
    if generated_at < setup_at:
        return "generatedUtcEpoch tidak boleh mendahului setupUtcEpoch"
    return None


def _event_account_binding_error(
    payload: dict[str, Any],
    *,
    current_fingerprint: dict[str, Any] | None = None,
) -> str | None:
    """Require immutable DEMO origin and a still-matching execution account."""

    if payload.get("event_account_binding_verified") is not True:
        return "event account binding tidak terverifikasi; broker entry diblokir"
    if str(payload.get("audience") or "").strip().lower() != "approved":
        return "event admin-only tidak boleh dipromosikan menjadi broker entry"

    origin_scope = str(
        payload.get("event_origin_account_scope")
        or payload.get("account_scope")
        or ""
    ).strip().lower()
    origin_login = str(
        payload.get("event_origin_account_login")
        or payload.get("account_login")
        or ""
    ).strip()
    origin_server = str(
        payload.get("event_origin_account_server")
        or payload.get("account_server")
        or ""
    ).strip()
    standard_scope = str(payload.get("account_scope") or "").strip().lower()
    standard_login = str(payload.get("account_login") or "").strip()
    standard_server = str(payload.get("account_server") or "").strip()
    if origin_scope != "demo" or not origin_login or not origin_server:
        return "event origin wajib terikat ke akun DEMO yang lengkap"
    if (
        standard_scope != origin_scope
        or standard_login != origin_login
        or standard_server != origin_server
    ):
        return "standard account fields tidak cocok dengan immutable event origin"

    bridge_scope = str(payload.get("current_account_scope") or "").strip().lower()
    bridge_login = str(payload.get("current_account_login") or "").strip()
    bridge_server = str(payload.get("current_account_server") or "").strip()
    if (
        bridge_scope != origin_scope
        or bridge_login != origin_login
        or bridge_server != origin_server
    ):
        return "event origin/current account bridge mismatch"

    if current_fingerprint is None:
        return None
    latest_scope = _account_scope_from_fingerprint(current_fingerprint)
    latest_login = str(current_fingerprint.get("login") or "").strip()
    latest_server = str(current_fingerprint.get("server") or "").strip()
    if (
        latest_scope != origin_scope
        or latest_login != origin_login
        or latest_server != origin_server
    ):
        return "akun MT5 berubah setelah event di-ingest; broker entry diblokir"
    return None


def _terminal_event_account_binding_error(
    payload: dict[str, Any],
    execution: dict[str, Any],
    *,
    setup_symbol: str,
) -> str | None:
    """Bind a terminal event to the exact immutable execution account."""

    if str(payload.get("source") or "").strip() != "mt5_expert_log":
        return "terminal event source bukan immutable MT5 expert log"
    event_binding_error = _event_account_binding_error(payload)
    if event_binding_error:
        return f"terminal event binding ditolak: {event_binding_error}"

    canonical_symbol = gold_i_profile().symbol
    event_symbol = str(payload.get("event_symbol") or "").strip()
    execution_symbol = str(execution.get("symbol") or "").strip()
    if (
        event_symbol != canonical_symbol
        or setup_symbol != canonical_symbol
        or execution_symbol != canonical_symbol
        or event_symbol != setup_symbol
        or event_symbol != execution_symbol
    ):
        return "terminal event symbol tidak cocok exact dengan setup/eksekusi GOLD.i#"

    origin_scope = str(
        payload.get("event_origin_account_scope") or ""
    ).strip().lower()
    origin_login = str(payload.get("event_origin_account_login") or "").strip()
    origin_server = str(payload.get("event_origin_account_server") or "").strip()
    if not origin_scope or not origin_login or not origin_server:
        return "terminal event immutable origin tidak lengkap"

    execution_scope = str(execution.get("account_scope") or "").strip().lower()
    execution_login = str(execution.get("account_login") or "").strip()
    execution_server = str(execution.get("account_server") or "").strip()
    if (
        execution_scope not in {"demo", "live"}
        or not execution_login
        or not execution_server
    ):
        return "snapshot akun immutable eksekusi tidak lengkap"
    if (
        origin_scope != execution_scope
        or origin_login != execution_login
        or origin_server != execution_server
    ):
        return "terminal event origin tidak cocok exact dengan akun immutable eksekusi"
    return None


def _append_account_context_error(payload: dict[str, Any], detail: str) -> None:
    existing = str(payload.get("account_context_error") or "").strip()
    values = [value for value in (existing, str(detail).strip()) if value]
    payload["account_context_error"] = "; ".join(dict.fromkeys(values))[:1000]
    payload["audience"] = "admin_only"


def _strict_positive_epoch(value: object) -> datetime | None:
    try:
        epoch = int(str(value))
    except (TypeError, ValueError):
        return None
    if epoch <= 0:
        return None
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _normalize_initial_levels(
    *, side: str, stop: float, target: float, tick_size: float
) -> tuple[float, float]:
    if tick_size <= 0:
        raise ValueError("MT5 trade tick size is unavailable")
    tick = Decimal(str(tick_size))

    def normalized(value: float, rounding: str) -> float:
        units = Decimal(str(value)) / tick
        return float(units.quantize(Decimal("1"), rounding=rounding) * tick)

    if side == "buy":
        return (
            normalized(stop, ROUND_CEILING),
            normalized(target, ROUND_FLOOR),
        )
    if side == "sell":
        return (
            normalized(stop, ROUND_FLOOR),
            normalized(target, ROUND_CEILING),
        )
    raise ValueError("initial level normalization requires BUY or SELL")


def _float(fields: dict[str, str], key: str) -> float:
    try:
        return float(fields.get(key, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


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


def _bool_value(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return False


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
