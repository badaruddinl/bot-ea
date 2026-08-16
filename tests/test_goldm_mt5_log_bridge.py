from __future__ import annotations

import base64
import sys
import tempfile
import os
import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldm_signal.notify import Mt5LogBridge, parse_mt5_log_line
from goldm_signal.storage import SignalStore
from goldm_signal.strategy import SetupState


def _origin_fields(
    *, scope: str = "demo", login: str = "108098316", server: str = "XMGlobal-MT5 5"
) -> str:
    encoded_server = base64.urlsafe_b64encode(server.encode("utf-8")).decode("ascii").rstrip("=")
    return (
        f"accountScope={scope} accountLogin={login} "
        f"originServerB64={encoded_server}"
    )


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
    "fibonacciReaction=4384.50 m1Confirmed=true retestBars=2 "
    + _origin_fields()
)
CANCELLED = (
    "SNIPER_EARLY_CANCELLED id=GOLD.i#-SELL-4400.00-2026.08.13 13:00 "
    "status=CANCELLED autoEntry=false confidenceEarly=62 reason=ENTRY_DISTANCE_EXCEEDED"
)


class GoldMMt5LogBridgeTests(unittest.TestCase):
    def test_ea_structured_events_emit_frozen_account_origin_metadata(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "mt5"
            / "Experts"
            / "bot-ea"
            / "GoldMSniperParity.mq5"
        ).read_text(encoding="utf-8")
        markers = (
            "SNIPER_CONFIG",
            "SNIPER_EARLY_CANDIDATE",
            "SNIPER_EARLY_PROMOTED",
            "SNIPER_SIGNAL",
            "SNIPER_EARLY_CANCELLED",
            "SNIPER_OUTCOME",
            "SNIPER_DIAGNOSTIC",
            "SNIPER_PERFORMANCE",
        )
        metadata = (
            "accountScope=%s accountLogin=%I64d originServerB64=%s"
        )
        for marker in markers:
            with self.subTest(marker=marker):
                literal_start = source.index(f'"{marker} ')
                literal_end = source.index('",', literal_start)
                self.assertIn(metadata, source[literal_start:literal_end])
        self.assertIn(
            "g_candidateId = BuildCandidateId();\n      CaptureCandidateAccountOrigin();",
            source,
        )
        self.assertIn(
            "g_activeAccountScope = g_candidateAccountScope;", source
        )
        self.assertIn("g_activeServerB64 = g_candidateServerB64;", source)
        self.assertIn(
            "g_candidateSetupUtcEpoch = ServerTimeToUtcEpoch(g_breakoutTime);",
            source,
        )
        self.assertIn(
            "g_activeSetupUtcEpoch = g_candidateSetupUtcEpoch;", source
        )
        self.assertNotIn(
            "ServerTimeToUtcEpoch(g_breakoutTime), GeneratedUtcEpoch()", source
        )

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
            "🕒 Dibuat: 13 Agu 2026 • 19:15 WIB (UTC+7)",
            event.telegram_text,
        )
        self.assertIn("• Setup M15: 13 Agu 2026 • 19:15 WIB (UTC+7)", event.telegram_text)
        self.assertTrue(
            event.telegram_text.endswith(
                "🆔 GOLD.i#-BUY-4379.22-2026.08.13 19:15 WIB"
            )
        )

    def test_entry_ready_message_uses_scannable_sections(self) -> None:
        event = parse_mt5_log_line(SIGNAL)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertIn("🔔 ENTRY READY", event.telegram_text)
        self.assertIn("• Entry: 4380.10", event.telegram_text)
        self.assertIn("• Lot: menunggu sizing MT5", event.telegram_text)
        self.assertIn("• Risiko estimasi: menunggu sizing MT5", event.telegram_text)
        self.assertIn("Approval Telegram hanya memberi akses notifikasi", event.telegram_text)

    def test_parser_marks_duplicate_fields_without_hiding_event(self) -> None:
        event = parse_mt5_log_line(
            SIGNAL + " strategyVersion=1.72 strategyVersion=9.99"
        )

        assert event is not None
        self.assertEqual(event.event_type, "SNIPER_SIGNAL")
        self.assertIn("strategyVersion", event.fields["_duplicateFields"])

    def test_strategy_direction_and_run_lineage_metadata_are_preserved(self) -> None:
        line = SIGNAL.replace(
            "autoEntryEligible=true",
            (
                "strategy=GOLDM_SNIPER_PARITY strategyVersion=1.72 "
                "directionProfile=BULL_ONLY runId=research-abc strategyMode=3 "
                "autoEntryEligible=true"
            ),
        )

        event = parse_mt5_log_line(line)

        assert event is not None
        self.assertEqual(event.fields["strategy"], "GOLDM_SNIPER_PARITY")
        self.assertEqual(event.fields["strategyVersion"], "1.72")
        self.assertEqual(event.fields["directionProfile"], "BULL_ONLY")
        self.assertEqual(event.fields["runId"], "research-abc")
        self.assertEqual(event.fields["strategyMode"], "3")

    def test_explicit_utc_epochs_override_broker_timestamp(self) -> None:
        line = (
            SIGNAL
            + " setupUtcEpoch=1786608900 generatedUtcEpoch=1786616580 "
            "serverUtcOffsetMinutes=180 validUntilUtcEpoch=1786616880 maxHoldingMinutes=1440"
        )
        event = parse_mt5_log_line(line)
        assert event is not None
        self.assertEqual(event.occurred_at, datetime.fromtimestamp(1786608900, tz=timezone.utc))
        self.assertEqual(event.generated_at, datetime.fromtimestamp(1786616580, tz=timezone.utc))
        self.assertNotEqual(event.occurred_at, event.generated_at)
        self.assertIn("Berlaku sampai", event.telegram_text)

    def test_broker_offset_fallback_does_not_treat_server_time_as_utc(self) -> None:
        event = parse_mt5_log_line(SIGNAL, server_utc_offset_minutes=180)
        assert event is not None
        self.assertEqual(event.occurred_at.hour, 9)

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
            self.assertEqual(promoted.state, SetupState.ACTIVE_SIGNAL)
            self.assertEqual(cancelled.state, SetupState.CANCELLED)

    def test_lifecycle_directory_accepts_only_matching_ea_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_directory = root / "MQL5" / "Logs"
            log_directory.mkdir(parents=True)
            old_log = log_directory / "20260814.log"
            current_log = log_directory / "20260815.log"
            old_log.write_text(SIGNAL + " runId=prod-session-old00\n", encoding="utf-8")
            current_log.write_text(
                "\n".join(
                    [
                        SIGNAL + " runId=research-session-0001",
                        SIGNAL + " runId=prod-session-20260815",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            os.utime(old_log, (1, 1))
            os.utime(current_log, (2, 2))
            store = SignalStore(root / "signal.db")
            store.initialize()
            bridge = Mt5LogBridge(
                store,
                log_directories=[log_directory],
                required_run_id="prod-session-20260815",
                account_context_provider=lambda: {
                    "login": "108098316",
                    "server": "XMGlobal-MT5 5",
                    "is_live": False,
                },
            )

            self.assertEqual(
                bridge.discover_log_paths(),
                [old_log.resolve(), current_log.resolve()],
            )
            self.assertEqual(bridge.run_once(), (2, 3, 1))
            pending = store.pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(
                pending[0]["payload"]["source_run_id"],
                "prod-session-20260815",
            )
            self.assertEqual(
                Path(pending[0]["payload"]["source_log_path"]),
                current_log.resolve(),
            )
            self.assertEqual(pending[0]["payload"]["account_scope"], "demo")
            self.assertEqual(pending[0]["payload"]["audience"], "approved")
            self.assertEqual(pending[0]["payload"]["account_login"], "108098316")
            self.assertEqual(
                pending[0]["payload"]["account_server"], "XMGlobal-MT5 5"
            )
            self.assertTrue(
                pending[0]["payload"]["event_account_binding_verified"]
            )
            self.assertEqual(
                pending[0]["payload"]["event_origin_account_server"],
                "XMGlobal-MT5 5",
            )
            self.assertEqual(
                pending[0]["payload"]["current_account_server"],
                "XMGlobal-MT5 5",
            )
            health = store.notification_health()["bridge"]
            self.assertEqual(health["matched_events"], 1)
            self.assertEqual(health["mismatched_events"], 2)
            self.assertNotIn("prod-session-20260815", str(health))

    def test_real_backlog_ingested_while_demo_is_never_viewer_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260815.log"
            session_id = "prod-session-real-backlog"
            real_origin = _origin_fields(
                scope="live", login="900000001", server="Broker REAL Server"
            )
            line = SIGNAL.replace(_origin_fields(), real_origin)
            log_path.write_text(f"{line} runId={session_id}\n", encoding="utf-8")
            store = SignalStore(root / "signal.db")
            store.initialize()

            bridge = Mt5LogBridge(
                store,
                log_paths=[log_path],
                required_run_id=session_id,
                account_context_provider=lambda: {
                    "login": "108098316",
                    "server": "XMGlobal-MT5 5",
                    "is_live": False,
                },
            )

            self.assertEqual(bridge.run_once(), (1, 1, 1))
            payload = store.pending()[0]["payload"]
            self.assertEqual(payload["account_scope"], "live")
            self.assertEqual(payload["account_login"], "900000001")
            self.assertEqual(payload["account_server"], "Broker REAL Server")
            self.assertEqual(payload["current_account_scope"], "demo")
            self.assertEqual(payload["audience"], "admin_only")
            self.assertFalse(payload["event_account_binding_verified"])
            self.assertIn("event origin account is live", payload["account_context_error"])
            self.assertIn("scope mismatch", payload["account_context_error"])
            self.assertTrue(
                payload["text"].startswith("⛔ EVENT ACCOUNT BINDING DIBLOKIR")
            )
            self.assertIn("hanya untuk audit admin", payload["text"])
            self.assertNotIn(session_id, payload["text"])
            self.assertNotIn(
                real_origin.split("originServerB64=", 1)[1], payload["text"]
            )
            health = store.notification_health()["bridge"]
            self.assertEqual(health["last_account_context_result"], "failure")
            self.assertEqual(health["provider_failures"], 1)

    def test_demo_origin_with_same_login_and_spaced_server_is_viewer_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260815.log"
            session_id = "prod-session-demo-match"
            log_path.write_text(f"{SIGNAL} runId={session_id}\n", encoding="utf-8")
            store = SignalStore(root / "signal.db")
            store.initialize()
            bridge = Mt5LogBridge(
                store,
                log_paths=[log_path],
                required_run_id=session_id,
                account_context_provider=lambda: {
                    "login": 108098316,
                    "server": "XMGlobal-MT5 5",
                    "is_live": False,
                },
            )

            self.assertEqual(bridge.run_once(), (1, 1, 1))
            payload = store.pending()[0]["payload"]
            self.assertEqual(payload["audience"], "approved")
            self.assertTrue(payload["event_account_binding_verified"])
            self.assertNotIn("account_context_error", payload)
            health = store.notification_health()["bridge"]
            self.assertEqual(health["last_account_context_result"], "ok")
            self.assertEqual(health["provider_failures"], 0)

    def test_noncanonical_runtime_symbol_is_admin_only_and_never_viewer_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260815.log"
            session_id = "prod-session-wrong-symbol"
            wrong_symbol = SIGNAL.replace("GOLD.i#", "XAUUSD")
            log_path.write_text(
                f"{wrong_symbol} runId={session_id}\n", encoding="utf-8"
            )
            store = SignalStore(root / "signal.db")
            store.initialize()
            bridge = Mt5LogBridge(
                store,
                log_paths=[log_path],
                required_run_id=session_id,
                expected_symbol="GOLD.i#",
                account_context_provider=lambda: {
                    "login": "108098316",
                    "server": "XMGlobal-MT5 5",
                    "is_live": False,
                },
            )

            self.assertEqual(bridge.run_once(), (1, 1, 1))
            payload = store.pending()[0]["payload"]
            self.assertEqual(payload["event_symbol"], "XAUUSD")
            self.assertEqual(payload["expected_symbol"], "GOLD.i#")
            self.assertEqual(payload["audience"], "admin_only")
            self.assertFalse(payload["event_account_binding_verified"])
            self.assertIn(
                "canonical runtime symbol", payload["account_context_error"]
            )
            self.assertTrue(
                payload["text"].startswith("⛔ EVENT ACCOUNT BINDING DIBLOKIR")
            )

    def test_account_server_binding_is_case_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260815.log"
            session_id = "prod-session-server-case"
            log_path.write_text(f"{SIGNAL} runId={session_id}\n", encoding="utf-8")
            store = SignalStore(root / "signal.db")
            store.initialize()
            bridge = Mt5LogBridge(
                store,
                log_paths=[log_path],
                required_run_id=session_id,
                account_context_provider=lambda: {
                    "login": "108098316",
                    "server": "xmglobal-mt5 5",
                    "is_live": False,
                },
            )

            self.assertEqual(bridge.run_once(), (1, 1, 1))
            payload = store.pending()[0]["payload"]
            self.assertFalse(payload["event_account_binding_verified"])
            self.assertEqual(payload["audience"], "admin_only")
            self.assertIn("server mismatch", payload["account_context_error"])

    def test_idle_account_switch_to_live_turns_bridge_health_to_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260815.log"
            session_id = "prod-session-idle-switch"
            log_path.write_text(f"{SIGNAL} runId={session_id}\n", encoding="utf-8")
            store = SignalStore(root / "signal.db")
            store.initialize()
            account = {
                "login": "108098316",
                "server": "XMGlobal-MT5 5",
                "is_live": False,
            }
            probes = 0

            def provider() -> dict[str, object]:
                nonlocal probes
                probes += 1
                return dict(account)

            bridge = Mt5LogBridge(
                store,
                log_paths=[log_path],
                required_run_id=session_id,
                account_context_provider=provider,
            )
            self.assertEqual(bridge.run_once(), (1, 1, 1))
            self.assertEqual(
                store.notification_health()["bridge"]["last_account_context_result"],
                "ok",
            )

            account.update(
                login="900000001", server="Broker REAL Server", is_live=True
            )
            self.assertEqual(bridge.run_once(), (1, 0, 0))
            health = store.notification_health()["bridge"]
            self.assertEqual(health["last_account_context_result"], "failure")
            self.assertEqual(health["provider_failures"], 1)
            self.assertIsNotNone(health["last_provider_failure_at"])
            self.assertEqual(probes, 2)

    def test_missing_or_noncanonical_origin_metadata_is_admin_only(self) -> None:
        cases = {
            "missing": SIGNAL.replace(" " + _origin_fields(), ""),
            "padded_server": SIGNAL.replace(
                _origin_fields(), _origin_fields() + "="
            ),
            "duplicate_scope": SIGNAL + " accountScope=demo",
        }
        for label, line in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                log_path = root / "20260815.log"
                session_id = f"prod-session-invalid-{label}"
                log_path.write_text(f"{line} runId={session_id}\n", encoding="utf-8")
                store = SignalStore(root / "signal.db")
                store.initialize()
                bridge = Mt5LogBridge(
                    store,
                    log_paths=[log_path],
                    required_run_id=session_id,
                    account_context_provider=lambda: {
                        "login": "108098316",
                        "server": "XMGlobal-MT5 5",
                        "is_live": False,
                    },
                )

                self.assertEqual(bridge.run_once(), (1, 1, 1))
                payload = store.pending()[0]["payload"]
                self.assertEqual(payload["audience"], "admin_only")
                self.assertFalse(payload["event_account_binding_verified"])
                self.assertTrue(payload["account_context_error"])
                if label == "duplicate_scope":
                    self.assertIn(
                        "security metadata has duplicate fields",
                        payload["account_context_error"],
                    )

    def test_duplicate_run_id_is_rejected_regardless_of_field_order(self) -> None:
        session_id = "prod-session-duplicate-run"
        cases = (
            f"{SIGNAL} runId=attacker-session runId={session_id}",
            f"{SIGNAL} runId={session_id} runId=attacker-session",
        )
        for index, line in enumerate(cases):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                log_path = root / "20260815.log"
                log_path.write_text(line + "\n", encoding="utf-8")
                store = SignalStore(root / "signal.db")
                store.initialize()
                bridge = Mt5LogBridge(
                    store,
                    log_paths=[log_path],
                    required_run_id=session_id,
                    account_context_provider=lambda: {
                        "login": "108098316",
                        "server": "XMGlobal-MT5 5",
                        "is_live": False,
                    },
                )

                self.assertEqual(bridge.run_once(), (1, 1, 0))
                self.assertEqual(store.pending(), [])
                health = store.notification_health()["bridge"]
                self.assertEqual(health["matched_events"], 0)
                self.assertEqual(health["mismatched_events"], 1)

    def test_duplicate_setup_id_is_rejected_before_setup_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260815.log"
            session_id = "prod-session-duplicate-id"
            line = (
                f"{SIGNAL} runId={session_id} "
                "id=GOLD.i#-SELL-9999.99-2026.08.13 12:16"
            )
            log_path.write_text(line + "\n", encoding="utf-8")
            store = SignalStore(root / "signal.db")
            store.initialize()
            bridge = Mt5LogBridge(
                store,
                log_paths=[log_path],
                required_run_id=session_id,
                account_context_provider=lambda: {
                    "login": "108098316",
                    "server": "XMGlobal-MT5 5",
                    "is_live": False,
                },
            )

            self.assertEqual(bridge.run_once(), (1, 1, 0))
            self.assertEqual(store.pending(), [])
            self.assertIsNone(
                store.load_setup("GOLD.i#-BUY-4379.22-2026.08.13 12:15")
            )

    def test_lifecycle_session_token_rejects_unset_or_short_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SignalStore(root / "signal.db")
            store.initialize()
            with self.assertRaises(ValueError):
                Mt5LogBridge(store, log_paths=[], required_run_id="UNSET")
            with self.assertRaises(ValueError):
                Mt5LogBridge(store, log_paths=[], required_run_id="short")

    def test_restart_after_midnight_consumes_older_outcome_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_directory = root / "MQL5" / "Logs"
            log_directory.mkdir(parents=True)
            old_log = log_directory / "20260814.log"
            new_log = log_directory / "20260815.log"
            session_id = "prod-session-midnight-01"
            old_log.write_text(f"{SIGNAL} runId={session_id}\n", encoding="utf-8")
            new_log.write_text("terminal startup\n", encoding="utf-8")
            store = SignalStore(root / "signal.db")
            store.initialize()
            account = lambda: {
                "login": "108098316",
                "server": "XMGlobal-MT5 5",
                "is_live": False,
            }
            first = Mt5LogBridge(
                store,
                log_directories=[log_directory],
                required_run_id=session_id,
                account_context_provider=account,
            )
            self.assertEqual(first.run_once(), (2, 2, 1))

            outcome = (
                "SNIPER_OUTCOME id=GOLD.i#-BUY-4379.22-2026.08.13 12:15 "
                "status=CLOSED side=BUY result=TARGET outcomeR=3.0 entry=4380.10 "
                "exitPrice=4397.80 durationMinutes=42 "
                f"runId={session_id}"
            )
            with old_log.open("a", encoding="utf-8") as handle:
                handle.write(outcome + "\n")

            restarted = Mt5LogBridge(
                store,
                log_directories=[log_directory],
                required_run_id=session_id,
                account_context_provider=account,
            )
            self.assertEqual(restarted.run_once(), (2, 1, 1))
            self.assertEqual(restarted.run_once(), (2, 0, 0))
            outcomes = [
                row
                for row in store.recent_events(limit=20)
                if row["event_type"] == "SNIPER_OUTCOME"
            ]
            self.assertEqual(len(outcomes), 1)
            self.assertEqual(
                Path(outcomes[0]["payload"]["source_log_path"]), old_log.resolve()
            )

    def test_same_path_truncate_and_regrow_resets_cursor_without_replaying(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260815.log"
            session_id = "prod-session-truncate-regrow"
            first_line = f"{SIGNAL} runId={session_id}"
            log_path.write_text(first_line + "\n", encoding="utf-8")
            original_size = log_path.stat().st_size
            store = SignalStore(root / "signal.db")
            store.initialize()
            bridge = Mt5LogBridge(
                store,
                log_paths=[log_path],
                required_run_id=session_id,
                account_context_provider=lambda: {
                    "login": "108098316",
                    "server": "XMGlobal-MT5 5",
                    "is_live": False,
                },
            )
            self.assertEqual(bridge.run_once(), (1, 1, 1))

            second_line = first_line.replace(
                "GOLD.i#-BUY-4379.22-2026.08.13 12:15",
                "GOLD.i#-BUY-4388.88-2026.08.13 12:30",
            )
            # Truncate and regrow the same inode. The new event is entirely
            # before the old byte offset; a size-only cursor would skip it.
            log_path.write_text(
                second_line + "\n" + ("replacement-padding " * original_size) + "\n",
                encoding="utf-8",
            )
            self.assertGreaterEqual(log_path.stat().st_size, original_size)

            self.assertEqual(bridge.run_once(), (1, 2, 1))
            self.assertEqual(bridge.run_once(), (1, 0, 0))
            self.assertEqual(len(store.pending()), 2)
            cursor = store.mt5_log_cursor(log_path.resolve())
            assert cursor is not None
            self.assertEqual(cursor["anchor_offset"], cursor["byte_offset"])
            self.assertRegex(cursor["anchor_sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(cursor["file_identity"])

    def test_same_path_atomic_replacement_resets_cursor_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260815.log"
            replacement = root / "replacement.log"
            session_id = "prod-session-path-replaced"
            first_line = f"{SIGNAL} runId={session_id}"
            log_path.write_text(first_line + "\n", encoding="utf-8")
            original_size = log_path.stat().st_size
            store = SignalStore(root / "signal.db")
            store.initialize()
            bridge = Mt5LogBridge(
                store,
                log_paths=[log_path],
                required_run_id=session_id,
                account_context_provider=lambda: {
                    "login": "108098316",
                    "server": "XMGlobal-MT5 5",
                    "is_live": False,
                },
            )
            self.assertEqual(bridge.run_once(), (1, 1, 1))

            second_line = first_line.replace(
                "GOLD.i#-BUY-4379.22-2026.08.13 12:15",
                "GOLD.i#-BUY-4399.99-2026.08.13 12:45",
            )
            replacement.write_text(
                second_line + "\n" + ("atomic-replacement " * original_size) + "\n",
                encoding="utf-8",
            )
            os.replace(replacement, log_path)

            self.assertEqual(bridge.run_once(), (1, 2, 1))
            self.assertEqual(bridge.run_once(), (1, 0, 0))
            setup_ids = {row["setup_id"] for row in store.pending()}
            self.assertEqual(
                setup_ids,
                {
                    "GOLD.i#-BUY-4379.22-2026.08.13 12:15",
                    "GOLD.i#-BUY-4399.99-2026.08.13 12:45",
                },
            )

    def test_cursor_reset_replay_cannot_regress_closed_setup_to_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260815.log"
            session_id = "prod-session-terminal-replay"
            signal = f"{SIGNAL} runId={session_id}"
            outcome = (
                "SNIPER_OUTCOME id=GOLD.i#-BUY-4379.22-2026.08.13 12:15 "
                "status=CLOSED side=BUY result=TARGET outcomeR=3.0 entry=4380.10 "
                "exitPrice=4397.80 durationMinutes=42 "
                f"{_origin_fields()} runId={session_id}"
            )
            original = signal + "\n" + outcome + "\n"
            log_path.write_text(original, encoding="utf-8")
            store = SignalStore(root / "signal.db")
            store.initialize()
            bridge = Mt5LogBridge(
                store,
                log_paths=[log_path],
                required_run_id=session_id,
                account_context_provider=lambda: {
                    "login": "108098316",
                    "server": "XMGlobal-MT5 5",
                    "is_live": False,
                },
            )
            self.assertEqual(bridge.run_once(), (1, 2, 2))
            setup = store.load_setup("GOLD.i#-BUY-4379.22-2026.08.13 12:15")
            assert setup is not None
            self.assertEqual(setup.state, SetupState.CLOSED)

            # Force continuity reset and replay only the earlier SIGNAL. The
            # duplicate outbox key and terminal setup state must remain atomic.
            log_path.write_text(
                signal + "\n" + ("regrow " * len(original)) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(bridge.run_once(), (1, 2, 0))
            replayed = store.load_setup("GOLD.i#-BUY-4379.22-2026.08.13 12:15")
            assert replayed is not None
            self.assertEqual(replayed.state, SetupState.CLOSED)
            self.assertEqual(len(store.pending()), 2)

    def test_identity_conflict_is_quarantined_without_starving_later_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260815.log"
            session_id = "prod-session-identity-poison"
            early = (
                f"{EARLY} {_origin_fields()} serverUtcOffsetMinutes=180 "
                f"runId={session_id}"
            )
            log_path.write_text(early + "\n", encoding="utf-8")
            store = SignalStore(root / "signal.db")
            store.initialize()
            account = lambda: {
                "login": "108098316",
                "server": "XMGlobal-MT5 5",
                "is_live": False,
            }
            first = Mt5LogBridge(
                store,
                log_paths=[log_path],
                required_run_id=session_id,
                account_context_provider=account,
            )
            self.assertEqual(first.run_once(), (1, 1, 1))

            # The same setup id with a conflicting server-time conversion is
            # permanently invalid. A correct later SIGNAL must still ingest.
            poison = f"{SIGNAL} serverUtcOffsetMinutes=0 runId={session_id}"
            valid = f"{SIGNAL} serverUtcOffsetMinutes=180 runId={session_id}"
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(poison + "\n" + valid + "\n")

            restarted = Mt5LogBridge(
                store,
                log_paths=[log_path],
                required_run_id=session_id,
                account_context_provider=account,
            )
            self.assertEqual(restarted.run_once(), (1, 2, 2))
            health = store.notification_health()["bridge"]
            self.assertEqual(health["provider_failures"], 1)
            self.assertEqual(health["last_account_context_result"], "failure")
            self.assertEqual(restarted.run_once(), (1, 0, 0))

            events = store.pending(limit=20)
            self.assertEqual(
                [row["event_type"] for row in events],
                [
                    "SNIPER_EARLY_CANDIDATE",
                    "MT5_SETUP_IDENTITY_REJECTED",
                    "SNIPER_SIGNAL",
                ],
            )
            rejected = events[1]["payload"]
            self.assertEqual(rejected["audience"], "admin_only")
            self.assertFalse(rejected["event_account_binding_verified"])
            self.assertIn("breakout_at", rejected["account_context_error"])
            setup = store.load_setup(
                "GOLD.i#-BUY-4379.22-2026.08.13 12:15"
            )
            assert setup is not None
            self.assertEqual(
                setup.breakout_at,
                datetime(2026, 8, 13, 9, 15, tzinfo=timezone.utc),
            )

    def test_transient_storage_error_is_not_quarantined_or_advanced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260815.log"
            log_path.write_text(SIGNAL + "\n", encoding="utf-8")
            store = SignalStore(root / "signal.db")
            store.initialize()
            bridge = Mt5LogBridge(store, log_paths=[log_path])
            original_ingest = store.ingest_mt5_event

            def fail_ingest(**_kwargs: object) -> bool:
                raise sqlite3.OperationalError("database is temporarily busy")

            store.ingest_mt5_event = fail_ingest  # type: ignore[method-assign]
            with self.assertRaisesRegex(
                sqlite3.OperationalError, "temporarily busy"
            ):
                bridge.run_once()
            self.assertIsNone(store.mt5_log_cursor(log_path.resolve()))
            self.assertEqual(store.pending(), [])

            store.ingest_mt5_event = original_ingest  # type: ignore[method-assign]
            self.assertEqual(bridge.run_once(), (1, 1, 1))

    def test_account_probe_failure_persists_event_for_admin_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260815.log"
            session_id = "prod-session-probe-fail"
            log_path.write_text(f"{SIGNAL} runId={session_id}\n", encoding="utf-8")
            store = SignalStore(root / "signal.db")
            store.initialize()

            def failed_probe() -> dict[str, object]:
                raise RuntimeError("terminal unavailable")

            bridge = Mt5LogBridge(
                store,
                log_paths=[log_path],
                required_run_id=session_id,
                account_context_provider=failed_probe,
            )
            self.assertEqual(bridge.run_once(), (1, 1, 1))
            payload = store.pending()[0]["payload"]
            self.assertEqual(payload["account_scope"], "demo")
            self.assertEqual(payload["account_login"], "108098316")
            self.assertEqual(payload["account_server"], "XMGlobal-MT5 5")
            self.assertEqual(payload["current_account_scope"], "unknown")
            self.assertEqual(payload["current_account_login"], "")
            self.assertEqual(payload["current_account_server"], "")
            self.assertEqual(payload["audience"], "admin_only")
            self.assertFalse(payload["event_account_binding_verified"])
            self.assertIn(
                "account context provider failed", payload["account_context_error"]
            )
            health = store.notification_health()["bridge"]
            self.assertEqual(health["provider_failures"], 1)
            self.assertIsNotNone(health["last_provider_failure_at"])

    def test_outcome_is_ingested_with_same_setup_id(self) -> None:
        outcome = (
            "SNIPER_OUTCOME id=GOLD.i#-BUY-4379.22-2026.08.13 12:15 status=CLOSED "
            "side=BUY result=TARGET outcomeR=3.0 entry=4380.10 exitPrice=4397.80 "
            "durationMinutes=42 setupUtcEpoch=1786608900 generatedUtcEpoch=1786616580 "
            "serverUtcOffsetMinutes=180 source=MODEL_SIMULATION"
        )
        event = parse_mt5_log_line(outcome)
        assert event is not None
        self.assertEqual(event.event_type, "SNIPER_OUTCOME")
        self.assertIn("HASIL MODEL STRATEGI", event.telegram_text)
        self.assertIn("Bukan", event.telegram_text.title())

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

    def test_split_utf8_codepoint_is_buffered_without_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260815.log"
            session_id = "prod-session-split-utf8"
            encoded = f"{SIGNAL} note=café runId={session_id}\n".encode("utf-8")
            split_at = encoded.index("é".encode("utf-8")) + 1
            log_path.write_bytes(encoded[:split_at])
            store = SignalStore(root / "signal.db")
            store.initialize()
            bridge = Mt5LogBridge(
                store,
                log_paths=[log_path],
                required_run_id=session_id,
                account_context_provider=lambda: {
                    "login": "108098316",
                    "server": "XMGlobal-MT5 5",
                    "is_live": False,
                },
            )

            self.assertEqual(bridge.run_once(), (1, 0, 0))
            first_cursor = store.mt5_log_cursor(log_path.resolve())
            assert first_cursor is not None
            self.assertEqual(first_cursor["raw_tail_b64"], "ww==")
            with log_path.open("ab") as handle:
                handle.write(encoded[split_at:])

            self.assertEqual(bridge.run_once(), (1, 1, 1))
            self.assertEqual(bridge.run_once(), (1, 0, 0))
            event = store.pending()[0]
            self.assertEqual(event["payload"]["fields"]["note"], "café")
            self.assertNotIn("�", str(event["payload"]))

    def test_split_utf16_code_unit_and_newline_are_ingested_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "20260815.log"
            session_id = "prod-session-split-utf16"
            encoded = b"\xff\xfe" + f"{SIGNAL} runId={session_id}\r\n".encode(
                "utf-16-le"
            )
            split_at = len(encoded) - 3
            log_path.write_bytes(encoded[:split_at])
            store = SignalStore(root / "signal.db")
            store.initialize()
            bridge = Mt5LogBridge(
                store,
                log_paths=[log_path],
                required_run_id=session_id,
                account_context_provider=lambda: {
                    "login": "108098316",
                    "server": "XMGlobal-MT5 5",
                    "is_live": False,
                },
            )

            self.assertEqual(bridge.run_once(), (1, 0, 0))
            first_cursor = store.mt5_log_cursor(log_path.resolve())
            assert first_cursor is not None
            self.assertEqual(first_cursor["encoding"], "utf-16-le")
            self.assertEqual(first_cursor["raw_tail_b64"], "DQ==")
            with log_path.open("ab") as handle:
                handle.write(encoded[split_at:])

            self.assertEqual(bridge.run_once(), (1, 1, 1))
            self.assertEqual(bridge.run_once(), (1, 0, 0))
            self.assertEqual(len(store.pending()), 1)
            final_cursor = store.mt5_log_cursor(log_path.resolve())
            assert final_cursor is not None
            self.assertEqual(final_cursor["raw_tail_b64"], "")

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
