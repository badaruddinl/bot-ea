from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GoldMRevisedRuntimeTests(unittest.TestCase):
    def test_config_is_isolated_and_buy_first(self) -> None:
        config = json.loads(
            (ROOT / "config" / "goldm-revised-shadow.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["strategy_id"], "GOLDM_REVISED")
        self.assertEqual(config["strategy_version"], "0.2.0")
        self.assertIn("goldm_revised_shadow", config["storage"]["db_path"])
        self.assertEqual(config["mt5"]["symbol"], "GOLD.i#")
        self.assertEqual(config["mt5"]["server_utc_offset_minutes"], 180)

    def test_runtime_has_no_cross_engine_imports_or_order_api(self) -> None:
        sources = "\n".join(
            (ROOT / "src" / "goldm_revised" / name).read_text(encoding="utf-8")
            for name in ("engine.py", "setup.py", "runtime.py", "replay.py", "mt5_source.py", "storage.py", "telegram.py")
        )
        self.assertNotIn("goldm_signal", sources)
        self.assertNotIn("goldm_bear", sources)
        for forbidden in ("order_send", "order_check", "positions_get", "orders_get", "getUpdates"):
            self.assertNotIn(forbidden, sources)

    def test_production_ea_source_is_still_exact_baseline(self) -> None:
        source = (ROOT / "mt5" / "Experts" / "bot-ea" / "GoldMSniperParity.mq5").read_text(
            encoding="utf-8"
        )
        self.assertIn('"GOLDM_SNIPER_PARITY"', source)
        self.assertNotIn('"GOLDM_REVISED"', source)

    def test_task_and_launcher_names_do_not_touch_production_worker(self) -> None:
        controller = (ROOT / "scripts" / "control-goldm-revised-shadow.ps1").read_text(
            encoding="utf-8"
        )
        registration = (ROOT / "scripts" / "register-goldm-revised-shadow.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("goldm revised shadow", controller)
        self.assertIn("goldm revised shadow", registration)
        self.assertNotIn("goldm telegram worker", controller)
        self.assertNotIn("control-goldm-worker.ps1", controller)
        self.assertIn("run-goldm-revised-shadow.py", registration)

    def test_bat_launchers_use_revised_runner_or_controller(self) -> None:
        run_bat = (ROOT / "scripts" / "run-goldm-revised-shadow.bat").read_text(encoding="utf-8")
        enable_bat = (ROOT / "scripts" / "enable-goldm-revised-shadow.bat").read_text(encoding="utf-8")
        disable_bat = (ROOT / "scripts" / "disable-goldm-revised-shadow.bat").read_text(encoding="utf-8")
        status_bat = (ROOT / "scripts" / "status-goldm-revised-shadow.bat").read_text(encoding="utf-8")
        self.assertIn("run-goldm-revised-shadow.py", run_bat)
        for source, action in ((enable_bat, "-Action Enable"), (disable_bat, "-Action Disable"), (status_bat, "-Action Status")):
            self.assertIn("control-goldm-revised-shadow.ps1", source)
            self.assertIn(action, source)
