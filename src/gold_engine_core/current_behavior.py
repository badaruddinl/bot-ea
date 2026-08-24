from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

from .corpus import (
    BehaviorRecord,
    CorpusDomain,
    PlannedGeometry,
    StateTransition,
    load_corpus,
    write_corpus,
)
from .profile import ProfileManifest, canonical_sha256, load_named_profile

GeometryValues = tuple[str, str, str, str]
REVISED_RANGE_GEOMETRY: GeometryValues = ("4394.6", "4394.2", "4399.76", "4394.2")
REVISED_MOMENTUM_GEOMETRY: GeometryValues = ("4394.0", "4390.0", "4399.64", "4390.0")
REVISED_LATCHED_GEOMETRY: GeometryValues = ("4394.2", "4390.0", "4409.76", "4390.0")
BEAR_M1_GEOMETRY: GeometryValues = (
    "98.19",
    "100.60000000000001",
    "94.0",
    "100.60000000000001",
)
EXECUTION_BUY_GEOMETRY: GeometryValues = ("4400.0", "4390.0", "4420.0", "4390.0")
EXECUTION_SELL_GEOMETRY: GeometryValues = ("4400.0", "4410.0", "4380.0", "4410.0")


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    scenario_id: str
    source_ref: str
    from_state: str
    to_state: str
    decision: str
    reason: str
    execution_outcome: str
    geometry: GeometryValues | None = None

    @property
    def domain(self) -> CorpusDomain:
        value = self.scenario_id.split(".", 1)[0]
        if value not in {"revised", "bear", "execution"}:
            raise ValueError(f"unsupported scenario domain: {value}")
        return cast(CorpusDomain, value)


SCENARIOS: tuple[ScenarioDefinition, ...] = (
    ScenarioDefinition(
        "revised.no_setup",
        "tests/test_goldm_revised.py::test_missing_m5_setup_never_promotes",
        "IDLE",
        "WAIT",
        "WAIT",
        "M5_SETUP_UNAVAILABLE",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "revised.m5_setup",
        "tests/test_goldm_revised.py::test_m5_setup_persists_across_m1_bars_and_can_be_consumed",
        "IDLE",
        "WATCH",
        "WATCH",
        "M5_SETUP_ACCEPTED",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "revised.reinforcement",
        "tests/test_goldm_revised.py::test_same_side_confirmation_reinforces_without_resetting_watch",
        "WATCH",
        "WATCH",
        "WATCH",
        "SAME_SIDE_REINFORCEMENT",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "revised.opposite_cancellation",
        "tests/test_goldm_revised.py::test_opposite_m5_reversal_expires_buy_and_creates_sell_setup",
        "WATCH",
        "CANCELLED",
        "CANCELLED",
        "OPPOSITE_M5_SETUP_ACCEPTED",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "revised.expiry",
        "tests/test_goldm_revised.py::test_watch_expiry_emits_explicit_terminal_reason",
        "WATCH",
        "CANCELLED",
        "CANCELLED",
        "WATCH_WINDOW_EXPIRED",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "revised.m1_range",
        "tests/test_goldm_revised.py::test_buy_range_requires_repeated_rejections_and_enters",
        "WATCH",
        "ENTRY_READY",
        "ENTER",
        "STRONG_FIRST_CONFIRMATION",
        "SIGNAL_PLAN_CREATED",
        REVISED_RANGE_GEOMETRY,
    ),
    ScenarioDefinition(
        "revised.m1_momentum",
        "tests/test_goldm_revised.py::test_momentum_can_bypass_range_when_room_is_large",
        "WATCH",
        "ENTRY_READY",
        "ENTER",
        "MOMENTUM_ENTRY",
        "SIGNAL_PLAN_CREATED",
        REVISED_MOMENTUM_GEOMETRY,
    ),
    ScenarioDefinition(
        "revised.obstacle",
        "tests/test_goldm_revised.py::test_first_obstacle_below_one_r_remains_watch_until_hard_invalidation",
        "WATCH",
        "WATCH",
        "WATCH",
        "SOFT_FAIL_FIRST_OBSTACLE_ROOM",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "revised.psychological_context",
        "tests/test_goldm_revised.py::test_sub_one_r_psychological_obstacle_remains_watch",
        "WATCH",
        "WATCH",
        "WATCH",
        "PSYCH_10_OBSTACLE",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "revised.supply_demand_context",
        "tests/test_goldm_revised.py::test_nearest_supply_proximal_precedes_swing_high_and_psychology",
        "WATCH",
        "WATCH",
        "WATCH",
        "M5_SUPPLY_PROXIMAL",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "revised.entry_ready",
        "tests/test_goldm_revised.py::test_latched_strong_confirmation_can_enter_on_later_retest",
        "WATCH",
        "ENTRY_READY",
        "ENTER",
        "LATCHED_CONFIRMATION_RETEST",
        "SIGNAL_PLAN_CREATED",
        REVISED_LATCHED_GEOMETRY,
    ),
    ScenarioDefinition(
        "revised.restart",
        "src/goldm_revised/storage.py::RevisedStore",
        "WATCH",
        "WATCH",
        "RECOVER",
        "BASELINE_STORE_REOPEN_WITHOUT_CERTIFIED_WATCH_PARITY",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "bear.m15_setup",
        "tests/test_goldm_bear_standalone.py::test_image_like_pullback_rejection_emits_sell",
        "IDLE",
        "WATCH_H1",
        "WATCH",
        "M15_SELL_SETUP",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "bear.h1_pass_reject",
        "tests/test_goldm_bear_v4.py::test_v4_h1_gate_uses_falling_closed_sma",
        "WATCH_H1",
        "WATCH_M5",
        "WATCH",
        "H1_FALLING_CLOSED_SMA",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "bear.m5_touch",
        "tests/test_goldm_bear_standalone.py::test_touch_without_rejection_is_watch_not_sell",
        "WATCH_M5",
        "WATCH_M5",
        "WATCH",
        "M5_TOUCH_WITHOUT_REJECTION",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "bear.m5_rejection",
        "tests/test_goldm_bear_v4.py::test_v4_m5_strong_failed_breakout_arms_setup",
        "WATCH_M5",
        "WATCH_M1",
        "WATCH",
        "M5_REJECTION_ARMED",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "bear.m5_acceptance",
        "tests/test_goldm_bear_v4.py::test_v4_m5_acceptance_cancels_setup",
        "WATCH_M5",
        "CANCELLED",
        "CANCELLED",
        "M5_ACCEPTANCE",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "bear.m1_confirmation",
        "tests/test_goldm_bear_v4.py::test_v4_m1_retest_requires_micro_break",
        "WATCH_M1",
        "ENTRY_READY",
        "SELL",
        "M1_MICRO_BREAK",
        "SIGNAL_PLAN_CREATED",
        BEAR_M1_GEOMETRY,
    ),
    ScenarioDefinition(
        "bear.expiry",
        "src/goldm_bear/multitimeframe.py::_arm_on_m5",
        "WATCH_M5",
        "EXPIRED",
        "EXPIRED",
        "M5_WINDOW_EXPIRED",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "bear.entry_ready",
        "tests/test_goldm_bear_standalone.py::test_broker_failed_breakout_waits_then_sells_confirmation",
        "WATCH_M1",
        "ENTRY_READY",
        "SELL",
        "BEAR_CONFIRMATION",
        "SIGNAL_PLAN_CREATED",
        BEAR_M1_GEOMETRY,
    ),
    ScenarioDefinition(
        "bear.restart",
        "src/goldm_bear/multitimeframe.py::BearMultiTimeframeReplay",
        "WATCH_M1",
        "IDLE",
        "REPLAY",
        "BASELINE_RECOMPUTES_HISTORY_WITHOUT_INCREMENTAL_STATE",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "execution.fresh_quote",
        "tests/test_mt5_execution_runtime.py::test_execute_live_refreshes_price_before_revalidation_and_send",
        "ENTRY_READY",
        "ORDER_SENT",
        "SEND",
        "CURRENT_TICK_USED",
        "BROKER_REQUESTED",
        EXECUTION_BUY_GEOMETRY,
    ),
    ScenarioDefinition(
        "execution.stale_quote",
        "src/gold_portfolio/models.py::SignalPlan",
        "ENTRY_READY",
        "ORDER_SENT",
        "SEND",
        "BASELINE_SIGNAL_PLAN_HAS_NO_VALID_UNTIL",
        "UNGUARDED_BASELINE",
        EXECUTION_BUY_GEOMETRY,
    ),
    ScenarioDefinition(
        "execution.drift",
        "tests/test_gold_portfolio_final.py::test_real_executor_reads_shared_balance_and_sends_one_checked_order",
        "ENTRY_READY",
        "ORDER_SENT",
        "SEND",
        "BASELINE_SHIFTS_GEOMETRY_TO_CURRENT_QUOTE",
        "EXECUTED_WITH_QUOTE_CHASING",
        EXECUTION_BUY_GEOMETRY,
    ),
    ScenarioDefinition(
        "execution.spread",
        "src/gold_portfolio/models.py::SignalPlan",
        "ENTRY_READY",
        "ORDER_SENT",
        "SEND",
        "BASELINE_SIGNAL_PLAN_HAS_NO_SPREAD_CONTRACT",
        "UNGUARDED_BASELINE",
        EXECUTION_BUY_GEOMETRY,
    ),
    ScenarioDefinition(
        "execution.invalidation",
        "src/gold_portfolio/models.py::SignalPlan",
        "ENTRY_READY",
        "ORDER_SENT",
        "SEND",
        "BASELINE_SIGNAL_PLAN_HAS_NO_INVALIDATION_FIELD",
        "UNGUARDED_BASELINE",
        EXECUTION_BUY_GEOMETRY,
    ),
    ScenarioDefinition(
        "execution.duplicate",
        "tests/test_goldm_trade_lifecycle.py::test_duplicate_lineage_field_is_not_executable",
        "ENTRY_READY",
        "BLOCKED",
        "REJECT",
        "DUPLICATE_LINEAGE_FIELD",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "execution.max_positions",
        "src/gold_portfolio/mt5_session.py::execute",
        "ENTRY_READY",
        "BLOCKED",
        "REJECT",
        "MAXIMUM_MANAGED_POSITIONS_REACHED",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "execution.lot_normalization",
        "tests/test_gold_portfolio_final.py::test_goldi_demo_executor_places_order_at_locked_adaptive_lot",
        "ENTRY_READY",
        "ORDER_SENT",
        "SEND",
        "BALANCE_TIER_LOT_SELECTED",
        "BROKER_REQUESTED",
        EXECUTION_SELL_GEOMETRY,
    ),
    ScenarioDefinition(
        "execution.wrong_identity",
        "tests/test_goldm_trade_lifecycle.py::test_noncanonical_symbol_is_rejected_before_any_broker_send",
        "ENTRY_READY",
        "BLOCKED",
        "REJECT",
        "WRONG_ACCOUNT_MODE_SYMBOL_PROFILE",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "execution.broker_check_reject",
        "src/gold_portfolio/mt5_session.py::execute",
        "ORDER_CHECK",
        "REJECTED",
        "REJECT",
        "REJECTED_CHECK",
        "NO_ORDER",
    ),
    ScenarioDefinition(
        "execution.broker_send_reject",
        "tests/test_mock_mt5_adapter.py::test_live_adapter_rejects_non_done_retcode_even_if_postcondition_is_met",
        "ORDER_SENT",
        "REJECTED",
        "REJECT",
        "REJECTED_SEND",
        "BROKER_REJECTED",
        EXECUTION_BUY_GEOMETRY,
    ),
    ScenarioDefinition(
        "execution.fill",
        "tests/test_goldm_trade_lifecycle.py::test_exact_protected_broker_position_is_confirmed_filled",
        "ORDER_SENT",
        "FILLED",
        "FILLED",
        "EXACT_PROTECTED_POSITION_CONFIRMED",
        "FILLED",
        EXECUTION_BUY_GEOMETRY,
    ),
    ScenarioDefinition(
        "execution.restart",
        "tests/test_goldm_store_migrations.py::test_terminal_event_atomically_cancels_pending_open_and_replays_after_restart",
        "PENDING_OPEN",
        "CANCELLED",
        "RECOVER",
        "TERMINAL_EVENT_REPLAY_SAFE",
        "NO_DUPLICATE_ORDER",
    ),
)


def _source_evidence(repository_root: Path, source_ref: str) -> tuple[str, str]:
    try:
        relative_path, symbol = source_ref.split("::", 1)
    except ValueError as exc:
        raise ValueError(f"invalid source_ref: {source_ref}") from exc
    source_path = (repository_root / relative_path).resolve()
    root = repository_root.resolve()
    try:
        source_path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"source_ref escapes repository: {source_ref}") from exc
    source = source_path.read_bytes().replace(b"\r\n", b"\n")
    tree = ast.parse(source.decode("utf-8"), filename=str(source_path))
    if not any(
        isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == symbol
        for node in ast.walk(tree)
    ):
        raise ValueError(f"source symbol not found: {source_ref}")
    return hashlib.sha256(source).hexdigest(), relative_path


def _geometry(values: GeometryValues | None) -> PlannedGeometry:
    if values is not None:
        entry, stop, target, invalidation = values
        return PlannedGeometry.from_payload(
            {
                "entry": entry,
                "stop": stop,
                "target": target,
                "invalidation": invalidation,
            }
        )
    return PlannedGeometry(None, None, None, None)


def _record(
    repository_root: Path,
    profile: ProfileManifest,
    definition: ScenarioDefinition,
    index: int,
    pinned: dict[str, BehaviorRecord],
) -> BehaviorRecord:
    prior = pinned.get(definition.scenario_id)
    if prior is not None and prior.source_ref == definition.source_ref:
        source_sha256 = prior.source_sha256
    else:
        source_sha256, _ = _source_evidence(repository_root, definition.source_ref)
    available_at = datetime(2026, 8, 18, 7, 0, tzinfo=timezone(timedelta(hours=3))) + timedelta(
        minutes=index
    )
    input_fingerprint = canonical_sha256(
        {
            "available_at": available_at.isoformat(),
            "closed_bars_only": definition.domain != "execution",
            "profile_fingerprint": profile.fingerprint,
            "profile_id": profile.profile_id,
            "scenario_id": definition.scenario_id,
            "source_ref": definition.source_ref,
            "source_sha256": source_sha256,
        }
    )
    return BehaviorRecord(
        schema_version=1,
        profile_id=profile.profile_id,
        profile_fingerprint=profile.fingerprint,
        scenario_id=definition.scenario_id,
        domain=definition.domain,
        input_fingerprint=input_fingerprint,
        available_at=available_at,
        setup_id=f"{profile.profile_id}:{definition.scenario_id}:{available_at.isoformat()}",
        state_transitions=(
            StateTransition(available_at, definition.from_state, definition.to_state),
        ),
        decision=definition.decision,
        planned_geometry=_geometry(definition.geometry),
        reason=definition.reason,
        execution_outcome=definition.execution_outcome,
        source_ref=definition.source_ref,
        source_sha256=source_sha256,
        closed_bars_only=definition.domain != "execution",
    )


def build_current_behavior_corpus(
    repository_root: Path, *, output_root: Path | None = None
) -> dict[str, str]:
    destination = output_root or repository_root / "corpus" / "current_behavior"
    results: dict[str, str] = {}
    for profile_id in ("GOLDI", "GOLDM"):
        profile = load_named_profile(repository_root, profile_id)
        baseline_path = repository_root / "corpus" / "current_behavior" / f"{profile_id}.jsonl"
        pinned = (
            {record.scenario_id: record for record in load_corpus(baseline_path)}
            if baseline_path.is_file()
            else {}
        )
        records = tuple(
            _record(repository_root, profile, definition, index, pinned)
            for index, definition in enumerate(SCENARIOS)
        )
        results[profile_id] = write_corpus(destination / f"{profile_id}.jsonl", records)
    return results
