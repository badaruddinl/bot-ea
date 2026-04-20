from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.validation import (  # noqa: E402
    build_promotion_audit_record,
    export_promotion_audit_markdown,
    PromotionCandidate,
    PromotionGateThresholds,
    TradeRecord,
    evaluate_cost_realism,
    evaluate_promotion_gate,
    summarize_execution_quality,
    summarize_trades,
)


class ValidationTests(unittest.TestCase):
    def test_summary_metrics(self) -> None:
        start = datetime(2026, 4, 20, 9, 0, 0)
        trades = [
            TradeRecord("EURUSD", "session_breakout", "buy", start, start + timedelta(minutes=10), 50.0, 25.0, 10.0),
            TradeRecord("EURUSD", "session_breakout", "sell", start + timedelta(minutes=15), start + timedelta(minutes=25), -25.0, 25.0, 12.0),
        ]
        summary = summarize_trades(trades, starting_equity=1000.0)
        self.assertEqual(summary.total_trades, 2)
        self.assertAlmostEqual(summary.win_rate, 0.5)
        self.assertGreater(summary.profit_factor, 1.0)
        self.assertGreaterEqual(summary.total_commission_cash, 0.0)

    def test_cost_realism_warning(self) -> None:
        start = datetime(2026, 4, 20, 9, 0, 0)
        trades = [
            TradeRecord("EURUSD", "session_breakout", "buy", start, start + timedelta(minutes=10), 50.0, 25.0, 30.0),
        ]
        warnings = evaluate_cost_realism(trades, spread_threshold_points=20.0)
        self.assertTrue(warnings)

    def test_execution_quality_summary(self) -> None:
        start = datetime(2026, 4, 20, 9, 0, 0)
        trades = [
            TradeRecord(
                "EURUSD",
                "session_breakout",
                "buy",
                start,
                start + timedelta(minutes=10),
                50.0,
                25.0,
                10.0,
                commission_cash=1.0,
                swap_cash=0.5,
                slippage_points=1.5,
                fill_latency_ms=120.0,
            ),
            TradeRecord(
                "EURUSD",
                "session_breakout",
                "sell",
                start + timedelta(minutes=20),
                start + timedelta(minutes=35),
                -10.0,
                25.0,
                12.0,
                commission_cash=1.2,
                swap_cash=0.0,
                slippage_points=2.5,
                fill_latency_ms=140.0,
            ),
        ]
        quality = summarize_execution_quality(trades, rejected_orders=1, total_order_attempts=3)
        self.assertEqual(quality.total_trade_records, 2)
        self.assertAlmostEqual(quality.reject_rate, 1 / 3)
        self.assertGreater(quality.average_slippage_points, 0.0)
        self.assertGreater(quality.average_fill_latency_ms, 0.0)

    def test_promotion_gate_rejects_weak_challenger(self) -> None:
        start = datetime(2026, 4, 20, 9, 0, 0)
        champion_trades = [
            TradeRecord("EURUSD", "session_breakout", "buy", start, start + timedelta(minutes=10), 40.0, 20.0, 8.0),
            TradeRecord("EURUSD", "session_breakout", "sell", start + timedelta(minutes=15), start + timedelta(minutes=30), 20.0, 20.0, 9.0),
        ] * 20
        challenger_trades = [
            TradeRecord(
                "EURUSD",
                "session_breakout",
                "buy",
                start,
                start + timedelta(minutes=10),
                -5.0,
                20.0,
                18.0,
                slippage_points=6.0,
                fill_latency_ms=250.0,
            ),
        ] * 30
        champion = PromotionCandidate(
            label="champion",
            out_of_sample_summary=summarize_trades(champion_trades, starting_equity=1000.0),
            execution_quality=summarize_execution_quality(champion_trades, rejected_orders=0, total_order_attempts=40),
        )
        challenger = PromotionCandidate(
            label="challenger",
            out_of_sample_summary=summarize_trades(challenger_trades, starting_equity=1000.0),
            execution_quality=summarize_execution_quality(challenger_trades, rejected_orders=6, total_order_attempts=36),
        )
        decision = evaluate_promotion_gate(
            champion,
            challenger,
            thresholds=PromotionGateThresholds(
                min_oos_trade_count=20,
                min_oos_expectancy_r=0.05,
                min_oos_profit_factor=1.05,
                max_oos_drawdown_pct=20.0,
                max_average_entry_spread_points=15.0,
                max_average_slippage_points=5.0,
                max_reject_rate=0.10,
            ),
        )
        self.assertFalse(decision.approved)
        self.assertTrue(decision.reasons)

    def test_promotion_audit_markdown_includes_thresholds_and_artifacts(self) -> None:
        start = datetime(2026, 4, 20, 9, 0, 0)
        champion_trades = [
            TradeRecord("EURUSD", "session_breakout", "buy", start, start + timedelta(minutes=10), 20.0, 20.0, 8.0),
        ] * 30
        challenger_trades = [
            TradeRecord("EURUSD", "session_breakout", "buy", start, start + timedelta(minutes=10), 25.0, 20.0, 7.0),
        ] * 30
        champion = PromotionCandidate(
            label="champion",
            out_of_sample_summary=summarize_trades(champion_trades, starting_equity=1000.0),
            execution_quality=summarize_execution_quality(champion_trades, rejected_orders=1, total_order_attempts=31),
            parameter_profile="baseline-v1",
            dataset_label="wf-2026q1",
        )
        challenger = PromotionCandidate(
            label="challenger",
            out_of_sample_summary=summarize_trades(challenger_trades, starting_equity=1000.0),
            execution_quality=summarize_execution_quality(challenger_trades, rejected_orders=0, total_order_attempts=30),
            parameter_profile="candidate-v2",
            dataset_label="wf-2026q2",
        )
        thresholds = PromotionGateThresholds(
            min_oos_trade_count=25,
            min_oos_expectancy_r=0.1,
            min_oos_profit_factor=1.05,
            max_oos_drawdown_pct=10.0,
            max_average_entry_spread_points=20.0,
            max_average_slippage_points=3.0,
            max_reject_rate=0.1,
        )
        decision = evaluate_promotion_gate(champion, challenger, thresholds=thresholds)
        audit = build_promotion_audit_record(
            champion,
            challenger,
            decision,
            thresholds=thresholds,
            notes=["reviewed in weekly tuning"],
            artifact_refs=["artifacts/oos_windows.json", "artifacts/promotion_decision.json"],
        )
        markdown = export_promotion_audit_markdown(audit)
        self.assertIn("## Thresholds Used", markdown)
        self.assertIn("min_oos_trade_count: 25", markdown)
        self.assertIn("candidate-v2", markdown)
        self.assertIn("wf-2026q2", markdown)
        self.assertIn("artifacts/oos_windows.json", markdown)
        self.assertIn("reviewed in weekly tuning", markdown)


if __name__ == "__main__":
    unittest.main()
