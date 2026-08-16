from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class PositionSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class BrokerActionStatus(StrEnum):
    NONE = "NONE"
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class ManagementAction(StrEnum):
    NONE = "NONE"
    WAIT = "WAIT"
    ACKNOWLEDGE_PROTECTION = "ACKNOWLEDGE_PROTECTION"
    MODIFY_PROTECTION = "MODIFY_PROTECTION"
    CLOSE_FULL = "CLOSE_FULL"


@dataclass(frozen=True, slots=True)
class PositionManagementPolicy:
    policy_id: str = "M1_R_LOCK"
    version: int = 1
    r1_threshold: float = 1.0
    r2_threshold: float = 2.0
    r3_threshold: float = 3.0
    r1_lock_r: float = 0.25
    r2_lock_r: float = 1.0
    r1_protection_enabled: bool = True
    r2_protection_enabled: bool = True
    r3_close_enabled: bool = True
    partial_close_enabled: bool = False

    def __post_init__(self) -> None:
        values = (
            self.r1_threshold,
            self.r2_threshold,
            self.r3_threshold,
            self.r1_lock_r,
            self.r2_lock_r,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("management policy values must be finite")
        if not 0 < self.r1_threshold < self.r2_threshold < self.r3_threshold:
            raise ValueError("management thresholds must satisfy 0 < R1 < R2 < R3")
        if not 0 <= self.r1_lock_r < self.r1_threshold:
            raise ValueError("R1 lock must be non-negative and below R1")
        if not self.r1_lock_r <= self.r2_lock_r < self.r2_threshold:
            raise ValueError("R2 lock must be at least the R1 lock and below R2")
        if self.partial_close_enabled:
            raise ValueError("partial close is not supported by M1_R_LOCK policy version 1")


@dataclass(frozen=True, slots=True)
class ManagedPosition:
    execution_id: str
    position_identifier: int
    symbol: str
    side: PositionSide | str
    actual_entry: float
    initial_stop: float
    current_stop: float
    current_take_profit: float
    initial_volume: float
    remaining_volume: float

    def __post_init__(self) -> None:
        try:
            resolved_side = PositionSide(self.side)
        except ValueError as exc:
            raise ValueError(f"unsupported position side: {self.side!r}") from exc
        object.__setattr__(self, "side", resolved_side)

        numeric = (
            self.actual_entry,
            self.initial_stop,
            self.current_stop,
            self.current_take_profit,
            self.initial_volume,
            self.remaining_volume,
        )
        if not all(isfinite(value) for value in numeric):
            raise ValueError("managed position values must be finite")
        if self.position_identifier <= 0:
            raise ValueError("position_identifier must be positive")
        if self.actual_entry <= 0 or self.initial_stop <= 0:
            raise ValueError("actual entry and immutable initial stop must be positive")
        if self.initial_volume <= 0 or not 0 < self.remaining_volume <= self.initial_volume:
            raise ValueError("remaining volume must be positive and no greater than initial volume")
        if resolved_side is PositionSide.BUY and self.initial_stop >= self.actual_entry:
            raise ValueError("BUY initial stop must be below actual entry")
        if resolved_side is PositionSide.SELL and self.initial_stop <= self.actual_entry:
            raise ValueError("SELL initial stop must be above actual entry")

    @property
    def initial_risk_distance(self) -> float:
        return abs(self.actual_entry - self.initial_stop)


@dataclass(frozen=True, slots=True)
class MilestoneState:
    r1_reached: bool = False
    r2_reached: bool = False
    r3_reached: bool = False
    r1_protection_status: BrokerActionStatus | str = BrokerActionStatus.NONE
    r2_protection_status: BrokerActionStatus | str = BrokerActionStatus.NONE
    r3_close_status: BrokerActionStatus | str = BrokerActionStatus.NONE

    def __post_init__(self) -> None:
        for field_name in (
            "r1_protection_status",
            "r2_protection_status",
            "r3_close_status",
        ):
            raw = getattr(self, field_name)
            try:
                status = BrokerActionStatus(raw)
            except ValueError as exc:
                raise ValueError(f"invalid {field_name}: {raw!r}") from exc
            object.__setattr__(self, field_name, status)


@dataclass(frozen=True, slots=True)
class BrokerActionPlan:
    action: ManagementAction
    current_r: float
    newly_reached: tuple[str, ...] = ()
    milestone: str | None = None
    target_stop: float | None = None
    preserve_take_profit: float | None = None
    target_remaining_volume: float | None = None
    reason: str = ""


def calculate_current_r(
    position: ManagedPosition,
    *,
    bid: float,
    ask: float,
) -> float:
    if not all(isfinite(value) and value > 0 for value in (bid, ask)):
        raise ValueError("bid and ask must be finite positive values")
    if ask < bid:
        raise ValueError("ask cannot be below bid")
    executable_price = bid if position.side is PositionSide.BUY else ask
    signed_move = (
        executable_price - position.actual_entry
        if position.side is PositionSide.BUY
        else position.actual_entry - executable_price
    )
    return signed_move / position.initial_risk_distance


def stop_for_r(position: ManagedPosition, lock_r: float) -> float:
    if not isfinite(lock_r):
        raise ValueError("lock_r must be finite")
    direction = 1.0 if position.side is PositionSide.BUY else -1.0
    return position.actual_entry + direction * lock_r * position.initial_risk_distance


def is_stop_at_least_as_protective(position: ManagedPosition, target_stop: float) -> bool:
    if position.current_stop <= 0:
        return False
    if position.side is PositionSide.BUY:
        return position.current_stop >= target_stop
    return position.current_stop <= target_stop


def plan_position_management(
    position: ManagedPosition,
    milestones: MilestoneState,
    *,
    bid: float,
    ask: float,
    policy: PositionManagementPolicy | None = None,
) -> BrokerActionPlan:
    resolved_policy = policy or PositionManagementPolicy()
    current_r = calculate_current_r(position, bid=bid, ask=ask)
    newly_reached = tuple(
        name
        for name, reached, threshold in (
            ("R1", milestones.r1_reached, resolved_policy.r1_threshold),
            ("R2", milestones.r2_reached, resolved_policy.r2_threshold),
            ("R3", milestones.r3_reached, resolved_policy.r3_threshold),
        )
        if current_r >= threshold and not reached
    )

    r3_due = milestones.r3_reached or current_r >= resolved_policy.r3_threshold
    if resolved_policy.r3_close_enabled and r3_due:
        if milestones.r3_close_status is BrokerActionStatus.CONFIRMED:
            return BrokerActionPlan(
                ManagementAction.NONE,
                current_r,
                newly_reached,
                milestone="R3",
                target_remaining_volume=0.0,
                reason="R3 close already confirmed",
            )
        if milestones.r3_close_status in {
            BrokerActionStatus.PENDING,
            BrokerActionStatus.SUBMITTED,
            BrokerActionStatus.UNKNOWN,
        }:
            return BrokerActionPlan(
                ManagementAction.WAIT,
                current_r,
                newly_reached,
                milestone="R3",
                target_remaining_volume=0.0,
                reason=f"R3 close is {milestones.r3_close_status.value}",
            )
        if milestones.r3_close_status is BrokerActionStatus.FAILED:
            return BrokerActionPlan(
                ManagementAction.WAIT,
                current_r,
                newly_reached,
                milestone="R3",
                target_remaining_volume=0.0,
                reason="R3 close failed; an explicit audited retry is required",
            )
        return BrokerActionPlan(
            ManagementAction.CLOSE_FULL,
            current_r,
            newly_reached,
            milestone="R3",
            target_remaining_volume=0.0,
            reason="R3 reached; full close has priority over protection changes",
        )

    protection = _highest_due_protection(
        current_r,
        resolved_policy,
        r1_reached=milestones.r1_reached,
        r2_reached=milestones.r2_reached,
    )
    if protection is None:
        return BrokerActionPlan(
            ManagementAction.NONE,
            current_r,
            newly_reached,
            reason="no management threshold reached",
        )

    milestone, lock_r, status = (
        ("R2", resolved_policy.r2_lock_r, milestones.r2_protection_status)
        if protection == "R2"
        else ("R1", resolved_policy.r1_lock_r, milestones.r1_protection_status)
    )
    target_stop = stop_for_r(position, lock_r)
    if is_stop_at_least_as_protective(position, target_stop):
        return BrokerActionPlan(
            ManagementAction.ACKNOWLEDGE_PROTECTION,
            current_r,
            newly_reached,
            milestone=milestone,
            target_stop=target_stop,
            preserve_take_profit=position.current_take_profit,
            reason=f"broker stop already satisfies {milestone} protection",
        )
    if status is BrokerActionStatus.CONFIRMED:
        # A confirmed database state with a weaker broker stop is divergence, not permission
        # to silently claim success or to loosen the desired protection.
        return BrokerActionPlan(
            ManagementAction.MODIFY_PROTECTION,
            current_r,
            newly_reached,
            milestone=milestone,
            target_stop=target_stop,
            preserve_take_profit=position.current_take_profit,
            reason=f"{milestone} database state diverged from broker stop; restore protection",
        )
    if status in {
        BrokerActionStatus.PENDING,
        BrokerActionStatus.SUBMITTED,
        BrokerActionStatus.UNKNOWN,
        BrokerActionStatus.FAILED,
    }:
        return BrokerActionPlan(
            ManagementAction.WAIT,
            current_r,
            newly_reached,
            milestone=milestone,
            target_stop=target_stop,
            preserve_take_profit=position.current_take_profit,
            reason=f"{milestone} protection is {status.value}; reconcile before retry",
        )
    return BrokerActionPlan(
        ManagementAction.MODIFY_PROTECTION,
        current_r,
        newly_reached,
        milestone=milestone,
        target_stop=target_stop,
        preserve_take_profit=position.current_take_profit,
        reason=f"{milestone} reached; request broker protection",
    )


def _highest_due_protection(
    current_r: float,
    policy: PositionManagementPolicy,
    *,
    r1_reached: bool = False,
    r2_reached: bool = False,
) -> str | None:
    if policy.r2_protection_enabled and (
        r2_reached or current_r >= policy.r2_threshold
    ):
        return "R2"
    if policy.r1_protection_enabled and (
        r1_reached or current_r >= policy.r1_threshold
    ):
        return "R1"
    return None
