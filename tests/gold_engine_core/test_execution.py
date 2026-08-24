from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from gold_engine_core import (
    BrokerCheck,
    ExecutionAccount,
    ExecutionContext,
    ExecutionContractError,
    ExecutionExposure,
    ExecutionPolicy,
    ExecutionReject,
    ExecutionSymbol,
    ExecutionValidation,
    ProfileConfig,
    Side,
    SignalPlan,
    Tick,
    load_execution_policy,
    load_named_profile,
    validate_execution,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=3))
READY = datetime(2026, 8, 21, 10, 0, tzinfo=TZ)
D = Decimal


def profile(profile_id: str) -> ProfileConfig:
    return ProfileConfig.from_manifest(
        load_named_profile(REPOSITORY_ROOT, profile_id), tick_size=D("0.01")
    )


def policy(profile_id: str) -> ExecutionPolicy:
    return load_execution_policy(
        REPOSITORY_ROOT / "config" / "execution_profiles" / f"{profile_id}.json"
    )


def plan(profile_id: str, *, side: Side = Side.BUY) -> SignalPlan:
    config = profile(profile_id)
    rule = policy(profile_id)
    if side is Side.BUY:
        entry, stop, target, invalidation = map(D, ("4400", "4390", "4425", "4390"))
    else:
        entry, stop, target, invalidation = map(D, ("4400", "4410", "4380", "4410"))
    demo = profile_id == "GOLDI"
    return SignalPlan(
        profile_id=profile_id,
        profile_version=config.profile_version,
        profile_fingerprint=config.manifest_fingerprint,
        strategy_id="GOLDM_REVISED" if side is Side.BUY else "GOLDM_BEAR",
        strategy_version="1.0.0",
        component="revised" if side is Side.BUY else "bear",
        reason="CONFIRMED",
        setup_id=f"{profile_id}:setup:1",
        signal_id=f"{profile_id}:signal:1",
        side=side,
        symbol=config.symbol,
        setup_created_at=READY - timedelta(minutes=2),
        entry_ready_at=READY,
        valid_until=READY + timedelta(seconds=rule.maximum_signal_age_seconds),
        planned_entry=entry,
        stop=stop,
        target=target,
        planned_risk=abs(entry - stop),
        invalidation=invalidation,
        maximum_spread=rule.maximum_spread,
        minimum_executable_rr=D("1.5") if side is Side.BUY else D("0.70"),
        tick_size=config.tick_size,
        volume=D("0.01") if demo else D("0.1"),
        account_login=123456 if demo else 654321,
        account_server="GOLDI-DEMO" if demo else "GOLDM-SAFE-DEMO",
        trade_mode="demo",
        terminal_identity=config.terminal_identity,
        magic=config.magic,
    )


def context(profile_id: str, *, side: Side = Side.BUY) -> ExecutionContext:
    config = profile(profile_id)
    value = plan(profile_id, side=side)
    if side is Side.BUY:
        bid, ask = D("4399.95"), D("4400.05")
    else:
        bid, ask = D("4399.95"), D("4400.05")
    return ExecutionContext(
        quote=Tick(READY + timedelta(seconds=1), bid, ask, volume=1.0),
        account=ExecutionAccount(
            value.account_login,
            value.account_server,
            value.trade_mode,
            value.terminal_identity,
            D("100"),
        ),
        symbol=ExecutionSymbol(
            config.symbol,
            D("0.01"),
            D("0.01"),
            D("0.01") if profile_id == "GOLDI" else D("0.1"),
            D("50") if profile_id == "GOLDI" else D("100"),
            D("0.01") if profile_id == "GOLDI" else D("0.1"),
            0,
            0,
            True,
        ),
        exposure=ExecutionExposure(0, D("0")),
        required_margin=D("1"),
        broker_check=BrokerCheck(True, 0, "ok"),
        engineering_demo=profile_id == "GOLDM",
    )


@pytest.mark.parametrize("profile_id", ["GOLDI", "GOLDM"])
@pytest.mark.parametrize("side", [Side.BUY, Side.SELL])
def test_valid_execution_keeps_structural_geometry_and_uses_current_quote(
    profile_id: str,
    side: Side,
) -> None:
    value = plan(profile_id, side=side)
    result = validate_execution(
        value, profile(profile_id), policy(profile_id), context(profile_id, side=side)
    )

    assert result.allowed is True
    assert result.reasons == ()
    assert result.order is not None
    assert result.order.stop == value.planned_stop
    assert result.order.target == value.planned_target
    assert result.order.price == (
        context(profile_id, side=side).quote.ask
        if side is Side.BUY
        else context(profile_id, side=side).quote.bid
    )
    assert result.actual_rr >= value.minimum_executable_rr
    assert result.adverse_drift_r <= result.maximum_adverse_drift_r
    assert result.quote_bid == context(profile_id, side=side).quote.bid
    assert result.quote_ask == context(profile_id, side=side).quote.ask


def assert_rejected(
    expected: ExecutionReject,
    value: SignalPlan,
    execution_context: ExecutionContext,
    *,
    execution_policy: ExecutionPolicy | None = None,
) -> None:
    result = validate_execution(
        value,
        profile(value.profile_id if value.profile_id in {"GOLDI", "GOLDM"} else "GOLDI"),
        execution_policy or policy("GOLDI"),
        execution_context,
    )
    assert result.allowed is False
    assert result.order is None
    assert expected in result.reasons


def test_profile_policy_age_drift_spread_and_invalidation_guards() -> None:
    value = plan("GOLDI")
    base = context("GOLDI")
    assert_rejected(ExecutionReject.PROFILE, replace(value, profile_fingerprint="0" * 64), base)
    assert_rejected(
        ExecutionReject.POLICY,
        value,
        base,
        execution_policy=policy("GOLDM"),
    )
    assert_rejected(
        ExecutionReject.AGE,
        value,
        replace(base, quote=replace(base.quote, time=value.valid_until + timedelta(seconds=1))),
    )
    assert_rejected(
        ExecutionReject.DRIFT,
        value,
        replace(base, quote=Tick(base.quote.time, D("4404.00"), D("4404.01"))),
    )
    assert_rejected(
        ExecutionReject.SPREAD,
        value,
        replace(base, quote=Tick(base.quote.time, D("4399.00"), D("4400.00"))),
    )
    assert_rejected(
        ExecutionReject.INVALIDATION,
        value,
        replace(base, quote=Tick(base.quote.time, D("4388.90"), D("4389.00"))),
    )


def test_buy_spread_is_guarded_separately_from_dynamic_rr() -> None:
    value = replace(
        plan("GOLDI"),
        stop=D("4399.00"),
        planned_risk=D("1.00"),
        invalidation=D("4399.00"),
    )
    base = context("GOLDI")
    spread_only = replace(
        base,
        quote=Tick(base.quote.time, D("4400.00"), D("4400.20")),
    )

    result = validate_execution(value, profile("GOLDI"), policy("GOLDI"), spread_only)

    assert result.allowed is True
    assert result.adverse_drift_r == D("0.20")
    assert result.actual_rr > value.minimum_executable_rr
    assert result.order is not None
    assert result.order.price == D("4400.20")


def test_adverse_buy_movement_is_allowed_until_strategy_rr_floor() -> None:
    value = replace(
        plan("GOLDI"),
        stop=D("4399.00"),
        planned_risk=D("1.00"),
        invalidation=D("4399.00"),
    )
    base = context("GOLDI")
    moved = replace(
        base,
        quote=Tick(base.quote.time, D("4403.70"), D("4403.90")),
    )

    result = validate_execution(value, profile("GOLDI"), policy("GOLDI"), moved)
    assert result.allowed is True
    assert result.actual_rr >= value.minimum_executable_rr

    stale = replace(
        base,
        quote=Tick(base.quote.time, D("4414.80"), D("4415.00")),
    )
    assert_rejected(ExecutionReject.DRIFT, value, stale)


def test_dynamic_rr_guard_is_profile_symmetric() -> None:
    value = replace(
        plan("GOLDM"),
        stop=D("4399.00"),
        planned_risk=D("1.00"),
        invalidation=D("4399.00"),
    )
    base = context("GOLDM")
    spread_only = replace(
        base,
        quote=Tick(base.quote.time, D("4400.00"), D("4400.20")),
    )

    result = validate_execution(value, profile("GOLDM"), policy("GOLDM"), spread_only)
    assert result.allowed is True
    assert result.actual_rr >= value.minimum_executable_rr


def test_august_24_goldi_momentum_regression_accepts_valid_realtime_quote() -> None:
    value = replace(
        plan("GOLDI"),
        planned_entry=D("4661.78"),
        stop=D("4660.87"),
        target=D("4669.39"),
        planned_risk=D("0.91"),
        invalidation=D("4660.87"),
        minimum_executable_rr=D("1.5"),
    )
    base = context("GOLDI")
    realtime = replace(
        base,
        quote=Tick(base.quote.time, D("4661.77"), D("4661.78")),
    )

    result = validate_execution(value, profile("GOLDI"), policy("GOLDI"), realtime)

    assert result.allowed is True
    assert ExecutionReject.DRIFT not in result.reasons
    assert result.order is not None
    assert result.order.price == D("4661.78")
    assert result.actual_rr == D("7.61") / D("0.91")


def test_identity_exposure_margin_duplicate_and_broker_guards() -> None:
    value = plan("GOLDI")
    base = context("GOLDI")
    assert_rejected(
        ExecutionReject.ACCOUNT,
        value,
        replace(base, account=replace(base.account, login=999)),
    )
    assert_rejected(
        ExecutionReject.SERVER_MODE,
        value,
        replace(base, account=replace(base.account, server="OTHER")),
    )
    assert_rejected(
        ExecutionReject.TERMINAL,
        value,
        replace(base, account=replace(base.account, terminal_identity="OTHER")),
    )
    assert_rejected(
        ExecutionReject.SYMBOL,
        value,
        replace(base, symbol=replace(base.symbol, symbol="GOLDm#")),
    )
    assert_rejected(ExecutionReject.MAGIC, replace(value, magic=999), base)
    assert_rejected(
        ExecutionReject.POSITION_COUNT,
        value,
        replace(base, exposure=ExecutionExposure(profile("GOLDI").max_positions, D("0"))),
    )
    assert_rejected(
        ExecutionReject.TOTAL_VOLUME,
        value,
        replace(base, exposure=ExecutionExposure(0, profile("GOLDI").max_total_lot)),
    )
    assert_rejected(
        ExecutionReject.FREE_MARGIN,
        value,
        replace(base, account=replace(base.account, free_margin=D("0"))),
    )
    assert_rejected(
        ExecutionReject.DUPLICATE,
        value,
        replace(base, exposure=ExecutionExposure(0, D("0"), frozenset({value.signal_id}))),
    )
    assert_rejected(
        ExecutionReject.BROKER_CHECK,
        value,
        replace(base, broker_check=BrokerCheck(False, 10030, "rejected")),
    )


def test_broker_constraints_and_executable_geometry_reject_without_quote_chasing() -> None:
    value = plan("GOLDI")
    base = context("GOLDI")
    assert_rejected(
        ExecutionReject.BROKER_CONSTRAINT,
        value,
        replace(base, symbol=replace(base.symbol, trade_enabled=False)),
    )
    assert_rejected(
        ExecutionReject.BROKER_CONSTRAINT,
        replace(value, volume=D("0.015")),
        base,
    )
    assert_rejected(
        ExecutionReject.GEOMETRY,
        value,
        replace(base, quote=Tick(base.quote.time, D("4425.00"), D("4425.01"))),
    )

    within_drift = replace(
        base,
        quote=Tick(base.quote.time, D("4400.99"), D("4401.00")),
    )
    result = validate_execution(value, profile("GOLDI"), policy("GOLDI"), within_drift)
    assert result.allowed is True
    assert result.order is not None
    assert result.order.stop == D("4390")
    assert result.order.target == D("4425")


def test_execution_policy_is_canonical_profile_bound_and_swap_rejected(tmp_path: Path) -> None:
    goldi = policy("GOLDI")
    goldm = policy("GOLDM")
    assert goldi.profile_fingerprint == profile("GOLDI").manifest_fingerprint
    assert goldm.profile_fingerprint == profile("GOLDM").manifest_fingerprint
    assert goldi.fingerprint != goldm.fingerprint

    path = tmp_path / "GOLDI.json"
    payload = goldi.to_payload()
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.with_suffix(".sha256").write_text(f"{'0' * 64}  GOLDI.json\n", encoding="ascii")
    with pytest.raises(ExecutionContractError, match="checksum"):
        load_execution_policy(path)

    swapped = replace(goldi, profile_fingerprint=goldm.profile_fingerprint)
    result = validate_execution(
        plan("GOLDI"),
        profile("GOLDI"),
        swapped,
        context("GOLDI"),
    )
    assert ExecutionReject.POLICY in result.reasons


def test_execution_contract_boundaries_are_strict() -> None:
    with pytest.raises(ExecutionContractError):
        ExecutionPolicy(2, "GOLDI", "short", "1", D("0.6"), 60)
    with pytest.raises(ExecutionContractError):
        ExecutionExposure(-1, D("0"))
    with pytest.raises(ExecutionContractError):
        ExecutionValidation(
            allowed=True,
            reasons=(),
            adverse_drift_r=D("0"),
            maximum_adverse_drift_r=D("1"),
            executable_price=D("1"),
            quote_bid=D("1"),
            quote_ask=D("1"),
            actual_risk=D("1"),
            actual_reward=D("1"),
            actual_rr=D("1"),
            order=None,
        )
