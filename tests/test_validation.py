from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.validation import (  # noqa: E402
    build_runtime_validation_report,
    build_trade_records_from_runtime,
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
    def test_build_trade_records_from_runtime_merges_ledger_and_fill_telemetry(self) -> None:
        position_events = [
            {
                "broker_position_id": "ord-1",
                "symbol": "EURUSD",
                "side": "buy",
                "status": "OPENED",
                "entry_price": 1.1010,
                "opened_at": "2026-04-20T09:00:05Z",
                "commission_cash": 0.5,
                "payload_json": {
                    "strategy_family": "breakout",
                    "risk_cash": 50.0,
                    "entry_spread_points": 9.0,
                    "quoted_price": 1.1008,
                },
            },
            {
                "broker_position_id": "ord-1",
                "symbol": "EURUSD",
                "side": "buy",
                "status": "CLOSED",
                "entry_price": 1.1010,
                "exit_price": 1.1025,
                "closed_at": "2026-04-20T09:12:00Z",
                "realized_pnl_cash": 75.0,
                "commission_cash": 0.7,
                "swap_cash": -0.2,
                "payload_json": '{"exit_reason":"tp_hit"}',
            },
        ]
        execution_events = [
            {
                "execution_id": 1,
                "attempt_id": "attempt-1",
                "phase": "PRECHECK",
                "status": "PRECHECK_OK",
                "symbol": "EURUSD",
                "side": "buy",
                "order_ticket": "ord-1",
                "polled_at": "2026-04-20T09:00:04Z",
            },
            {
                "execution_id": 2,
                "attempt_id": "attempt-1",
                "phase": "FILL",
                "status": "FILLED",
                "symbol": "EURUSD",
                "side": "buy",
                "order_ticket": "ord-1",
                "deal_ticket": "deal-1",
                "quoted_price": 1.1008,
                "executed_price": 1.1010,
                "slippage_points": 1.2,
                "fill_latency_ms": 180.0,
                "polled_at": "2026-04-20T09:00:05Z",
            },
        ]

        trades = build_trade_records_from_runtime(position_events, execution_events)

        self.assertEqual(len(trades), 1)
        trade = trades[0]
        self.assertEqual(trade.symbol, "EURUSD")
        self.assertEqual(trade.strategy_family, "breakout")
        self.assertEqual(trade.side, "buy")
        self.assertEqual(trade.entry_time, datetime.fromisoformat("2026-04-20T09:00:05+00:00"))
        self.assertEqual(trade.exit_time, datetime.fromisoformat("2026-04-20T09:12:00+00:00"))
        self.assertAlmostEqual(trade.pnl_cash, 75.0)
        self.assertAlmostEqual(trade.risk_cash, 50.0)
        self.assertAlmostEqual(trade.entry_spread_points, 9.0)
        self.assertAlmostEqual(trade.quoted_entry_price or 0.0, 1.1008)
        self.assertAlmostEqual(trade.realized_entry_price or 0.0, 1.1010)
        self.assertAlmostEqual(trade.commission_cash, 1.2)
        self.assertAlmostEqual(trade.swap_cash, -0.2)
        self.assertAlmostEqual(trade.slippage_points, 1.2)
        self.assertAlmostEqual(trade.fill_latency_ms, 180.0)
        self.assertEqual(trade.exit_reason, "tp_hit")
        self.assertFalse(trade.notes)

    def test_build_runtime_validation_report_uses_terminal_attempts_and_bridge_warnings(self) -> None:
        position_events = [
            {
                "broker_position_id": "ord-1",
                "symbol": "EURUSD",
                "side": "buy",
                "status": "OPENED",
                "entry_price": 1.1002,
                "opened_at": "2026-04-20T09:00:00Z",
                "commission_cash": 0.3,
                "payload_json": {"strategy_family": "breakout", "risk_cash": 25.0, "entry_spread_points": 6.0},
            },
            {
                "broker_position_id": "ord-1",
                "symbol": "EURUSD",
                "side": "buy",
                "status": "CLOSED",
                "entry_price": 1.1002,
                "exit_price": 1.1015,
                "closed_at": "2026-04-20T09:14:00Z",
                "realized_pnl_cash": 30.0,
                "commission_cash": 0.4,
                "payload_json": {"exit_reason": "target_hit"},
            },
            {
                "broker_position_id": "ord-2",
                "symbol": "GBPUSD",
                "side": "sell",
                "status": "OPENED",
                "entry_price": 1.2500,
                "opened_at": "2026-04-20T09:20:00Z",
                "payload_json": {"risk_cash": 15.0},
            },
            {
                "broker_position_id": "ord-3",
                "symbol": "USDJPY",
                "side": "buy",
                "status": "CLOSED",
                "entry_price": 155.10,
                "exit_price": 154.90,
                "opened_at": "2026-04-20T09:30:00Z",
                "closed_at": "2026-04-20T09:40:00Z",
                "realized_pnl_cash": -10.0,
                "commission_cash": 0.1,
                "payload_json": {"risk_cash_budget": 20.0, "entry_spread_points": 7.0},
            },
        ]
        execution_events = [
            {
                "execution_id": 1,
                "attempt_id": "attempt-1",
                "phase": "INTENT",
                "status": "READY",
                "symbol": "EURUSD",
                "side": "buy",
                "order_ticket": "ord-1",
                "polled_at": "2026-04-20T09:00:00Z",
            },
            {
                "execution_id": 2,
                "attempt_id": "attempt-1",
                "phase": "FILL",
                "status": "FILLED",
                "symbol": "EURUSD",
                "side": "buy",
                "order_ticket": "ord-1",
                "quoted_price": 1.1000,
                "executed_price": 1.1002,
                "slippage_points": 0.5,
                "fill_latency_ms": 80.0,
                "polled_at": "2026-04-20T09:00:01Z",
            },
            {
                "execution_id": 3,
                "attempt_id": "attempt-2",
                "phase": "PRECHECK",
                "status": "PRECHECK_REJECTED",
                "symbol": "EURUSD",
                "side": "sell",
                "retcode": "10030",
                "polled_at": "2026-04-20T09:05:00Z",
            },
            {
                "execution_id": 4,
                "attempt_id": "attempt-3",
                "phase": "GUARD",
                "status": "GUARD_REJECTED",
                "symbol": "GBPUSD",
                "side": "buy",
                "polled_at": "2026-04-20T09:10:00Z",
            },
            {
                "execution_id": 5,
                "attempt_id": "attempt-4",
                "phase": "FILL",
                "status": "FILLED",
                "symbol": "AUDUSD",
                "side": "buy",
                "order_ticket": "ord-x",
                "quoted_price": 0.6500,
                "executed_price": 0.6503,
                "slippage_points": 1.0,
                "fill_latency_ms": 120.0,
                "polled_at": "2026-04-20T09:50:00Z",
            },
        ]

        report = build_runtime_validation_report(
            position_events,
            execution_events,
            starting_equity=1000.0,
        )

        self.assertEqual(len(report.trade_records), 2)
        self.assertEqual(report.validation_summary.total_trades, 2)
        self.assertEqual(report.execution_quality.total_trade_records, 2)
        self.assertEqual(report.execution_quality.total_order_attempts, 4)
        self.assertEqual(report.execution_quality.rejected_orders, 2)
        self.assertAlmostEqual(report.execution_quality.reject_rate, 0.5)
        self.assertAlmostEqual(report.execution_quality.average_fill_latency_ms, 40.0)
        self.assertAlmostEqual(report.validation_summary.total_commission_cash, 0.8)
        self.assertTrue(any("open position event skipped" in warning for warning in report.warnings))
        self.assertTrue(any("closed trade missing fill telemetry linkage" in warning for warning in report.warnings))
        self.assertTrue(any("filled execution attempt was not matched to a ledger position" in warning for warning in report.warnings))
        self.assertIn(
            "fill telemetry missing; runtime ledger used as fallback",
            report.trade_records[1].notes,
        )
        self.assertTrue(any("open position event skipped" in warning for warning in report.validation_summary.warnings))
        self.assertTrue(any("filled execution attempt was not matched to a ledger position" in warning for warning in report.execution_quality.warnings))

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
