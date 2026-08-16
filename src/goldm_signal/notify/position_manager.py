from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from bot_ea.models import OperatingMode, RiskPolicy, TradingStyle
from bot_ea.mt5_adapter import (
    MT5Adapter,
    MutationAccountBinding,
    OpenPositionSnapshot,
)
from bot_ea.mt5_execution_runtime import MT5ExecutionRuntime
from bot_ea.polling_runtime import AIIntent, DecisionAction, MT5SnapshotProvider

from ..position_management import (
    BrokerActionStatus,
    ManagedPosition,
    ManagementAction,
    MilestoneState,
    PositionManagementPolicy,
    is_stop_at_least_as_protective,
    plan_position_management,
)
from ..storage.database import SignalStore


_OPEN_ACTION = "OPEN"
_INITIAL_PROTECTION_ACTION = "SET_INITIAL_PROTECTION"
_MODIFY_STOP_ACTION = "MODIFY_SL"
_CLOSE_ACTION = "CLOSE_FULL"


@dataclass(slots=True)
class PositionManagementCycle:
    executions_seen: int = 0
    actions_claimed: int = 0
    actions_confirmed: int = 0
    actions_failed: int = 0
    actions_unknown: int = 0
    notifications_enqueued: int = 0
    isolated_failures: int = 0
    closed_positions: int = 0


class BrokerPositionManager:
    """Durable, fail-closed broker management for already-authorized positions.

    Entry permission is consulted only for a still-PENDING OPEN intent. Once an
    OPEN mutation is fenced SUBMITTED, or a broker position is confirmed, OFF
    mode never disables reconciliation, protection, or closing of that position.
    """

    def __init__(
        self,
        *,
        store: SignalStore,
        adapter: MT5Adapter,
        now_fn=None,
        lease_owner: str | None = None,
        max_actions_per_cycle: int = 20,
    ) -> None:
        self.store = store
        self.adapter = adapter
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.lease_owner = lease_owner or f"goldm-position-{uuid4().hex}"
        self.max_actions_per_cycle = max(1, int(max_actions_per_cycle))

    def run_once(
        self,
        *,
        current_entry_mode: str = "off",
        allow_live_open: bool = False,
    ) -> PositionManagementCycle:
        result = PositionManagementCycle()
        self._reconcile_action_ledger(result)
        self._drain_pending_actions(
            current_entry_mode=current_entry_mode,
            allow_live_open=allow_live_open,
            result=result,
        )

        try:
            executions = self.store.active_trade_executions()
        except Exception:
            result.isolated_failures += 1
            return result

        for record in executions:
            result.executions_seen += 1
            try:
                self._reconcile_execution_actions(record, result)
                refreshed = self.store.trade_execution(str(record["setup_id"]))
                if refreshed is not None:
                    self._process_execution(refreshed, result)
            except Exception as exc:
                result.isolated_failures += 1
                result.notifications_enqueued += int(
                    self._enqueue_management_error(record, str(exc))
                )

        self._drain_pending_actions(
            current_entry_mode=current_entry_mode,
            allow_live_open=allow_live_open,
            result=result,
        )
        self._reconcile_action_ledger(result)
        return result

    def _process_execution(
        self, record: dict[str, Any], result: PositionManagementCycle
    ) -> None:
        status = str(record.get("status") or "").upper()
        position = self._find_position(record)
        if status in {
            "OPEN_PENDING",
            "OPEN_SUBMITTED",
            "OPEN_UNKNOWN",
            "PLACED",
            "UNKNOWN",
            "PARTIAL",
            "UNPROTECTED",
        }:
            if position is not None:
                if status == "UNPROTECTED":
                    identity_error = self._position_identity_error(record, position)
                    if identity_error:
                        raise RuntimeError(identity_error)
                    account_error = self._broker_account_identity_error(record)
                    if account_error:
                        raise RuntimeError(account_error)
                    post_fill_repair_stop = (
                        self._filled_repair_stop(record)
                        if self._has_frozen_initial_protection(record)
                        else None
                    )
                    record = self._bind_unprotected_position(record, position)
                    if self._holding_deadline_reached(record, position):
                        self.queue_close(
                            record,
                            reason="MAX_HOLDING_EXPIRED",
                            closed_by="strategy_auto",
                        )
                        return
                    if post_fill_repair_stop is not None:
                        self._stage_filled_protection_repair(
                            record,
                            position,
                            target_stop=post_fill_repair_stop,
                            result=result,
                        )
                        return
                self._adopt_or_protect_position(record, position, result)
            elif status == "UNPROTECTED":
                result.notifications_enqueued += int(
                    self._enqueue(
                        record,
                        event_type="POSITION_PROTECTION_FAILED",
                        event_key="POSITION_PROTECTION_FAILED:POSITION_ABSENT",
                        text=(
                            "🚨 POSISI TIDAK DITEMUKAN SAAT PROTEKSI AWAL\n"
                            f"{record['symbol']}  •  {record['side']}\n"
                            "Broker state harus diperiksa manual; tidak ada retry order buta.\n"
                            f"🆔 {record['setup_id']}"
                        ),
                        force_admin=True,
                    )
                )
            elif status != "OPEN_PENDING":
                self._reconcile_unobserved_open_history(record, result)
            return

        if status not in {
            "FILLED",
            "CLOSE_SUBMITTED",
            "CLOSE_UNKNOWN",
            "CLOSE_REJECTED",
        }:
            return
        if position is None:
            account_error = self._broker_account_identity_error(record)
            if account_error:
                raise RuntimeError(
                    f"cannot infer position absence on a different account: {account_error}"
                )
            self._reconcile_closed_execution(record, result)
            return
        self._manage_filled_position(record, position, result)

    def _manage_filled_position(
        self,
        record: dict[str, Any],
        position: OpenPositionSnapshot,
        result: PositionManagementCycle,
    ) -> None:
        identity_error = self._position_identity_error(record, position)
        if identity_error:
            raise RuntimeError(identity_error)
        account_error = self._broker_account_identity_error(record)
        if account_error:
            raise RuntimeError(account_error)
        repair_stop = self._filled_repair_stop(record)
        protection_degraded = not (
            self._stop_postcondition(position, repair_stop)
            and self._price_equal(
                position.symbol,
                position.tp,
                float(record.get("initial_take_profit_price") or 0.0),
            )
        )
        record = self.store.sync_trade_position_binding(
            str(record["setup_id"]),
            position_ticket=position.ticket,
            position_identifier=self._position_identifier(position),
            symbol=position.symbol,
            side=position.side,
            comment=position.comment,
            remaining_volume=position.volume,
            current_stop_price=position.sl,
            current_take_profit_price=position.tp,
            protection_degraded=protection_degraded,
            magic=position.magic,
            account_login=str(record["account_login"]),
            account_server=str(record["account_server"]),
            account_scope=str(record["account_scope"]),
            last_broker_sync_at=self.now_fn(),
        )
        deferred_close_reason = str(record.get("deferred_close_reason") or "").strip()
        if deferred_close_reason:
            self.queue_close(
                record,
                reason=deferred_close_reason,
                closed_by="strategy_auto",
            )
            return
        if self._holding_deadline_reached(record, position):
            self.queue_close(
                record,
                reason="MAX_HOLDING_EXPIRED",
                closed_by="strategy_auto",
            )
            return
        if protection_degraded:
            self._stage_filled_protection_repair(
                record,
                position,
                target_stop=repair_stop,
                result=result,
            )
            return
        if str(record.get("status")) == "UNPROTECTED":
            self._adopt_or_protect_position(record, position, result)
            return
        policy = self._policy_from_record(record)
        managed = self._managed_position(record, position)
        tick = self.adapter.load_price_tick(str(record["symbol"]))
        milestones = self._milestones_from_record(record)
        plan = plan_position_management(
            managed,
            milestones,
            bid=float(tick.bid),
            ask=float(tick.ask),
            policy=policy,
        )
        result.notifications_enqueued += self._record_observation(
            record,
            position,
            plan.current_r,
            plan.newly_reached,
            policy,
        )

        if plan.action is ManagementAction.ACKNOWLEDGE_PROTECTION:
            assert plan.milestone is not None
            self._set_milestone_action_status(
                record, plan.milestone, BrokerActionStatus.CONFIRMED
            )
            result.notifications_enqueued += int(
                self._enqueue_protection_result(
                    record,
                    milestone=plan.milestone,
                    confirmed=True,
                    detail="SL broker sudah lebih protektif dari target",
                    broker_stop=position.sl,
                )
            )
            return
        if plan.action is ManagementAction.MODIFY_PROTECTION:
            assert plan.milestone is not None and plan.target_stop is not None
            target_stop = self._normalize_protective_stop(
                position.symbol,
                position.side,
                plan.target_stop,
            )
            if self._stop_postcondition(position, target_stop):
                self._set_milestone_action_status(
                    record, plan.milestone, BrokerActionStatus.CONFIRMED
                )
                result.notifications_enqueued += int(
                    self._enqueue_protection_result(
                        record,
                        milestone=plan.milestone,
                        confirmed=True,
                        detail="SL broker memenuhi target yang dinormalisasi ke tick size",
                        broker_stop=position.sl,
                    )
                )
                return
            stored_status = str(
                record.get(f"{plan.milestone.lower()}_protection_status") or ""
            ).upper()
            repair = stored_status == BrokerActionStatus.CONFIRMED.value
            self._create_management_action(
                record,
                position,
                action_type=_MODIFY_STOP_ACTION,
                milestone=plan.milestone,
                repair=repair,
                current_r=plan.current_r,
                reached_milestones=plan.newly_reached,
                payload={
                    "source_milestone": plan.milestone,
                    "target_stop": target_stop,
                    "take_profit_before": position.tp,
                    "position_identifier": self._position_identifier(position),
                },
            )
            return
        if plan.action is ManagementAction.CLOSE_FULL:
            self._create_management_action(
                record,
                position,
                action_type=_CLOSE_ACTION,
                milestone="R3",
                repair=False,
                current_r=plan.current_r,
                reached_milestones=plan.newly_reached,
                payload={
                    "position_identifier": self._position_identifier(position),
                    "volume": position.volume,
                    "reason": "R3_TARGET",
                },
            )

    def _record_observation(
        self,
        record: dict[str, Any],
        position: OpenPositionSnapshot,
        current_r: float,
        newly_reached: tuple[str, ...],
        policy: PositionManagementPolicy,
    ) -> int:
        observed_at = self.now_fn()
        milestone_payloads = {
            milestone: self._event_payload(
                record,
                event_type=f"POSITION_{milestone}_TOUCHED",
                text=self._milestone_touch_text(
                    record, milestone, current_r, policy
                ),
            )
            for milestone in newly_reached
        }
        return self.store.record_position_observation_with_milestone_alerts(
            str(record["setup_id"]),
            remaining_volume=position.volume,
            current_stop_price=position.sl,
            current_take_profit_price=position.tp,
            highest_observed_r=current_r,
            last_broker_sync_at=observed_at,
            reached_at=observed_at,
            milestone_payloads=milestone_payloads,
        )

    def queue_close(
        self,
        record: dict[str, Any],
        *,
        reason: str,
        closed_by: str = "strategy_auto",
    ) -> bool:
        """Stage a durable full-close intent without performing broker I/O."""

        account_error = self._broker_account_identity_error(record)
        if account_error:
            self._enqueue_management_error(
                record,
                "close intent ditunda sampai akun broker kembali cocok: "
                f"{account_error}",
            )
            return False
        position = self._find_position(record)
        if position is None:
            return False
        identity_error = self._position_identity_error(record, position)
        if identity_error:
            raise RuntimeError(identity_error)
        latest = self._save_execution(
            record,
            close_reason=str(reason),
            closed_by=str(closed_by),
        )
        action, created = self._create_management_action(
            latest,
            position,
            action_type=_CLOSE_ACTION,
            milestone="R3" if reason == "R3_TARGET" else "MODEL",
            repair=False,
            current_r=None,
            reached_milestones=(),
            payload={
                "position_identifier": self._position_identifier(position),
                "reason": str(reason),
            },
        )
        return bool(created or action)

    def _reconcile_action_ledger(self, result: PositionManagementCycle) -> None:
        attempted_action_ids: set[int] = set()
        for _ in range(self.max_actions_per_cycle * 4):
            try:
                action = self.store.claim_position_action_projection(
                    lease_owner=self.lease_owner,
                    exclude_action_ids=tuple(attempted_action_ids),
                    lease_seconds=30.0,
                    now=self.now_fn(),
                )
            except Exception:
                result.isolated_failures += 1
                return
            if action is None:
                return
            attempted_action_ids.add(int(action["id"]))
            try:
                self._project_terminal_action(action, result)
                if not self.store.mark_position_action_projected(
                    str(action["idempotency_key"]),
                    lease_owner=self.lease_owner,
                    projected_at=self.now_fn(),
                ):
                    raise RuntimeError("lost position-action projection lease")
            except Exception as exc:
                self.store.release_position_action_projection(
                    idempotency_key=str(action["idempotency_key"]),
                    lease_owner=self.lease_owner,
                    retry_seconds=self._projection_retry_seconds(
                        int(action.get("projection_attempt_count") or 1)
                    ),
                    now=self.now_fn(),
                )
                result.isolated_failures += 1
                record = self._record_for_action(action)
                if record is not None:
                    result.notifications_enqueued += int(
                        self._enqueue_management_error(record, str(exc))
                    )

    def _project_terminal_action(
        self, action: dict[str, Any], result: PositionManagementCycle
    ) -> None:
        record = self._record_for_action(action)
        if record is None:
            raise RuntimeError("cannot project action without execution")
        action_type = str(action.get("action_type") or "").upper()
        status = str(action.get("status") or "").upper()
        if action_type == _OPEN_ACTION:
            if status == "CONFIRMED" and str(record.get("status")) == "FILLED":
                result.notifications_enqueued += int(
                    self._enqueue_position_opened(record)
                )
            elif status == "FAILED":
                self._project_open_failure(record, action, result)
            elif status == "UNKNOWN":
                self._project_open_unknown(record, action, result)
            return
        if action_type == _INITIAL_PROTECTION_ACTION:
            if bool(action.get("payload", {}).get("repair_filled")):
                self._project_filled_protection_repair(
                    record, action, status, result
                )
                return
            if status == "CONFIRMED" and str(record.get("status")) == "FILLED":
                result.notifications_enqueued += int(
                    self._enqueue_position_opened(record)
                )
            else:
                self._project_initial_protection_failure(
                    record,
                    action,
                    result,
                    unknown=status == "UNKNOWN",
                )
            return
        if action_type == _MODIFY_STOP_ACTION:
            self._project_protection_action(record, action, status, result)
            return
        if action_type == _CLOSE_ACTION:
            self._project_close_action(record, action, status, result)
            return
        raise RuntimeError(f"unsupported terminal action projection {action_type!r}")

    def _reconcile_execution_actions(
        self, record: dict[str, Any], result: PositionManagementCycle
    ) -> None:
        for action in self.store.position_actions(
            setup_id=str(record["setup_id"]), limit=200
        ):
            if str(action.get("status")) in {"SUBMITTED", "UNKNOWN"}:
                self._reconcile_action(action, result)

    def _reconcile_action(
        self, action: dict[str, Any], result: PositionManagementCycle
    ) -> None:
        record = self._record_for_action(action)
        if record is None:
            return
        action_type = str(action.get("action_type") or "").upper()
        status = str(action.get("status") or "").upper()
        if action_type != _OPEN_ACTION:
            account_error = self._broker_account_identity_error(record)
            if account_error:
                raise RuntimeError(
                    "cannot reconcile broker postcondition on a different account: "
                    f"{account_error}"
                )
        position = self._find_position(record)

        if action_type == _OPEN_ACTION:
            if position is not None:
                self._adopt_or_protect_position(
                    record,
                    position,
                    result,
                    action_key=str(action["idempotency_key"]),
                )
            elif status == "FAILED":
                self._project_open_failure(record, action, result)
            elif status in {"SUBMITTED", "UNKNOWN"}:
                self._project_open_unknown(record, action, result)
            return

        if action_type == _INITIAL_PROTECTION_ACTION:
            if position is not None and self._initial_protection_postcondition(
                position, action
            ):
                if bool(action.get("payload", {}).get("repair_filled")):
                    _, action = self._finalize_management_action(
                        record,
                        action,
                        outcome="CONFIRMED",
                        current_stop_price=position.sl,
                        current_take_profit_price=position.tp,
                        remaining_volume=position.volume,
                        broker_position_ticket=position.ticket,
                        broker_reference="filled protection repair observed",
                    )
                    result.actions_confirmed += 1
                    self._project_filled_protection_repair(
                        record, action, "CONFIRMED", result
                    )
                else:
                    self._confirm_position(
                        record,
                        position,
                        action_key=str(action["idempotency_key"]),
                        result=result,
                    )
            elif (
                position is None
                and bool(action.get("payload", {}).get("repair_filled"))
                and status in {"SUBMITTED", "UNKNOWN"}
            ):
                account_error = self._broker_account_identity_error(record)
                if account_error:
                    raise RuntimeError(
                        f"cannot infer repair target absence: {account_error}"
                    )
                _, action = self._finalize_management_action(
                    record,
                    action,
                    outcome="FAILED",
                    error="position absent before filled protection repair confirmed",
                    broker_reference="position absent",
                )
                result.actions_failed += 1
                self._project_filled_protection_repair(
                    record, action, "FAILED", result
                )
            elif status in {"FAILED", "UNKNOWN"}:
                if bool(action.get("payload", {}).get("repair_filled")):
                    self._project_filled_protection_repair(
                        record, action, status, result
                    )
                else:
                    self._project_initial_protection_failure(
                        record, action, result, unknown=status == "UNKNOWN"
                    )
            return

        if action_type == _MODIFY_STOP_ACTION:
            if position is not None and self._modify_postcondition(position, action):
                if status != "CONFIRMED":
                    _, action = self._finalize_management_action(
                        record,
                        action,
                        outcome="CONFIRMED",
                        current_stop_price=position.sl,
                        current_take_profit_price=position.tp,
                        remaining_volume=position.volume,
                        broker_position_ticket=position.ticket,
                        broker_reference="reconciled from broker protection",
                    )
                    result.actions_confirmed += 1
                self._project_protection_action(record, action, "CONFIRMED", result)
            elif position is None and status in {"SUBMITTED", "UNKNOWN"}:
                account_error = self._broker_account_identity_error(record)
                if account_error:
                    raise RuntimeError(
                        f"cannot infer protection target absence: {account_error}"
                    )
                _, action = self._finalize_management_action(
                    record,
                    action,
                    outcome="FAILED",
                    error="position absent before protection could be confirmed",
                    broker_reference="position absent",
                )
                result.actions_failed += 1
                self._project_protection_action(record, action, "FAILED", result)
            elif status in {"FAILED", "UNKNOWN"}:
                self._project_protection_action(record, action, status, result)
            return

        if action_type == _CLOSE_ACTION:
            if position is None:
                account_error = self._broker_account_identity_error(record)
                if account_error:
                    raise RuntimeError(
                        f"cannot confirm close absence on a different account: {account_error}"
                    )
                if status != "CONFIRMED":
                    _, action = self._finalize_management_action(
                        record,
                        action,
                        outcome="CONFIRMED",
                        remaining_volume=0.0,
                        broker_reference="matching broker position absent",
                    )
                    result.actions_confirmed += 1
                self._project_close_action(record, action, "CONFIRMED", result)
                self._reconcile_closed_execution(
                    self.store.trade_execution(str(record["setup_id"])) or record,
                    result,
                )
            elif status == "CONFIRMED":
                result.notifications_enqueued += int(
                    self._enqueue_management_error(
                        record,
                        "close ledger CONFIRMED tetapi posisi broker masih ada; tidak ada retry otomatis",
                    )
                )
            elif status in {"FAILED", "UNKNOWN"}:
                self._project_close_action(record, action, status, result)

    def _drain_pending_actions(
        self,
        *,
        current_entry_mode: str,
        allow_live_open: bool,
        result: PositionManagementCycle,
    ) -> None:
        for _ in range(self.max_actions_per_cycle):
            try:
                action = self.store.claim_position_action(
                    lease_owner=self.lease_owner,
                    lease_seconds=30.0,
                    now=self.now_fn(),
                )
            except Exception:
                result.isolated_failures += 1
                return
            if action is None:
                return
            result.actions_claimed += 1
            action_type = str(action.get("action_type") or "").upper()
            record = self._record_for_action(action)
            if action_type != _OPEN_ACTION and record is not None:
                account_error = self._broker_account_identity_error(record)
                if account_error:
                    if not self.store.defer_pending_position_action(
                        idempotency_key=str(action["idempotency_key"]),
                        lease_owner=self.lease_owner,
                        retry_seconds=5.0,
                        now=self.now_fn(),
                    ):
                        result.isolated_failures += 1
                        return
                    result.isolated_failures += 1
                    result.notifications_enqueued += int(
                        self._enqueue_management_error(
                            record,
                            "broker action ditunda sampai akun kembali cocok: "
                            f"{account_error}",
                        )
                    )
                    continue
            try:
                self._execute_claimed_action(
                    action,
                    current_entry_mode=current_entry_mode,
                    allow_live_open=allow_live_open,
                    result=result,
                )
            except Exception as exc:
                # Once SUBMITTED, any transport/adapter exception is ambiguous.
                refreshed = self.store.position_action(str(action["idempotency_key"]))
                status = str((refreshed or action).get("status") or "").upper()
                terminal_action = refreshed or action
                record = self._record_for_action(terminal_action)
                is_management = str(terminal_action.get("action_type")) in {
                    _MODIFY_STOP_ACTION,
                    _CLOSE_ACTION,
                }
                if status == "PENDING":
                    if is_management and record is not None:
                        _, terminal_action = self._finalize_management_action(
                            record,
                            terminal_action,
                            outcome="FAILED",
                            error=f"pre-mutation failure: {exc}",
                        )
                    else:
                        self.store.mark_position_action_failed(
                            str(action["idempotency_key"]),
                            f"pre-mutation failure: {exc}",
                            lease_owner=self.lease_owner,
                        )
                    result.actions_failed += 1
                elif status == "SUBMITTED":
                    if is_management and record is not None:
                        _, terminal_action = self._finalize_management_action(
                            record,
                            terminal_action,
                            outcome="UNKNOWN",
                            error=f"broker mutation outcome unknown: {exc}",
                        )
                    else:
                        self.store.mark_position_action_unknown(
                            str(action["idempotency_key"]),
                            f"broker mutation outcome unknown: {exc}",
                        )
                    result.actions_unknown += 1
                result.isolated_failures += 1
                if record is not None:
                    result.notifications_enqueued += int(
                        self._enqueue_management_error(record, str(exc))
                    )

    def _execute_claimed_action(
        self,
        action: dict[str, Any],
        *,
        current_entry_mode: str,
        allow_live_open: bool,
        result: PositionManagementCycle,
    ) -> None:
        action_type = str(action.get("action_type") or "").upper()
        if action_type == _OPEN_ACTION:
            self._execute_open_action(
                action, current_entry_mode, allow_live_open, result
            )
        elif action_type == _INITIAL_PROTECTION_ACTION:
            self._execute_initial_protection_action(action, result)
        elif action_type == _MODIFY_STOP_ACTION:
            self._execute_modify_action(action, result)
        elif action_type == _CLOSE_ACTION:
            self._execute_close_action(action, result)
        else:
            self.store.mark_position_action_failed(
                str(action["idempotency_key"]),
                f"unsupported position action {action_type!r}",
                lease_owner=self.lease_owner,
            )
            result.actions_failed += 1

    def _execute_open_action(
        self,
        action: dict[str, Any],
        current_entry_mode: str,
        allow_live_open: bool,
        result: PositionManagementCycle,
    ) -> None:
        record = self._require_record_for_action(action)
        position = self._find_position(record)
        if position is not None:
            self._fence_submitted(action, broker_position_ticket=position.ticket)
            self._adopt_or_protect_position(
                record,
                position,
                result,
                action_key=str(action["idempotency_key"]),
            )
            return

        expected_mode = str(record.get("account_scope") or "").lower()
        if (
            current_entry_mode not in {"demo", "live"}
            or current_entry_mode != expected_mode
            or (expected_mode == "live" and not allow_live_open)
        ):
            detail = (
                f"pending OPEN dibatalkan: mode aktif {current_entry_mode!r} "
                f"tidak cocok dengan snapshot {expected_mode!r}"
            )
            self.store.mark_position_action_failed(
                str(action["idempotency_key"]),
                detail,
                lease_owner=self.lease_owner,
            )
            self._save_execution(record, status="REJECTED", last_error=detail)
            result.actions_failed += 1
            self._project_open_failure(record, action, result, detail=detail)
            return

        first_guard = self._broker_mutation_guard(record)
        if first_guard:
            self.store.mark_position_action_failed(
                str(action["idempotency_key"]),
                first_guard,
                lease_owner=self.lease_owner,
            )
            self._save_execution(record, status="GUARD_REJECTED", last_error=first_guard)
            result.actions_failed += 1
            self._project_open_failure(record, action, result, detail=first_guard)
            return

        payload = dict(action.get("payload") or {})
        snapshot = self._runtime_snapshot(record, payload, timeframe="M15")
        size = SimpleNamespace(
            normalized_volume=float(record["volume"]),
            mode=self._operating_mode(payload),
        )
        intent = AIIntent(
            action=DecisionAction.OPEN,
            side=str(record["side"]).lower(),
            reason=str(record["client_tag"]),
            stop_distance_points=float(snapshot.stop_distance_points),
            entry_price=float(record["requested_entry"]),
            payload={
                "sl": float(record["stop_price"]),
                "tp": float(record["target_price"]),
            },
        )
        runtime = MT5ExecutionRuntime(
            adapter=self.adapter,
            allow_live_orders=True,
            magic=int(record["magic"]),
            comment_prefix="GMS",
        )
        preflight = runtime.preflight(snapshot, intent, size)
        if str(preflight.get("status")) != "PRECHECK_OK":
            detail = str(preflight.get("detail") or "broker preflight rejected")
            self.store.mark_position_action_failed(
                str(action["idempotency_key"]),
                detail,
                lease_owner=self.lease_owner,
                broker_retcode=_optional_int(preflight.get("retcode")),
            )
            self._save_execution(record, status=str(preflight["status"]), last_error=detail)
            result.actions_failed += 1
            self._project_open_failure(record, action, result, detail=detail)
            return

        self._fence_submitted(action)
        self._save_execution(record, status="OPEN_SUBMITTED", last_error=None)
        second_guard = self._broker_mutation_guard(record)
        if expected_mode == "live" and not allow_live_open:
            second_guard = "deployment kill switch menolak pending live OPEN"
        if second_guard:
            self.store.mark_position_action_failed(
                str(action["idempotency_key"]), second_guard
            )
            self._save_execution(record, status="GUARD_REJECTED", last_error=second_guard)
            result.actions_failed += 1
            self._project_open_failure(record, action, result, detail=second_guard)
            return

        binding_error, mutation_binding = self._broker_mutation_check(record)
        if binding_error or mutation_binding is None:
            detail = binding_error or "broker mutation binding tidak tersedia"
            self.store.mark_position_action_failed(
                str(action["idempotency_key"]), detail
            )
            self._save_execution(record, status="GUARD_REJECTED", last_error=detail)
            result.actions_failed += 1
            self._project_open_failure(record, action, result, detail=detail)
            return
        request = preflight.get("request")
        if not isinstance(request, dict):
            detail = "broker preflight tidak memiliki request untuk account binding"
            self.store.mark_position_action_failed(
                str(action["idempotency_key"]), detail
            )
            self._save_execution(record, status="GUARD_REJECTED", last_error=detail)
            result.actions_failed += 1
            self._project_open_failure(record, action, result, detail=detail)
            return
        request["_mutation_binding"] = mutation_binding
        broker_result = runtime.execute(snapshot, intent, size, preflight)
        broker_status = str(broker_result.get("status") or "UNKNOWN").upper()
        broker_detail = str(broker_result.get("detail") or broker_status)
        broker_updates = {
            "order_ticket": _optional_int(broker_result.get("order")),
            "deal_ticket": _optional_int(broker_result.get("deal")),
        }
        position = self._find_position(record)
        if position is not None:
            record = self._save_execution(record, **broker_updates)
            self._adopt_or_protect_position(
                record,
                position,
                result,
                action_key=str(action["idempotency_key"]),
            )
            return

        if broker_status in {"FILLED", "PARTIAL", "PLACED"}:
            self.store.mark_position_action_unknown(
                str(action["idempotency_key"]),
                f"{broker_status} dilaporkan tetapi posisi exact belum terlihat: {broker_detail}",
                broker_retcode=_optional_int(broker_result.get("retcode")),
            )
            self._save_execution(
                record,
                status="OPEN_SUBMITTED",
                last_error="menunggu rekonsiliasi posisi broker exact",
                **broker_updates,
            )
            result.actions_unknown += 1
            self._project_open_unknown(
                record,
                action,
                result,
                detail=(
                    f"broker melaporkan {broker_status}, tetapi posisi exact belum terlihat"
                ),
            )
            return
        if broker_status == "UNKNOWN" or bool(broker_result.get("outcome_unknown")):
            self.store.mark_position_action_unknown(
                str(action["idempotency_key"]),
                broker_detail,
                broker_retcode=_optional_int(broker_result.get("retcode")),
            )
            self._save_execution(
                record,
                status="OPEN_UNKNOWN",
                last_error=broker_detail,
                **broker_updates,
            )
            result.actions_unknown += 1
            self._project_open_unknown(
                record, action, result, detail=broker_detail
            )
            return

        self.store.mark_position_action_failed(
            str(action["idempotency_key"]),
            broker_detail,
            broker_retcode=_optional_int(broker_result.get("retcode")),
        )
        self._save_execution(
            record, status="REJECTED", last_error=broker_detail, **broker_updates
        )
        result.actions_failed += 1
        self._project_open_failure(record, action, result, detail=broker_detail)

    def _execute_initial_protection_action(
        self, action: dict[str, Any], result: PositionManagementCycle
    ) -> None:
        if bool(action.get("payload", {}).get("repair_filled")):
            self._execute_filled_protection_repair(action, result)
            return
        record = self._require_record_for_action(action)
        self._require_matching_broker_account(record)
        position = self._find_position(record)
        if position is None:
            self.store.mark_position_action_unknown(
                str(action["idempotency_key"]),
                "position absent while initial protection outcome is unresolved",
                lease_owner=self.lease_owner,
            )
            result.actions_unknown += 1
            return
        identity_error = self._position_identity_error(record, position)
        if identity_error:
            self.store.mark_position_action_failed(
                str(action["idempotency_key"]),
                identity_error,
                lease_owner=self.lease_owner,
            )
            result.actions_failed += 1
            self._project_initial_protection_failure(record, action, result)
            return
        if self._initial_protection_postcondition(position, action):
            self._fence_submitted(action, broker_position_ticket=position.ticket)
            self._confirm_position(
                record,
                position,
                action_key=str(action["idempotency_key"]),
                result=result,
            )
            return

        guard_error = self._broker_mutation_guard(record)
        if guard_error:
            self.store.mark_position_action_failed(
                str(action["idempotency_key"]),
                guard_error,
                lease_owner=self.lease_owner,
            )
            result.actions_failed += 1
            self._project_initial_protection_failure(
                record, action, result, detail=guard_error
            )
            return
        self._fence_submitted(action, broker_position_ticket=position.ticket)
        guard_error = self._broker_mutation_guard(record)
        if guard_error:
            self.store.mark_position_action_failed(
                str(action["idempotency_key"]), guard_error
            )
            result.actions_failed += 1
            self._project_initial_protection_failure(
                record, action, result, detail=guard_error
            )
            return

        payload = dict(action.get("payload") or {})
        target_stop = float(payload["target_stop"])
        target_tp = float(payload["target_tp"])
        preserve_better_stop = self._stop_postcondition(position, target_stop)
        binding_error, mutation_binding = self._broker_mutation_check(record)
        if binding_error or mutation_binding is None:
            detail = binding_error or "broker mutation binding tidak tersedia"
            self.store.mark_position_action_failed(
                str(action["idempotency_key"]), detail
            )
            result.actions_failed += 1
            self._project_initial_protection_failure(
                record, action, result, detail=detail
            )
            return
        try:
            broker_result = self.adapter.modify_position_protection(
                position_identifier=self._position_identifier(position),
                sl=None if preserve_better_stop else target_stop,
                tp=target_tp,
                mutation_binding=mutation_binding,
            )
        except Exception as exc:
            self.store.mark_position_action_unknown(
                str(action["idempotency_key"]),
                f"initial protection transport outcome unknown: {exc}",
            )
            result.actions_unknown += 1
            self._project_initial_protection_failure(
                record, action, result, detail=str(exc), unknown=True
            )
            return

        observed = self._find_position(record)
        if observed is not None and self._initial_protection_postcondition(
            observed, action
        ):
            self._confirm_position(
                record,
                observed,
                action_key=str(action["idempotency_key"]),
                result=result,
            )
            return
        detail = str(getattr(broker_result, "detail", "initial protection rejected"))
        if bool(getattr(broker_result, "outcome_unknown", False)):
            self.store.mark_position_action_unknown(
                str(action["idempotency_key"]), detail
            )
            result.actions_unknown += 1
            self._project_initial_protection_failure(
                record, action, result, detail=detail, unknown=True
            )
        else:
            self.store.mark_position_action_failed(
                str(action["idempotency_key"]),
                detail,
                broker_retcode=getattr(broker_result, "retcode", None),
            )
            result.actions_failed += 1
            self._project_initial_protection_failure(
                record, action, result, detail=detail
            )

    def _execute_filled_protection_repair(
        self, action: dict[str, Any], result: PositionManagementCycle
    ) -> None:
        record = self._require_record_for_action(action)
        self._require_matching_broker_account(record)
        position = self._find_position(record)
        if position is None:
            account_error = self._broker_account_identity_error(record)
            detail = account_error or "position absent before protection repair"
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="FAILED" if account_error is None else "UNKNOWN",
                error=detail,
                broker_reference="position absent",
            )
            if account_error is None:
                result.actions_failed += 1
                status = "FAILED"
            else:
                result.actions_unknown += 1
                status = "UNKNOWN"
            self._project_filled_protection_repair(record, action, status, result)
            return
        identity_error = self._position_identity_error(record, position)
        if identity_error:
            _, action = self._finalize_management_action(
                record, action, outcome="FAILED", error=identity_error
            )
            result.actions_failed += 1
            self._project_filled_protection_repair(
                record, action, "FAILED", result
            )
            return
        payload = dict(action.get("payload") or {})
        target_stop = float(payload["target_stop"])
        target_tp = float(payload["target_tp"])
        if self._initial_protection_postcondition(position, action):
            self._fence_submitted(action, broker_position_ticket=position.ticket)
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="CONFIRMED",
                remaining_volume=position.volume,
                current_stop_price=position.sl,
                current_take_profit_price=position.tp,
                broker_position_ticket=position.ticket,
                broker_reference="filled protection already restored",
            )
            result.actions_confirmed += 1
            self._project_filled_protection_repair(
                record, action, "CONFIRMED", result
            )
            return
        preserve_better_stop = self._stop_postcondition(position, target_stop)
        if not preserve_better_stop:
            protection_error = self._protection_precheck(position, target_stop)
            if protection_error:
                _, action = self._finalize_management_action(
                    record, action, outcome="FAILED", error=protection_error
                )
                result.actions_failed += 1
                self._project_filled_protection_repair(
                    record, action, "FAILED", result
                )
                return
        guard_error = self._broker_mutation_guard(record)
        if guard_error:
            _, action = self._finalize_management_action(
                record, action, outcome="FAILED", error=guard_error
            )
            result.actions_failed += 1
            self._project_filled_protection_repair(
                record, action, "FAILED", result
            )
            return
        self._fence_submitted(action, broker_position_ticket=position.ticket)
        guard_error = self._broker_mutation_guard(record)
        if guard_error:
            _, action = self._finalize_management_action(
                record, action, outcome="FAILED", error=guard_error
            )
            result.actions_failed += 1
            self._project_filled_protection_repair(
                record, action, "FAILED", result
            )
            return
        binding_error, mutation_binding = self._broker_mutation_check(record)
        if binding_error or mutation_binding is None:
            detail = binding_error or "broker mutation binding tidak tersedia"
            _, action = self._finalize_management_action(
                record, action, outcome="FAILED", error=detail
            )
            result.actions_failed += 1
            self._project_filled_protection_repair(
                record, action, "FAILED", result
            )
            return
        try:
            broker_result = self.adapter.modify_position_protection(
                position_identifier=self._position_identifier(position),
                sl=None if preserve_better_stop else target_stop,
                tp=target_tp,
                mutation_binding=mutation_binding,
            )
        except Exception as exc:
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="UNKNOWN",
                error=f"filled protection repair outcome unknown: {exc}",
            )
            result.actions_unknown += 1
            self._project_filled_protection_repair(
                record, action, "UNKNOWN", result
            )
            return
        observed = self._find_position(record)
        if observed is not None and self._initial_protection_postcondition(
            observed, action
        ):
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="CONFIRMED",
                remaining_volume=observed.volume,
                current_stop_price=observed.sl,
                current_take_profit_price=observed.tp,
                broker_position_ticket=observed.ticket,
                broker_retcode=getattr(broker_result, "retcode", None),
                broker_reference="filled protection repair postcondition verified",
            )
            result.actions_confirmed += 1
            self._project_filled_protection_repair(
                record, action, "CONFIRMED", result
            )
            return
        detail = str(
            getattr(broker_result, "detail", "filled protection repair failed")
        )
        outcome = (
            "UNKNOWN"
            if bool(getattr(broker_result, "outcome_unknown", False))
            else "FAILED"
        )
        _, action = self._finalize_management_action(
            record,
            action,
            outcome=outcome,
            error=detail,
            broker_retcode=getattr(broker_result, "retcode", None),
        )
        if outcome == "UNKNOWN":
            result.actions_unknown += 1
        else:
            result.actions_failed += 1
        self._project_filled_protection_repair(record, action, outcome, result)

    def _execute_modify_action(
        self, action: dict[str, Any], result: PositionManagementCycle
    ) -> None:
        record = self._require_record_for_action(action)
        self._require_matching_broker_account(record)
        position = self._find_position(record)
        if position is None:
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="FAILED",
                error="position absent before protection mutation",
            )
            result.actions_failed += 1
            self._project_protection_action(record, action, "FAILED", result)
            return
        identity_error = self._position_identity_error(record, position)
        if identity_error:
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="FAILED",
                error=identity_error,
            )
            result.actions_failed += 1
            self._project_protection_action(record, action, "FAILED", result)
            return
        if self._modify_postcondition(position, action):
            self._fence_submitted(action, broker_position_ticket=position.ticket)
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="CONFIRMED",
                remaining_volume=position.volume,
                current_stop_price=position.sl,
                current_take_profit_price=position.tp,
                broker_position_ticket=position.ticket,
                broker_reference="protection already satisfied",
            )
            result.actions_confirmed += 1
            self._project_protection_action(record, action, "CONFIRMED", result)
            return

        target_stop = float(action["payload"]["target_stop"])
        protection_error = self._protection_precheck(position, target_stop)
        if protection_error:
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="FAILED",
                error=protection_error,
            )
            result.actions_failed += 1
            self._project_protection_action(record, action, "FAILED", result)
            return

        guard_error = self._broker_mutation_guard(record)
        if guard_error:
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="FAILED",
                error=guard_error,
            )
            result.actions_failed += 1
            self._project_protection_action(record, action, "FAILED", result)
            return
        self._fence_submitted(action, broker_position_ticket=position.ticket)
        guard_error = self._broker_mutation_guard(record)
        if guard_error:
            _, action = self._finalize_management_action(
                record, action, outcome="FAILED", error=guard_error
            )
            result.actions_failed += 1
            self._project_protection_action(record, action, "FAILED", result)
            return
        protection_error = self._protection_precheck(position, target_stop)
        if protection_error:
            _, action = self._finalize_management_action(
                record, action, outcome="FAILED", error=protection_error
            )
            result.actions_failed += 1
            self._project_protection_action(record, action, "FAILED", result)
            return
        binding_error, mutation_binding = self._broker_mutation_check(record)
        if binding_error or mutation_binding is None:
            detail = binding_error or "broker mutation binding tidak tersedia"
            _, action = self._finalize_management_action(
                record, action, outcome="FAILED", error=detail
            )
            result.actions_failed += 1
            self._project_protection_action(record, action, "FAILED", result)
            return
        try:
            broker_result = self.adapter.modify_position_protection(
                position_identifier=self._position_identifier(position),
                sl=target_stop,
                tp=None,
                mutation_binding=mutation_binding,
            )
        except Exception as exc:
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="UNKNOWN",
                error=f"protection transport outcome unknown: {exc}",
            )
            result.actions_unknown += 1
            self._project_protection_action(record, action, "UNKNOWN", result)
            return
        observed = self._find_position(record)
        if observed is not None and self._modify_postcondition(observed, action):
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="CONFIRMED",
                remaining_volume=observed.volume,
                current_stop_price=observed.sl,
                current_take_profit_price=observed.tp,
                broker_position_ticket=observed.ticket,
                broker_retcode=getattr(broker_result, "retcode", None),
                broker_reference=str(getattr(broker_result, "detail", "confirmed")),
            )
            result.actions_confirmed += 1
            self._project_protection_action(record, action, "CONFIRMED", result)
            return
        detail = str(getattr(broker_result, "detail", "protection postcondition failed"))
        if bool(getattr(broker_result, "outcome_unknown", False)):
            _, action = self._finalize_management_action(
                record, action, outcome="UNKNOWN", error=detail
            )
            result.actions_unknown += 1
            self._project_protection_action(record, action, "UNKNOWN", result)
        else:
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="FAILED",
                error=detail,
                broker_retcode=getattr(broker_result, "retcode", None),
            )
            result.actions_failed += 1
            self._project_protection_action(record, action, "FAILED", result)

    def _execute_close_action(
        self, action: dict[str, Any], result: PositionManagementCycle
    ) -> None:
        record = self._require_record_for_action(action)
        self._require_matching_broker_account(record)
        position = self._find_position(record)
        if position is None:
            account_error = self._broker_account_identity_error(record)
            if account_error:
                raise RuntimeError(
                    f"cannot confirm close absence on a different account: {account_error}"
                )
            self._fence_submitted(action)
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="CONFIRMED",
                remaining_volume=0.0,
                broker_reference="matching broker position already absent",
            )
            result.actions_confirmed += 1
            self._project_close_action(record, action, "CONFIRMED", result)
            self._reconcile_closed_execution(record, result)
            return
        identity_error = self._position_identity_error(record, position)
        if identity_error:
            _, action = self._finalize_management_action(
                record, action, outcome="FAILED", error=identity_error
            )
            result.actions_failed += 1
            self._project_close_action(record, action, "FAILED", result)
            return
        guard_error = self._broker_mutation_guard(record)
        if guard_error:
            _, action = self._finalize_management_action(
                record, action, outcome="FAILED", error=guard_error
            )
            result.actions_failed += 1
            self._project_close_action(record, action, "FAILED", result)
            return
        payload = dict(action.get("payload") or {})
        snapshot = self._runtime_snapshot(record, payload, timeframe="M1")
        runtime = MT5ExecutionRuntime(
            adapter=self.adapter,
            allow_live_orders=True,
            magic=int(record["magic"]),
            comment_prefix="GMS",
        )
        intent = AIIntent(
            action=DecisionAction.CLOSE,
            side=str(record["side"]).lower(),
            reason=f"close-{str(record.get('client_tag') or '')}",
            payload={
                "position_ticket": position.ticket,
                "volume": position.volume,
            },
        )
        size = SimpleNamespace(
            normalized_volume=position.volume,
            mode=OperatingMode.RECOMMEND,
        )
        preflight = runtime.preflight(snapshot, intent, size)
        if str(preflight.get("status")) != "PRECHECK_OK":
            detail = str(preflight.get("detail") or "close preflight rejected")
            _, action = self._finalize_management_action(
                record, action, outcome="FAILED", error=detail
            )
            result.actions_failed += 1
            self._project_close_action(record, action, "FAILED", result)
            return
        self._fence_submitted(action, broker_position_ticket=position.ticket)
        guard_error = self._broker_mutation_guard(record)
        if guard_error:
            _, action = self._finalize_management_action(
                record, action, outcome="FAILED", error=guard_error
            )
            result.actions_failed += 1
            self._project_close_action(record, action, "FAILED", result)
            return
        binding_error, mutation_binding = self._broker_mutation_check(record)
        if binding_error or mutation_binding is None:
            detail = binding_error or "broker mutation binding tidak tersedia"
            _, action = self._finalize_management_action(
                record, action, outcome="FAILED", error=detail
            )
            result.actions_failed += 1
            self._project_close_action(record, action, "FAILED", result)
            return
        request = preflight.get("request")
        if not isinstance(request, dict):
            detail = "close preflight tidak memiliki request untuk account binding"
            _, action = self._finalize_management_action(
                record, action, outcome="FAILED", error=detail
            )
            result.actions_failed += 1
            self._project_close_action(record, action, "FAILED", result)
            return
        request["_mutation_binding"] = mutation_binding
        try:
            broker_result = runtime.execute(snapshot, intent, size, preflight)
        except Exception as exc:
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="UNKNOWN",
                error=f"close transport outcome unknown: {exc}",
            )
            self._save_execution(record, status="CLOSE_UNKNOWN", last_error=str(exc))
            result.actions_unknown += 1
            self._project_close_action(record, action, "UNKNOWN", result)
            return

        observed = self._find_position(record)
        if observed is None:
            account_error = self._broker_account_identity_error(record)
            if account_error:
                _, action = self._finalize_management_action(
                    record,
                    action,
                    outcome="UNKNOWN",
                    error=(
                        "close response diterima tetapi postcondition tidak dapat "
                        f"diverifikasi: {account_error}"
                    ),
                )
                self._save_execution(
                    record,
                    status="CLOSE_UNKNOWN",
                    last_error=account_error,
                )
                result.actions_unknown += 1
                self._project_close_action(record, action, "UNKNOWN", result)
                return
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="CONFIRMED",
                remaining_volume=0.0,
                broker_order_ticket=_optional_int(broker_result.get("order")),
                broker_deal_ticket=_optional_int(broker_result.get("deal")),
                broker_retcode=_optional_int(broker_result.get("retcode")),
                broker_reference="matching broker position absent after close",
            )
            result.actions_confirmed += 1
            record = self._save_execution(
                record,
                status="CLOSE_SUBMITTED",
                order_ticket=_optional_int(broker_result.get("order"))
                or record.get("order_ticket"),
                deal_ticket=_optional_int(broker_result.get("deal"))
                or record.get("deal_ticket"),
                last_error=None,
            )
            self._project_close_action(record, action, "CONFIRMED", result)
            self._reconcile_closed_execution(record, result)
            return

        broker_status = str(broker_result.get("status") or "UNKNOWN").upper()
        detail = str(broker_result.get("detail") or broker_status)
        if broker_status in {"UNKNOWN", "FILLED", "PARTIAL", "PLACED"}:
            _, action = self._finalize_management_action(
                record,
                action,
                outcome="UNKNOWN",
                remaining_volume=observed.volume,
                current_stop_price=observed.sl,
                current_take_profit_price=observed.tp,
                error=f"close belum terkonfirmasi; posisi masih ada: {detail}",
                broker_retcode=_optional_int(broker_result.get("retcode")),
            )
            self._save_execution(
                record,
                status="CLOSE_UNKNOWN",
                remaining_volume=observed.volume,
                last_error=detail,
            )
            result.actions_unknown += 1
            self._project_close_action(record, action, "UNKNOWN", result)
            return
        _, action = self._finalize_management_action(
            record,
            action,
            outcome="FAILED",
            error=detail,
            broker_retcode=_optional_int(broker_result.get("retcode")),
        )
        self._save_execution(record, status="CLOSE_REJECTED", last_error=detail)
        result.actions_failed += 1
        self._project_close_action(record, action, "FAILED", result)

    def _adopt_or_protect_position(
        self,
        record: dict[str, Any],
        position: OpenPositionSnapshot,
        result: PositionManagementCycle,
        *,
        action_key: str | None = None,
    ) -> None:
        identity_error = self._position_identity_error(record, position)
        if identity_error:
            raise RuntimeError(identity_error)
        account_error = self._broker_account_identity_error(record)
        if account_error:
            raise RuntimeError(account_error)
        if position.price_open <= 0 or position.volume <= 0:
            raise RuntimeError("broker position has invalid entry price or volume")

        if not self._position_ready_for_confirmation(record, position):
            open_key = action_key or self._confirmation_action_key(record)
            if open_key:
                open_action = self.store.position_action(open_key)
                if (
                    open_action
                    and str(open_action.get("action_type")) == _OPEN_ACTION
                    and str(open_action.get("status")) == "PENDING"
                ):
                    self.store.mark_position_action_submitted(
                        open_key,
                        broker_position_ticket=position.ticket,
                        broker_reference="exact unprotected broker position observed",
                    )
                    open_action = self.store.position_action(open_key)
                if open_action and str(open_action.get("status")) == "SUBMITTED":
                    self.store.mark_position_action_unknown(
                        open_key,
                        "exact position exists but initial protection is incomplete",
                        broker_position_ticket=position.ticket,
                    )
                    result.actions_unknown += 1
            latest = self._bind_unprotected_position(record, position)
            if self._holding_deadline_reached(latest, position):
                self.queue_close(
                    latest,
                    reason="MAX_HOLDING_EXPIRED",
                    closed_by="strategy_auto",
                )
                return
            identifier = self._position_identifier(position)
            emergency_key = f"SET_INITIAL_PROTECTION:{record['setup_id']}:{identifier}"
            self.store.create_position_action(
                idempotency_key=emergency_key,
                action_type=_INITIAL_PROTECTION_ACTION,
                setup_id=str(record["setup_id"]),
                position_ticket=position.ticket,
                position_identifier=identifier,
                payload={
                    "target_stop": float(record["stop_price"]),
                    "target_tp": float(record["target_price"]),
                    "position_identifier": identifier,
                },
                management_policy=str(record["management_policy"]),
                account_login=str(record["account_login"]),
                account_server=str(record["account_server"]),
                account_scope=str(record["account_scope"]),
            )
            result.notifications_enqueued += int(
                self._enqueue(
                    latest,
                    event_type="POSITION_UNPROTECTED",
                    event_key=f"POSITION_UNPROTECTED:{identifier}",
                    text="\n".join(
                        [
                            "🚨 POSISI BROKER BELUM TERPROTEKSI",
                            f"{record['symbol']}  •  {record['side']}",
                            f"• Ticket/identifier: {position.ticket}/{identifier}",
                            "• SL/TP broker belum sesuai; emergency protection sudah diantrikan sekali.",
                            "• Posisi belum dinyatakan FILLED oleh lifecycle sampai proteksi terkonfirmasi.",
                            f"🆔 {record['setup_id']}",
                        ]
                    ),
                    force_admin=True,
                )
            )
            return

        confirmation_key = action_key or self._confirmation_action_key(record)
        if confirmation_key is None:
            raise RuntimeError("exact broker position found without a reconcilable OPEN action")
        action = self.store.position_action(confirmation_key)
        if action and str(action.get("status")) == "PENDING":
            self.store.mark_position_action_submitted(
                confirmation_key,
                broker_position_ticket=position.ticket,
                broker_reference="position existed before reconciliation",
            )
        self._confirm_position(
            record,
            position,
            action_key=confirmation_key,
            result=result,
        )

    def _confirm_position(
        self,
        record: dict[str, Any],
        position: OpenPositionSnapshot,
        *,
        action_key: str,
        result: PositionManagementCycle,
    ) -> dict[str, Any]:
        identity_error = self._position_identity_error(record, position)
        if identity_error:
            raise RuntimeError(identity_error)
        account_error = self._broker_account_identity_error(record)
        if account_error:
            raise RuntimeError(account_error)
        if not self._position_ready_for_confirmation(record, position):
            raise RuntimeError(
                "cannot confirm FILLED until broker SL and TP postconditions are met"
            )
        opened_at = position.opened_at
        if not opened_at:
            raise RuntimeError("cannot freeze position without broker opened_at")
        policy_json = self._policy_json(record)
        confirmed = self.store.confirm_trade_position(
            str(record["setup_id"]),
            action_idempotency_key=action_key,
            position_ticket=position.ticket,
            position_identifier=self._position_identifier(position),
            symbol=position.symbol,
            side=position.side,
            comment=position.comment,
            actual_entry=position.price_open,
            opened_at=opened_at,
            initial_volume=position.volume,
            initial_stop_price=position.sl,
            current_stop_price=position.sl,
            initial_take_profit_price=position.tp,
            current_take_profit_price=position.tp,
            magic=position.magic,
            strategy_id=str(record["strategy_id"]),
            strategy_version=str(record["strategy_version"]),
            direction_profile=str(record["direction_profile"]),
            entry_side_policy=str(record["entry_side_policy"]),
            execution_profile=str(record["execution_profile"]),
            management_policy=str(record["management_policy"]),
            management_policy_version=str(record["management_policy_version"]),
            management_policy_json=policy_json,
            account_login=str(record["account_login"]),
            account_server=str(record["account_server"]),
            account_scope=str(record["account_scope"]),
            account_margin_mode=str(record["account_margin_mode"]),
            last_broker_sync_at=self.now_fn(),
        )
        result.actions_confirmed += 1
        result.notifications_enqueued += int(
            self._enqueue_position_opened(confirmed)
        )
        return confirmed

    def _bind_unprotected_position(
        self,
        record: dict[str, Any],
        position: OpenPositionSnapshot,
    ) -> dict[str, Any]:
        if not position.opened_at:
            raise RuntimeError(
                "cannot enforce frozen max holding without broker opened_at"
            )
        return self.store.bind_unprotected_trade_position(
            str(record["setup_id"]),
            position_ticket=position.ticket,
            position_identifier=self._position_identifier(position),
            symbol=position.symbol,
            side=position.side,
            comment=position.comment,
            actual_entry=position.price_open,
            opened_at=position.opened_at,
            volume=position.volume,
            current_stop_price=position.sl,
            current_take_profit_price=position.tp,
            magic=position.magic,
            account_login=str(record["account_login"]),
            account_server=str(record["account_server"]),
            account_scope=str(record["account_scope"]),
            last_broker_sync_at=self.now_fn(),
        )

    def _holding_deadline_reached(
        self,
        record: dict[str, Any],
        position: OpenPositionSnapshot,
    ) -> bool:
        minutes = _optional_int(record.get("max_holding_minutes"))
        if minutes is None:
            return False
        opened_at = _parse_iso(record.get("opened_at")) or _parse_iso(
            position.opened_at
        )
        if opened_at is None:
            raise RuntimeError(
                "active position has max_holding_minutes but no valid opened_at"
            )
        now = self.now_fn()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc) >= (
            opened_at.astimezone(timezone.utc) + timedelta(minutes=minutes)
        )

    def _stage_filled_protection_repair(
        self,
        record: dict[str, Any],
        position: OpenPositionSnapshot,
        *,
        target_stop: float,
        result: PositionManagementCycle,
    ) -> None:
        existing = [
            action
            for action in self.store.position_actions(
                setup_id=str(record["setup_id"]), limit=200
            )
            if str(action.get("action_type")) == _INITIAL_PROTECTION_ACTION
            and bool(action.get("payload", {}).get("repair_filled"))
        ]
        if existing and str(existing[-1].get("status")) in {
            "PENDING",
            "SUBMITTED",
            "UNKNOWN",
            "FAILED",
        }:
            # FAILED/UNKNOWN are never retried blindly. An operator must first
            # resolve/re-arm that durable intent.
            return
        ordinal = len(existing) + 1
        identifier = self._position_identifier(position)
        key = (
            f"RESTORE_PROTECTION:{record['setup_id']}:{identifier}:{ordinal}"
        )
        _, _, created = self.store.stage_position_management_action(
            str(record["setup_id"]),
            action_idempotency_key=key,
            action_type=_INITIAL_PROTECTION_ACTION,
            milestone=None,
            reached_milestones=(),
            reached_at=self.now_fn(),
            current_r=None,
            payload={
                "repair_filled": True,
                "target_stop": target_stop,
                "target_tp": float(record["initial_take_profit_price"]),
                "position_identifier": identifier,
            },
        )
        if not created:
            return
        result.notifications_enqueued += int(
            self._enqueue(
                record,
                event_type="POSITION_PROTECTION_DEGRADED",
                event_key=f"POSITION_PROTECTION_DEGRADED:{identifier}:{ordinal}",
                text="\n".join(
                    [
                        "🚨 PROTEKSI POSISI BROKER MENURUN",
                        f"{record['symbol']}  •  {record['side']}",
                        f"• SL broker: {position.sl}",
                        f"• TP broker: {position.tp}",
                        f"• Target repair SL/TP: {target_stop} / {record['initial_take_profit_price']}",
                        "Repair dipagari ledger; tidak ada retry mutasi buta.",
                        f"🆔 {record['setup_id']}",
                    ]
                ),
                force_admin=True,
            )
        )

    def _create_management_action(
        self,
        record: dict[str, Any],
        position: OpenPositionSnapshot,
        *,
        action_type: str,
        milestone: str,
        repair: bool,
        current_r: float | None,
        reached_milestones: tuple[str, ...],
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        existing = [
            action
            for action in self.store.position_actions(
                setup_id=str(record["setup_id"]), limit=200
            )
            if str(action.get("action_type")) == action_type
            and str(
                action.get("payload", {}).get("source_milestone")
                or action.get("payload", {}).get("milestone")
                or milestone
            )
            == str(payload.get("source_milestone") or milestone)
        ]
        if existing:
            latest = existing[-1]
            if str(latest.get("status")) in {
                "PENDING",
                "SUBMITTED",
                "UNKNOWN",
                "FAILED",
            }:
                return latest, False
        ordinal = len(existing) + 1
        identifier = self._position_identifier(position)
        action_payload = dict(payload)
        action_payload.setdefault("position_identifier", identifier)
        key = (
            f"{action_type}:{record['setup_id']}:{identifier}:"
            f"{milestone}:{ordinal}"
        )
        _, action, created = self.store.stage_position_management_action(
            str(record["setup_id"]),
            action_idempotency_key=key,
            action_type=action_type,
            milestone=milestone,
            reached_milestones=reached_milestones,
            reached_at=self.now_fn(),
            current_r=current_r,
            payload=action_payload,
            repair=repair,
        )
        return action, created

    def _set_milestone_action_status(
        self,
        record: dict[str, Any],
        milestone: str,
        status: BrokerActionStatus | str,
    ) -> None:
        value = BrokerActionStatus(status).value
        column = {
            "R1": "r1_protection_status",
            "R2": "r2_protection_status",
            "R3": "r3_close_status",
        }.get(str(milestone).upper())
        if column:
            self.store.update_trade_execution_management(
                str(record["setup_id"]), **{column: value}
            )

    def _finalize_management_action(
        self,
        record: dict[str, Any],
        action: dict[str, Any],
        *,
        outcome: str,
        remaining_volume: float | None = None,
        current_stop_price: float | None = None,
        current_take_profit_price: float | None = None,
        broker_order_ticket: int | None = None,
        broker_deal_ticket: int | None = None,
        broker_position_ticket: int | None = None,
        broker_retcode: int | None = None,
        broker_reference: str | None = None,
        error: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        milestone = action.get("payload", {}).get("milestone")
        return self.store.finalize_position_management_action(
            str(action["idempotency_key"]),
            setup_id=str(record["setup_id"]),
            outcome=outcome,
            milestone=str(milestone) if milestone else None,
            remaining_volume=remaining_volume,
            current_stop_price=current_stop_price,
            current_take_profit_price=current_take_profit_price,
            last_broker_sync_at=self.now_fn(),
            broker_order_ticket=broker_order_ticket,
            broker_deal_ticket=broker_deal_ticket,
            broker_position_ticket=broker_position_ticket,
            broker_retcode=broker_retcode,
            broker_reference=broker_reference,
            error=error,
        )

    def _project_protection_action(
        self,
        record: dict[str, Any],
        action: dict[str, Any],
        status: str,
        result: PositionManagementCycle,
    ) -> None:
        milestone = str(
            action.get("payload", {}).get("source_milestone")
            or action.get("payload", {}).get("milestone")
            or ""
        )
        if milestone not in {"R1", "R2"}:
            return
        broker_status = BrokerActionStatus(status)
        self._set_milestone_action_status(record, milestone, broker_status)
        position = self._find_position(record)
        broker_stop = position.sl if position is not None else None
        detail = str(action.get("last_error") or "")
        if status == "CONFIRMED":
            detail = "postcondition SL broker terkonfirmasi; TP dipertahankan"
        elif status == "UNKNOWN":
            detail = "hasil mutasi belum dapat dikonfirmasi; tidak ada retry otomatis"
        result.notifications_enqueued += int(
            self._enqueue_protection_result(
                record,
                milestone=milestone,
                confirmed=status == "CONFIRMED",
                detail=detail or "broker protection failed",
                broker_stop=broker_stop,
                unknown=status == "UNKNOWN",
                action_key=str(action["idempotency_key"]),
            )
        )

    def _project_close_action(
        self,
        record: dict[str, Any],
        action: dict[str, Any],
        status: str,
        result: PositionManagementCycle,
    ) -> None:
        is_r3 = (
            str(action.get("payload", {}).get("milestone") or "") == "R3"
            or str(record.get("close_reason") or "") == "R3_TARGET"
        )
        if is_r3:
            self._set_milestone_action_status(record, "R3", BrokerActionStatus(status))
        event_type = {
            "CONFIRMED": "POSITION_CLOSE_CONFIRMED",
            "FAILED": "POSITION_CLOSE_FAILED",
            "UNKNOWN": "POSITION_CLOSE_UNKNOWN",
        }[status]
        if status == "CONFIRMED":
            self.store.update_trade_execution_management(
                str(record["setup_id"]),
                remaining_volume=0.0,
                last_broker_sync_at=self.now_fn(),
            )
            self._save_execution(record, status="CLOSE_SUBMITTED", last_error=None)
            headline = "✅ CLOSE BROKER TERKONFIRMASI"
            detail = "Posisi exact sudah tidak ada; P/L final menunggu deal history broker."
        elif status == "UNKNOWN":
            headline = "⚠️ CLOSE BELUM TERKONFIRMASI"
            detail = "Posisi masih ada/hasil ambigu; tidak ada retry otomatis."
        else:
            headline = "🚨 CLOSE BROKER GAGAL"
            detail = str(action.get("last_error") or "broker rejected close")
        result.notifications_enqueued += int(
            self._enqueue(
                record,
                event_type=event_type,
                event_key=f"{event_type}:{action['idempotency_key']}",
                text="\n".join(
                    [
                        headline,
                        f"{record['symbol']}  •  {record['side']}",
                        f"• Pemicu: {record.get('close_reason') or action.get('payload', {}).get('milestone') or '-'}",
                        f"• Detail: {detail}",
                        f"🆔 {record['setup_id']}",
                    ]
                ),
                force_admin=status != "CONFIRMED",
            )
        )

    def _project_open_failure(
        self,
        record: dict[str, Any],
        action: dict[str, Any],
        result: PositionManagementCycle,
        *,
        detail: str | None = None,
    ) -> None:
        result.notifications_enqueued += int(
            self._enqueue(
                record,
                event_type="POSITION_OPEN_REJECTED",
                event_key=f"POSITION_OPEN_REJECTED:{action['idempotency_key']}",
                text="\n".join(
                    [
                        "🚫 OPEN BROKER TIDAK DILANJUTKAN",
                        f"{record['symbol']}  •  {record['side']}",
                        f"• Detail: {detail or action.get('last_error') or 'broker action failed'}",
                        "Tidak ada posisi yang diklaim terbuka.",
                        f"🆔 {record['setup_id']}",
                    ]
                ),
                force_admin=str(record.get("account_scope")) == "live",
            )
        )

    def _project_open_unknown(
        self,
        record: dict[str, Any],
        action: dict[str, Any],
        result: PositionManagementCycle,
        *,
        detail: str | None = None,
    ) -> None:
        result.notifications_enqueued += int(
            self._enqueue(
                record,
                event_type="POSITION_OPEN_UNKNOWN",
                event_key=f"POSITION_OPEN_UNKNOWN:{action['idempotency_key']}",
                text="\n".join(
                    [
                        "⚠️ STATUS OPEN BROKER AMBIGU",
                        f"{record['symbol']}  •  {record['side']}",
                        f"• Detail: {detail or action.get('last_error') or 'hasil broker belum pasti'}",
                        "• Tidak ada retry order otomatis.",
                        "• POSITION_OPENED hanya akan dikirim setelah posisi exact + SL/TP terkonfirmasi.",
                        "• Jika posisi sudah buka-lalu-tutup sebelum terlihat, rekonsiliasi deal IN/OUT "
                        "belum dapat membekukan SL/TP aktual secara aman; periksa history broker manual.",
                        f"🆔 {record['setup_id']}",
                    ]
                ),
                force_admin=True,
            )
        )

    def _project_initial_protection_failure(
        self,
        record: dict[str, Any],
        action: dict[str, Any],
        result: PositionManagementCycle,
        *,
        detail: str | None = None,
        unknown: bool = False,
    ) -> None:
        event_type = (
            "POSITION_PROTECTION_UNKNOWN" if unknown else "POSITION_PROTECTION_FAILED"
        )
        result.notifications_enqueued += int(
            self._enqueue(
                record,
                event_type=event_type,
                event_key=f"{event_type}:{action['idempotency_key']}",
                text="\n".join(
                    [
                        "🚨 PROTEKSI AWAL BELUM TERKONFIRMASI",
                        f"{record['symbol']}  •  {record['side']}",
                        f"• Detail: {detail or action.get('last_error') or 'unknown'}",
                        "Periksa posisi broker segera; lifecycle tidak mengklaim posisi aman.",
                        f"🆔 {record['setup_id']}",
                    ]
                ),
                force_admin=True,
            )
        )

    def _project_filled_protection_repair(
        self,
        record: dict[str, Any],
        action: dict[str, Any],
        status: str,
        result: PositionManagementCycle,
    ) -> None:
        normalized = str(status or "").upper()
        event_type = {
            "CONFIRMED": "POSITION_PROTECTION_RESTORED",
            "FAILED": "POSITION_PROTECTION_REPAIR_FAILED",
            "UNKNOWN": "POSITION_PROTECTION_REPAIR_UNKNOWN",
        }.get(normalized)
        if event_type is None:
            return
        payload = dict(action.get("payload") or {})
        result.notifications_enqueued += int(
            self._enqueue(
                record,
                event_type=event_type,
                event_key=f"{event_type}:{action['idempotency_key']}",
                text="\n".join(
                    [
                        (
                            "✅ PROTEKSI POSISI DIPULIHKAN"
                            if normalized == "CONFIRMED"
                            else "🚨 REPAIR PROTEKSI BELUM TERKONFIRMASI"
                        ),
                        f"{record['symbol']}  •  {record['side']}",
                        f"• Target SL/TP: {payload.get('target_stop')} / {payload.get('target_tp')}",
                        f"• Status ledger: {normalized}",
                        f"• Detail: {action.get('last_error') or action.get('broker_reference') or '-'}",
                        f"🆔 {record['setup_id']}",
                    ]
                ),
                force_admin=normalized != "CONFIRMED",
            )
        )

    def _enqueue_touch(
        self,
        record: dict[str, Any],
        milestone: str,
        current_r: float,
        policy: PositionManagementPolicy,
    ) -> bool:
        return self._enqueue(
            record,
            event_type=f"POSITION_{milestone}_TOUCHED",
            event_key=f"POSITION_{milestone}_TOUCHED:{record.get('position_identifier')}",
            text=self._milestone_touch_text(record, milestone, current_r, policy),
        )

    @staticmethod
    def _milestone_touch_text(
        record: dict[str, Any],
        milestone: str,
        current_r: float,
        policy: PositionManagementPolicy,
    ) -> str:
        enabled = {
            "R1": policy.r1_protection_enabled,
            "R2": policy.r2_protection_enabled,
            "R3": policy.r3_close_enabled,
        }[milestone]
        return "\n".join(
            [
                f"🎯 {milestone} TERSENTUH",
                f"{record['symbol']}  •  {record['side']}",
                f"• R executable broker: {current_r:.3f}",
                f"• Action {milestone}: {'aktif' if enabled else 'nonaktif'}",
                "Touch ini bukan konfirmasi bahwa SL/close broker berhasil.",
                f"🆔 {record['setup_id']}",
            ]
        )

    def _enqueue_protection_result(
        self,
        record: dict[str, Any],
        *,
        milestone: str,
        confirmed: bool,
        detail: str,
        broker_stop: float | None,
        unknown: bool = False,
        action_key: str | None = None,
    ) -> bool:
        suffix = "UNKNOWN" if unknown else ("CONFIRMED" if confirmed else "FAILED")
        event_type = f"POSITION_{milestone}_PROTECTION_{suffix}"
        headline = {
            "CONFIRMED": f"✅ PROTEKSI {milestone} TERKONFIRMASI",
            "FAILED": f"🚨 PROTEKSI {milestone} GAGAL",
            "UNKNOWN": f"⚠️ PROTEKSI {milestone} BELUM TERKONFIRMASI",
        }[suffix]
        return self._enqueue(
            record,
            event_type=event_type,
            event_key=f"{event_type}:{action_key or record.get('position_identifier')}",
            text="\n".join(
                [
                    headline,
                    f"{record['symbol']}  •  {record['side']}",
                    f"• SL broker teramati: {broker_stop if broker_stop is not None else '-'}",
                    f"• Detail: {detail}",
                    f"🆔 {record['setup_id']}",
                ]
            ),
            force_admin=not confirmed,
        )

    def _enqueue_position_opened(self, record: dict[str, Any]) -> int:
        identifier = record.get("position_identifier")
        enqueued = int(
            self._enqueue(
                record,
                event_type="POSITION_OPENED",
                event_key=f"POSITION_OPENED:{identifier}",
                text="\n".join(
                    [
                        "✅ POSISI BROKER TERBUKA DAN TERPROTEKSI",
                        f"{record['symbol']}  •  {record['side']}",
                        f"• Lot aktual: {float(record['initial_volume']):.2f}",
                        f"• Entry aktual: {record['actual_entry']}",
                        f"• Initial SL aktual: {record['initial_stop_price']}",
                        f"• Initial TP aktual: {record['initial_take_profit_price']}",
                        f"• Risiko awal aktual: {record['initial_risk_distance']}",
                        f"• Expected loss: {float(record['risk_cash']):.2f} (mata uang akun)",
                        f"• Expected profit: {float(record['expected_profit_cash']):.2f} (mata uang akun)",
                        f"• Entry time broker: {record['opened_at']}",
                        f"• Entry TTL sinyal (valid-until): {record.get('valid_until') or '-'}",
                        f"• Max holding: {record.get('max_holding_minutes') or '-'} menit",
                        f"• Expected end (UTC): {_expected_position_end(record)}",
                        f"• Ticket/identifier: {record['position_ticket']}/{identifier}",
                        f"• Policy: {record['management_policy']} v{record['management_policy_version']}",
                        f"🆔 {record['setup_id']}",
                    ]
                ),
            )
        )
        enqueued += int(self._enqueue_r3_unreachable_warning(record))
        return enqueued

    def _enqueue_r3_unreachable_warning(self, record: dict[str, Any]) -> bool:
        policy = self._policy_from_record(record)
        if not policy.r3_close_enabled:
            return False
        entry = float(record.get("actual_entry") or 0.0)
        stop = float(record.get("initial_stop_price") or 0.0)
        target = float(record.get("initial_take_profit_price") or 0.0)
        risk = abs(entry - stop)
        side = str(record.get("side") or "").lower()
        reward = target - entry if side == "buy" else entry - target
        if risk <= 0 or reward <= 0:
            return False
        broker_tp_r = reward / risk
        if broker_tp_r + 1e-9 >= float(policy.r3_threshold):
            return False
        identifier = record.get("position_identifier")
        return self._enqueue(
            record,
            event_type="R3_UNREACHABLE_BEFORE_BROKER_TP",
            event_key=f"R3_UNREACHABLE_BEFORE_BROKER_TP:{identifier}",
            text="\n".join(
                [
                    "⚠️ R3 TIDAK DAPAT TERCAPAI SEBELUM TP BROKER",
                    f"{record['symbol']}  •  {record['side']}",
                    f"• TP broker beku: {broker_tp_r:.3f}R",
                    f"• Ambang R3 policy: {float(policy.r3_threshold):.3f}R",
                    "• TP broker tetap dipertahankan dan akan menutup posisi lebih dahulu.",
                    "• Algoritma, TP, dan SL tidak diubah oleh alert ini.",
                    f"🆔 {record['setup_id']}",
                ]
            ),
            force_admin=True,
        )

    def _enqueue_management_error(
        self, record: dict[str, Any], detail: str
    ) -> bool:
        digest = hashlib.sha256(detail.encode("utf-8", errors="replace")).hexdigest()[:12]
        return self._enqueue(
            record,
            event_type="POSITION_MANAGEMENT_ERROR",
            event_key=f"POSITION_MANAGEMENT_ERROR:{digest}",
            text="\n".join(
                [
                    "🚨 POSITION MANAGEMENT ERROR",
                    f"{record.get('symbol', '?')}  •  {record.get('side', '?')}",
                    f"• Detail: {detail}",
                    "Posisi lain tetap diproses; tidak ada mutasi yang di-retry buta.",
                    f"🆔 {record.get('setup_id', '?')}",
                ]
            ),
            force_admin=True,
        )

    def _enqueue(
        self,
        record: dict[str, Any],
        *,
        event_type: str,
        event_key: str,
        text: str,
        force_admin: bool = False,
    ) -> bool:
        return self.store.enqueue(
            setup_id=str(record["setup_id"]),
            event_type=event_type,
            event_key=event_key,
            payload=self._event_payload(
                record,
                event_type=event_type,
                text=text,
                force_admin=force_admin,
            ),
        )

    @staticmethod
    def _event_payload(
        record: dict[str, Any],
        *,
        event_type: str,
        text: str,
        force_admin: bool = False,
    ) -> dict[str, Any]:
        raw_scope = str(record.get("account_scope") or "unknown").strip().lower()
        scope = raw_scope if raw_scope in {"demo", "live"} else "unknown"
        audience = "approved" if scope == "demo" and not force_admin else "admin_only"
        return {
            "text": text,
            "setup_id": str(record["setup_id"]),
            "event_type": event_type,
            "source": "mt5_broker_position_manager",
            "account_scope": scope,
            "account_login": str(record.get("account_login") or ""),
            "account_server": str(record.get("account_server") or ""),
            "audience": audience,
        }

    def _reconcile_closed_execution(
        self, record: dict[str, Any], result: PositionManagementCycle
    ) -> None:
        account_error = self._broker_account_identity_error(record)
        if account_error:
            raise RuntimeError(
                f"cannot query close history on a different account: {account_error}"
            )
        if self._find_position(record) is not None:
            return
        since = _parse_iso(record.get("opened_at")) or (
            self.now_fn() - timedelta(days=2)
        )
        deals = self.adapter.load_deals(
            since=since, symbol=str(record["symbol"])
        )
        identifier = _optional_int(record.get("position_identifier"))
        ticket = _optional_int(record.get("position_ticket"))
        magic = int(record.get("magic") or 0)
        client_tag = str(record.get("client_tag") or "")
        matching = [
            deal
            for deal in deals
            if str(deal.entry) in {"out", "inout", "out_by"}
            and (
                (identifier and int(deal.position_ticket) == identifier)
                or (ticket and int(deal.position_ticket) == ticket)
                or (
                    client_tag
                    and client_tag in str(deal.comment)
                    and (not magic or int(deal.magic) == magic)
                )
            )
        ]
        if not matching:
            # Position absence confirms a close postcondition, but never invents
            # a final exit price or P/L without broker deal evidence.
            return
        last = max(matching, key=lambda deal: str(deal.occurred_at or ""))
        related = [
            deal
            for deal in deals
            if int(deal.position_ticket) == int(last.position_ticket)
        ]
        profit = sum(
            float(deal.profit)
            + float(deal.commission)
            + float(deal.swap)
            + float(getattr(deal, "fee", 0.0) or 0.0)
            for deal in related
        )
        opened_at = _parse_iso(record.get("opened_at")) or since
        closed_at = _parse_iso(last.occurred_at) or self.now_fn()
        duration = max(0, int((closed_at - opened_at).total_seconds() // 60))
        closed_by = _closed_by(str(last.reason), record.get("closed_by"))
        latest = self._save_execution(
            record,
            status="CLOSED",
            position_ticket=int(last.position_ticket),
            closed_at=closed_at.isoformat(),
            exit_price=float(last.price),
            profit_cash=profit,
            close_reason=str(last.reason),
            closed_by=closed_by,
            last_error=None,
        )
        predicted = _prediction_label(
            str(last.reason),
            float(record["target_price"]),
            float(record["stop_price"]),
            float(last.price),
        )
        if self._enqueue(
            latest,
            event_type="POSITION_CLOSED",
            event_key=f"POSITION_CLOSED:{last.ticket}",
            text="\n".join(
                [
                    "🏁 POSISI BROKER DITUTUP",
                    f"{record['symbol']}  •  {record['side']}",
                    f"• Ditutup oleh: {closed_by}",
                    f"• Alasan broker: {last.reason}",
                    f"• Entry aktual: {record['actual_entry']}",
                    f"• Exit aktual: {last.price}",
                    f"• P/L aktual: {profit:.2f} (mata uang akun)",
                    f"• Durasi aktual: {duration} menit",
                    f"• Hasil vs rencana: {predicted}",
                    f"🆔 {record['setup_id']}",
                ]
            ),
        ):
            result.notifications_enqueued += 1
        result.closed_positions += 1

    def _reconcile_unobserved_open_history(
        self, record: dict[str, Any], result: PositionManagementCycle
    ) -> None:
        """Surface an exact deal round-trip without inventing SL/TP truth.

        MT5 deal rows prove fills and realized cash, but they do not contain the
        position's actual initial SL/TP snapshot. Consequently an OPEN that was
        filled and closed before the first position observation remains
        OPEN_UNKNOWN. The evidence is still reported durably to the admin so it
        cannot look like a harmless missing fill.
        """

        account_error = self._broker_account_identity_error(record)
        if account_error:
            raise RuntimeError(
                "cannot query ambiguous OPEN history on a different account: "
                f"{account_error}"
            )
        if self._find_position(record) is not None:
            return
        magic = _optional_int(record.get("magic"))
        client_tag = str(record.get("client_tag") or "")
        symbol = str(record.get("symbol") or "")
        side = str(record.get("side") or "").lower()
        if not magic or not client_tag or not symbol or side not in {"buy", "sell"}:
            return
        since = _parse_iso(record.get("created_at")) or (
            self.now_fn() - timedelta(days=2)
        )
        deals = self.adapter.load_deals(since=since, symbol=symbol)
        entry_deal_ticket = _optional_int(record.get("deal_ticket"))
        entries = [
            deal
            for deal in deals
            if str(deal.symbol) == symbol
            and str(deal.entry).lower() == "in"
            and str(deal.side).lower() == side
            and int(deal.magic) == magic
            and client_tag in str(deal.comment)
            and float(deal.volume) > 0
            and float(deal.price) > 0
            and (
                entry_deal_ticket is None
                or int(deal.ticket) == entry_deal_ticket
            )
        ]
        identifiers = {int(deal.position_ticket) for deal in entries}
        if len(identifiers) != 1:
            return
        position_identifier = identifiers.pop()
        related = [
            deal
            for deal in deals
            if str(deal.symbol) == symbol
            and int(deal.position_ticket) == position_identifier
            and int(deal.magic) == magic
        ]
        exits = [
            deal
            for deal in related
            if str(deal.entry).lower() in {"out", "inout", "out_by"}
            and float(deal.volume) > 0
            and float(deal.price) > 0
        ]
        entry_volume = sum(float(deal.volume) for deal in entries)
        exit_volume = sum(float(deal.volume) for deal in exits)
        if not exits or exit_volume + 1e-9 < entry_volume:
            return
        entry_price = sum(
            float(deal.price) * float(deal.volume) for deal in entries
        ) / entry_volume
        exit_price = sum(
            float(deal.price) * float(deal.volume) for deal in exits
        ) / exit_volume
        first_entry = min(entries, key=lambda deal: str(deal.occurred_at or ""))
        last_exit = max(exits, key=lambda deal: str(deal.occurred_at or ""))
        realized_cash = sum(
            float(deal.profit)
            + float(deal.commission)
            + float(deal.swap)
            + float(getattr(deal, "fee", 0.0) or 0.0)
            for deal in related
        )
        detail = (
            "broker deal IN/OUT exact ditemukan, tetapi snapshot SL/TP awal aktual "
            "tidak tersedia; status tetap UNKNOWN dan perlu verifikasi manual"
        )
        latest = self._save_execution(
            record,
            status="OPEN_UNKNOWN",
            last_error=detail,
        )
        if self._enqueue(
            latest,
            event_type="POSITION_ROUND_TRIP_UNRESOLVED",
            event_key=(
                "POSITION_ROUND_TRIP_UNRESOLVED:"
                f"{position_identifier}:{int(last_exit.ticket)}"
            ),
            text="\n".join(
                [
                    "🚨 OPEN DAN CLOSE BROKER TERDETEKSI SEBELUM SNAPSHOT POSISI",
                    f"{symbol}  •  {str(record['side']).upper()}",
                    f"• Position identifier: {position_identifier}",
                    f"• Entry deal: {first_entry.ticket} @ {entry_price}",
                    f"• Exit deal terakhir: {last_exit.ticket} @ {exit_price}",
                    f"• Volume IN/OUT: {entry_volume} / {exit_volume}",
                    f"• P/L broker teramati: {realized_cash:.2f} (termasuk komisi/swap/fee)",
                    "• SL/TP awal aktual tidak tersedia di deal history; "
                    "POSITION_OPENED/POSITION_CLOSED tidak diklaim.",
                    "Periksa order dan history broker secara manual.",
                    f"🆔 {record['setup_id']}",
                ]
            ),
            force_admin=True,
        ):
            result.notifications_enqueued += 1

    def _record_for_action(
        self, action: dict[str, Any]
    ) -> dict[str, Any] | None:
        setup_id = action.get("setup_id")
        return self.store.trade_execution(str(setup_id)) if setup_id else None

    def _require_record_for_action(
        self, action: dict[str, Any]
    ) -> dict[str, Any]:
        record = self._record_for_action(action)
        if record is None:
            raise RuntimeError("position action has no trade execution")
        return record

    def _save_execution(
        self, record: dict[str, Any], **updates: Any
    ) -> dict[str, Any]:
        latest = self.store.trade_execution(str(record["setup_id"])) or dict(record)
        latest.update(updates)
        self.store.save_trade_execution(latest)
        return self.store.trade_execution(str(record["setup_id"])) or latest

    def _find_position(
        self, record: dict[str, Any]
    ) -> OpenPositionSnapshot | None:
        symbol = str(record.get("symbol") or "")
        identifier = _optional_int(record.get("position_identifier"))
        ticket = _optional_int(record.get("position_ticket"))
        if identifier:
            return self.adapter.find_open_position(
                position_identifier=identifier, symbol=symbol
            )
        if ticket:
            found = self.adapter.find_open_position(
                position_ticket=ticket, symbol=symbol
            )
            if found is not None:
                return found

        magic = _optional_int(record.get("magic"))
        client_tag = str(record.get("client_tag") or "")
        side = str(record.get("side") or "").lower()
        if not symbol or not magic or not client_tag or side not in {"buy", "sell"}:
            return None
        candidates = [
            position
            for position in self.adapter.load_open_positions(symbol=symbol)
            if position.symbol == symbol
            and str(position.side).lower() == side
            and int(position.magic) == magic
            and client_tag in str(position.comment)
        ]
        if len(candidates) > 1:
            raise RuntimeError(
                "multiple broker positions match immutable magic/client tag; refusing adoption"
            )
        return candidates[0] if candidates else None

    def _position_identity_error(
        self, record: dict[str, Any], position: OpenPositionSnapshot
    ) -> str | None:
        if position.symbol != str(record.get("symbol") or ""):
            return "broker position symbol does not match frozen execution"
        if str(position.side).lower() != str(record.get("side") or "").lower():
            return "broker position side does not match frozen execution"
        if int(position.magic) != int(record.get("magic") or 0):
            return "broker position magic does not match frozen execution"
        if str(record.get("client_tag") or "") not in str(position.comment):
            return "broker position comment does not contain frozen client tag"
        frozen_identifier = _optional_int(record.get("position_identifier"))
        if frozen_identifier and self._position_identifier(position) != frozen_identifier:
            return "broker position stable identifier does not match frozen execution"
        if position.volume <= 0:
            return "broker position volume is not positive"
        return None

    def _broker_mutation_guard(self, record: dict[str, Any]) -> str | None:
        error, _ = self._broker_mutation_check(record)
        return error

    def _broker_mutation_check(
        self, record: dict[str, Any]
    ) -> tuple[str | None, MutationAccountBinding | None]:
        identity_error = self._broker_account_identity_error(record)
        if identity_error:
            return identity_error, None
        expected_server = str(record.get("account_server") or "")
        terminal = self.adapter.load_terminal_status()
        if not terminal.connected:
            return "terminal MT5 tidak terhubung", None
        if not terminal.trade_allowed or terminal.tradeapi_disabled:
            return "terminal MT5 menolak API trading", None
        if not terminal.account_trade_allowed or not terminal.account_trade_expert:
            return "akun MT5 menolak expert trading", None
        if terminal.server and str(terminal.server) != expected_server:
            return "terminal server berubah dari snapshot posisi", None
        return (
            None,
            MutationAccountBinding(
                login=str(record.get("account_login") or ""),
                server=expected_server,
                account_scope=str(record.get("account_scope") or ""),
                margin_mode=str(record.get("account_margin_mode") or "UNKNOWN"),
                terminal_path=str(getattr(terminal, "path", "") or ""),
                terminal_data_path=str(getattr(terminal, "data_path", "") or ""),
            ),
        )

    def _broker_account_identity_error(
        self, record: dict[str, Any]
    ) -> str | None:
        fingerprint = self.adapter.load_account_fingerprint()
        expected_login = str(record.get("account_login") or "")
        expected_server = str(record.get("account_server") or "")
        expected_margin_mode = str(record.get("account_margin_mode") or "").upper()
        scope = str(record.get("account_scope") or "").lower()
        if not expected_login or str(fingerprint.login) != expected_login:
            return "MT5 login tidak cocok dengan snapshot posisi"
        if not expected_server or str(fingerprint.server) != expected_server:
            return "MT5 server tidak cocok dengan snapshot posisi"
        if scope == "demo" and fingerprint.is_live is not False:
            return "snapshot demo menolak akun live/tidak teridentifikasi"
        if scope == "live" and fingerprint.is_live is not True:
            return "snapshot live menolak akun demo/tidak teridentifikasi"
        if scope not in {"demo", "live"}:
            return "account scope posisi tidak valid"
        if expected_margin_mode and str(fingerprint.margin_mode).upper() != expected_margin_mode:
            return "MT5 account margin mode tidak cocok dengan snapshot posisi"
        return None

    def _require_matching_broker_account(self, record: dict[str, Any]) -> None:
        error = self._broker_account_identity_error(record)
        if error:
            raise RuntimeError(
                "broker postcondition cannot be observed on a different account: "
                f"{error}"
            )

    def _normalize_protective_stop(
        self, symbol: str, side: str, target_stop: float
    ) -> float:
        snapshot = self.adapter.load_symbol_snapshot(symbol)
        tick_size = float(snapshot.tick_size or snapshot.point or 0.0)
        if tick_size <= 0:
            raise ValueError("symbol tick size is unavailable")
        units = Decimal(str(target_stop)) / Decimal(str(tick_size))
        rounding = ROUND_CEILING if str(side).lower() == "buy" else ROUND_FLOOR
        normalized = units.quantize(Decimal("1"), rounding=rounding) * Decimal(
            str(tick_size)
        )
        return float(normalized)

    def _protection_precheck(
        self, position: OpenPositionSnapshot, target_stop: float
    ) -> str | None:
        symbol = self.adapter.load_symbol_snapshot(position.symbol)
        tick = self.adapter.load_price_tick(position.symbol)
        point = float(symbol.point or 0.0)
        if point <= 0:
            return "symbol point tidak valid untuk proteksi"
        minimum = max(
            float(symbol.stops_level_points or 0.0),
            float(symbol.freeze_level_points or 0.0),
        ) * point
        tolerance = point * 0.51
        if str(position.side).lower() == "buy":
            distance = float(tick.bid) - target_stop
        else:
            distance = target_stop - float(tick.ask)
        if distance <= 0:
            return "target SL berada di sisi pasar yang tidak valid"
        if distance + tolerance < minimum:
            return (
                "target SL melanggar broker stops/freeze level; "
                "tidak ada mutasi dikirim"
            )
        return None

    def _runtime_snapshot(
        self,
        record: dict[str, Any],
        payload: dict[str, Any],
        *,
        timeframe: str,
    ):
        risk_payload = payload.get("risk_policy")
        if not isinstance(risk_payload, dict):
            # Management actions can be staged long after OPEN. The immutable
            # execution still contains enough conservative risk limits for a
            # close snapshot only when copied into its action payload.
            risk_payload = {
                "base_risk_pct": 0.01,
                "max_total_open_risk_pct": 100.0,
                "daily_loss_limit_pct": 100.0,
            }
        allowed = set(RiskPolicy.__dataclass_fields__)
        unknown = set(risk_payload) - allowed
        if unknown:
            raise ValueError(f"unknown frozen risk policy fields: {sorted(unknown)}")
        policy = RiskPolicy(**risk_payload)
        symbol_snapshot = self.adapter.load_symbol_snapshot(str(record["symbol"]))
        point = float(symbol_snapshot.point or 0.0)
        if point <= 0:
            raise ValueError("MT5 symbol point is unavailable")
        initial_stop = float(
            record.get("initial_stop_price") or record.get("stop_price") or 0.0
        )
        entry = float(record.get("actual_entry") or record["requested_entry"])
        stop_points = abs(entry - initial_stop) / point
        if stop_points <= 0:
            raise ValueError("frozen stop distance is invalid")
        return MT5SnapshotProvider(
            adapter=self.adapter,
            symbol=str(record["symbol"]),
            timeframe=timeframe,
            risk_policy=policy,
            trading_style=TradingStyle.INTRADAY,
            stop_distance_points=stop_points,
        ).get_snapshot()

    @staticmethod
    def _operating_mode(payload: dict[str, Any]) -> OperatingMode:
        try:
            return OperatingMode(str(payload.get("operating_mode") or "recommend"))
        except ValueError as exc:
            raise ValueError("invalid frozen operating mode") from exc

    def _policy_json(self, record: dict[str, Any]) -> dict[str, Any]:
        raw = record.get("management_policy_json")
        if isinstance(raw, str):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("invalid frozen management policy JSON") from exc
        else:
            value = raw
        if not isinstance(value, dict):
            raise ValueError("frozen management policy must be an object")
        return dict(value)

    def _policy_from_record(
        self, record: dict[str, Any]
    ) -> PositionManagementPolicy:
        value = self._policy_json(record)
        allowed = set(PositionManagementPolicy.__dataclass_fields__)
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(
                f"unknown frozen management policy fields: {sorted(unknown)}"
            )
        policy = PositionManagementPolicy(**value)
        if policy.policy_id != str(record.get("management_policy") or ""):
            raise ValueError("management policy id snapshot mismatch")
        if str(policy.version) != str(record.get("management_policy_version") or ""):
            raise ValueError("management policy version snapshot mismatch")
        return policy

    def _managed_position(
        self, record: dict[str, Any], position: OpenPositionSnapshot
    ) -> ManagedPosition:
        return ManagedPosition(
            execution_id=str(record["setup_id"]),
            position_identifier=int(record["position_identifier"]),
            symbol=str(record["symbol"]),
            side=str(record["side"]).lower(),
            actual_entry=float(record["actual_entry"]),
            initial_stop=float(record["initial_stop_price"]),
            current_stop=float(position.sl),
            current_take_profit=float(position.tp),
            initial_volume=float(record["initial_volume"]),
            remaining_volume=float(position.volume),
        )

    @staticmethod
    def _milestones_from_record(record: dict[str, Any]) -> MilestoneState:
        return MilestoneState(
            r1_reached=bool(record.get("r1_reached_at")),
            r2_reached=bool(record.get("r2_reached_at")),
            r3_reached=bool(record.get("r3_reached_at")),
            r1_protection_status=str(
                record.get("r1_protection_status") or BrokerActionStatus.NONE.value
            ),
            r2_protection_status=str(
                record.get("r2_protection_status") or BrokerActionStatus.NONE.value
            ),
            r3_close_status=str(
                record.get("r3_close_status") or BrokerActionStatus.NONE.value
            ),
        )

    def _initial_protection_postcondition(
        self, position: OpenPositionSnapshot, action: dict[str, Any]
    ) -> bool:
        payload = dict(action.get("payload") or {})
        try:
            target_stop = float(payload["target_stop"])
            target_tp = float(payload["target_tp"])
        except (KeyError, TypeError, ValueError):
            return False
        return self._stop_postcondition(position, target_stop) and self._price_equal(
            position.symbol, position.tp, target_tp
        )

    def _modify_postcondition(
        self, position: OpenPositionSnapshot, action: dict[str, Any]
    ) -> bool:
        payload = dict(action.get("payload") or {})
        try:
            target_stop = float(payload["target_stop"])
            tp_before = float(payload["take_profit_before"])
        except (KeyError, TypeError, ValueError):
            return False
        return self._stop_postcondition(position, target_stop) and self._price_equal(
            position.symbol, position.tp, tp_before
        )

    def _stop_postcondition(
        self, position: OpenPositionSnapshot, target_stop: float
    ) -> bool:
        tolerance = self._price_tolerance(position.symbol)
        if str(position.side).lower() == "buy":
            return position.sl > 0 and position.sl + tolerance >= target_stop
        return position.sl > 0 and position.sl - tolerance <= target_stop

    def _price_equal(self, symbol: str, left: float, right: float) -> bool:
        return abs(float(left) - float(right)) <= self._price_tolerance(symbol)

    def _price_tolerance(self, symbol: str) -> float:
        snapshot = self.adapter.load_symbol_snapshot(symbol)
        tick_size = float(snapshot.tick_size or snapshot.point or 0.0)
        if tick_size <= 0:
            raise ValueError("symbol tick size is unavailable for postcondition")
        return max(tick_size * 0.51, 1e-9)

    @staticmethod
    def _filled_repair_stop(record: dict[str, Any]) -> float:
        initial = float(record.get("initial_stop_price") or 0.0)
        current = float(record.get("current_stop_price") or 0.0)
        if initial <= 0:
            raise ValueError("FILLED execution is missing frozen initial stop")
        if current <= 0:
            return initial
        side = str(record.get("side") or "").lower()
        if side == "buy":
            return max(initial, current)
        if side == "sell":
            return min(initial, current)
        raise ValueError("FILLED execution side is invalid")

    @staticmethod
    def _has_frozen_initial_protection(record: dict[str, Any]) -> bool:
        return all(
            float(record.get(field) or 0.0) > 0
            for field in (
                "actual_entry",
                "initial_volume",
                "initial_stop_price",
                "initial_take_profit_price",
                "initial_risk_distance",
            )
        )

    @staticmethod
    def _projection_retry_seconds(attempt_count: int) -> float:
        """Bound durable projection retries while later actions keep moving."""

        exponent = max(0, min(int(attempt_count) - 1, 6))
        return float(min(300, 5 * (2**exponent)))

    @staticmethod
    def _valid_initial_stop(position: OpenPositionSnapshot) -> bool:
        if position.sl <= 0 or position.price_open <= 0:
            return False
        if str(position.side).lower() == "buy":
            return position.sl < position.price_open
        if str(position.side).lower() == "sell":
            return position.sl > position.price_open
        return False

    def _position_ready_for_confirmation(
        self, record: dict[str, Any], position: OpenPositionSnapshot
    ) -> bool:
        if not self._valid_initial_stop(position):
            return False
        side = str(position.side).lower()
        if side == "buy" and not position.tp > position.price_open:
            return False
        if side == "sell" and not 0 < position.tp < position.price_open:
            return False
        return self._stop_postcondition(
            position, float(record["stop_price"])
        ) and self._price_equal(
            position.symbol,
            position.tp,
            float(record["target_price"]),
        )

    @staticmethod
    def _position_identifier(position: OpenPositionSnapshot) -> int:
        identifier = int(position.position_identifier or 0)
        if identifier <= 0:
            raise ValueError("broker position_identifier must be positive")
        return identifier

    def _confirmation_action_key(self, record: dict[str, Any]) -> str | None:
        actions = self.store.position_actions(
            setup_id=str(record["setup_id"]), limit=100
        )
        preferred = (
            (_INITIAL_PROTECTION_ACTION, _OPEN_ACTION)
            if str(record.get("status")) == "UNPROTECTED"
            else (_OPEN_ACTION, _INITIAL_PROTECTION_ACTION)
        )
        for action_type in preferred:
            for action in reversed(actions):
                if (
                    str(action.get("action_type")) == action_type
                    and str(action.get("status"))
                    in {"PENDING", "SUBMITTED", "UNKNOWN", "CONFIRMED"}
                ):
                    return str(action["idempotency_key"])
        return None

    def _fence_submitted(
        self,
        action: dict[str, Any],
        *,
        broker_position_ticket: int | None = None,
    ) -> None:
        changed = self.store.mark_position_action_submitted(
            str(action["idempotency_key"]),
            lease_owner=self.lease_owner,
            broker_position_ticket=broker_position_ticket,
        )
        if not changed:
            raise RuntimeError("position action lost SUBMITTED fence")


def _optional_int(value: Any) -> int | None:
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
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _expected_position_end(record: dict[str, Any]) -> str:
    opened_at = _parse_iso(record.get("opened_at"))
    minutes = _optional_int(record.get("max_holding_minutes"))
    if opened_at is None or minutes is None:
        return "-"
    return (opened_at + timedelta(minutes=minutes)).astimezone(
        timezone.utc
    ).isoformat()


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


def _prediction_label(
    reason: str, target: float, stop: float, exit_price: float
) -> str:
    if reason == "take_profit" or abs(exit_price - target) <= 1e-6:
        return "sesuai target (predicted)"
    if reason == "stop_loss" or abs(exit_price - stop) <= 1e-6:
        return "sesuai batas risiko (predicted stop)"
    return "keluar di luar TP/SL awal (not predicted)"
