from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldm_signal.notify import Mt5LogBridge, parse_mt5_log_line
from goldm_signal.storage import SignalStore
from goldm_signal.strategy import SetupState


EARLY = (
    "SNIPER_EARLY_CANDIDATE id=GOLD.i#-BUY-4379.22-2026.08.13 12:15 "
    "status=WATCH_ONLY autoEntry=false side=BUY level=4379.22 watchPrice=4380.00 "
    "invalidation=4374.00 confidence=64 threshold=>60.0 m5Votes=3 "
    "pattern=MORNING_STAR fibonacciReaction=4384.50 next=M1_AND_FINAL_RISK_CHECK"
)
PROMOTED = (
    "SNIPER_EARLY_PROMOTED id=GOLD.i#-BUY-4379.22-2026.08.13 12:15 "
    "status=ENTRY_READY confidenceEarly=64 scoreFinal=78"
)
SIGNAL = (
    "SNIPER_SIGNAL id=GOLD.i#-BUY-4379.22-2026.08.13 12:15 "
    "status=ENTRY_READY autoEntryEligible=true side=BUY level=4379.22 entry=4380.10 "
    "stop=4374.20 target=4397.80 riskTF=M15 entryDistanceATR=0.200 stopDistanceATR=0.600 "
    "projectedR=3.000 score=78 m5Votes=3 pattern=MORNING_STAR fibonacciAligned=true "
    "fibonacciReaction=4384.50 m1Confirmed=true retestBars=2"
)
CANCELLED = (
    "SNIPER_EARLY_CANCELLED id=GOLD.i#-SELL-4400.00-2026.08.13 13:00 "
    "status=CANCELLED autoEntry=false confidenceEarly=62 reason=ENTRY_DISTANCE_EXCEEDED"
)


class GoldMMt5LogBridgeTests(unittest.TestCase):
    def test_parser_preserves_setup_id_with_embedded_timestamp_space(self) -> None:
        event = parse_mt5_log_line(f"2026.08.13\tExpert\t{EARLY}")
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.setup_id, "GOLD.i#-BUY-4379.22-2026.08.13 12:15")
        self.assertEqual(event.fields["confidence"], "64")
        self.assertIn("Belum entry", event.telegram_text)
        self.assertIn("📍 LEVEL PANTAU\n• Trigger: 4379.22", event.telegram_text)
        self.assertIn("📊 VALIDASI", event.telegram_text)
        self.assertIn(
            "🕒 Waktu sinyal: 13 Agu 2026 • 19:15 WIB (UTC+7)",
            event.telegram_text,
        )
        self.assertTrue(
            event.telegram_text.endswith(
                "🆔 GOLD.i#-BUY-4379.22-2026.08.13 19:15 WIB"
            )
        )

    def test_entry_ready_message_uses_scannable_sections(self) -> None:
        event = parse_mt5_log_line(SIGNAL)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(
            event.telegram_text,
            "\n".join(
                [
                    "🔔 ENTRY READY",
                    "GOLD.i#  •  BUY",
                    "🕒 Waktu sinyal: 13 Agu 2026 • 19:15 WIB (UTC+7)",
                    "",
                    "💰 RENCANA TRADE",
                    "• Entry: 4380.10",
                    "• Stop Loss: 4374.20",
                    "• Take Profit: 4397.80",
                    "",
                    "📊 VALIDASI FINAL",
                    "• Score: 78/100",
                    "• Projected R: 3.000R",
                    "• M5 votes: 3",
                    "• Konfirmasi M1: ✅ Ya",
                    "",
                    "⚠️ STATUS ORDER",
                    "Sinyal akun demo — bukan konfirmasi bahwa order broker sudah terbuka.",
                    "Periksa tab Trade di MT5 untuk status eksekusi.",
                    "",
                    "🆔 GOLD.i#-BUY-4379.22-2026.08.13 19:15 WIB",
                ]
            ),
        )

    def test_utf16_log_is_tailed_enqueued_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260813.log"
            log_path.write_bytes(("\ufeff" + "\r\n".join([EARLY, PROMOTED, SIGNAL, CANCELLED]) + "\r\n").encode("utf-16-le"))
            store = SignalStore(root / "signal.db")
            store.initialize()
            bridge = Mt5LogBridge(store, log_paths=[log_path])

            files, lines, enqueued = bridge.run_once()
            self.assertEqual((files, lines, enqueued), (1, 4, 4))
            self.assertEqual(len(store.pending()), 4)
            self.assertEqual(bridge.run_once(), (1, 0, 0))

            promoted = store.load_setup("GOLD.i#-BUY-4379.22-2026.08.13 12:15")
            cancelled = store.load_setup("GOLD.i#-SELL-4400.00-2026.08.13 13:00")
            assert promoted is not None and cancelled is not None
            self.assertEqual(promoted.state, SetupState.CONFIRMED_A_PLUS)
            self.assertEqual(cancelled.state, SetupState.CANCELLED)

    def test_partial_line_waits_for_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260813.log"
            log_path.write_bytes(("\ufeff" + EARLY).encode("utf-16-le"))
            store = SignalStore(root / "signal.db")
            store.initialize()
            bridge = Mt5LogBridge(store, log_paths=[log_path])

            self.assertEqual(bridge.run_once(), (1, 0, 0))
            with log_path.open("ab") as handle:
                handle.write("\r\n".encode("utf-16-le"))
            self.assertEqual(bridge.run_once(), (1, 1, 1))

    def test_debug_notification_uses_full_outbox_path_without_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            bridge = Mt5LogBridge(store, log_paths=[])
            added = bridge.enqueue_debug_notification(
                now=datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
            )
            self.assertTrue(added)
            pending = store.pending()
            self.assertEqual(len(pending), 1)
            self.assertTrue(pending[0]["payload"]["debug"])
            self.assertIn("bukan entry", pending[0]["payload"]["text"])


if __name__ == "__main__":
    unittest.main()
