from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "research-goldm-prod-baseline.py"
)
SPEC = importlib.util.spec_from_file_location("goldm_prod_baseline_research", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GoldMProductionBaselineResearchTests(unittest.TestCase):
    def test_export_is_read_only_and_omits_account_identity(self) -> None:
        server_timezone = timezone(timedelta(hours=3))
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "signals.db"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE setups (
                    setup_id TEXT PRIMARY KEY, symbol TEXT, side TEXT, level REAL,
                    breakout_at TEXT, state TEXT, reason TEXT
                );
                CREATE TABLE signal_outbox (
                    id INTEGER PRIMARY KEY, setup_id TEXT, event_type TEXT,
                    created_at TEXT, sent_at TEXT, payload_json TEXT
                );
                """
            )
            connection.execute(
                "INSERT INTO setups VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "GOLD.i#-BUY-4400-20260818T1403",
                    "GOLD.i#",
                    "BUY",
                    4400.0,
                    "2026-08-18T11:03:00+00:00",
                    "CLOSED",
                    "SNIPER_OUTCOME",
                ),
            )
            payload = {
                "generated_at_utc": "2026-08-18T11:03:00+00:00",
                "setup_at_utc": "2026-08-18T11:03:00+00:00",
                "event_account_login": "108098316",
                "fields": {
                    "entry": "4395.00",
                    "target": "4405.00",
                    "outcomeR": "1.0",
                    "accountLogin": "108098316",
                    "originServerB64": "secretish",
                },
            }
            connection.execute(
                "INSERT INTO signal_outbox VALUES (?, ?, ?, ?, ?, ?)",
                (
                    1,
                    "GOLD.i#-BUY-4400-20260818T1403",
                    "SNIPER_SIGNAL",
                    "2026-08-18T11:03:00+00:00",
                    None,
                    json.dumps(payload),
                ),
            )
            connection.commit()
            connection.close()

            evidence = MODULE.load_evidence(
                db_path,
                start=datetime(2026, 8, 18, tzinfo=server_timezone),
                end=datetime(2026, 8, 19, tzinfo=server_timezone),
                server_timezone=server_timezone,
            )

        encoded = json.dumps(evidence)
        self.assertEqual(evidence["signal_side_counts"], {"BUY": 1})
        self.assertEqual(evidence["signals"][0]["target"], "4405.00")
        self.assertIn('"target": "4405.00"', encoded)
        self.assertNotIn("108098316", encoded)
        self.assertNotIn("secretish", encoded)


if __name__ == "__main__":
    unittest.main()
