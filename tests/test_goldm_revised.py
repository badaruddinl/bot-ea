from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from goldm_revised.engine import (
    ConfirmationMode,
    RevisedAction,
    RevisedBar,
    RevisedEngine,
    RevisedEngineConfig,
    RevisedSide,
    RevisedSnapshot,
    RevisedState,
)
from goldm_revised.evidence import august_five, validate_evidence
from goldm_revised.mt5_source import RevisedMt5ReadOnlySource
from goldm_revised.replay import ReplayInspection, ReplayPosition, RevisedReplay
from goldm_revised.storage import RevisedStore
from goldm_revised.setup import RevisedSetupDetector, classify_m5_setup
from goldm_revised.telegram import RevisedAdminNotifier


TZ = timezone(timedelta(hours=3))


def test_august_five_evidence_contract_and_matching() -> None:
    expectations = august_five(TZ)
    assert [(item.evidence_id, item.expected_side.value, item.expected_profile) for item in expectations] == [
        ("E1", "SELL", "CORE"),
        ("E2", "BUY", "CORE"),
        ("E3", "SELL", "CORE"),
        ("E4", "BUY", "SCALPER"),
        ("E5", "BUY", "CORE"),
    ]
    expected = expectations[1]
    inspection = ReplayInspection(
        requested_time=expected.requested_time,
        side=RevisedSide.BUY,
        setup_trigger_time=expected.requested_time + timedelta(minutes=5),
        decision_time=expected.requested_time + timedelta(minutes=8),
        state=RevisedState.ENTRY_READY,
        reason="confirmed",
        entry_profile="CORE",
        validation_status="CONFIRMED",
        retest_count=2,
        entry=4400.0,
        stop=4395.0,
        target=4407.5,
        first_obstacle_r=1.5,
        touch_count=2,
        rejection_count=2,
        m1_votes=3,
        exhausted=False,
        risk_source="m1_structure",
    )

    result = validate_evidence((expected,), (inspection,), ())

    assert result[0]["status"] == "PASS"
    assert result[0]["matched"] is True


def bar(index: int, open_: float, high: float, low: float, close: float, *, minutes: int = 1) -> RevisedBar:
    high = max(high, open_, close)
    low = min(low, open_, close)
    return RevisedBar(
        time=datetime(2026, 8, 18, 12, 0, tzinfo=TZ) + timedelta(minutes=index * minutes),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100 + index,
        spread=0.20,
    )


def flat_m5() -> tuple[RevisedBar, ...]:
    values = []
    for index in range(20):
        close = 4392.0 + (0.2 if index % 2 else 0.0)
        values.append(bar(index, close - 0.1, close + 1.0, close - 1.0, close, minutes=5))
    return tuple(values)


def range_m1(*, side: RevisedSide = RevisedSide.BUY) -> tuple[RevisedBar, ...]:
    if side is RevisedSide.BUY:
        values = [
            (4391.0, 4394.0, 4390.0, 4393.5),
            (4393.5, 4394.0, 4392.0, 4393.0),
            (4393.0, 4394.0, 4391.5, 4392.5),
            (4392.5, 4394.0, 4390.0, 4394.0),
            (4393.4, 4394.0, 4392.0, 4393.2),
            (4393.2, 4394.0, 4391.5, 4392.8),
            (4392.8, 4394.0, 4390.0, 4394.0),
            (4393.4, 4394.0, 4392.0, 4393.0),
            (4393.0, 4394.0, 4391.5, 4392.7),
            (4392.7, 4394.0, 4390.0, 4394.0),
            (4393.5, 4394.0, 4392.0, 4393.0),
            (4393.0, 4395.0, 4392.5, 4394.6),
        ]
    else:
        values = [
            (4404.0, 4405.0, 4401.0, 4401.5),
            (4401.5, 4403.0, 4400.5, 4401.8),
            (4401.8, 4403.5, 4400.8, 4402.0),
            (4402.0, 4405.0, 4401.0, 4401.6),
            (4401.6, 4403.0, 4400.5, 4401.9),
            (4401.9, 4403.5, 4400.8, 4402.1),
            (4402.1, 4405.0, 4401.0, 4401.7),
            (4401.7, 4403.0, 4400.5, 4401.9),
            (4401.9, 4403.5, 4400.8, 4402.0),
            (4402.0, 4405.0, 4401.0, 4401.8),
            (4401.8, 4403.0, 4400.5, 4401.7),
            (4401.7, 4402.0, 4398.5, 4399.0),
        ]
    warmup = (
        [(4392.0, 4393.0, 4391.0, 4392.5)] * 4
        if side is RevisedSide.BUY
        else [(4402.0, 4404.0, 4401.0, 4402.5)] * 4
    )
    values = warmup + values
    return tuple(bar(index, *values[index]) for index in range(len(values)))


def snapshot(*, side: RevisedSide = RevisedSide.BUY, m1=None, m5=None, entry=None, stop=None, invalidation=None, pattern="BULL_ENGULFING", votes=3) -> RevisedSnapshot:
    m1 = tuple(m1 or range_m1(side=side))
    m5 = tuple(m5 or flat_m5())
    return RevisedSnapshot(
        symbol="GOLD.i#",
        side=side,
        current_time=m1[-1].time,
        m1_bars=m1,
        m5_bars=m5,
        m5_trigger_time=m1[0].time - timedelta(minutes=1),
        m5_pattern=pattern,
        m5_votes=votes,
        confidence=92.0,
        entry=entry,
        stop=stop,
        invalidation=invalidation,
    )


class GoldMRevisedEngineTests(unittest.TestCase):
    def test_package_is_independent_of_other_engines(self) -> None:
        import goldm_revised.engine as module

        source = inspect.getsource(module)
        self.assertNotIn("goldm_signal", source)
        self.assertNotIn("goldm_bear", source)
        self.assertEqual(module.STRATEGY_ID, "GOLDM_REVISED")
        self.assertEqual(module.STRATEGY_VERSION, "0.5.0")

    def test_buy_range_requires_repeated_rejections_and_enters(self) -> None:
        decision = RevisedEngine().evaluate(snapshot())
        self.assertEqual(decision.side, RevisedSide.BUY)
        self.assertEqual(decision.state, RevisedState.ENTRY_READY)
        self.assertEqual(decision.action, RevisedAction.ENTER)
        self.assertEqual(decision.mode, ConfirmationMode.RANGE)
        self.assertGreaterEqual(decision.touch_count, 2)
        self.assertGreaterEqual(decision.rejection_count, 2)
        self.assertGreaterEqual(decision.m1_votes, 3)
        self.assertGreater(decision.first_obstacle or 0.0, decision.entry or 0.0)

    def test_sell_is_symmetric_but_observation_only(self) -> None:
        decision = RevisedEngine().evaluate(
            snapshot(
                side=RevisedSide.SELL,
                m1=range_m1(side=RevisedSide.SELL),
                pattern="BEAR_ENGULFING",
                entry=4399.0,
                stop=4401.0,
            )
        )
        self.assertEqual(decision.side, RevisedSide.SELL)
        self.assertTrue(decision.observation_only)
        self.assertEqual(decision.action, RevisedAction.ENTER)

    def test_first_obstacle_below_one_r_remains_watch_until_hard_invalidation(self) -> None:
        decision = RevisedEngine().evaluate(snapshot(entry=4399.9, stop=4399.0))
        self.assertEqual(decision.state, RevisedState.WATCH)
        self.assertEqual(decision.reason, "SOFT_FAIL_FIRST_OBSTACLE_ROOM")
        self.assertEqual(decision.validation_status, "WATCH_ONLY")
        self.assertLess(decision.confidence, 60.0)

    def test_two_closes_beyond_setup_invalidation_hard_cancel(self) -> None:
        bars = list(range_m1())
        bars.extend(
            [
                bar(len(bars), 4390.0, 4390.2, 4387.8, 4388.2),
                bar(len(bars) + 1, 4388.2, 4388.5, 4386.8, 4387.1),
            ]
        )
        decision = RevisedEngine().evaluate(
            snapshot(m1=tuple(bars), entry=4387.1, stop=4386.0, invalidation=4390.0)
        )

        self.assertEqual(decision.state, RevisedState.CANCELLED)
        self.assertEqual(decision.reason, "HARD_INVALIDATION_ACCEPTED")
        self.assertEqual(decision.validation_status, "HARD_INVALID")

    def test_fibonacci_retests_are_counted_after_leaving_zone(self) -> None:
        m5 = tuple(
            bar(
                index,
                4390.0 + index,
                4391.0 + index,
                4389.0 + index,
                4390.8 + index,
                minutes=5,
            )
            for index in range(12)
        )
        trigger = m5[-1].time + timedelta(minutes=5)
        m1 = tuple(
            [
                bar(101, 4397.2, 4398.0, 4396.5, 4397.5),
                bar(102, 4397.6, 4398.8, 4397.5, 4398.5),
                bar(103, 4398.5, 4398.9, 4398.1, 4398.4),
                bar(104, 4397.1, 4398.0, 4396.7, 4397.6),
                bar(105, 4397.6, 4398.8, 4397.5, 4398.5),
            ]
        )
        value = RevisedSnapshot(
            symbol="GOLD.i#",
            side=RevisedSide.BUY,
            current_time=m1[-1].time,
            m1_bars=m1,
            m5_bars=m5,
            m5_trigger_time=trigger,
            m5_pattern="BULL_REJECTION",
            m5_votes=2,
        )

        stats = RevisedEngine()._fibonacci_stats(value, RevisedSide.BUY, atr_m1=1.0)

        self.assertTrue(stats["available"])
        self.assertEqual(stats["retests"], 2)
        self.assertTrue(stats["current_rejection"])

    def test_sub_one_r_buy_is_labeled_scalper_and_excluded_from_core(self) -> None:
        decision = RevisedEngine().evaluate(snapshot(entry=4399.7, stop=4398.7))

        self.assertEqual(decision.state, RevisedState.ENTRY_READY)
        self.assertEqual(decision.entry_profile, "SCALPER")
        self.assertTrue(decision.observation_only)
        self.assertEqual(decision.reason, "SCALPER_FIRST_OBSTACLE_ENTRY")
        self.assertLess(decision.first_obstacle_r or 1.0, 1.0)
        self.assertGreater(decision.target or 0.0, decision.entry or 0.0)
        self.assertLess(decision.target or 0.0, decision.first_obstacle or 0.0)

    def test_core_buy_target_is_lowered_further_before_obstacle(self) -> None:
        earlier = RevisedEngine(
            RevisedEngineConfig(strict_target_buffer_atr=0.08)
        ).evaluate(snapshot())
        revised = RevisedEngine().evaluate(snapshot())

        self.assertEqual(revised.entry_profile, "CORE")
        self.assertEqual(revised.state, RevisedState.ENTRY_READY)
        self.assertLess(revised.target or 0.0, earlier.target or 0.0)

    def test_single_m1_micro_swing_does_not_override_psychological_obstacle(self) -> None:
        obstacle, kind = RevisedEngine()._first_obstacle(
            snapshot(),
            entry=4394.6,
            atr_m1=1.0,
        )

        self.assertEqual(obstacle, 4400.0)
        self.assertEqual(kind, "PSYCH_10")

    def test_momentum_can_bypass_range_when_room_is_large(self) -> None:
        m5 = tuple(
            bar(index, 4390 + index * 2.0, 4392 + index * 2.0, 4389 + index * 2.0, 4392 + index * 2.0, minutes=5)
            for index in range(20)
        )
        decision = RevisedEngine().evaluate(
            snapshot(m5=m5, m1=range_m1(), entry=4394.0, stop=4390.0, pattern="BULL_ENGULFING", votes=3)
        )
        self.assertEqual(decision.mode, ConfirmationMode.MOMENTUM)
        self.assertEqual(decision.action, RevisedAction.ENTER)

    def test_exhaustion_forces_range_mode(self) -> None:
        m5 = list(flat_m5())
        m5[-4:] = [
            bar(16, 4392.0, 4394.0, 4391.0, 4393.8, minutes=5),
            bar(17, 4393.8, 4395.0, 4392.5, 4394.1, minutes=5),
            bar(18, 4394.1, 4395.0, 4393.5, 4394.3, minutes=5),
            bar(19, 4394.3, 4394.8, 4393.8, 4394.4, minutes=5),
        ]
        decision = RevisedEngine().evaluate(snapshot(m5=tuple(m5), m1=range_m1()))
        self.assertTrue(decision.exhausted)
        self.assertNotEqual(decision.mode, ConfirmationMode.MOMENTUM)

    def test_latest_closed_bar_is_the_only_bar_read(self) -> None:
        bars = list(range_m1())
        future = bar(99, 5000.0, 5001.0, 4999.0, 5000.5)
        before = RevisedEngine().evaluate(snapshot(m1=tuple(bars)))
        after = RevisedEngine().evaluate(snapshot(m1=tuple(bars + [future])))
        self.assertNotEqual(before.time, after.time)
        self.assertLess(before.time, after.time)

    def test_missing_m5_setup_never_promotes(self) -> None:
        value = snapshot()
        decision = RevisedEngine().evaluate(
            RevisedSnapshot(
                symbol=value.symbol,
                side=value.side,
                current_time=value.current_time,
                m1_bars=value.m1_bars,
                m5_bars=value.m5_bars,
            )
        )
        self.assertEqual(decision.state, RevisedState.WAIT)
        self.assertEqual(decision.reason, "M5_SETUP_UNAVAILABLE")

    def test_m5_setup_persists_across_m1_bars_and_can_be_consumed(self) -> None:
        m5 = list(flat_m5())
        m5[-2] = bar(18, 4392.0, 4393.0, 4391.0, 4391.5, minutes=5)
        m5[-1] = bar(19, 4391.4, 4395.0, 4391.0, 4394.5, minutes=5)
        detector = RevisedSetupDetector(maximum_m1_bars=12)
        first_time = m5[-1].time + timedelta(minutes=6)
        setup_value = detector.update(tuple(m5), current_m1_time=first_time, side=RevisedSide.BUY)
        self.assertIsNotNone(setup_value)
        persisted = detector.update(
            tuple(m5),
            current_m1_time=first_time + timedelta(minutes=4),
            side=RevisedSide.BUY,
        )
        self.assertEqual(persisted, setup_value)
        detector.consume(RevisedSide.BUY, setup_value.trigger_time)
        self.assertIsNone(
            detector.update(
                tuple(m5),
                current_m1_time=first_time + timedelta(minutes=5),
                side=RevisedSide.BUY,
            )
        )

    def test_opposite_m5_reversal_expires_buy_and_creates_sell_setup(self) -> None:
        m5 = list(flat_m5())
        m5[-2] = bar(18, 4392.0, 4393.0, 4390.5, 4391.0, minutes=5)
        m5[-1] = bar(19, 4390.8, 4395.0, 4390.7, 4394.6, minutes=5)
        detector = RevisedSetupDetector(maximum_m1_bars=12)
        buy_time = m5[-1].time + timedelta(minutes=6)
        buy = detector.update(tuple(m5), current_m1_time=buy_time, side=RevisedSide.BUY)
        self.assertIsNotNone(buy)

        m5.append(bar(20, 4394.8, 4395.1, 4388.0, 4388.5, minutes=5))
        sell_time = m5[-1].time + timedelta(minutes=6)
        sell = detector.update(tuple(m5), current_m1_time=sell_time, side=RevisedSide.SELL)

        self.assertIsNotNone(sell)
        self.assertTrue(sell.pattern.startswith("BEAR_"))
        terminated = detector.pop_termination(RevisedSide.BUY)
        self.assertIsNotNone(terminated)
        self.assertEqual(terminated[1], "OPPOSITE_M5_SETUP_ACCEPTED")
        self.assertIsNone(
            detector.update(tuple(m5), current_m1_time=sell_time, side=RevisedSide.BUY)
        )

    def test_watch_expiry_emits_explicit_terminal_reason(self) -> None:
        m5 = list(flat_m5())
        m5[-2] = bar(18, 4392.0, 4393.0, 4391.0, 4391.5, minutes=5)
        m5[-1] = bar(19, 4391.4, 4395.0, 4391.0, 4394.5, minutes=5)
        detector = RevisedSetupDetector(maximum_m1_bars=2)
        first_time = m5[-1].time + timedelta(minutes=6)
        setup_value = detector.update(
            tuple(m5), current_m1_time=first_time, side=RevisedSide.BUY
        )
        self.assertIsNotNone(setup_value)

        expired = detector.update(
            tuple(m5),
            current_m1_time=setup_value.trigger_time + timedelta(minutes=3),
            side=RevisedSide.BUY,
        )
        termination = detector.pop_termination(RevisedSide.BUY)

        self.assertIsNone(expired)
        self.assertEqual(termination[1], "WATCH_WINDOW_EXPIRED")
        terminal = RevisedEngine().terminal_decision(
            snapshot(), termination[1]
        )
        self.assertEqual(terminal.state, RevisedState.CANCELLED)
        self.assertEqual(terminal.validation_status, "HARD_INVALID")

    def test_m5_strong_rejection_and_star_patterns_are_symmetric(self) -> None:
        bull_rejection = classify_m5_setup(
            (
                bar(0, 4394.0, 4394.5, 4391.5, 4392.0, minutes=5),
                bar(1, 4392.5, 4394.0, 4389.0, 4393.5, minutes=5),
            ),
            RevisedSide.BUY,
        )
        bear_rejection = classify_m5_setup(
            (
                bar(0, 4392.0, 4394.5, 4391.5, 4394.0, minutes=5),
                bar(1, 4393.5, 4397.0, 4392.0, 4392.5, minutes=5),
            ),
            RevisedSide.SELL,
        )
        evening_star = classify_m5_setup(
            (
                bar(0, 4390.0, 4394.5, 4389.5, 4394.0, minutes=5),
                bar(1, 4394.0, 4394.3, 4393.5, 4393.8, minutes=5),
                bar(2, 4393.5, 4393.8, 4391.0, 4391.5, minutes=5),
            ),
            RevisedSide.SELL,
        )

        self.assertEqual(bull_rejection.pattern, "BULL_REJECTION")
        self.assertEqual(bear_rejection.pattern, "BEAR_REJECTION")
        self.assertEqual(evening_star.pattern, "BEAR_EVENING_STAR")

    def test_m1_structure_can_make_early_buy_valid_without_relaxing_one_r_gate(self) -> None:
        warmup = [
            (4397.4, 4398.4, 4396.9, 4397.8),
            (4397.8, 4398.5, 4397.0, 4397.9),
            (4397.9, 4398.5, 4397.1, 4398.0),
            (4398.0, 4398.6, 4397.2, 4398.1),
        ]
        confirmation = [
            (4397.2, 4398.5, 4396.7, 4397.8),
            (4397.8, 4398.6, 4397.4, 4398.4),
            (4398.3, 4398.6, 4396.7, 4397.9),
            (4397.9, 4398.7, 4397.5, 4398.5),
            (4398.4, 4398.7, 4396.7, 4397.9),
            (4397.9, 4398.6, 4397.6, 4398.3),
            (4398.2, 4398.7, 4398.1, 4398.4),
            (4398.3, 4398.6, 4398.0, 4398.2),
            (4398.2, 4398.6, 4398.2, 4398.4),
            (4398.3, 4398.5, 4397.8, 4398.1),
            (4398.1, 4398.4, 4398.0, 4398.2),
            (4398.1, 4398.7, 4398.0, 4398.5),
        ]
        m1 = tuple(
            bar(index, *values)
            for index, values in enumerate(warmup + confirmation)
        )
        decision = RevisedEngine().evaluate(
            snapshot(
                m1=m1,
                entry=4398.5,
                stop=4388.0,
                pattern="BULL_ENGULFING",
                votes=3,
            )
        )

        self.assertEqual(decision.state, RevisedState.ENTRY_READY)
        self.assertEqual(decision.evidence["risk"]["source"], "M1_CONFIRMED_STRUCTURE")
        self.assertGreater(decision.stop or 0.0, 4388.0)
        self.assertGreaterEqual(decision.first_obstacle_r or 0.0, 1.0)
        self.assertGreater(decision.target or 0.0, decision.entry or 0.0)
        self.assertLess(decision.target or 0.0, decision.first_obstacle or 0.0)

    def test_strict_room_rejects_weak_m5_pattern_but_accepts_engulfing(self) -> None:
        weak = RevisedEngine().evaluate(
            snapshot(entry=4395.0, stop=4390.0, pattern="BULL_MICRO_BREAK", votes=3)
        )
        strong = RevisedEngine().evaluate(
            snapshot(entry=4395.0, stop=4390.0, pattern="BULL_ENGULFING", votes=3)
        )
        self.assertEqual(weak.state, RevisedState.WATCH)
        self.assertEqual(strong.state, RevisedState.ENTRY_READY)


class GoldMRevisedStorageTests(unittest.TestCase):
    def test_events_are_idempotent_and_outcome_is_shadow_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RevisedStore(Path(directory) / "revised.db")
            decision = RevisedEngine().evaluate(snapshot())
            self.assertTrue(store.record_decision(decision))
            self.assertFalse(store.record_decision(decision))
            store.record_outcome(
                setup_id=store._setup_id(decision),
                status="TARGET",
                close_reason="TARGET",
                exit_price=4399.0,
                mfe=1.5,
                mae=-0.2,
            )
            pending = store.pending_notifications()
            self.assertEqual(len(pending), 2)
            payload = json.loads(pending[-1]["payload_json"])
            self.assertEqual(payload["close_reason"], "TARGET")
            self.assertFalse((Path(directory) / "revised.db").stat().st_size == 0)

    def test_replay_outcome_starts_after_entry_and_tracks_target(self) -> None:
        opened = datetime(2026, 8, 18, 12, 1, tzinfo=TZ)
        position = ReplayPosition(
            side=RevisedSide.BUY,
            trigger_time=opened - timedelta(minutes=5),
            opened_at=opened,
            entry=4392.0,
            stop=4390.0,
            target=4396.0,
            first_obstacle_r=2.0,
        )
        active = {RevisedSide.BUY: position}
        outcomes = []
        same_bar = RevisedBar(opened - timedelta(minutes=1), 4392, 4397, 4389, 4393)
        RevisedReplay._update_positions(active, outcomes, same_bar)
        self.assertEqual(outcomes, [])
        target_bar = RevisedBar(opened, 4393, 4396.5, 4392, 4396)
        RevisedReplay._update_positions(active, outcomes, target_bar)
        self.assertEqual(outcomes[0].result, "TARGET")
        self.assertEqual(outcomes[0].outcome_r, 2.0)


class GoldMRevisedSafetyTests(unittest.TestCase):
    def test_watch_notification_labels_soft_fail_and_retest(self) -> None:
        text = RevisedAdminNotifier.format_event(
            "REVISED_WATCH",
            {
                "side": "BUY",
                "entry_profile": "CORE",
                "validation_status": "SOFT_FAIL",
                "retest_count": 3,
                "reason": "M1_PENDING",
            },
        )
        self.assertIn("WATCH", text)
        self.assertIn("SOFT_FAIL", text)
        self.assertIn("Retest: 3", text)

    def test_mt5_adapter_and_notifier_have_no_trade_or_polling_api(self) -> None:
        adapter_source = inspect.getsource(RevisedMt5ReadOnlySource)
        notifier_source = inspect.getsource(RevisedAdminNotifier)
        for forbidden in ("order_send", "order_check", "positions_get", "orders_get"):
            self.assertNotIn(forbidden, adapter_source)
        self.assertNotIn("getUpdates", notifier_source)

    def test_mt5_source_reads_closed_series_and_shutdowns_without_trade_api(self) -> None:
        class FakeMt5:
            TIMEFRAME_M1 = 1
            TIMEFRAME_M5 = 5
            TIMEFRAME_H1 = 60
            TIMEFRAME_D1 = 1440

            def __init__(self) -> None:
                self.shutdown_called = False

            def initialize(self) -> bool:
                return True

            def shutdown(self) -> None:
                self.shutdown_called = True

            def last_error(self):
                return (0, "ok")

            def symbol_select(self, symbol, selected):
                return symbol == "GOLD.i#" and selected

            def symbol_info(self, symbol):
                return SimpleNamespace(point=0.01, digits=2, spread=20)

            def account_info(self):
                return SimpleNamespace(login=108098316, server="XMGlobal-MT5 5")

            def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
                base = 4390.0 + timeframe / 100.0
                return [
                    {
                        "time": int((datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=index)).timestamp()),
                        "open": base + index * 0.01,
                        "high": base + index * 0.01 + 1.0,
                        "low": base + index * 0.01 - 1.0,
                        "close": base + index * 0.01 + 0.2,
                        "tick_volume": 100,
                        "spread": 20,
                    }
                    for index in range(max(16, count))
                ]

        fake = FakeMt5()
        source = RevisedMt5ReadOnlySource(
            mt5_module=fake,
            config=__import__("goldm_revised.mt5_source", fromlist=["RevisedMt5Config"]).RevisedMt5Config(
                symbol="GOLD.i#",
                server_timezone=TZ,
            ),
        )
        snapshot_value = source.snapshot(side=RevisedSide.BUY)
        self.assertEqual(snapshot_value.symbol, "GOLD.i#")
        self.assertEqual(snapshot_value.m1_bars[-1].time.utcoffset(), timedelta(hours=3))
        source.close()
        self.assertTrue(fake.shutdown_called)


if __name__ == "__main__":
    unittest.main()
