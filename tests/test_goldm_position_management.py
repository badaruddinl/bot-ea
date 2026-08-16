from __future__ import annotations

import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldm_signal.position_management import (  # noqa: E402
    BrokerActionStatus,
    ManagedPosition,
    ManagementAction,
    MilestoneState,
    PositionManagementPolicy,
    calculate_current_r,
    plan_position_management,
)


def managed_position(
    *,
    side: str = "buy",
    entry: float = 100.0,
    initial_stop: float | None = None,
    current_stop: float | None = None,
) -> ManagedPosition:
    resolved_initial_stop = initial_stop if initial_stop is not None else (90.0 if side == "buy" else 110.0)
    resolved_current_stop = current_stop if current_stop is not None else resolved_initial_stop
    return ManagedPosition(
        execution_id="demo:setup-1",
        position_identifier=7001,
        symbol="GOLD.i#",
        side=side,
        actual_entry=entry,
        initial_stop=resolved_initial_stop,
        current_stop=resolved_current_stop,
        current_take_profit=130.0 if side == "buy" else 70.0,
        initial_volume=0.10,
        remaining_volume=0.10,
    )


class GoldMPositionManagementTests(unittest.TestCase):
    def test_buy_uses_bid_and_sell_uses_ask_for_current_r(self) -> None:
        buy = managed_position(side="buy")
        sell = managed_position(side="sell")
        self.assertAlmostEqual(calculate_current_r(buy, bid=110.0, ask=110.5), 1.0)
        self.assertAlmostEqual(calculate_current_r(sell, bid=89.5, ask=90.0), 1.0)

    def test_initial_risk_reference_is_immutable(self) -> None:
        position = managed_position(side="buy", current_stop=102.5)
        self.assertEqual(position.initial_risk_distance, 10.0)
        self.assertAlmostEqual(calculate_current_r(position, bid=120.0, ask=120.5), 2.0)
        with self.assertRaises(FrozenInstanceError):
            position.initial_stop = 102.5  # type: ignore[misc]

    def test_exact_thresholds_select_expected_actions(self) -> None:
        position = managed_position()
        below_r1 = plan_position_management(position, MilestoneState(), bid=109.999, ask=110.1)
        at_r1 = plan_position_management(position, MilestoneState(), bid=110.0, ask=110.1)
        at_r2 = plan_position_management(position, MilestoneState(), bid=120.0, ask=120.1)
        at_r3 = plan_position_management(position, MilestoneState(), bid=130.0, ask=130.1)

        self.assertEqual(below_r1.action, ManagementAction.NONE)
        self.assertEqual(at_r1.action, ManagementAction.MODIFY_PROTECTION)
        self.assertEqual(at_r1.target_stop, 102.5)
        self.assertEqual(at_r2.action, ManagementAction.MODIFY_PROTECTION)
        self.assertEqual(at_r2.target_stop, 110.0)
        self.assertEqual(at_r3.action, ManagementAction.CLOSE_FULL)

    def test_sell_lock_prices_are_mirrored(self) -> None:
        position = managed_position(side="sell")
        r1 = plan_position_management(position, MilestoneState(), bid=89.5, ask=90.0)
        r2 = plan_position_management(position, MilestoneState(), bid=79.5, ask=80.0)
        self.assertEqual(r1.target_stop, 97.5)
        self.assertEqual(r2.target_stop, 90.0)

    def test_gap_to_r2_records_both_milestones_but_only_one_modify(self) -> None:
        plan = plan_position_management(
            managed_position(),
            MilestoneState(),
            bid=121.0,
            ask=121.2,
        )
        self.assertEqual(plan.newly_reached, ("R1", "R2"))
        self.assertEqual(plan.milestone, "R2")
        self.assertEqual(plan.action, ManagementAction.MODIFY_PROTECTION)
        self.assertEqual(plan.target_stop, 110.0)

    def test_gap_to_r3_prioritizes_full_close(self) -> None:
        plan = plan_position_management(
            managed_position(),
            MilestoneState(),
            bid=135.0,
            ask=135.2,
        )
        self.assertEqual(plan.newly_reached, ("R1", "R2", "R3"))
        self.assertEqual(plan.action, ManagementAction.CLOSE_FULL)
        self.assertEqual(plan.target_remaining_volume, 0.0)

    def test_existing_more_protective_stop_is_never_loosened(self) -> None:
        buy = plan_position_management(
            managed_position(side="buy", current_stop=115.0),
            MilestoneState(),
            bid=120.0,
            ask=120.2,
        )
        sell = plan_position_management(
            managed_position(side="sell", current_stop=85.0),
            MilestoneState(),
            bid=79.8,
            ask=80.0,
        )
        self.assertEqual(buy.action, ManagementAction.ACKNOWLEDGE_PROTECTION)
        self.assertEqual(sell.action, ManagementAction.ACKNOWLEDGE_PROTECTION)

    def test_pending_or_ambiguous_action_waits_for_reconciliation(self) -> None:
        for status in (
            BrokerActionStatus.PENDING,
            BrokerActionStatus.SUBMITTED,
            BrokerActionStatus.UNKNOWN,
        ):
            with self.subTest(status=status):
                plan = plan_position_management(
                    managed_position(),
                    MilestoneState(r1_protection_status=status),
                    bid=110.0,
                    ask=110.2,
                )
                self.assertEqual(plan.action, ManagementAction.WAIT)

    def test_latched_r2_remains_due_after_price_retraces(self) -> None:
        plan = plan_position_management(
            managed_position(),
            MilestoneState(r1_reached=True, r2_reached=True),
            bid=105.0,
            ask=105.2,
        )

        self.assertEqual(plan.action, ManagementAction.MODIFY_PROTECTION)
        self.assertEqual(plan.milestone, "R2")
        self.assertEqual(plan.target_stop, 110.0)

    def test_latched_r3_close_remains_due_after_price_retraces(self) -> None:
        plan = plan_position_management(
            managed_position(),
            MilestoneState(r1_reached=True, r2_reached=True, r3_reached=True),
            bid=105.0,
            ask=105.2,
        )

        self.assertEqual(plan.action, ManagementAction.CLOSE_FULL)
        self.assertEqual(plan.milestone, "R3")

    def test_failed_action_requires_explicit_retry(self) -> None:
        protection = plan_position_management(
            managed_position(),
            MilestoneState(
                r1_reached=True,
                r1_protection_status=BrokerActionStatus.FAILED,
            ),
            bid=105.0,
            ask=105.2,
        )
        close = plan_position_management(
            managed_position(),
            MilestoneState(
                r3_reached=True,
                r3_close_status=BrokerActionStatus.FAILED,
            ),
            bid=105.0,
            ask=105.2,
        )

        self.assertEqual(protection.action, ManagementAction.WAIT)
        self.assertEqual(close.action, ManagementAction.WAIT)

    def test_confirmed_database_state_with_weaker_stop_is_repaired(self) -> None:
        plan = plan_position_management(
            managed_position(current_stop=90.0),
            MilestoneState(r2_reached=True, r2_protection_status="CONFIRMED"),
            bid=120.0,
            ask=120.2,
        )
        self.assertEqual(plan.action, ManagementAction.MODIFY_PROTECTION)
        self.assertIn("diverged", plan.reason)

    def test_touches_are_reported_when_all_broker_actions_are_disabled(self) -> None:
        policy = PositionManagementPolicy(
            r1_protection_enabled=False,
            r2_protection_enabled=False,
            r3_close_enabled=False,
        )

        plan = plan_position_management(
            managed_position(),
            MilestoneState(),
            bid=135.0,
            ask=135.2,
            policy=policy,
        )

        self.assertEqual(plan.action, ManagementAction.NONE)
        self.assertEqual(plan.newly_reached, ("R1", "R2", "R3"))

    def test_disabled_r2_falls_back_to_enabled_r1_protection(self) -> None:
        plan = plan_position_management(
            managed_position(),
            MilestoneState(),
            bid=121.0,
            ask=121.2,
            policy=PositionManagementPolicy(r2_protection_enabled=False),
        )

        self.assertEqual(plan.action, ManagementAction.MODIFY_PROTECTION)
        self.assertEqual(plan.milestone, "R1")
        self.assertEqual(plan.target_stop, 102.5)

    def test_invalid_position_ticks_and_policy_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "initial stop"):
            managed_position(side="buy", initial_stop=100.0)
        with self.assertRaisesRegex(ValueError, "ask cannot be below bid"):
            calculate_current_r(managed_position(), bid=101.0, ask=100.0)
        with self.assertRaisesRegex(ValueError, "partial close"):
            PositionManagementPolicy(partial_close_enabled=True)


if __name__ == "__main__":
    unittest.main()
