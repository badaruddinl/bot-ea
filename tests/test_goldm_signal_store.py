from __future__ import annotations

import tempfile
import unittest
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldm_signal.notify import OutboxWorker
from goldm_signal.storage import SignalStore
from goldm_signal.strategy import SetupRecord, SetupState, SetupStateMachine, build_setup_id


class GoldMSignalStoreTests(unittest.TestCase):
    def test_setup_state_is_persistent_and_outbox_is_deduplicated(self) -> None:
        breakout_at = datetime(2026, 8, 12, 14, 15, tzinfo=timezone.utc)
        setup_id = build_setup_id("GOLD.i#", "BUY", 4320.0, breakout_at)
        record = SetupRecord(setup_id, "GOLD.i#", "BUY", 4320.0, breakout_at)
        machine = SetupStateMachine(record)
        machine.transition(SetupState.LEVEL_APPROACH, reason="price approached H1 confluence")
        machine.transition(SetupState.BREAKOUT_DETECTED, reason="closed M15 breakout")
        machine.transition(SetupState.WAITING_RETEST, reason="wait for acceptance above level")

        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            store.save_setup(record)

            first = store.enqueue(
                setup_id=setup_id,
                event_type="A_PLUS_SIGNAL",
                payload={"text": "test signal"},
            )
            duplicate = store.enqueue(
                setup_id=setup_id,
                event_type="A_PLUS_SIGNAL",
                payload={"text": "duplicate signal"},
            )

            self.assertTrue(first)
            self.assertFalse(duplicate)
            loaded = store.load_setup(setup_id)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.state, SetupState.WAITING_RETEST)
            self.assertEqual(setup_id, "GOLD.i#-BUY-4320-20260812T1415")

    def test_outbox_worker_retries_failure_and_marks_success(self) -> None:
        breakout_at = datetime(2026, 8, 12, 14, 15, tzinfo=timezone.utc)
        setup_id = build_setup_id("GOLD.i#", "BUY", 4320.0, breakout_at)
        record = SetupRecord(setup_id, "GOLD.i#", "BUY", 4320.0, breakout_at)

        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            store.save_setup(record)
            store.enqueue(setup_id=setup_id, event_type="CANCELLED", payload={"text": "cancel"})
            attempts = 0

            def flaky_sender(event: dict[str, object]) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("temporary network error")

            worker = OutboxWorker(store, flaky_sender)
            self.assertEqual(worker.run_once(), (0, 1))
            self.assertEqual(len(store.pending()), 1)
            self.assertEqual(worker.run_once(), (1, 0))
            self.assertEqual(store.pending(), [])

    def test_retest_expires_on_tenth_closed_m15_bar(self) -> None:
        breakout_at = datetime(2026, 8, 12, 14, 15, tzinfo=timezone.utc)
        record = SetupRecord("id", "GOLD.i#", "BUY", 4320.0, breakout_at, state=SetupState.WAITING_RETEST)
        machine = SetupStateMachine(record, maximum_retest_bars=10)

        for _ in range(9):
            machine.record_retest_bar()
        self.assertEqual(record.state, SetupState.WAITING_RETEST)
        machine.record_retest_bar()
        self.assertEqual(record.state, SetupState.EXPIRED)

    def test_early_candidate_is_watch_only_until_final_promotion(self) -> None:
        breakout_at = datetime(2026, 8, 12, 14, 15, tzinfo=timezone.utc)
        record = SetupRecord("id", "GOLD.i#", "BUY", 4320.0, breakout_at)
        machine = SetupStateMachine(record)
        machine.transition(SetupState.LEVEL_APPROACH, reason="channel level approached")
        machine.transition(SetupState.BREAKOUT_DETECTED, reason="M15 channel breakout")
        machine.transition(SetupState.WAITING_RETEST, reason="wait for M15 retest")
        machine.transition(SetupState.RETEST_VALID, reason="M15 retest accepted")
        machine.transition(SetupState.WAITING_M5_TRIGGER, reason="wait for M5 evidence")
        machine.transition(SetupState.EARLY_CANDIDATE, reason="preliminary confidence above 60")

        self.assertEqual(record.state, SetupState.EARLY_CANDIDATE)
        machine.transition(SetupState.CONFIRMED_A_PLUS, reason="M1 and final risk checks passed")
        self.assertEqual(record.state, SetupState.CONFIRMED_A_PLUS)

    def test_early_candidate_can_cancel_without_becoming_entry(self) -> None:
        breakout_at = datetime(2026, 8, 12, 14, 15, tzinfo=timezone.utc)
        record = SetupRecord(
            "id", "GOLD.i#", "SELL", 4320.0, breakout_at, state=SetupState.EARLY_CANDIDATE
        )
        machine = SetupStateMachine(record)

        machine.transition(SetupState.CANCELLED, reason="entry distance exceeded M15 ATR limit")
        self.assertEqual(record.state, SetupState.CANCELLED)


if __name__ == "__main__":
    unittest.main()
