from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import cast

from .contracts import ProfileConfig, Side, SignalPlan, Tick
from .profile import TradeMode, canonical_json, canonical_sha256


class ExecutionContractError(ValueError):
    """Raised when execution inputs violate a durable boundary contract."""


class ExecutionReject(StrEnum):
    PROFILE = "PROFILE_MISMATCH"
    POLICY = "POLICY_MISMATCH"
    AGE = "SIGNAL_AGE_INVALID"
    DRIFT = "ENTRY_DRIFT_EXCEEDED"
    SPREAD = "SPREAD_EXCEEDED"
    INVALIDATION = "SETUP_INVALIDATED"
    ACCOUNT = "ACCOUNT_MISMATCH"
    SERVER_MODE = "SERVER_MODE_MISMATCH"
    TERMINAL = "TERMINAL_MISMATCH"
    SYMBOL = "SYMBOL_MISMATCH"
    MAGIC = "MAGIC_MISMATCH"
    POSITION_COUNT = "POSITION_COUNT_EXCEEDED"
    TOTAL_VOLUME = "TOTAL_VOLUME_EXCEEDED"
    FREE_MARGIN = "FREE_MARGIN_INSUFFICIENT"
    BROKER_CONSTRAINT = "BROKER_CONSTRAINT_REJECTED"
    DUPLICATE = "DUPLICATE_SIGNAL"
    GEOMETRY = "EXECUTABLE_GEOMETRY_INVALID"
    BROKER_CHECK = "BROKER_CHECK_REJECTED"


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    schema_version: int
    profile_id: str
    profile_fingerprint: str
    policy_version: str
    maximum_drift_r: Decimal
    maximum_spread: Decimal
    maximum_signal_age_seconds: int

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ExecutionContractError("execution policy schema_version must equal 1")
        if not self.profile_id or not self.policy_version:
            raise ExecutionContractError("execution policy identity is required")
        if len(self.profile_fingerprint) != 64:
            raise ExecutionContractError("execution policy profile fingerprint is invalid")
        _positive(self.maximum_drift_r, "policy.maximum_drift_r", allow_zero=True)
        _positive(self.maximum_spread, "policy.maximum_spread")
        if self.maximum_signal_age_seconds < 1:
            raise ExecutionContractError("maximum_signal_age_seconds must be positive")

    @classmethod
    def from_payload(cls, payload: object) -> ExecutionPolicy:
        data = _mapping(payload, "execution_policy")
        expected = {
            "maximum_drift_r",
            "maximum_signal_age_seconds",
            "maximum_spread",
            "policy_version",
            "profile_fingerprint",
            "profile_id",
            "schema_version",
        }
        if set(data) != expected:
            raise ExecutionContractError(f"execution policy keys must be {sorted(expected)}")
        schema = data["schema_version"]
        age = data["maximum_signal_age_seconds"]
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise ExecutionContractError("schema_version must be an integer")
        if isinstance(age, bool) or not isinstance(age, int):
            raise ExecutionContractError("maximum_signal_age_seconds must be an integer")
        return cls(
            schema_version=schema,
            profile_id=_string(data["profile_id"], "profile_id"),
            profile_fingerprint=_string(data["profile_fingerprint"], "profile_fingerprint"),
            policy_version=_string(data["policy_version"], "policy_version"),
            maximum_drift_r=_decimal(data["maximum_drift_r"], "maximum_drift_r"),
            maximum_spread=_decimal(data["maximum_spread"], "maximum_spread"),
            maximum_signal_age_seconds=age,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "maximum_drift_r": str(self.maximum_drift_r),
            "maximum_signal_age_seconds": self.maximum_signal_age_seconds,
            "maximum_spread": str(self.maximum_spread),
            "policy_version": self.policy_version,
            "profile_fingerprint": self.profile_fingerprint,
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
        }

    @property
    def fingerprint(self) -> str:
        return str(canonical_sha256(self.to_payload()))


@dataclass(frozen=True, slots=True)
class ExecutionAccount:
    login: int
    server: str
    trade_mode: TradeMode
    terminal_identity: str
    free_margin: Decimal

    def __post_init__(self) -> None:
        if self.login <= 0 or not self.server or not self.terminal_identity:
            raise ExecutionContractError("execution account identity is invalid")
        _positive(self.free_margin, "account.free_margin", allow_zero=True)


@dataclass(frozen=True, slots=True)
class ExecutionSymbol:
    symbol: str
    tick_size: Decimal
    point: Decimal
    volume_minimum: Decimal
    volume_maximum: Decimal
    volume_step: Decimal
    stops_level_points: int
    freeze_level_points: int
    trade_enabled: bool

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ExecutionContractError("execution symbol is required")
        for name, value in (
            ("tick_size", self.tick_size),
            ("point", self.point),
            ("volume_minimum", self.volume_minimum),
            ("volume_maximum", self.volume_maximum),
            ("volume_step", self.volume_step),
        ):
            _positive(value, f"symbol.{name}")
        if self.volume_maximum < self.volume_minimum:
            raise ExecutionContractError("symbol volume range is inverted")
        if self.stops_level_points < 0 or self.freeze_level_points < 0:
            raise ExecutionContractError("symbol stop/freeze levels cannot be negative")


@dataclass(frozen=True, slots=True)
class ExecutionExposure:
    position_count: int
    total_volume: Decimal
    active_signal_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.position_count < 0:
            raise ExecutionContractError("position_count cannot be negative")
        _positive(self.total_volume, "exposure.total_volume", allow_zero=True)


@dataclass(frozen=True, slots=True)
class BrokerCheck:
    allowed: bool
    retcode: int
    comment: str


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    quote: Tick
    account: ExecutionAccount
    symbol: ExecutionSymbol
    exposure: ExecutionExposure
    required_margin: Decimal
    broker_check: BrokerCheck
    engineering_demo: bool = False

    def __post_init__(self) -> None:
        _positive(self.required_margin, "required_margin")


@dataclass(frozen=True, slots=True)
class ExecutionOrder:
    signal_id: str
    symbol: str
    side: Side
    volume: Decimal
    price: Decimal
    stop: Decimal
    target: Decimal
    magic: int
    deviation_points: int


@dataclass(frozen=True, slots=True)
class ExecutionValidation:
    allowed: bool
    reasons: tuple[ExecutionReject, ...]
    drift_r: Decimal
    executable_price: Decimal
    order: ExecutionOrder | None = None

    def __post_init__(self) -> None:
        if self.allowed != (not self.reasons and self.order is not None):
            raise ExecutionContractError("execution validation result is inconsistent")


def validate_execution(
    plan: SignalPlan,
    profile: ProfileConfig,
    policy: ExecutionPolicy,
    context: ExecutionContext,
) -> ExecutionValidation:
    reasons: list[ExecutionReject] = []
    executable = context.quote.ask if plan.side is Side.BUY else context.quote.bid
    # Strategy entries are derived from MT5 bars, whose reference price is Bid.
    # Spread has its own independent guard and must not be counted again as
    # market drift for BUY orders (which execute at Ask).
    drift_reference = context.quote.bid if plan.profile_id == "GOLDI" else executable
    drift_r = abs(drift_reference - plan.planned_entry) / plan.planned_risk

    if (
        plan.profile_id != profile.profile_id
        or plan.profile_version != profile.profile_version
        or plan.profile_fingerprint != profile.manifest_fingerprint
    ):
        reasons.append(ExecutionReject.PROFILE)
    if (
        policy.profile_id != profile.profile_id
        or policy.profile_fingerprint != profile.manifest_fingerprint
        or plan.maximum_drift_r != policy.maximum_drift_r
        or plan.maximum_spread != policy.maximum_spread
    ):
        reasons.append(ExecutionReject.POLICY)
    maximum_age = timedelta(seconds=policy.maximum_signal_age_seconds)
    if (
        context.quote.time < plan.entry_ready_at
        or context.quote.time > plan.valid_until
        or plan.valid_until - plan.entry_ready_at > maximum_age
    ):
        reasons.append(ExecutionReject.AGE)
    if drift_r > policy.maximum_drift_r:
        reasons.append(ExecutionReject.DRIFT)
    if context.quote.spread > policy.maximum_spread:
        reasons.append(ExecutionReject.SPREAD)
    if (plan.side is Side.BUY and executable <= plan.invalidation) or (
        plan.side is Side.SELL and executable >= plan.invalidation
    ):
        reasons.append(ExecutionReject.INVALIDATION)
    if context.account.login != plan.account_login:
        reasons.append(ExecutionReject.ACCOUNT)
    expected_mode = (
        profile.engineering_trade_mode if context.engineering_demo else profile.expected_trade_mode
    )
    if (
        context.account.server != plan.account_server
        or context.account.trade_mode != plan.trade_mode
        or plan.trade_mode != expected_mode
    ):
        reasons.append(ExecutionReject.SERVER_MODE)
    if context.account.terminal_identity != plan.terminal_identity:
        reasons.append(ExecutionReject.TERMINAL)
    if context.symbol.symbol != plan.symbol or plan.symbol != profile.symbol:
        reasons.append(ExecutionReject.SYMBOL)
    if plan.magic != profile.magic:
        reasons.append(ExecutionReject.MAGIC)
    if context.exposure.position_count >= profile.max_positions:
        reasons.append(ExecutionReject.POSITION_COUNT)
    if context.exposure.total_volume + plan.volume > profile.max_total_lot:
        reasons.append(ExecutionReject.TOTAL_VOLUME)
    if context.account.free_margin < context.required_margin:
        reasons.append(ExecutionReject.FREE_MARGIN)
    if plan.signal_id in context.exposure.active_signal_ids:
        reasons.append(ExecutionReject.DUPLICATE)

    minimum_distance = (
        max(
            context.symbol.stops_level_points,
            context.symbol.freeze_level_points,
        )
        * context.symbol.point
    )
    constraints_ok = bool(
        context.symbol.trade_enabled
        and context.symbol.tick_size == profile.tick_size == plan.tick_size
        and context.symbol.volume_minimum <= plan.volume <= context.symbol.volume_maximum
        and _aligned(plan.volume, context.symbol.volume_step)
        and _aligned(plan.planned_entry, context.symbol.tick_size)
        and _aligned(plan.planned_stop, context.symbol.tick_size)
        and _aligned(plan.planned_target, context.symbol.tick_size)
        and abs(executable - plan.planned_stop) >= minimum_distance
        and abs(plan.planned_target - executable) >= minimum_distance
    )
    if not constraints_ok:
        reasons.append(ExecutionReject.BROKER_CONSTRAINT)

    geometry_ok = (
        plan.planned_stop < executable < plan.planned_target
        if plan.side is Side.BUY
        else plan.planned_target < executable < plan.planned_stop
    )
    if not geometry_ok:
        reasons.append(ExecutionReject.GEOMETRY)
    if not context.broker_check.allowed:
        reasons.append(ExecutionReject.BROKER_CHECK)

    unique_reasons = tuple(dict.fromkeys(reasons))
    order = (
        None
        if unique_reasons
        else ExecutionOrder(
            signal_id=plan.signal_id,
            symbol=plan.symbol,
            side=plan.side,
            volume=plan.volume,
            price=executable,
            stop=plan.planned_stop,
            target=plan.planned_target,
            magic=plan.magic,
            deviation_points=profile.deviation_points,
        )
    )
    return ExecutionValidation(
        allowed=not unique_reasons,
        reasons=unique_reasons,
        drift_r=drift_r,
        executable_price=executable,
        order=order,
    )


def load_execution_policy(path: Path) -> ExecutionPolicy:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionContractError(f"cannot read execution policy: {path}") from exc
    policy = ExecutionPolicy.from_payload(payload)
    if canonical_json(policy.to_payload()) != canonical_json(payload):
        raise ExecutionContractError("execution policy is not canonical")
    checksum = path.with_suffix(".sha256")
    try:
        fields = checksum.read_text(encoding="ascii").strip().split()
    except OSError as exc:
        raise ExecutionContractError(f"cannot read execution policy checksum: {checksum}") from exc
    if len(fields) != 2 or fields[1] != path.name or fields[0] != policy.fingerprint:
        raise ExecutionContractError("execution policy checksum mismatch")
    return policy


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ExecutionContractError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExecutionContractError(f"{field} must be a non-empty string")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ExecutionContractError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ExecutionContractError(f"{field} is not a decimal") from exc
    _positive(result, field, allow_zero=True)
    return result


def _positive(value: Decimal, field: str, *, allow_zero: bool = False) -> None:
    if not value.is_finite():
        raise ExecutionContractError(f"{field} must be finite")
    if value < 0 or (not allow_zero and value == 0):
        relation = ">= 0" if allow_zero else "> 0"
        raise ExecutionContractError(f"{field} must be {relation}")


def _aligned(value: Decimal, step: Decimal) -> bool:
    return value % step == 0
