from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from goldm_signal.research_policy import ResearchPurpose, StatisticalClassification
from goldm_signal.research_run import (
    ResearchCosts,
    ResearchRunSpec,
    TerminalDataMode,
    TerminalProbeResult,
    TerminalState,
    TesterSettings,
)
from goldm_signal.research_stage_a import (
    DEVELOPMENT_SEGMENTS,
    STAGE_A_CANDIDATES,
    AppendOnlyResearchRegistry,
    BaselineBinding,
    GateStatus,
    RegistryState,
    StageACell,
    StageAError,
    StageAOrchestrator,
    StageAPlan,
    evaluate_stage_a,
    load_stage_a_plan,
    portable_execution_lease,
    validate_stage_a_plan,
)


def _canonical_sha256(value: object) -> str:
    text = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StageAFixture:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.repository = self.root / "repo"
        self.terminal = self.root / "portable-terminal"
        self.artifacts = self.root / "artifacts"
        self.specs = self.root / "specs"
        for directory in (
            self.repository,
            self.artifacts,
            self.specs,
            self.terminal / "reports",
            self.terminal / "MQL5" / "Experts" / "bot-ea",
            self.terminal / "MQL5" / "Profiles" / "Tester",
            self.terminal / "Tester" / "logs",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.terminal_path = self.terminal / "terminal64.exe"
        self.terminal_path.write_bytes(b"terminal")
        self.ea_source = self.repository / "GoldMSniperParity.mq5"
        self.ea_source.write_text(
            "\n".join(
                (
                    "input int InpStrategyMode = 3;",
                    "input int InpDirectionProfile = 0;",
                    'input string InpResearchRunId = "";',
                    'input string InpExpectedSymbol = "GOLD_i_DEV_SAFE";',
                    "",
                )
            ),
            encoding="utf-8",
        )
        self.ea_binary = (
            self.terminal
            / "MQL5"
            / "Experts"
            / "bot-ea"
            / "GoldMSniperParity.ex5"
        )
        self.ea_binary.write_bytes(b"compiled-ea")
        self.compile_log = self.repository / "GoldMSniperParity.compile.log"
        self.compile_log.write_text("Result: 0 errors, 0 warnings\n", encoding="utf-8")
        self.symbol_evidence = self.repository / "symbol-spec-source.json"
        self.history_evidence = self.repository / "bounded-development-ticks.csv"
        self.dataset_manifest = self.repository / "bounded-development-dataset.json"
        self.dataset_source_evidence = self.repository / "bounded-development-source.json"
        self.dataset_authority = self.repository / "bounded-development-authority.txt"
        self.network_evidence = self.repository / "offline-firewall-proof.json"
        self.cost_source = self.repository / "broker-cost-source.json"
        self.symbol_evidence.write_text('{"source":"demo symbol metadata"}\n', encoding="utf-8")
        warmup_start = datetime(2021, 1, 1, 12, tzinfo=timezone.utc)
        evaluation_start = datetime(2022, 2, 28, tzinfo=timezone.utc)
        warmup_days = (evaluation_start.date() - warmup_start.date()).days
        history_times = [
            int((warmup_start + timedelta(days=index)).timestamp() * 1000)
            for index in range(warmup_days)
        ]
        history_times.extend(
            (
                1646006400000,
                1656374400000,
                1666915200000,
                1677542400000,
                1687910400000,
                1698451200000,
                1709078340000,
            )
        )
        self.history_evidence.write_text(
            "time_msc,bid,ask,last,volume,flags,volume_real\n"
            + "".join(
                f"{value},1999.90,2000.10,0,1,6,1.0\n"
                for value in history_times
            ),
            encoding="utf-8",
        )
        self.dataset_authority.write_text("approved test export\n", encoding="utf-8")
        source_payload = {
            "schema_version": 1,
            "status": "APPROVED_BOUNDED_OFFLINE_SOURCE",
            "evidence_id": "approved-goldm-stage-a-source",
            "attested_at": "2026-08-15T00:00:00Z",
            "provenance_kind": "SEALED_OFFLINE_EXPORT",
            "authority": "GoldM test authority",
            "capture_method": "EXACT_BOUNDED_TICK_EXPORT",
            "purpose": "Development",
            "statistical_classification": "DEVELOPMENT_SELECTION",
            "source_symbol": "GOLD.i#",
            "warmup_from_inclusive": "2021-01-01",
            "run_from_inclusive": "2022-02-28",
            "to_exclusive": "2024-02-28",
            "dataset_path": str(self.history_evidence),
            "dataset_sha256": _sha256(self.history_evidence),
            "authority_artifact_path": str(self.dataset_authority),
            "authority_artifact_sha256": _sha256(self.dataset_authority),
        }
        source_payload["evidence_sha256"] = _canonical_sha256(source_payload)
        self.dataset_source_evidence.write_text(
            json.dumps(source_payload, sort_keys=True), encoding="utf-8"
        )
        dataset_payload = {
            "schema_version": 2,
            "dataset_id": "goldm-development-ticks-v1",
            "registered_at": "2026-08-15T00:00:00Z",
            "purpose": "Development",
            "statistical_classification": "DEVELOPMENT_SELECTION",
            "custom_symbol": "GOLD_i_DEV_SAFE",
            "source_symbol": "GOLD.i#",
            "warmup_from_inclusive": "2021-01-01",
            "run_from_inclusive": "2022-02-28",
            "to_exclusive": "2024-02-28",
            "format": "MT5_TICKS_CSV_V1",
            "time_semantics": "UTC_HALF_OPEN",
            "row_count": len(history_times),
            "first_time_msc": history_times[0],
            "last_time_msc": 1709078340000,
            "dataset_path": str(self.history_evidence),
            "dataset_sha256": _sha256(self.history_evidence),
            "source_evidence_path": str(self.dataset_source_evidence),
            "source_evidence_sha256": _sha256(self.dataset_source_evidence),
        }
        dataset_payload["manifest_sha256"] = _canonical_sha256(dataset_payload)
        self.dataset_manifest.write_text(
            json.dumps(dataset_payload, sort_keys=True), encoding="utf-8"
        )
        self.network_evidence.write_text('{"offline":true}\n', encoding="utf-8")
        self.cost_source.write_text('{"source":"broker schedule"}\n', encoding="utf-8")
        self.cost_values = {
            "spread_model": "tester-current-spread",
            "commission_model": "declared",
            "swap_model": "declared",
            "slippage_model": "fixed-points",
            "execution_delay_ms": 25,
            "commission_per_lot_round_turn": 7.0,
            "slippage_points": 2.0,
            "spread_points": 20.0,
            "swap_per_lot_round_turn": 0.5,
            "reference_volume_lots": 0.1,
        }
        self.provenance_path = self.repository / "GoldMSniperParity.provenance.json"
        self.provenance_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "captured_at": "2026-08-15T00:00:00Z",
                    "broker_server": "Research-Broker",
                    "management_policy_version": "M1_R_LOCK_V1",
                    "symbol_specification": {
                        "symbol": "GOLD_i_DEV_SAFE",
                        "source_symbol": "GOLD.i#",
                        "is_custom": True,
                        "captured_at": "2026-08-15T00:00:00Z",
                        "capture_method": "MT5_DEMO_SYMBOL_METADATA",
                        "source_path": str(self.symbol_evidence),
                        "source_sha256": _sha256(self.symbol_evidence),
                        "digits": 2,
                        "point": 0.01,
                        "trade_tick_size": 0.01,
                        "trade_tick_value": 1.0,
                        "trade_contract_size": 100.0,
                        "volume_min": 0.01,
                        "volume_max": 100.0,
                        "volume_step": 0.01,
                        "currency_profit": "USD",
                        "currency_margin": "USD",
                    },
                    "history_declaration": {
                        "symbol": "GOLD_i_DEV_SAFE",
                        "source_symbol": "GOLD.i#",
                        "data_kind": "TICKS_UTC",
                        "warmup_from_inclusive": "2021-01-01",
                        "from_inclusive": "2022-02-28",
                        "to_exclusive": "2024-02-28",
                        "row_count": len(history_times),
                        "first_timestamp_utc": "2021-01-01T12:00:00Z",
                        "last_timestamp_utc": "2024-02-27T23:59:00Z",
                        "integrity_verified": True,
                        "captured_at": "2026-08-15T00:00:00Z",
                        "capture_method": "GUARDED_HALF_OPEN_EXPORT",
                        "source_path": str(self.history_evidence),
                        "source_sha256": _sha256(self.history_evidence),
                        "dataset_manifest_path": str(self.dataset_manifest),
                        "dataset_manifest_sha256": _sha256(self.dataset_manifest),
                        "access_mode": "OFFLINE_BOUNDED_DATASET",
                        "network_isolation_evidence_path": str(self.network_evidence),
                        "network_isolation_evidence_sha256": _sha256(self.network_evidence),
                    },
                    "broker_cost_evidence": {
                        "captured_at": "2026-08-15T00:00:00Z",
                        "capture_method": "BROKER_SCHEDULE_AND_DEMO_METADATA",
                        "account_scope": "DEMO",
                        "broker_server": "Research-Broker",
                        "symbol": "GOLD_i_DEV_SAFE",
                        "source_symbol": "GOLD.i#",
                        "source_path": str(self.cost_source),
                        "source_sha256": _sha256(self.cost_source),
                        "costs": self.cost_values,
                    },
                    "compilation": {
                        "status": "SUCCESS_ZERO_ERRORS_ZERO_WARNINGS",
                        "exit_code": 0,
                        "errors": 0,
                        "warnings": 0,
                        "source_path": str(self.ea_source),
                        "source_sha256": _sha256(self.ea_source),
                        "binary_path": str(self.ea_binary),
                        "binary_sha256": _sha256(self.ea_binary),
                        "log_path": str(self.compile_log),
                        "log_sha256": _sha256(self.compile_log),
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self.set_paths: dict[str, Path] = {}
        for profile, value in (("ALL", 0), ("BULL_ONLY", 1), ("BEAR_ONLY", 2)):
            path = self.repository / f"{profile}.set"
            path.write_text(
                "\n".join(
                    (
                        "InpStrategyMode=3",
                        f"InpDirectionProfile={value}",
                        "InpResearchRunId=",
                        "InpExpectedSymbol=GOLD_i_DEV_SAFE",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            self.set_paths[profile] = path
        self.shared_log = self.terminal / "Tester" / "logs" / "20260815.log"

    def spec(self, candidate_id: str, segment_id: str) -> ResearchRunSpec:
        profile = STAGE_A_CANDIDATES[candidate_id]
        from_date, to_date = DEVELOPMENT_SEGMENTS[segment_id]
        run_id = f"stagea-{candidate_id}-{segment_id}-0001"
        return ResearchRunSpec(
            run_id=run_id,
            repository_root=self.repository,
            terminal_path=self.terminal_path,
            terminal_data_path=self.terminal,
            terminal_data_mode=TerminalDataMode.PORTABLE,
            terminal_build="5000.0.0.0",
            ea_source_path=self.ea_source,
            ea_binary_path=self.ea_binary,
            set_source_path=self.set_paths[profile],
            staged_set_path=(
                self.terminal
                / "MQL5"
                / "Profiles"
                / "Tester"
                / f"{run_id}.set"
            ),
            config_path=self.artifacts / f"{run_id}.ini",
            report_path=self.terminal / "reports" / f"{run_id}.html",
            log_path=self.shared_log,
            metrics_path=self.artifacts / f"{run_id}.metrics.json",
            manifest_path=self.artifacts / f"{run_id}.manifest.json",
            expert_name="bot-ea\\GoldMSniperParity",
            symbol="GOLD_i_DEV_SAFE",
            timeframe="M5",
            from_date=from_date,
            to_date=to_date,
            purpose=ResearchPurpose.DEVELOPMENT,
            statistical_classification=(
                StatisticalClassification.DEVELOPMENT_SELECTION
            ),
            direction_profile=profile,
            strategy_mode=3,
            execution_profile="stage-a-fixed",
            costs=ResearchCosts(**self.cost_values),
            tester=TesterSettings(
                model=4,
                deposit=10_000.0,
                currency="USD",
                leverage="1:100",
                news_enabled=False,
            ),
            provenance_path=self.provenance_path,
        )

    def plan(
        self, *, baseline_bindings: tuple[BaselineBinding, ...] = ()
    ) -> StageAPlan:
        cells: list[StageACell] = []
        for candidate_id in STAGE_A_CANDIDATES:
            for segment_id in DEVELOPMENT_SEGMENTS:
                provisional = StageACell(
                candidate_id=candidate_id,
                segment_id=segment_id,
                spec_path=self.specs / f"{candidate_id}-{segment_id}.json",
                    spec_sha256="",
                spec=self.spec(candidate_id, segment_id),
                )
                self.write_spec(provisional)
                cells.append(
                    replace(provisional, spec_sha256=_sha256(provisional.spec_path))
                )
        provisional_plan = StageAPlan(
            matrix_id="stage-a-control-001",
            created_at="2026-08-15T01:02:03Z",
            additional_cost_stress_r=0.10,
            cells=tuple(cells),
            baseline_bindings=baseline_bindings,
            plan_sha256="",
        )
        return self.rehash_plan(provisional_plan)

    def rehash_plan(self, plan: StageAPlan) -> StageAPlan:
        payload = {
            "schema_version": 1,
            "matrix_id": plan.matrix_id,
            "created_at": plan.created_at,
            "additional_cost_stress_r": plan.additional_cost_stress_r,
            "cells": [
                {
                    "candidate_id": cell.candidate_id,
                    "segment_id": cell.segment_id,
                    "spec_path": str(cell.spec_path),
                    "spec_sha256": cell.spec_sha256,
                }
                for cell in plan.cells
            ],
            "baseline_bindings": [
                {
                    "segment_id": binding.segment_id,
                    "metrics_path": str(binding.metrics_path),
                    "sha256": binding.sha256,
                }
                for binding in plan.baseline_bindings
            ],
        }
        return replace(plan, plan_sha256=_canonical_sha256(payload))

    def replace_cell_spec(
        self, plan: StageAPlan, index: int, spec: ResearchRunSpec
    ) -> StageAPlan:
        old = plan.cells[index]
        provisional = replace(old, spec=spec)
        self.write_spec(provisional)
        updated = replace(provisional, spec_sha256=_sha256(provisional.spec_path))
        cells = list(plan.cells)
        cells[index] = updated
        return self.rehash_plan(replace(plan, cells=tuple(cells)))

    def write_spec(self, cell: StageACell) -> None:
        spec = cell.spec
        payload = {
            "schema_version": 1,
            "run_id": spec.run_id,
            "repository_root": str(spec.repository_root),
            "terminal_path": str(spec.terminal_path),
            "terminal_data_path": str(spec.terminal_data_path),
            "terminal_data_mode": spec.terminal_data_mode.value,
            "terminal_build": spec.terminal_build,
            "ea_source_path": str(spec.ea_source_path),
            "ea_binary_path": str(spec.ea_binary_path),
            "set_source_path": str(spec.set_source_path),
            "provenance_path": str(spec.provenance_path),
            "staged_set_path": str(spec.staged_set_path),
            "config_path": str(spec.config_path),
            "report_path": str(spec.report_path),
            "log_path": str(spec.log_path),
            "metrics_path": str(spec.metrics_path),
            "manifest_path": str(spec.manifest_path),
            "expert_name": spec.expert_name,
            "symbol": spec.symbol,
            "timeframe": spec.timeframe,
            "from_date": spec.from_date,
            "to_date": spec.to_date,
            "purpose": spec.purpose.value,
            "statistical_classification": spec.statistical_classification.value,
            "direction_profile": spec.direction_profile,
            "strategy_mode": spec.strategy_mode,
            "execution_profile": spec.execution_profile,
            "costs": {
                "spread_model": spec.costs.spread_model,
                "commission_model": spec.costs.commission_model,
                "swap_model": spec.costs.swap_model,
                "slippage_model": spec.costs.slippage_model,
                "execution_delay_ms": spec.costs.execution_delay_ms,
                "commission_per_lot_round_turn": (
                    spec.costs.commission_per_lot_round_turn
                ),
                "slippage_points": spec.costs.slippage_points,
                "spread_points": spec.costs.spread_points,
                "swap_per_lot_round_turn": spec.costs.swap_per_lot_round_turn,
                "reference_volume_lots": spec.costs.reference_volume_lots,
            },
            "tester": {
                "model": spec.tester.model,
                "deposit": spec.tester.deposit,
                "currency": spec.tester.currency,
                "leverage": spec.tester.leverage,
                "news_enabled": spec.tester.news_enabled,
                "use_local": spec.tester.use_local,
                "use_remote": spec.tester.use_remote,
                "use_cloud": spec.tester.use_cloud,
                "visual": spec.tester.visual,
                "optimization": spec.tester.optimization,
            },
        }
        cell.spec_path.write_text(json.dumps(payload), encoding="utf-8")

    def trades(self, candidate_id: str, segment_id: str) -> list[dict[str, object]]:
        count = 10 if candidate_id == "A0" else 5
        side = "BUY" if candidate_id == "A1" else "SELL" if candidate_id == "A2" else None
        return [
            {
                "setup_id": f"{candidate_id}-{segment_id}-{index:02d}",
                "side": side or ("BUY" if index % 2 == 0 else "SELL"),
                "entry": 2000.0 + index,
                "initial_stop": 1999.0 + index,
                "result": "TARGET",
                "outcome_r": 1.0,
                "hit_r1": True,
                "hit_r2": index % 2 == 0,
                "hit_r3": False,
                "mfe_r": 1.2,
                "mae_r": -0.2,
            }
            for index in range(count)
        ]

    def write_metrics(
        self,
        cell: StageACell,
        *,
        trades: list[dict[str, object]] | None = None,
        path: Path | None = None,
    ) -> Path:
        output = path or cell.spec.metrics_path
        selected = self.trades(cell.candidate_id, cell.segment_id) if trades is None else trades
        payload = {
            "schema_version": 1,
            "run_id": cell.spec.run_id,
            "statistical_classification": "DEVELOPMENT_SELECTION",
            "lineage": {
                "strategy": "GOLDM_SNIPER_PARITY",
                "strategy_version": "1.72",
                "direction_profile": cell.spec.direction_profile,
                "strategy_mode": 3,
            },
            "report_contract": {
                "contract_id": "MT5_STRATEGY_TEST_HTML_EN_V1",
                "strict_actual_report_verified": True,
            },
            "history_observation": {
                "contract_id": "MT5_STRATEGY_TEST_HTML_EN_V1",
                "symbol": cell.spec.symbol,
                "timeframe": cell.spec.timeframe,
                "from_inclusive": cell.spec.from_date,
                "to_exclusive": cell.spec.to_date,
                "broker_server": "Research-Broker",
                "history_quality": "100.00%",
                "bars": 100,
                "ticks": 1000,
            },
            "trades": selected,
            "metrics": {
                "pooled": {
                    "trades": len(selected),
                    "total_r": sum(float(item["outcome_r"]) for item in selected),
                }
            },
        }
        output.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return output

    def write_manifest(
        self,
        cell: StageACell,
        *,
        protocol_complete: bool,
        status: str = "VERIFIED",
    ) -> Path:
        metrics_path = self.write_metrics(cell)
        manifest: dict[str, object] = {
            "schema_version": 2,
            "status": status,
            "run_id": cell.spec.run_id,
            "started_at": "2026-08-15T02:01:00Z",
            "completed_at": "2026-08-15T02:02:00Z",
            "repository": {"commit": "b" * 40, "dirty": False},
            "inputs": {
                "ea_source": {
                    "path": str(self.ea_source),
                    "sha256": _sha256(self.ea_source),
                },
                "ea_binary": {
                    "path": str(self.ea_binary),
                    "sha256": _sha256(self.ea_binary),
                },
                "set_source": {
                    "path": str(cell.spec.set_source_path),
                    "sha256": _sha256(cell.spec.set_source_path),
                },
                "provenance_evidence": {
                    "path": str(cell.spec.provenance_path),
                    "sha256": _sha256(cell.spec.provenance_path),
                },
            },
            "profile": {
                "direction": cell.spec.direction_profile,
                "strategy_mode": 3,
                "execution": "stage-a-fixed",
            },
            "market": {
                "symbol": "GOLD_i_DEV_SAFE",
                "timeframe": "M5",
                "from_inclusive": cell.spec.from_date,
                "to_exclusive": cell.spec.to_date,
                "purpose": "Development",
                "statistical_classification": "DEVELOPMENT_SELECTION",
                "history_observation": {
                    "contract_id": "MT5_STRATEGY_TEST_HTML_EN_V1",
                    "symbol": cell.spec.symbol,
                    "timeframe": cell.spec.timeframe,
                    "from_inclusive": cell.spec.from_date,
                    "to_exclusive": cell.spec.to_date,
                    "broker_server": "Research-Broker",
                    "history_quality": "100.00%",
                    "bars": 100,
                    "ticks": 1000,
                },
            },
            "terminal": {
                "path": str(self.terminal_path),
                "data_path": str(self.terminal),
                "data_mode": "PORTABLE",
                "build": "5000.0.0.0",
            },
            "costs": asdict(cell.spec.costs),
            "tester_settings": asdict(cell.spec.tester),
            "artifacts": {
                "metrics": {"path": str(metrics_path), "sha256": _sha256(metrics_path)},
                "report": {"sha256": "c" * 64},
                "log": {"sha256": "d" * 64},
            },
        }
        if protocol_complete:
            manifest["inputs"].update(  # type: ignore[union-attr]
                {
                    "symbol_spec_evidence": {
                        "path": str(self.symbol_evidence),
                        "sha256": _sha256(self.symbol_evidence),
                    },
                    "bounded_history_evidence": {
                        "path": str(self.history_evidence),
                        "sha256": _sha256(self.history_evidence),
                    },
                    "bounded_history_manifest": {
                        "path": str(self.dataset_manifest),
                        "sha256": _sha256(self.dataset_manifest),
                    },
                    "network_isolation_evidence": {
                        "path": str(self.network_evidence),
                        "sha256": _sha256(self.network_evidence),
                    },
                    "broker_cost_source": {
                        "path": str(self.cost_source),
                        "sha256": _sha256(self.cost_source),
                    },
                }
            )
            manifest["profile"].update(  # type: ignore[union-attr]
                {
                    "strategy": "GOLDM_SNIPER_PARITY",
                    "strategy_version": "1.72",
                    "management_policy_version": "M1_R_LOCK_V1",
                }
            )
            manifest["market"].update(  # type: ignore[union-attr]
                {
                    "broker_server": "Research-Broker",
                    "symbol_specification": {
                        "symbol": "GOLD_i_DEV_SAFE",
                        "source_symbol": "GOLD.i#",
                        "is_custom": True,
                        "digits": 2,
                        "point": 0.01,
                        "trade_tick_size": 0.01,
                        "trade_tick_value": 1.0,
                    },
                    "history_declaration": json.loads(
                        self.provenance_path.read_text(encoding="utf-8")
                    )["history_declaration"],
                }
            )
            manifest["broker_cost_evidence"] = json.loads(
                self.provenance_path.read_text(encoding="utf-8")
            )["broker_cost_evidence"]
            manifest["report_contract"] = {
                "contract_id": "MT5_STRATEGY_TEST_HTML_EN_V1",
                "strict_actual_report_verified": True,
            }
            manifest["compilation"] = {
                "status": "SUCCESS_ZERO_ERRORS_ZERO_WARNINGS",
                "log_sha256": "e" * 64,
            }
        cell.spec.manifest_path.write_text(
            json.dumps(manifest, sort_keys=True), encoding="utf-8"
        )
        return cell.spec.manifest_path

    def proof(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": "PORTABLE_EXCLUSIVE_PATH_LOCK",
            "lock_path": str(self.terminal / ".goldm-stage-a-execution.lock"),
            "terminal_path": str(self.terminal_path),
            "terminal_data_path": str(self.terminal),
        }


class GoldMResearchStageATests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = StageAFixture(Path(self.temporary.name))
        self.plan = self.fixture.plan()
        self.registry = AppendOnlyResearchRegistry(
            self.fixture.artifacts / "stage-a.registry.jsonl"
        )

    def test_exact_three_by_six_matrix_is_required(self) -> None:
        validate_stage_a_plan(self.plan)
        missing = self.fixture.rehash_plan(
            replace(self.plan, cells=self.plan.cells[:-1])
        )
        with self.assertRaisesRegex(StageAError, "exactly the immutable 3x6 matrix"):
            validate_stage_a_plan(missing)

        first = self.plan.cells[0]
        wrong_range = self.fixture.replace_cell_spec(
            self.plan,
            0,
            replace(first.spec, to_date="2022-06-27"),
        )
        with self.assertRaisesRegex(StageAError, "exact half-open range"):
            validate_stage_a_plan(wrong_range)

    def test_stage_a_requires_portable_mode_and_exact_direction(self) -> None:
        first = self.plan.cells[0]
        standard = self.fixture.replace_cell_spec(
            self.plan,
            0,
            replace(first.spec, terminal_data_mode=TerminalDataMode.STANDARD),
        )
        with self.assertRaisesRegex(StageAError, "PORTABLE"):
            validate_stage_a_plan(standard)

        self.plan = self.fixture.plan()
        first = self.plan.cells[0]
        wrong_direction = self.fixture.replace_cell_spec(
            self.plan,
            0,
            replace(first.spec, direction_profile="BULL_ONLY"),
        )
        with self.assertRaisesRegex(StageAError, "direction profile ALL"):
            validate_stage_a_plan(wrong_direction)

    def test_plan_loader_rejects_digest_tampering(self) -> None:
        for cell in self.plan.cells:
            self.fixture.write_spec(cell)
        payload = {
            "schema_version": 1,
            "matrix_id": self.plan.matrix_id,
            "created_at": self.plan.created_at,
            "additional_cost_stress_r": self.plan.additional_cost_stress_r,
            "cells": [
                {
                    "candidate_id": cell.candidate_id,
                    "segment_id": cell.segment_id,
                    "spec_path": str(cell.spec_path),
                    "spec_sha256": cell.spec_sha256,
                }
                for cell in self.plan.cells
            ],
            "baseline_bindings": [],
        }
        payload["plan_sha256"] = _canonical_sha256(payload)
        path = self.fixture.root / "stage-a-plan.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_stage_a_plan(path)
        self.assertEqual(len(loaded.cells), 18)

        payload["additional_cost_stress_r"] = 0.11
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(StageAError, "does not match"):
            load_stage_a_plan(path)

    def test_registry_is_append_only_hash_chained_and_forbids_run_id_reuse(self) -> None:
        self.registry.plan_matrix(self.plan, recorded_at="2026-08-15T02:00:00Z")
        records = self.registry.records()
        self.assertEqual(len(records), 18)
        self.assertTrue(all(record.state is RegistryState.PLANNED for record in records))
        self.assertIsNone(records[0].previous_record_sha256)
        self.assertEqual(records[1].previous_record_sha256, records[0].record_sha256)
        with self.assertRaisesRegex(StageAError, "run ID reuse"):
            self.registry.plan_matrix(self.plan)

        lines = self.registry.path.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(lines[0])
        tampered["candidate_id"] = "A2"
        lines[0] = json.dumps(tampered, separators=(",", ":"), sort_keys=True)
        self.registry.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(StageAError, "hash mismatch"):
            self.registry.records()

    def test_registry_lock_serializes_concurrent_matrix_planning(self) -> None:
        registries = (
            AppendOnlyResearchRegistry(self.registry.path),
            AppendOnlyResearchRegistry(self.registry.path),
        )

        def plan_once(registry: AppendOnlyResearchRegistry) -> str:
            try:
                registry.plan_matrix(self.plan)
                return "planned"
            except StageAError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(plan_once, registries))
        self.assertEqual(outcomes.count("planned"), 1)
        self.assertEqual(sum("run ID reuse" in value for value in outcomes), 1)
        self.assertEqual(len(self.registry.records()), 18)

    def test_registry_final_transitions_are_strict_and_truthful(self) -> None:
        self.registry.plan_matrix(self.plan)
        completed = self.plan.cells[0]
        self.fixture.write_manifest(completed, protocol_complete=False)
        self.registry.start(
            self.plan,
            completed,
            execution_proof=self.fixture.proof(),
        )
        self.registry.complete(
            self.plan,
            completed,
            manifest_path=completed.spec.manifest_path,
            execution_proof=self.fixture.proof(),
        )
        failed = self.plan.cells[1]
        failed.spec.manifest_path.write_text(
            json.dumps(
                {"status": "FAILED", "run_id": failed.spec.run_id, "failure": "boom"}
            ),
            encoding="utf-8",
        )
        self.registry.fail(
            self.plan,
            failed,
            failure="boom",
            manifest_path=failed.spec.manifest_path,
        )
        final = {record.run_id: record for record in self.registry.records()}
        self.assertIs(final[completed.spec.run_id].state, RegistryState.COMPLETED)
        self.assertIs(final[failed.spec.run_id].state, RegistryState.FAILED)
        with self.assertRaisesRegex(StageAError, "unfinished run state"):
            self.registry.fail(self.plan, completed, failure="late rewrite")

    def test_registry_recovery_requires_stopped_exact_process_evidence(self) -> None:
        self.registry.plan_matrix(self.plan)
        cell = self.plan.cells[0]
        self.registry.start(
            self.plan,
            cell,
            execution_proof=self.fixture.proof(),
            recorded_at="2026-08-15T02:00:00Z",
        )
        self.fixture.write_manifest(cell, protocol_complete=False)

        def observation(state: TerminalState) -> TerminalProbeResult:
            return TerminalProbeResult(
                state=state,
                executable_path=cell.spec.terminal_path,
                data_path=cell.spec.terminal_data_path,
                data_mode=cell.spec.terminal_data_mode,
                build=cell.spec.terminal_build,
                detail="fixture process evidence",
            )

        with self.assertRaisesRegex(StageAError, "exact STOPPED"):
            self.registry.reconcile_unfinished(
                self.plan,
                cell,
                terminal_probe=lambda _: observation(TerminalState.RUNNING),
            )
        self.assertIs(self.registry.records()[-1].state, RegistryState.STARTED)

        orchestrator = StageAOrchestrator(
            runner_factory=lambda _spec: self.fail("recovery must never launch"),
            registry=self.registry,
        )
        state = orchestrator.recover_smoke_a0_d1(
            self.plan,
            terminal_probe=lambda _: observation(TerminalState.STOPPED),
        )
        self.assertIs(state, RegistryState.COMPLETED)
        final = self.registry.records()[-1]
        self.assertIs(final.state, RegistryState.COMPLETED)
        self.assertEqual(final.reconciliation["prior_state"], "STARTED")

    def test_portable_execution_lease_is_exclusive_and_path_bound(self) -> None:
        with portable_execution_lease(self.fixture.terminal_path, self.fixture.terminal):
            with self.assertRaisesRegex(StageAError, "exclusive lock is busy"):
                with portable_execution_lease(
                    self.fixture.terminal_path,
                    self.fixture.terminal,
                    timeout_seconds=0.02,
                ):
                    self.fail("a second execution lease must never be acquired")
        other = self.fixture.root / "other-data"
        other.mkdir()
        with self.assertRaisesRegex(StageAError, "terminal_data_path"):
            with portable_execution_lease(self.fixture.terminal_path, other):
                self.fail("non-portable data binding must be rejected")

    def test_orchestrator_uses_fake_runner_sequentially_and_records_completion(self) -> None:
        observed: list[str] = []

        class FakeRunner:
            def run(
                inner_self,
                spec: ResearchRunSpec,
                **_kwargs: object,
            ) -> dict[str, object]:
                observed.append(spec.run_id)
                result = {"status": "VERIFIED", "run_id": spec.run_id}
                spec.manifest_path.write_text(json.dumps(result), encoding="utf-8")
                return result

        orchestrator = StageAOrchestrator(
            runner_factory=lambda _spec: FakeRunner(),
            registry=self.registry,
        )
        smoke = orchestrator.execute_smoke_a0_d1(self.plan)
        self.assertEqual(smoke["run_id"], "stagea-A0-D1-0001")
        self.assertEqual(observed, ["stagea-A0-D1-0001"])
        repeated = orchestrator.execute_smoke_a0_d1(self.plan)
        self.assertEqual(repeated, smoke)
        self.assertEqual(observed, ["stagea-A0-D1-0001"])

        results = orchestrator.execute(self.plan)
        self.assertEqual(len(results), 18)
        self.assertEqual(len(observed), 18)
        self.assertEqual(observed.count("stagea-A0-D1-0001"), 1)
        records = self.registry.records()
        self.assertEqual(len(records), 54)
        final_by_run = {record.run_id: record for record in records}
        self.assertEqual(len(final_by_run), 18)
        self.assertTrue(
            all(
                record.state is RegistryState.COMPLETED
                for record in final_by_run.values()
            )
        )

    def test_gate_is_blocked_when_runs_or_baseline_evidence_are_missing(self) -> None:
        report = evaluate_stage_a(self.plan, self.registry)
        self.assertIs(report.status, GateStatus.BLOCKED)
        self.assertIn("MISSING_REGISTRY_RECORD", {item.code for item in report.blockers})
        self.assertIn("BASELINE_ARTIFACTS_MISSING", {item.code for item in report.blockers})

    def test_gate_rejects_manifest_without_protocol_provenance(self) -> None:
        self.registry.plan_matrix(self.plan)
        for cell in self.plan.cells:
            self.fixture.write_manifest(cell, protocol_complete=False)
            self.registry.start(
                self.plan,
                cell,
                execution_proof=self.fixture.proof(),
            )
            self.registry.complete(
                self.plan,
                cell,
                manifest_path=cell.spec.manifest_path,
                execution_proof=self.fixture.proof(),
            )
        report = evaluate_stage_a(self.plan, self.registry)
        self.assertIs(report.status, GateStatus.BLOCKED)
        self.assertIn("PROVENANCE_INCOMPLETE", {item.code for item in report.blockers})
        self.assertIn("MATRIX_INCOMPLETE", {item.code for item in report.blockers})

    def test_full_evidence_passes_aggregate_gates_and_bound_a0_parity(self) -> None:
        baseline_bindings: list[BaselineBinding] = []
        for segment_id in DEVELOPMENT_SEGMENTS:
            cell = next(
                item
                for item in self.plan.cells
                if item.candidate_id == "A0" and item.segment_id == segment_id
            )
            path = self.fixture.artifacts / f"baseline-{segment_id}.metrics.json"
            self.fixture.write_metrics(cell, path=path)
            baseline_bindings.append(
                BaselineBinding(segment_id=segment_id, metrics_path=path, sha256=_sha256(path))
            )
        plan = self.fixture.plan(baseline_bindings=tuple(baseline_bindings))
        self.registry.plan_matrix(plan)
        for cell in plan.cells:
            self.fixture.write_manifest(cell, protocol_complete=True)
            self.registry.start(
                plan,
                cell,
                execution_proof=self.fixture.proof(),
            )
            self.registry.complete(
                plan,
                cell,
                manifest_path=cell.spec.manifest_path,
                execution_proof=self.fixture.proof(),
            )
        report = evaluate_stage_a(plan, self.registry)
        self.assertIs(report.status, GateStatus.BLOCKED)
        self.assertIn(
            "SELECTION_BIAS_SPA_BLOCKED",
            {item.code for item in report.blockers},
        )
        self.assertFalse(report.failures)
        self.assertEqual({item.trades for item in report.candidates}, {30, 60})

        first_baseline = baseline_bindings[0]
        payload = json.loads(first_baseline.metrics_path.read_text(encoding="utf-8"))
        payload["trades"][0]["outcome_r"] = 0.5
        first_baseline.metrics_path.write_text(json.dumps(payload), encoding="utf-8")
        mismatch = evaluate_stage_a(plan, self.registry)
        self.assertIs(mismatch.status, GateStatus.BLOCKED)
        self.assertIn("A0_PARITY_FAILED", {item.code for item in mismatch.failures})


if __name__ == "__main__":
    unittest.main()
