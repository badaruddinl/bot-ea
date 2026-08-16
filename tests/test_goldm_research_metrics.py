from __future__ import annotations

import unittest

from goldm_signal.research_metrics import (
    BrokerCostEvidence,
    ResearchMetricsError,
    broker_cost_r,
    deflated_sharpe_ratio,
    moving_block_bootstrap_mean_ci,
    parse_research_log,
    probability_of_backtest_overfitting,
    superior_predictive_ability,
)


RUN_ID = "gmr-metrics-0001"
LINEAGE = (
    "strategy=GOLDM_SNIPER_PARITY strategyVersion=1.72 "
    f"directionProfile=ALL runId={RUN_ID} strategyMode=3"
)


def _signal(
    setup_id: str,
    *,
    side: str,
    entry: float,
    stop: float,
    setup_epoch: int,
) -> str:
    target = entry + 3 * abs(entry - stop) if side == "BUY" else entry - 3 * abs(entry - stop)
    return (
        f"SNIPER_SIGNAL id={setup_id} status=ENTRY_READY {LINEAGE} side={side} "
        f"entry={entry:.2f} stop={stop:.2f} target={target:.2f} projectedR=3.0000 "
        "score=80 m5Votes=3 pattern=TEST_PATTERN fibonacciAligned=true "
        "m1Confirmed=true "
        f"setupUtcEpoch={setup_epoch} generatedUtcEpoch={setup_epoch + 1}"
    )


def _outcome(
    setup_id: str,
    *,
    side: str,
    outcome_r: float,
    entry: float,
    exit_price: float,
    hit1: bool,
    hit2: bool,
    hit3: bool,
    setup_epoch: int,
    outcome_epoch: int,
    result: str,
) -> str:
    return (
        f"SNIPER_OUTCOME id={setup_id} status=CLOSED {LINEAGE} side={side} "
        f"result={result} outcomeR={outcome_r:.4f} entry={entry:.2f} "
        f"exitPrice={exit_price:.2f} stop=0.00 target=0.00 projectedR=3.0000 "
        f"hit1R={str(hit1).lower()} hit2R={str(hit2).lower()} "
        f"hit3R={str(hit3).lower()} mfeR={max(outcome_r, 0.0):.4f} "
        f"maeR={min(outcome_r, 0.0):.4f} durationMinutes=5 "
        f"setupUtcEpoch={setup_epoch} generatedUtcEpoch={outcome_epoch} "
        "source=MODEL_SIMULATION"
    )


def _complete_log() -> str:
    return "\n".join(
        [
            f"SNIPER_CONFIG {LINEAGE} signalOnly=true",
            _signal("one", side="BUY", entry=100.0, stop=99.0, setup_epoch=10),
            _outcome(
                "one",
                side="BUY",
                outcome_r=-1.0,
                entry=100.0,
                exit_price=99.0,
                hit1=False,
                hit2=False,
                hit3=False,
                setup_epoch=10,
                outcome_epoch=100,
                result="STOP",
            ),
            _signal("two", side="SELL", entry=200.0, stop=202.0, setup_epoch=20),
            _outcome(
                "two",
                side="SELL",
                outcome_r=2.0,
                entry=200.0,
                exit_price=196.0,
                hit1=True,
                hit2=True,
                hit3=False,
                setup_epoch=20,
                outcome_epoch=160,
                result="PROTECTED_STOP",
            ),
            _signal("three", side="BUY", entry=300.0, stop=297.0, setup_epoch=30),
            _outcome(
                "three",
                side="BUY",
                outcome_r=0.5,
                entry=300.0,
                exit_price=301.5,
                hit1=True,
                hit2=False,
                hit3=False,
                setup_epoch=30,
                outcome_epoch=220,
                result="M1_MANAGEMENT",
            ),
            (
                f"SNIPER_PERFORMANCE {LINEAGE} resolved=3 stopped=1 protectedStops=1 "
                "timedOut=0 m1ManagedExits=1 hit1R=2 hit2R=1 hit3R=0 "
                "P1=66.67 P2=33.33 P3=0.00 "
                "expectancyR=0.50000 totalR=1.50000 averageMFE_R=0.83333 "
                "averageMAE_R=-0.33333 averageProjectedR=3.00000 averageScore=80.00"
            ),
        ]
    )


class GoldMResearchMetricsTests(unittest.TestCase):
    def test_correlated_log_produces_pooled_and_side_metrics(self) -> None:
        parsed = parse_research_log(
            _complete_log(),
            expected_run_id=RUN_ID,
            expected_direction_profile="ALL",
            expected_strategy_mode=3,
        )
        metrics = parsed.metrics()

        self.assertEqual([trade.setup_id for trade in parsed.trades], ["one", "two", "three"])
        self.assertEqual(metrics.pooled.trades, 3)
        self.assertAlmostEqual(metrics.pooled.total_r, 1.5)
        self.assertAlmostEqual(metrics.pooled.mean_r or 0.0, 0.5)
        self.assertAlmostEqual(metrics.pooled.median_r or 0.0, 0.5)
        self.assertAlmostEqual(metrics.pooled.profit_factor or 0.0, 2.5)
        self.assertAlmostEqual(metrics.pooled.win_rate or 0.0, 2 / 3)
        self.assertAlmostEqual(metrics.pooled.payoff_ratio or 0.0, 1.25)
        self.assertAlmostEqual(metrics.pooled.maximum_drawdown_r, 1.0)
        self.assertEqual(metrics.pooled.maximum_loss_streak, 1)
        self.assertEqual(metrics.pooled.time_under_water_seconds, 60)
        self.assertEqual(metrics.by_side["BUY"].trades, 2)
        self.assertEqual(metrics.by_side["SELL"].trades, 1)
        self.assertAlmostEqual(metrics.hit_r1_rate or 0.0, 2 / 3)
        self.assertAlmostEqual(metrics.hit_r2_rate or 0.0, 1 / 3)
        self.assertEqual(
            metrics.exit_reasons,
            {"M1_MANAGEMENT": 1, "PROTECTED_STOP": 1, "STOP": 1},
        )
        self.assertEqual(metrics.pattern_counts, {"TEST_PATTERN": 3})
        self.assertAlmostEqual(metrics.average_score or 0.0, 80.0)
        self.assertAlmostEqual(parsed.trades[1].initial_risk_price, 2.0)

    def test_explicit_cost_stress_is_subtracted_once_per_trade(self) -> None:
        metrics = parse_research_log(
            _complete_log(), expected_run_id=RUN_ID
        ).metrics(per_trade_cost_r=0.1)

        self.assertAlmostEqual(metrics.pooled.total_r, 1.2)
        self.assertAlmostEqual(metrics.pooled.mean_r or 0.0, 0.4)
        self.assertAlmostEqual(metrics.per_trade_cost_r, 0.1)

    def test_stale_interleaved_run_is_rejected_not_filtered(self) -> None:
        polluted = _complete_log() + "\n" + _complete_log().replace(RUN_ID, "gmr-stale-0002")
        with self.assertRaisesRegex(ResearchMetricsError, "runId mismatch"):
            parse_research_log(polluted, expected_run_id=RUN_ID)

    def test_missing_duplicate_and_orphan_lifecycle_events_are_rejected(self) -> None:
        lines = _complete_log().splitlines()
        without_one_outcome = "\n".join(line for line in lines if not line.startswith("SNIPER_OUTCOME id=one"))
        with self.assertRaisesRegex(ResearchMetricsError, "signals without outcomes"):
            parse_research_log(without_one_outcome, expected_run_id=RUN_ID)

        duplicated_signal = next(
            line for line in lines if line.startswith("SNIPER_SIGNAL id=one")
        )
        duplicate = "\n".join([*lines[:-1], duplicated_signal, lines[-1]])
        with self.assertRaisesRegex(ResearchMetricsError, "duplicate SNIPER_SIGNAL"):
            parse_research_log(duplicate, expected_run_id=RUN_ID)

        orphan = "\n".join(
            line for line in lines if not line.startswith("SNIPER_SIGNAL id=one")
        )
        with self.assertRaisesRegex(ResearchMetricsError, "outcomes without signals"):
            parse_research_log(orphan, expected_run_id=RUN_ID)

    def test_event_order_and_duplicate_fields_fail_closed(self) -> None:
        lines = _complete_log().splitlines()
        signal_index = next(
            index for index, line in enumerate(lines) if line.startswith("SNIPER_SIGNAL id=one")
        )
        outcome_index = next(
            index for index, line in enumerate(lines) if line.startswith("SNIPER_OUTCOME id=one")
        )
        reordered = list(lines)
        reordered[signal_index], reordered[outcome_index] = (
            reordered[outcome_index],
            reordered[signal_index],
        )
        with self.assertRaisesRegex(ResearchMetricsError, "precedes its SNIPER_SIGNAL"):
            parse_research_log("\n".join(reordered), expected_run_id=RUN_ID)

        config_last = "\n".join(lines[1:] + lines[:1])
        with self.assertRaisesRegex(ResearchMetricsError, "SNIPER_CONFIG must be the first"):
            parse_research_log(config_last, expected_run_id=RUN_ID)

        truncated_tail = "\n".join(lines[:-1])
        with self.assertRaisesRegex(ResearchMetricsError, "SNIPER_PERFORMANCE must be the last"):
            parse_research_log(truncated_tail, expected_run_id=RUN_ID)

        duplicate_run_id = lines[0] + f" runId={RUN_ID}"
        duplicate_fields = "\n".join([duplicate_run_id, *lines[1:]])
        with self.assertRaisesRegex(ResearchMetricsError, "duplicate fields"):
            parse_research_log(duplicate_fields, expected_run_id=RUN_ID)

    def test_direction_and_performance_tampering_fail_closed(self) -> None:
        bull_only = _complete_log().replace("directionProfile=ALL", "directionProfile=BULL_ONLY")
        with self.assertRaisesRegex(ResearchMetricsError, "non-BUY"):
            parse_research_log(
                bull_only,
                expected_run_id=RUN_ID,
                expected_direction_profile="BULL_ONLY",
            )

        bad_total = _complete_log().replace("totalR=1.50000", "totalR=9.50000")
        with self.assertRaisesRegex(ResearchMetricsError, "totalR"):
            parse_research_log(bad_total, expected_run_id=RUN_ID)

        bad_hits = _complete_log().replace("hit2R=1 hit3R=0", "hit2R=2 hit3R=0")
        with self.assertRaisesRegex(ResearchMetricsError, "hit2R"):
            parse_research_log(bad_hits, expected_run_id=RUN_ID)

    def test_projected_r_accepts_only_the_ea_three_decimal_rounding_envelope(self) -> None:
        legitimate = _complete_log().replace(
            "averageProjectedR=3.00000", "averageProjectedR=3.00044"
        )
        parse_research_log(legitimate, expected_run_id=RUN_ID)

        impossible = _complete_log().replace(
            "averageProjectedR=3.00000", "averageProjectedR=3.00060"
        )
        with self.assertRaisesRegex(ResearchMetricsError, "averageProjectedR"):
            parse_research_log(impossible, expected_run_id=RUN_ID)

    def test_zero_trade_run_is_a_valid_explicit_result(self) -> None:
        log = "\n".join(
            [
                f"SNIPER_CONFIG {LINEAGE} signalOnly=true",
                (
                    f"SNIPER_PERFORMANCE {LINEAGE} resolved=0 stopped=0 protectedStops=0 "
                    "timedOut=0 m1ManagedExits=0 hit1R=0 hit2R=0 hit3R=0 "
                    "P1=0.00 P2=0.00 P3=0.00 "
                    "expectancyR=0.00000 totalR=0.00000 averageMFE_R=0.00000 "
                    "averageMAE_R=0.00000 averageProjectedR=0.00000 averageScore=0.00"
                ),
            ]
        )
        metrics = parse_research_log(log, expected_run_id=RUN_ID).metrics()
        self.assertEqual(metrics.pooled.trades, 0)
        self.assertIsNone(metrics.pooled.mean_r)
        self.assertIsNone(metrics.pooled.profit_factor)
        self.assertEqual(metrics.pooled.maximum_drawdown_r, 0.0)

    def test_moving_block_bootstrap_is_deterministic_and_validated(self) -> None:
        values = (-1.0, 0.5, 1.0, -0.25, 2.0, -0.5)
        first = moving_block_bootstrap_mean_ci(
            values, block_size=2, samples=500, seed=42
        )
        second = moving_block_bootstrap_mean_ci(
            values, block_size=2, samples=500, seed=42
        )
        self.assertEqual(first, second)
        self.assertLessEqual(first[0], sum(values) / len(values))
        self.assertGreaterEqual(first[1], sum(values) / len(values))

        with self.assertRaises(ResearchMetricsError):
            moving_block_bootstrap_mean_ci((), block_size=1)
        with self.assertRaises(ResearchMetricsError):
            moving_block_bootstrap_mean_ci(values, block_size=0)
        with self.assertRaises(ResearchMetricsError):
            moving_block_bootstrap_mean_ci(values, block_size=1.5)  # type: ignore[arg-type]

    def test_broker_cost_is_converted_from_cash_to_initial_risk_r(self) -> None:
        evidence = BrokerCostEvidence(
            volume_lots=0.1,
            point=0.01,
            tick_size=0.01,
            tick_value=1.0,
            spread_points=20.0,
            commission_per_lot_round_turn=7.0,
            swap_per_lot_round_turn=0.5,
            slippage_points=2.0,
        )
        self.assertAlmostEqual(
            broker_cost_r(entry=2000.0, initial_stop=1999.0, evidence=evidence),
            0.295,
        )
        with self.assertRaisesRegex(ResearchMetricsError, "non-zero initial risk"):
            broker_cost_r(entry=2000.0, initial_stop=2000.0, evidence=evidence)

    def test_selection_bias_diagnostics_are_deterministic_or_blocked(self) -> None:
        pbo_input = {
            "A0": (0.1, 0.2, -0.1, 0.3, 0.1, 0.2),
            "A1": (0.2, -0.2, 0.4, -0.1, 0.3, 0.0),
            "A2": (-0.1, 0.1, 0.0, 0.2, -0.2, 0.4),
        }
        self.assertEqual(
            probability_of_backtest_overfitting(pbo_input),
            probability_of_backtest_overfitting(pbo_input),
        )
        self.assertEqual(
            probability_of_backtest_overfitting({"A0": (1.0, 2.0)}).status,
            "BLOCKED",
        )

        outcomes = tuple((index % 7 - 2) / 10.0 for index in range(40))
        dsr = deflated_sharpe_ratio(outcomes, candidate_trials=3)
        self.assertEqual(dsr.status, "OK")
        self.assertEqual(deflated_sharpe_ratio(outcomes[:10], candidate_trials=3).status, "BLOCKED")

        differentials = {
            "A1": tuple((index % 5 - 1) / 20.0 for index in range(40)),
            "A2": tuple((index % 7 - 3) / 25.0 for index in range(40)),
        }
        spa = superior_predictive_ability(
            differentials, block_size=3, samples=500, seed=17
        )
        self.assertEqual(spa.status, "OK")
        self.assertEqual(
            spa,
            superior_predictive_ability(
                differentials, block_size=3, samples=500, seed=17
            ),
        )
        self.assertEqual(
            superior_predictive_ability(
                {"A1": differentials["A1"][:6]},
                block_size=2,
                samples=500,
            ).status,
            "BLOCKED",
        )


if __name__ == "__main__":
    unittest.main()
