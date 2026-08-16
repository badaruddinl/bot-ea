from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from goldm_signal.config import (
    EntrySidePolicy,
    NotificationSideFilter,
    StrategyEngine,
)
from goldm_signal.notify.trade_lifecycle import TradeLifecycleConfig
from goldm_signal.storage.database import SignalStore


class GoldMSidePolicyTests(unittest.TestCase):
    def test_strategy_engine_is_immutable_d7_identity(self) -> None:
        self.assertIs(
            StrategyEngine.parse("D7_CHANNEL_CONTINUATION"),
            StrategyEngine.D7_CHANNEL_CONTINUATION,
        )
        for ambiguous in ("ALL", "BULL_ONLY", "BEAR_ONLY", "BUY_ONLY"):
            with self.subTest(ambiguous=ambiguous):
                with self.assertRaisesRegex(ValueError, "D7_CHANNEL_CONTINUATION"):
                    StrategyEngine.parse(ambiguous)

    def test_entry_side_policy_is_not_an_engine_selector(self) -> None:
        self.assertTrue(EntrySidePolicy.ALL.allows("buy"))
        self.assertTrue(EntrySidePolicy.ALL.allows("SELL"))
        self.assertTrue(EntrySidePolicy.BUY_ONLY.allows("buy"))
        self.assertFalse(EntrySidePolicy.BUY_ONLY.allows("sell"))
        self.assertTrue(EntrySidePolicy.SELL_ONLY.allows("sell"))
        self.assertFalse(EntrySidePolicy.SELL_ONLY.allows("buy"))
        self.assertFalse(EntrySidePolicy.ALL.allows("sideways"))
        for legacy in ("BULL_ONLY", "BEAR_ONLY"):
            with self.subTest(legacy=legacy):
                with self.assertRaisesRegex(ValueError, "entry side policy"):
                    EntrySidePolicy.parse(legacy)

    def test_notification_filter_is_a_separate_type(self) -> None:
        self.assertIs(
            NotificationSideFilter.parse("buy-only"),
            NotificationSideFilter.BUY_ONLY,
        )
        self.assertNotIsInstance(
            NotificationSideFilter.BUY_ONLY,
            EntrySidePolicy,
        )

    def test_legacy_ambiguous_environment_keys_are_rejected(self) -> None:
        for name in (
            "GOLDM_DIRECTION_PROFILE",
            "GOLDM_NOTIFICATION_DIRECTION_PROFILE",
        ):
            with self.subTest(name=name), patch.dict(
                os.environ, {name: "ALL"}, clear=True
            ):
                with self.assertRaisesRegex(ValueError, "ambiguous"):
                    TradeLifecycleConfig.from_env()

    def test_legacy_runtime_key_blocks_new_entries_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = SignalStore(Path(temp) / "goldm.db")
            store.initialize()
            store.set_runtime_settings(
                {"trade.direction_profile": "ALL"}, updated_by="migration-test"
            )
            config = TradeLifecycleConfig.from_sources(
                store,
                fallback=TradeLifecycleConfig(),
            )
            self.assertIsNone(config.entry_side_policy)

    def test_core_v2_keeps_production_172_strategy_defaults(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (
            root / "mt5" / "Experts" / "bot-ea" / "GoldMSniperParity.mq5"
        ).read_text(encoding="utf-8")
        self.assertIn("input int    InpStrategyMode = 0;", source)
        self.assertIn("input int    InpBreakoutChannelBars = 8;", source)
        self.assertNotIn("InpDirectionProfile", source)
        self.assertNotIn("DetectBullEngulfReclaim", source)
        self.assertNotIn("DetectBearSingleRejection", source)

    def test_telegram_labels_cannot_imply_engine_switching(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "goldm_signal"
            / "notify"
            / "approval.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Engine aktif (read-only)", source)
        self.assertIn("Entry: BUY", source)
        self.assertIn("Entry: SELL", source)
        self.assertNotIn("Entry: BULL", source)
        self.assertNotIn("Entry: BEAR", source)
        self.assertNotIn("ctl:direction:", source)


if __name__ == "__main__":
    unittest.main()
