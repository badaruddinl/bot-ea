from __future__ import annotations

import json
import hashlib
import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from goldm_signal.research_run import (
    MT5ResearchRunner,
    ProcessResult,
    RepositoryState,
    ResearchCosts,
    ResearchRunError,
    ResearchRunSpec,
    TerminalDataMode,
    TerminalProbeResult,
    TerminalState,
    TesterSettings,
    WindowsProcessSnapshot,
    _issue_matrix_execution_authorization,
    launch_windows_terminal_once,
    load_research_run_spec,
    probe_windows_terminal,
)
from goldm_signal.research_policy import StatisticalClassification
from goldm_signal.research_import import (
    prepare_offline_import_bundle,
    seal_offline_import_receipt,
)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class GoldMResearchRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name).resolve()
        repository = root / "repository"
        terminal_root = root / "terminal"
        terminal_data = terminal_root
        artifacts = root / "artifacts"
        logs = root / "logs"
        for directory in (
            repository / "mt5" / "Experts" / "bot-ea",
            repository / "mt5" / "Profiles" / "Tester",
            terminal_root,
            terminal_root / "reports",
            terminal_root / "MQL5" / "Profiles" / "Tester",
            terminal_data / "MQL5" / "Experts" / "bot-ea",
            terminal_data / "Tester" / "logs",
            artifacts,
            logs,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        terminal_path = terminal_root / "terminal64.exe"
        ea_source = repository / "mt5" / "Experts" / "bot-ea" / "GoldMSniperParity.mq5"
        ea_binary = terminal_data / "MQL5" / "Experts" / "bot-ea" / "GoldMSniperParity.ex5"
        set_source = repository / "mt5" / "Profiles" / "Tester" / "D7_ALL.set"
        terminal_path.write_bytes(b"test terminal binary")
        (terminal_root / "metaeditor64.exe").write_bytes(b"test metaeditor binary")
        (terminal_root / "metatester64.exe").write_bytes(b"test metatester binary")
        ea_source.write_text(
            "input int InpStrategyMode = 3;\n"
            "input DirectionProfile InpDirectionProfile = ALL;\n"
            'input string InpResearchRunId = "";\n'
            "input int InpBreakoutChannelBars = 12;\n",
            encoding="utf-8",
        )
        ea_binary.write_bytes(b"test compiled EA")
        compile_log = repository / "GoldMSniperParity.compile.log"
        compile_log.write_text("Result: 0 errors, 0 warnings\n", encoding="utf-8")
        symbol_evidence = repository / "symbol-spec-source.json"
        history_evidence = repository / "bounded-development-ticks.csv"
        dataset_manifest = repository / "bounded-development-dataset.json"
        dataset_source_evidence = repository / "bounded-development-source.json"
        dataset_authority = repository / "bounded-development-authority.txt"
        network_evidence = repository / "offline-firewall-proof.json"
        broker_cost_source = repository / "broker-cost-source.json"
        symbol_evidence.write_text('{"source":"demo symbol metadata"}\n', encoding="utf-8")
        history_evidence.write_text(
            "time_msc,bid,ask,last,volume,flags,volume_real\n"
            "1672531140000,1999.90,2000.10,0,1,6,1.0\n"
            "1672531200000,1999.91,2000.11,0,1,6,1.0\n"
            "1675209540000,1999.92,2000.12,0,1,6,1.0\n",
            encoding="utf-8",
        )
        dataset_authority.write_text("approved test export\n", encoding="utf-8")
        source_payload = {
            "schema_version": 1,
            "status": "APPROVED_BOUNDED_OFFLINE_SOURCE",
            "evidence_id": "approved-goldm-run-source",
            "attested_at": "2026-08-15T00:00:00Z",
            "provenance_kind": "TRUSTED_EXTERNAL_EXPORT",
            "authority": "GoldM test authority",
            "capture_method": "EXACT_BOUNDED_TICK_EXPORT",
            "purpose": "Development",
            "statistical_classification": "DEVELOPMENT_SELECTION",
            "source_symbol": "GOLD.i#",
            "warmup_from_inclusive": "2022-12-31",
            "run_from_inclusive": "2023-01-01",
            "to_exclusive": "2023-02-01",
            "dataset_path": str(history_evidence),
            "dataset_sha256": hashlib.sha256(history_evidence.read_bytes()).hexdigest(),
            "authority_artifact_path": str(dataset_authority),
            "authority_artifact_sha256": hashlib.sha256(
                dataset_authority.read_bytes()
            ).hexdigest(),
        }
        source_payload["evidence_sha256"] = _canonical_sha256(source_payload)
        dataset_source_evidence.write_text(
            json.dumps(source_payload, sort_keys=True), encoding="utf-8"
        )
        dataset_payload = {
            "schema_version": 2,
            "dataset_id": "goldm-dev-test-dataset-v1",
            "registered_at": "2026-08-15T00:00:00Z",
            "purpose": "Development",
            "statistical_classification": "DEVELOPMENT_SELECTION",
            "custom_symbol": "GOLD_i_DEV_TEST",
            "source_symbol": "GOLD.i#",
            "warmup_from_inclusive": "2022-12-31",
            "run_from_inclusive": "2023-01-01",
            "to_exclusive": "2023-02-01",
            "format": "MT5_TICKS_CSV_V1",
            "time_semantics": "UTC_HALF_OPEN",
            "row_count": 3,
            "first_time_msc": 1672531140000,
            "last_time_msc": 1675209540000,
            "dataset_path": str(history_evidence),
            "dataset_sha256": hashlib.sha256(history_evidence.read_bytes()).hexdigest(),
            "source_evidence_path": str(dataset_source_evidence),
            "source_evidence_sha256": hashlib.sha256(
                dataset_source_evidence.read_bytes()
            ).hexdigest(),
        }
        dataset_payload["manifest_sha256"] = hashlib.sha256(
            json.dumps(
                dataset_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        dataset_manifest.write_text(
            json.dumps(dataset_payload, sort_keys=True), encoding="utf-8"
        )
        network_payload = {
            "schema_version": 1,
            "status": "ENFORCED_OFFLINE",
            "terminal_root": str(terminal_data),
            "terminal_sha256": hashlib.sha256(terminal_path.read_bytes()).hexdigest(),
            "metatester_sha256": hashlib.sha256(
                (terminal_root / "metatester64.exe").read_bytes()
            ).hexdigest(),
            "enforcement": "WINDOWS_FIREWALL_BLOCK_OUTBOUND",
            "verified_at": "2026-08-15T00:00:00Z",
        }
        network_payload["evidence_sha256"] = _canonical_sha256(network_payload)
        network_evidence.write_text(json.dumps(network_payload), encoding="utf-8")
        broker_cost_source.write_text('{"source":"broker schedule"}\n', encoding="utf-8")
        cost_values = {
            "spread_model": "historical_ticks",
            "commission_model": "broker_tester",
            "swap_model": "broker_tester",
            "slippage_model": "fixed_delay",
            "execution_delay_ms": 100,
            "commission_per_lot_round_turn": 7.0,
            "slippage_points": 2.0,
            "spread_points": 20.0,
            "swap_per_lot_round_turn": 0.5,
            "reference_volume_lots": 0.1,
        }
        symbol_import_spec = repository / "custom-symbol-import-spec.json"
        sessions = [
            {"day": day, "index": 0, "from_seconds": 0, "to_seconds": 86400}
            for day in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")
        ]
        import_spec_payload = {
            "schema_version": 1,
            "custom_symbol": "GOLD_i_DEV_TEST",
            "source_symbol": "GOLD.i#",
            "custom_group": "GoldMOffline",
            "description": "GoldM test custom ticks",
            "digits": 2,
            "chart_mode": "BID",
            "point": 0.01,
            "trade_tick_size": 0.01,
            "trade_tick_value": 1.0,
            "trade_tick_value_profit": 1.0,
            "trade_tick_value_loss": 1.0,
            "trade_contract_size": 100.0,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "volume_limit": 0.0,
            "trade_calc_mode": 0,
            "trade_mode": 4,
            "trade_execution_mode": 2,
            "trade_stops_level": 0,
            "trade_freeze_level": 0,
            "spread_float": True,
            "spread_points": 20,
            "order_mode": 127,
            "filling_mode": 3,
            "expiration_mode": 15,
            "swap_mode": 0,
            "swap_long": 0.0,
            "swap_short": 0.0,
            "currency_base": "XAU",
            "currency_profit": "USD",
            "currency_margin": "USD",
            "quote_sessions": sessions,
            "trade_sessions": sessions,
        }
        import_spec_payload["spec_sha256"] = _canonical_sha256(import_spec_payload)
        symbol_import_spec.write_text(json.dumps(import_spec_payload), encoding="utf-8")
        import_bundle = prepare_offline_import_bundle(
            dataset_manifest_path=dataset_manifest,
            symbol_spec_path=symbol_import_spec,
            terminal_root=terminal_data,
            network_isolation_evidence_path=network_evidence,
            import_id="gmr-test-import-0001",
            expected_run_start=datetime(2023, 1, 1, tzinfo=timezone.utc),
            expected_end=datetime(2023, 2, 1, tzinfo=timezone.utc),
            expected_purpose="Development",
            expected_classification="DEVELOPMENT_SELECTION",
            created_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        )
        raw_receipt_rows = {
            "format": "MT5_CUSTOM_TICK_IMPORT_RECEIPT_V1",
            "status": "VERIFIED_CACHE_MATCH",
            "import_id": "gmr-test-import-0001",
            "custom_symbol": "GOLD_i_DEV_TEST",
            "source_symbol": "GOLD.i#",
            "dataset_sha256": dataset_payload["dataset_sha256"],
            "dataset_manifest_sha256": hashlib.sha256(dataset_manifest.read_bytes()).hexdigest(),
            "symbol_spec_sha256": hashlib.sha256(symbol_import_spec.read_bytes()).hexdigest(),
            "control_sha256": import_bundle.control_sha256,
            "row_count": "3",
            "first_time_msc": "1672531140000",
            "last_time_msc": "1675209540000",
            "formula": "EMPTY",
            "origin": "NONE",
            "portable": "TRUE",
            "connected": "FALSE",
        }
        import_bundle.raw_receipt_path.write_text(
            "key;value\n"
            + "".join(f"{key};{value}\n" for key, value in raw_receipt_rows.items()),
            encoding="utf-8",
        )
        custom_cache = terminal_data / "bases" / "Custom" / "GoldMOffline" / "ticks.hcc"
        custom_cache.parent.mkdir(parents=True)
        custom_cache.write_bytes(b"verified test custom cache")
        sealed_import_receipt = repository / "custom-symbol-import-receipt.json"
        seal_offline_import_receipt(
            import_plan_path=import_bundle.plan_path,
            output_path=sealed_import_receipt,
            terminal_stopped_probe=lambda terminal: terminal == terminal_data,
            sealed_at=datetime(2026, 8, 15, 0, 30, tzinfo=timezone.utc),
        )
        provenance_path = repository / "GoldMSniperParity.provenance.json"
        provenance_path.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "captured_at": "2026-08-15T00:00:00Z",
                    "broker_server": "Research-Broker",
                    "management_policy_version": "M1_R_LOCK_V1",
                    "symbol_specification": {
                        "symbol": "GOLD_i_DEV_TEST",
                        "source_symbol": "GOLD.i#",
                        "is_custom": True,
                        "captured_at": "2026-08-15T00:00:00Z",
                        "capture_method": "MT5_DEMO_SYMBOL_METADATA",
                        "source_path": str(symbol_evidence),
                        "source_sha256": hashlib.sha256(symbol_evidence.read_bytes()).hexdigest(),
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
                        "symbol": "GOLD_i_DEV_TEST",
                        "source_symbol": "GOLD.i#",
                        "data_kind": "TICKS_UTC",
                        "warmup_from_inclusive": "2022-12-31",
                        "from_inclusive": "2023-01-01",
                        "to_exclusive": "2023-02-01",
                        "row_count": 3,
                        "first_timestamp_utc": "2022-12-31T23:59:00Z",
                        "last_timestamp_utc": "2023-01-31T23:59:00Z",
                        "integrity_verified": True,
                        "captured_at": "2026-08-15T00:00:00Z",
                        "capture_method": "GUARDED_HALF_OPEN_EXPORT",
                        "source_path": str(history_evidence),
                        "source_sha256": hashlib.sha256(history_evidence.read_bytes()).hexdigest(),
                        "dataset_manifest_path": str(dataset_manifest),
                        "dataset_manifest_sha256": hashlib.sha256(dataset_manifest.read_bytes()).hexdigest(),
                        "access_mode": "OFFLINE_BOUNDED_DATASET",
                        "network_isolation_evidence_path": str(network_evidence),
                        "network_isolation_evidence_sha256": hashlib.sha256(network_evidence.read_bytes()).hexdigest(),
                    },
                    "custom_symbol_import": {
                        "receipt_path": str(sealed_import_receipt),
                        "receipt_sha256": hashlib.sha256(
                            sealed_import_receipt.read_bytes()
                        ).hexdigest(),
                    },
                    "broker_cost_evidence": {
                        "captured_at": "2026-08-15T00:00:00Z",
                        "capture_method": "BROKER_SCHEDULE_AND_DEMO_METADATA",
                        "account_scope": "DEMO",
                        "broker_server": "Research-Broker",
                        "symbol": "GOLD_i_DEV_TEST",
                        "source_symbol": "GOLD.i#",
                        "source_path": str(broker_cost_source),
                        "source_sha256": hashlib.sha256(broker_cost_source.read_bytes()).hexdigest(),
                        "costs": cost_values,
                    },
                    "compilation": {
                        "status": "SUCCESS_ZERO_ERRORS_ZERO_WARNINGS",
                        "exit_code": 0,
                        "errors": 0,
                        "warnings": 0,
                        "source_path": str(ea_source),
                        "source_sha256": hashlib.sha256(ea_source.read_bytes()).hexdigest(),
                        "binary_path": str(ea_binary),
                        "binary_sha256": hashlib.sha256(ea_binary.read_bytes()).hexdigest(),
                        "log_path": str(compile_log),
                        "log_sha256": hashlib.sha256(compile_log.read_bytes()).hexdigest(),
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        set_source.write_text(
            "InpStrategyMode=3\n"
            "InpDirectionProfile=0\n"
            "InpResearchRunId=\n"
            "InpBreakoutChannelBars=12\n",
            encoding="utf-8",
        )

        run_id = "gmr-test-0001"
        self.spec = ResearchRunSpec(
            run_id=run_id,
            repository_root=repository,
            terminal_path=terminal_path,
            terminal_data_path=terminal_data,
            terminal_data_mode=TerminalDataMode.PORTABLE,
            terminal_build="5327",
            ea_source_path=ea_source,
            ea_binary_path=ea_binary,
            set_source_path=set_source,
            staged_set_path=(
                terminal_root
                / "MQL5"
                / "Profiles"
                / "Tester"
                / f"D7_ALL_{run_id}.set"
            ),
            config_path=artifacts / f"{run_id}.ini",
            report_path=terminal_root / "reports" / f"{run_id}.html",
            log_path=terminal_data / "Tester" / "logs" / "20260815.log",
            metrics_path=artifacts / f"{run_id}.metrics.json",
            manifest_path=artifacts / f"{run_id}.manifest.json",
            expert_name=r"bot-ea\GoldMSniperParity",
            symbol="GOLD_i_DEV_TEST",
            timeframe="M15",
            from_date="2023-01-01",
            to_date="2023-02-01",
            purpose="Development",
            statistical_classification=(
                StatisticalClassification.DEVELOPMENT_SELECTION
            ),
            direction_profile="ALL",
            strategy_mode=3,
            execution_profile="D7_R_LOCK_V1",
            costs=ResearchCosts(**cost_values),
            tester=TesterSettings(
                model=4,
                deposit=100.0,
                currency="USD",
                leverage="1:1000",
                news_enabled=True,
            ),
            provenance_path=provenance_path,
        )
        self.probe_calls: list[Path] = []
        self.launch_calls: list[tuple[Path, Path, TerminalDataMode]] = []
        self.network_verify_calls: list[tuple[Path, Path]] = []

    def _probe(
        self,
        path: Path,
        *,
        state: TerminalState = TerminalState.STOPPED,
        build: str = "5327",
    ) -> TerminalProbeResult:
        self.probe_calls.append(path)
        return TerminalProbeResult(
            state=state,
            executable_path=path,
            data_path=self.spec.terminal_data_path,
            data_mode=self.spec.terminal_data_mode,
            build=build,
            detail="test probe",
        )

    def _write_success_artifacts(self, spec: ResearchRunSpec) -> None:
        spec.report_path.write_text(
            self._complete_report(spec), encoding="utf-8"
        )
        with spec.log_path.open("a", encoding="utf-8") as stream:
            stream.write(self._complete_success_log(spec) + "\n")

    def _refresh_compile_provenance(self) -> None:
        payload = json.loads(self.spec.provenance_path.read_text(encoding="utf-8"))
        compilation = payload["compilation"]
        compile_log = Path(compilation["log_path"])
        compilation["source_sha256"] = hashlib.sha256(
            self.spec.ea_source_path.read_bytes()
        ).hexdigest()
        compilation["binary_sha256"] = hashlib.sha256(
            self.spec.ea_binary_path.read_bytes()
        ).hexdigest()
        compilation["log_sha256"] = hashlib.sha256(compile_log.read_bytes()).hexdigest()
        self.spec.provenance_path.write_text(
            json.dumps(payload, sort_keys=True), encoding="utf-8"
        )

    @staticmethod
    def _complete_report(spec: ResearchRunSpec) -> str:
        return "\n".join(
            (
                "<html><body><table>",
                "<tr><td>Strategy Tester Report</td></tr>",
                "<tr><td>Settings</td></tr>",
                "<tr><td>Expert Advisor:</td><td>GoldMSniperParity</td></tr>",
                f"<tr><td>Symbol:</td><td>{spec.symbol}</td></tr>",
                f"<tr><td>Period:</td><td>{spec.timeframe} "
                f"({spec.from_date.replace('-', '.')} - {spec.to_date.replace('-', '.')})"
                "</td></tr>",
                f"<tr><td>Parameters:</td><td>InpResearchRunId={spec.run_id}</td></tr>",
                "<tr><td>Broker:</td><td>Research-Broker</td></tr>",
                "<tr><td>History Quality:</td><td>100.00%</td></tr>",
                "<tr><td>Bars:</td><td>100</td><td>Ticks:</td><td>1000</td></tr>",
                "</table></body></html>",
                "",
            )
        )

    @staticmethod
    def _complete_success_log(spec: ResearchRunSpec) -> str:
        lineage = (
            "strategy=GOLDM_SNIPER_PARITY strategyVersion=1.72 "
            f"directionProfile={spec.direction_profile} runId={spec.run_id} "
            f"strategyMode={spec.strategy_mode}"
        )
        side = "SELL" if spec.direction_profile == "BEAR_ONLY" else "BUY"
        stop = "101.00" if side == "SELL" else "99.00"
        target = "97.00" if side == "SELL" else "103.00"
        exit_price = "99.00" if side == "SELL" else "101.00"
        return "\n".join(
            (
                f"SNIPER_CONFIG {lineage} signalOnly=true",
                f"SNIPER_SIGNAL id=one status=ENTRY_READY {lineage} side={side} "
                f"entry=100.00 stop={stop} target={target} projectedR=3.000 "
                "score=80 m5Votes=2 pattern=CHANNEL_CONT fibonacciAligned=true "
                "m1Confirmed=true "
                "setupUtcEpoch=10 generatedUtcEpoch=11",
                f"SNIPER_OUTCOME id=one status=CLOSED {lineage} side={side} "
                "result=M1_MANAGEMENT outcomeR=1.0000 entry=100.00 "
                f"exitPrice={exit_price} stop={stop} target={target} projectedR=3.0000 "
                "hit1R=true hit2R=false hit3R=false mfeR=1.0000 maeR=0.0000 "
                "durationMinutes=5 setupUtcEpoch=10 generatedUtcEpoch=100 "
                "source=MODEL_SIMULATION",
                f"SNIPER_PERFORMANCE {lineage} resolved=1 stopped=0 "
                "protectedStops=0 timedOut=0 m1ManagedExits=1 hit1R=1 hit2R=0 "
                "hit3R=0 P1=100.00 P2=0.00 P3=0.00 "
                "expectancyR=1.00000 totalR=1.00000 "
                "averageMFE_R=1.00000 averageMAE_R=0.00000 "
                "averageProjectedR=3.00000 averageScore=80.00",
            )
        )

    def _launcher(
        self,
        terminal_path: Path,
        config_path: Path,
        data_mode: TerminalDataMode,
    ) -> ProcessResult:
        self.launch_calls.append((terminal_path, config_path, data_mode))
        self._write_success_artifacts(self.spec)
        return ProcessResult(
            exit_code=0,
            executable_path=terminal_path,
            data_mode=data_mode,
        )

    def _verify_network(self, evidence_path: Path, terminal_root: Path) -> bool:
        self.network_verify_calls.append((evidence_path, terminal_root))
        return True

    def _runner(self, *, probe=None, launcher=None, network_verifier=None) -> MT5ResearchRunner:
        return MT5ResearchRunner(
            terminal_probe=probe or self._probe,
            launcher=launcher or self._launcher,
            network_isolation_verifier=network_verifier or self._verify_network,
            repository_state_loader=lambda _: RepositoryState(
                commit="a" * 40,
                dirty=True,
                dirty_files=(" M src/example.py",),
            ),
        )

    @staticmethod
    def _spec_payload(spec: ResearchRunSpec) -> dict[str, object]:
        return {
            "schema_version": 1,
            **{
                name: str(value) if isinstance(value, Path) else value
                for name, value in asdict(spec).items()
                if name not in {"costs", "tester"}
            },
            "costs": asdict(spec.costs),
            "tester": asdict(spec.tester),
        }

    def _run(
        self,
        runner: MT5ResearchRunner | None = None,
        spec: ResearchRunSpec | None = None,
    ) -> dict[str, object]:
        bound_spec = spec or self.spec
        spec_path = bound_spec.repository_root / f"{bound_spec.run_id}.matrix-spec.json"
        spec_path.write_text(
            json.dumps(self._spec_payload(bound_spec), sort_keys=True),
            encoding="utf-8",
        )
        authorization = _issue_matrix_execution_authorization(
            matrix_id="test-matrix-001",
            plan_sha256="b" * 64,
            spec_path=spec_path,
            spec_sha256=hashlib.sha256(spec_path.read_bytes()).hexdigest(),
            spec=bound_spec,
        )
        return (runner or self._runner()).run(
            bound_spec,
            _matrix_authorization=authorization,
        )

    def test_verified_run_manifest_is_fully_correlated_and_hashed(self) -> None:
        manifest = self._run()

        self.assertEqual(manifest["status"], "VERIFIED")
        self.assertEqual(manifest["run_id"], self.spec.run_id)
        self.assertEqual(manifest["repository"]["commit"], "a" * 40)
        self.assertTrue(manifest["repository"]["dirty"])
        self.assertEqual(manifest["profile"]["direction"], "ALL")
        self.assertEqual(manifest["profile"]["strategy_mode"], 3)
        self.assertEqual(manifest["profile"]["execution"], "D7_R_LOCK_V1")
        self.assertEqual(manifest["profile"]["strategy"], "GOLDM_SNIPER_PARITY")
        self.assertEqual(manifest["profile"]["strategy_version"], "1.72")
        self.assertEqual(
            manifest["profile"]["management_policy_version"], "M1_R_LOCK_V1"
        )
        self.assertEqual(manifest["market"]["from_inclusive"], "2023-01-01")
        self.assertEqual(manifest["market"]["to_exclusive"], "2023-02-01")
        self.assertEqual(manifest["market"]["range_semantics"], "half-open [from, to)")
        self.assertEqual(manifest["market"]["purpose"], "Development")
        self.assertEqual(
            manifest["market"]["statistical_classification"],
            "DEVELOPMENT_SELECTION",
        )
        self.assertEqual(manifest["market"]["broker_server"], "Research-Broker")
        self.assertEqual(manifest["market"]["symbol_specification"]["digits"], 2)
        self.assertEqual(manifest["market"]["history_declaration"]["row_count"], 3)
        self.assertIn("bounded_history_manifest", manifest["inputs"])
        self.assertEqual(manifest["market"]["history_observation"]["bars"], 100)
        self.assertTrue(manifest["report_contract"]["strict_actual_report_verified"])
        self.assertEqual(
            manifest["compilation"]["status"],
            "SUCCESS_ZERO_ERRORS_ZERO_WARNINGS",
        )
        self.assertEqual(manifest["terminal"]["path"], str(self.spec.terminal_path))
        self.assertEqual(manifest["terminal"]["data_path"], str(self.spec.terminal_data_path))
        self.assertEqual(manifest["terminal"]["build"], "5327")
        self.assertEqual(
            manifest["terminal"]["preexisting_process_policy"], "REJECT_NEVER_CLOSE"
        )
        self.assertEqual(manifest["terminal"]["data_mode"], "PORTABLE")
        self.assertEqual(
            manifest["terminal"]["data_path_binding"],
            "PORTABLE_INSTALL_DIRECTORY",
        )
        self.assertIn("custom_symbol_import_receipt", manifest["inputs"])
        for artifact in ("ea_source", "ea_binary", "set_source", "staged_set"):
            self.assertRegex(manifest["inputs"][artifact]["sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(manifest["artifacts"]["report"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(manifest["artifacts"]["log"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(manifest["artifacts"]["metrics"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(manifest["inputs"]["set_values"]["InpResearchRunId"], self.spec.run_id)
        self.assertEqual(manifest["correlation"]["run_id"], self.spec.run_id)
        self.assertTrue(manifest["correlation"]["lifecycle_verified"])
        self.assertTrue(manifest["correlation"]["report_identity_verified"])
        self.assertEqual(
            manifest["correlation"]["report_identity"]["to_exclusive"],
            "2023-02-01",
        )
        self.assertEqual(manifest["result"]["trade_count"], 1)
        self.assertEqual(manifest["result"]["raw_metrics"]["pooled"]["trades"], 1)
        self.assertEqual(len(self.probe_calls), 3)
        self.assertEqual(
            self.launch_calls,
            [
                (
                    self.spec.terminal_path,
                    self.spec.config_path,
                    TerminalDataMode.PORTABLE,
                )
            ],
        )

        source_text = self.spec.set_source_path.read_text(encoding="utf-8")
        staged_text = self.spec.staged_set_path.read_text(encoding="utf-8")
        config_text = self.spec.config_path.read_text(encoding="ascii")
        disk_manifest = json.loads(self.spec.manifest_path.read_text(encoding="utf-8"))
        metrics_artifact = json.loads(self.spec.metrics_path.read_text(encoding="utf-8"))
        self.assertIn("InpResearchRunId=\n", source_text)
        self.assertIn(f"InpResearchRunId={self.spec.run_id}", staged_text)
        self.assertIn(f"ExpertParameters={self.spec.staged_set_path.name}", config_text)
        self.assertIn(f"Report=reports\\{self.spec.run_id}.html", config_text)
        self.assertIn("ReplaceReport=0", config_text)
        self.assertIn("ShutdownTerminal=1", config_text)
        self.assertIn("FromDate=2023.01.01", config_text)
        self.assertIn("ToDate=2023.02.01", config_text)
        self.assertEqual(disk_manifest["status"], "VERIFIED")
        self.assertEqual(metrics_artifact["run_id"], self.spec.run_id)
        self.assertEqual(metrics_artifact["metric_basis"], "RAW_MODEL_R_NO_ADDITIONAL_COST")
        self.assertEqual(metrics_artifact["trades"][0]["setup_id"], "one")
        self.assertEqual(metrics_artifact["metrics"]["pooled"]["total_r"], 1.0)
        self.assertEqual(
            disk_manifest["artifacts"]["metrics"]["sha256"],
            hashlib.sha256(self.spec.metrics_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(len(self.network_verify_calls), 3)
        self.assertFalse(hasattr(self._runner(), "close_terminal"))
        self.assertFalse(hasattr(self._runner(), "kill_terminal"))

    def test_preflight_is_read_only_and_does_not_launch(self) -> None:
        prepared = self._runner().preflight(self.spec)

        self.assertEqual(prepared.manifest["status"], "PREFLIGHT_OK")
        self.assertEqual(self.launch_calls, [])
        self.assertEqual(len(self.probe_calls), 1)
        self.assertEqual(len(self.network_verify_calls), 1)
        for path in (
            self.spec.staged_set_path,
            self.spec.config_path,
            self.spec.report_path,
            self.spec.metrics_path,
            self.spec.manifest_path,
        ):
            self.assertFalse(path.exists())

    def test_live_network_gate_fails_before_write_or_launch(self) -> None:
        with self.assertRaisesRegex(
            ResearchRunError, "live network isolation verifier did not return"
        ):
            self._runner(network_verifier=lambda evidence, terminal: False).preflight(
                self.spec
            )
        self.assertFalse(self.spec.manifest_path.exists())
        self.assertFalse(self.spec.config_path.exists())
        self.assertEqual(self.launch_calls, [])

    def test_preexisting_report_is_rejected_as_stale_before_launch(self) -> None:
        self.spec.report_path.write_text("old report", encoding="utf-8")

        with self.assertRaisesRegex(ResearchRunError, "already exists"):
            self._run()

        self.assertEqual(self.launch_calls, [])
        self.assertFalse(self.spec.manifest_path.exists())

    def test_preexisting_metrics_artifact_is_rejected_before_launch(self) -> None:
        self.spec.metrics_path.write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(ResearchRunError, "metrics already exists"):
            self._run()

        self.assertEqual(self.launch_calls, [])
        self.assertFalse(self.spec.manifest_path.exists())

    def test_utf16_mt5_report_and_log_are_correlated(self) -> None:
        def launcher(
            terminal_path: Path,
            config_path: Path,
            data_mode: TerminalDataMode,
        ) -> ProcessResult:
            self.spec.report_path.write_text(
                self._complete_report(self.spec), encoding="utf-16"
            )
            self.spec.log_path.write_text(
                self._complete_success_log(self.spec) + "\n",
                encoding="utf-16",
            )
            return ProcessResult(0, terminal_path, data_mode)

        manifest = self._run(self._runner(launcher=launcher))

        self.assertEqual(manifest["status"], "VERIFIED")
        self.assertTrue(manifest["correlation"]["report_run_id_verified"])

    def test_report_broker_or_requested_range_mismatch_fails_closed(self) -> None:
        cases = (
            ("Research-Broker", "Other-Broker", "broker mismatch"),
            ("<td>M15 (", "<td>M5 (", "timeframe or half-open"),
        )
        for original, replacement, expected in cases:
            with self.subTest(expected=expected):
                def launcher(
                    terminal_path: Path,
                    config_path: Path,
                    data_mode: TerminalDataMode,
                ) -> ProcessResult:
                    report = self._complete_report(self.spec).replace(
                        original, replacement, 1
                    )
                    self.spec.report_path.write_text(report, encoding="utf-8")
                    self.spec.log_path.write_text(
                        self._complete_success_log(self.spec) + "\n",
                        encoding="utf-8",
                    )
                    return ProcessResult(0, terminal_path, data_mode)

                with self.assertRaisesRegex(ResearchRunError, expected):
                    self._run(self._runner(launcher=launcher))
                manifest = json.loads(
                    self.spec.manifest_path.read_text(encoding="utf-8")
                )
                self.assertEqual(manifest["status"], "FAILED")
                for path in (
                    self.spec.staged_set_path,
                    self.spec.config_path,
                    self.spec.report_path,
                    self.spec.log_path,
                    self.spec.manifest_path,
                ):
                    if path.exists():
                        path.unlink()

    def test_existing_log_is_verified_only_from_its_append_offset(self) -> None:
        prefix = "unrelated prior run\n"
        self.spec.log_path.write_text(prefix, encoding="utf-8")
        prefix_size = self.spec.log_path.stat().st_size

        manifest = self._run()

        self.assertEqual(
            manifest["correlation"]["log_start_offset"], prefix_size
        )
        self.assertRegex(
            manifest["artifacts"]["log"]["prefix_sha256"], r"^[0-9a-f]{64}$"
        )

    def test_log_replacement_during_run_is_rejected(self) -> None:
        self.spec.log_path.write_text("trusted prefix\n", encoding="utf-8")

        def launcher(
            terminal_path: Path,
            config_path: Path,
            data_mode: TerminalDataMode,
        ) -> ProcessResult:
            self.spec.report_path.write_text(
                f"InpResearchRunId={self.spec.run_id}", encoding="utf-8"
            )
            self.spec.log_path.write_text(
                "replaced prefix with other bytes\n"
                f"SNIPER_CONFIG directionProfile=ALL runId={self.spec.run_id} strategyMode=3\n"
                f"SNIPER_PERFORMANCE runId={self.spec.run_id} strategyMode=3\n",
                encoding="utf-8",
            )
            return ProcessResult(0, terminal_path, data_mode)

        with self.assertRaisesRegex(ResearchRunError, "log prefix changed"):
            self._run(self._runner(launcher=launcher))

    def test_running_or_unknown_terminal_is_never_closed_or_launched(self) -> None:
        for state in (TerminalState.RUNNING, TerminalState.UNKNOWN):
            with self.subTest(state=state):
                self.probe_calls.clear()
                runner = self._runner(
                    probe=lambda path, state=state: self._probe(path, state=state)
                )
                with self.assertRaisesRegex(ResearchRunError, "refusing to close or reuse"):
                    self._run(runner)
                self.assertEqual(self.launch_calls, [])
                self.assertFalse(self.spec.manifest_path.exists())

    def test_development_single_run_execution_is_rejected_before_any_write(self) -> None:
        with self.assertRaisesRegex(ResearchRunError, "matrix-only"):
            self._runner().run(self.spec)
        self.assertEqual(self.probe_calls, [])
        self.assertEqual(self.launch_calls, [])
        self.assertFalse(self.spec.manifest_path.exists())

    def test_terminal_build_or_exact_path_mismatch_is_rejected(self) -> None:
        wrong_terminal = self.spec.terminal_path.parent / "other-terminal64.exe"
        wrong_terminal.write_bytes(b"other")
        cases = (
            lambda path: self._probe(path, build="9999"),
            lambda path: TerminalProbeResult(
                TerminalState.STOPPED,
                wrong_terminal,
                self.spec.terminal_data_path,
                self.spec.terminal_data_mode,
                "5327",
            ),
            lambda path: TerminalProbeResult(
                TerminalState.STOPPED,
                path,
                self.spec.repository_root,
                self.spec.terminal_data_mode,
                "5327",
            ),
        )
        for probe in cases:
            with self.subTest(probe=probe):
                with self.assertRaises(ResearchRunError):
                    self._run(self._runner(probe=probe))
                self.assertEqual(self.launch_calls, [])
                self.assertFalse(self.spec.manifest_path.exists())

    def test_windows_probe_binds_exact_process_data_path_and_build(self) -> None:
        (self.spec.terminal_data_path / "origin.txt").write_text(
            str(self.spec.terminal_path.parent), encoding="utf-8"
        )

        stopped = probe_windows_terminal(
            self.spec.terminal_path,
            self.spec.terminal_data_path,
            TerminalDataMode.STANDARD,
            process_snapshot_loader=lambda _: WindowsProcessSnapshot(()),
            build_loader=lambda _: "5.0.0.5327",
            platform="nt",
        )
        running = probe_windows_terminal(
            self.spec.terminal_path,
            self.spec.terminal_data_path,
            TerminalDataMode.STANDARD,
            process_snapshot_loader=lambda _: WindowsProcessSnapshot(
                (self.spec.terminal_path,)
            ),
            build_loader=lambda _: "5.0.0.5327",
            platform="nt",
        )
        unknown = probe_windows_terminal(
            self.spec.terminal_path,
            self.spec.terminal_data_path,
            TerminalDataMode.STANDARD,
            process_snapshot_loader=lambda _: WindowsProcessSnapshot((), 1),
            build_loader=lambda _: "5.0.0.5327",
            platform="nt",
        )

        self.assertIs(stopped.state, TerminalState.STOPPED)
        self.assertIs(running.state, TerminalState.RUNNING)
        self.assertIs(unknown.state, TerminalState.UNKNOWN)
        self.assertEqual(stopped.executable_path, self.spec.terminal_path)
        self.assertEqual(stopped.data_path, self.spec.terminal_data_path)
        self.assertEqual(stopped.build, "5.0.0.5327")

    def test_windows_probe_rejects_scoped_metatester_collision(self) -> None:
        (self.spec.terminal_data_path / "origin.txt").write_text(
            str(self.spec.terminal_path.parent), encoding="utf-8"
        )
        tester_path = (
            self.spec.terminal_data_path
            / "Tester"
            / "Agent-127.0.0.1-3000"
            / "MetaTester64.exe"
        )
        tester_path.parent.mkdir(parents=True)
        tester_path.write_bytes(b"tester")

        def snapshot(executable_name: str) -> WindowsProcessSnapshot:
            if executable_name.casefold() == "metatester64.exe":
                return WindowsProcessSnapshot((tester_path,))
            return WindowsProcessSnapshot(())

        result = probe_windows_terminal(
            self.spec.terminal_path,
            self.spec.terminal_data_path,
            TerminalDataMode.STANDARD,
            process_snapshot_loader=snapshot,
            build_loader=lambda _: "5.0.0.5327",
            platform="nt",
        )
        self.assertIs(result.state, TerminalState.RUNNING)
        self.assertIn("MetaTester64", result.detail)

    def test_portable_probe_requires_install_directory_without_origin_file(self) -> None:
        portable_data_path = self.spec.terminal_path.parent

        result = probe_windows_terminal(
            self.spec.terminal_path,
            portable_data_path,
            TerminalDataMode.PORTABLE,
            process_snapshot_loader=lambda _: WindowsProcessSnapshot(()),
            build_loader=lambda _: "5.0.0.5327",
            platform="nt",
        )

        self.assertIs(result.state, TerminalState.STOPPED)
        self.assertIs(result.data_mode, TerminalDataMode.PORTABLE)
        self.assertEqual(result.data_path, portable_data_path)
        wrong_data_path = self.spec.repository_root
        with self.assertRaisesRegex(ResearchRunError, "installation directory"):
            probe_windows_terminal(
                self.spec.terminal_path,
                wrong_data_path,
                TerminalDataMode.PORTABLE,
                process_snapshot_loader=lambda _: WindowsProcessSnapshot(()),
                build_loader=lambda _: "5.0.0.5327",
                platform="nt",
            )

    def test_windows_launcher_starts_once_waits_and_never_kills(self) -> None:
        self.spec.config_path.write_text("[Tester]\n", encoding="ascii")
        calls: list[tuple[list[str], dict]] = []

        class FakeProcess:
            pid = 1234
            kill_called = False
            terminate_called = False

            def wait(self, *, timeout):
                self.timeout = timeout
                return 0

            def kill(self):
                self.kill_called = True

            def terminate(self):
                self.terminate_called = True

        process = FakeProcess()

        def popen(arguments, **kwargs):
            calls.append((arguments, kwargs))
            return process

        result = launch_windows_terminal_once(
            self.spec.terminal_path,
            self.spec.config_path,
            TerminalDataMode.PORTABLE,
            timeout_seconds=30,
            popen_factory=popen,
            platform="nt",
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0][0],
            [
                str(self.spec.terminal_path),
                f"/config:{self.spec.config_path}",
                "/portable",
            ],
        )
        self.assertIs(result.data_mode, TerminalDataMode.PORTABLE)
        self.assertFalse(calls[0][1]["shell"])
        self.assertFalse(process.kill_called)
        self.assertFalse(process.terminate_called)

    def test_windows_launcher_timeout_leaves_process_untouched(self) -> None:
        self.spec.config_path.write_text("[Tester]\n", encoding="ascii")

        class TimedOutProcess:
            pid = 4321
            kill_called = False
            terminate_called = False

            def wait(self, *, timeout):
                raise subprocess.TimeoutExpired("terminal64.exe", timeout)

            def kill(self):
                self.kill_called = True

            def terminate(self):
                self.terminate_called = True

        process = TimedOutProcess()

        with self.assertRaisesRegex(ResearchRunError, "left running"):
            launch_windows_terminal_once(
                self.spec.terminal_path,
                self.spec.config_path,
                TerminalDataMode.STANDARD,
                timeout_seconds=1,
                popen_factory=lambda *args, **kwargs: process,
                platform="nt",
            )

        self.assertFalse(process.kill_called)
        self.assertFalse(process.terminate_called)

    def test_json_spec_loader_is_strict_and_preserves_exact_paths(self) -> None:
        payload = {
            "schema_version": 1,
            **{
                name: str(value) if isinstance(value, Path) else value
                for name, value in asdict(self.spec).items()
                if name not in {"costs", "tester"}
            },
            "costs": asdict(self.spec.costs),
            "tester": asdict(self.spec.tester),
        }
        spec_path = self.spec.repository_root / "research-spec.json"
        spec_path.write_text(json.dumps(payload), encoding="utf-8")

        loaded = load_research_run_spec(spec_path)

        self.assertEqual(loaded, self.spec)
        payload["unexpected"] = True
        spec_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ResearchRunError, "unknown"):
            load_research_run_spec(spec_path)

    def test_json_spec_without_explicit_terminal_data_mode_is_rejected(self) -> None:
        payload = {
            "schema_version": 1,
            **{
                name: str(value) if isinstance(value, Path) else value
                for name, value in asdict(self.spec).items()
                if name not in {"costs", "tester", "terminal_data_mode"}
            },
            "costs": asdict(self.spec.costs),
            "tester": asdict(self.spec.tester),
        }
        spec_path = self.spec.repository_root / "research-spec.json"
        spec_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ResearchRunError, "terminal_data_mode"):
            load_research_run_spec(spec_path)

    def test_json_spec_without_statistical_classification_is_rejected(self) -> None:
        payload = {
            "schema_version": 1,
            **{
                name: str(value) if isinstance(value, Path) else value
                for name, value in asdict(self.spec).items()
                if name not in {"costs", "tester", "statistical_classification"}
            },
            "costs": asdict(self.spec.costs),
            "tester": asdict(self.spec.tester),
        }
        spec_path = self.spec.repository_root / "research-spec.json"
        spec_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ResearchRunError, "statistical_classification"):
            load_research_run_spec(spec_path)

    def test_json_spec_rejects_implicit_primitive_type_coercion(self) -> None:
        base_payload = {
            "schema_version": 1,
            **{
                name: str(value) if isinstance(value, Path) else value
                for name, value in asdict(self.spec).items()
                if name not in {"costs", "tester"}
            },
            "costs": asdict(self.spec.costs),
            "tester": asdict(self.spec.tester),
        }
        spec_path = self.spec.repository_root / "research-spec.json"
        cases = (
            ("strategy_mode", True, "strategy_mode"),
            ("terminal_path", 123, "terminal_path"),
        )
        for field_name, value, expected in cases:
            with self.subTest(field_name=field_name):
                payload = dict(base_payload)
                payload[field_name] = value
                spec_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ResearchRunError, expected):
                    load_research_run_spec(spec_path)

        payload = dict(base_payload)
        payload["costs"] = {**base_payload["costs"], "execution_delay_ms": "100"}
        spec_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ResearchRunError, "execution_delay_ms"):
            load_research_run_spec(spec_path)

    def test_portable_spec_fails_closed_when_data_path_is_not_install_path(self) -> None:
        portable = replace(
            self.spec,
            terminal_data_path=self.spec.repository_root,
            terminal_data_mode=TerminalDataMode.PORTABLE,
        )

        with self.assertRaisesRegex(ResearchRunError, "installation directory"):
            self._runner().preflight(portable)

        self.assertEqual(self.probe_calls, [])

    def test_portable_clone_with_account_database_is_rejected_before_probe(self) -> None:
        config = self.spec.terminal_path.parent / "Config"
        config.mkdir()
        (config / "accounts.dat").write_bytes(b"must-not-be-reused")
        portable = replace(
            self.spec,
            terminal_data_path=self.spec.terminal_path.parent,
            terminal_data_mode=TerminalDataMode.PORTABLE,
        )
        with self.assertRaisesRegex(ResearchRunError, "accounts.dat"):
            self._runner().preflight(portable)
        self.assertEqual(self.probe_calls, [])

    def test_run_id_contract_rejects_short_long_whitespace_and_equals(self) -> None:
        invalid_values = (
            "short",
            "x" * 97,
            "bad run id",
            "bad=runid",
        )
        for value in invalid_values:
            with self.subTest(value=value[:16]):
                with self.assertRaisesRegex(ResearchRunError, "run_id"):
                    self._runner().preflight(replace(self.spec, run_id=value))
        self.assertEqual(self.probe_calls, [])

    def test_online_history_mode_is_rejected_before_probe(self) -> None:
        payload = json.loads(self.spec.provenance_path.read_text(encoding="utf-8"))
        payload["history_declaration"]["access_mode"] = "BROKER_ONLINE"
        self.spec.provenance_path.write_text(
            json.dumps(payload, sort_keys=True), encoding="utf-8"
        )
        with self.assertRaisesRegex(ResearchRunError, "OFFLINE_BOUNDED_DATASET"):
            self._runner().preflight(self.spec)
        self.assertEqual(self.probe_calls, [])

    def test_dataset_and_broker_cost_sources_are_rehashed_before_probe(self) -> None:
        payload = json.loads(self.spec.provenance_path.read_text(encoding="utf-8"))
        for evidence_key, expected in (
            ("history_declaration", "bounded history source"),
            ("broker_cost_evidence", "broker cost source"),
        ):
            with self.subTest(evidence_key=evidence_key):
                source = Path(payload[evidence_key]["source_path"])
                original = source.read_bytes()
                source.write_bytes(original + b"tampered")
                with self.assertRaisesRegex(ResearchRunError, expected):
                    self._runner().preflight(self.spec)
                source.write_bytes(original)
        self.assertEqual(self.probe_calls, [])

    def test_execution_requires_schema3_custom_symbol_import_receipt(self) -> None:
        payload = json.loads(self.spec.provenance_path.read_text(encoding="utf-8"))
        payload["schema_version"] = 2
        payload.pop("custom_symbol_import")
        self.spec.provenance_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ResearchRunError, "import receipt exists"):
            self._run()
        with self.assertRaisesRegex(ResearchRunError, "import receipt exists"):
            self._runner().prepare(self.spec)
        self.assertEqual(self.launch_calls, [])
        self.assertFalse(self.spec.staged_set_path.exists())
        self.assertFalse(self.spec.config_path.exists())
        self.assertFalse(self.spec.manifest_path.exists())

    def test_runner_rejects_legacy_dataset_without_source_lineage(self) -> None:
        provenance = json.loads(
            self.spec.provenance_path.read_text(encoding="utf-8")
        )
        manifest_path = Path(
            provenance["history_declaration"]["dataset_manifest_path"]
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = 1
        manifest.pop("source_evidence_path")
        manifest.pop("source_evidence_sha256")
        manifest["manifest_sha256"] = _canonical_sha256(
            {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        provenance["history_declaration"]["dataset_manifest_sha256"] = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        self.spec.provenance_path.write_text(
            json.dumps(provenance, sort_keys=True), encoding="utf-8"
        )
        with self.assertRaisesRegex(ResearchRunError, "schema_version 2"):
            self._run()

    def test_imported_custom_cache_tampering_is_rejected_before_launch(self) -> None:
        provenance = json.loads(self.spec.provenance_path.read_text(encoding="utf-8"))
        receipt = json.loads(
            Path(provenance["custom_symbol_import"]["receipt_path"]).read_text(
                encoding="utf-8"
            )
        )
        cache_path = self.spec.terminal_data_path / receipt["custom_cache_inventory"][0][
            "relative_path"
        ]
        cache_path.write_bytes(b"cache changed after sealing")
        with self.assertRaisesRegex(ResearchRunError, "cache changed"):
            self._run()
        self.assertEqual(self.launch_calls, [])
        self.assertFalse(self.spec.manifest_path.exists())

    def test_cli_defaults_to_read_only_preflight(self) -> None:
        script_path = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "run-goldm-research-safe.py"
        )
        module_spec = importlib.util.spec_from_file_location(
            "test_run_goldm_research_safe",
            script_path,
        )
        self.assertIsNotNone(module_spec)
        self.assertIsNotNone(module_spec.loader)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        calls: list[tuple[str, object]] = []

        class FakeRunner:
            def __init__(
                self, *, terminal_probe, launcher, network_isolation_verifier
            ):
                calls.append(
                    ("init", (terminal_probe, launcher, network_isolation_verifier))
                )

            def preflight(self, spec):
                calls.append(("preflight", spec))
                return SimpleNamespace(manifest={"status": "PREFLIGHT_OK"})

            def run(self, spec):
                raise AssertionError("default CLI mode must not execute")

        module.load_research_run_spec = lambda _: self.spec
        module.make_windows_terminal_probe = (
            lambda data_path, data_mode: (data_path, data_mode)
        )
        module.make_windows_launcher = lambda timeout: timeout
        module.verify_portable_research_clone = lambda *args, **kwargs: SimpleNamespace(
            destination_root=self.spec.terminal_data_path
        )
        module.MT5ResearchRunner = FakeRunner
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = module.main(
                [
                    "--spec",
                    str(self.spec.repository_root / "research-spec.json"),
                    "--clone-manifest",
                    str(self.spec.repository_root / "clone-manifest.json"),
                    "--expected-signer-thumbprint",
                    "A" * 40,
                    "--expected-file-version",
                    "5.0.0.6090",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual([name for name, _ in calls], ["init", "preflight"])
        self.assertEqual(json.loads(output.getvalue())["status"], "PREFLIGHT_OK")
        recovery_args = module.build_parser().parse_args(
            [
                "--stage-a-plan",
                str(self.spec.repository_root / "stage-a-plan.json"),
                "--registry",
                str(self.spec.repository_root / "stage-a-registry.jsonl"),
                "--recover-smoke-a0-d1",
            ]
        )
        self.assertIsNone(recovery_args.clone_manifest)

    def test_quarantine_range_is_rejected_before_probe_or_writes(self) -> None:
        quarantined = replace(
            self.spec,
            from_date="2026-03-01",
            to_date="2026-04-01",
            purpose="Diagnostic",
            statistical_classification=StatisticalClassification.DIAGNOSTIC_ONLY,
        )

        with self.assertRaisesRegex(ValueError, "protected quarantine"):
            self._runner().run(quarantined)

        self.assertEqual(self.probe_calls, [])
        self.assertEqual(self.launch_calls, [])
        self.assertFalse(quarantined.manifest_path.exists())

    def test_statistical_classification_must_match_declared_purpose(self) -> None:
        mislabeled = replace(
            self.spec,
            statistical_classification=(
                StatisticalClassification.LOCKED_LEGACY_VALIDATION
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "requires statistical classification DEVELOPMENT_SELECTION",
        ):
            self._runner().preflight(mislabeled)

        self.assertEqual(self.probe_calls, [])
        self.assertEqual(self.launch_calls, [])

    def test_relative_or_noncanonical_terminal_path_is_rejected(self) -> None:
        relative = replace(self.spec, terminal_path=Path("terminal64.exe"))

        with self.assertRaisesRegex(ResearchRunError, "terminal_path"):
            self._run(spec=relative)

        self.assertEqual(self.probe_calls, [])

    def test_report_path_cannot_escape_terminal_installation_or_hide_extension(self) -> None:
        cases = (
            (
                replace(
                    self.spec,
                    report_path=self.spec.manifest_path.parent
                    / f"{self.spec.run_id}.html",
                ),
                "inside the exact terminal installation",
            ),
            (
                replace(
                    self.spec,
                    report_path=self.spec.report_path.with_suffix(".xml"),
                ),
                "explicit .htm or .html",
            ),
        )
        for invalid, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ResearchRunError, expected):
                    self._runner().preflight(invalid)
        self.assertEqual(self.probe_calls, [])

    def test_missing_report_fails_and_records_failed_manifest(self) -> None:
        def launcher(
            terminal_path: Path,
            config_path: Path,
            data_mode: TerminalDataMode,
        ) -> ProcessResult:
            with self.spec.log_path.open("a", encoding="utf-8") as stream:
                stream.write(
                    f"SNIPER_CONFIG directionProfile=ALL runId={self.spec.run_id} strategyMode=3\n"
                )
            return ProcessResult(0, terminal_path, data_mode)

        with self.assertRaisesRegex(ResearchRunError, "missing report"):
            self._run(self._runner(launcher=launcher))

        manifest = json.loads(self.spec.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "FAILED")
        self.assertIn("missing report", manifest["failure"])

    def test_stale_report_mtime_is_rejected(self) -> None:
        def launcher(
            terminal_path: Path,
            config_path: Path,
            data_mode: TerminalDataMode,
        ) -> ProcessResult:
            self._write_success_artifacts(self.spec)
            os.utime(self.spec.report_path, (946684800, 946684800))
            return ProcessResult(0, terminal_path, data_mode)

        with self.assertRaisesRegex(ResearchRunError, "report is stale"):
            self._run(self._runner(launcher=launcher))

    def test_mismatched_log_run_id_is_rejected(self) -> None:
        def launcher(
            terminal_path: Path,
            config_path: Path,
            data_mode: TerminalDataMode,
        ) -> ProcessResult:
            self.spec.report_path.write_text(
                f"InpResearchRunId={self.spec.run_id}", encoding="utf-8"
            )
            self.spec.log_path.write_text(
                "SNIPER_CONFIG directionProfile=ALL runId=gmr-other-0001 strategyMode=3\n"
                "SNIPER_PERFORMANCE directionProfile=ALL runId=gmr-other-0001 strategyMode=3\n",
                encoding="utf-8",
            )
            return ProcessResult(0, terminal_path, data_mode)

        with self.assertRaisesRegex(ResearchRunError, "runId mismatch"):
            self._run(self._runner(launcher=launcher))

    def test_missing_log_run_id_is_rejected(self) -> None:
        def launcher(
            terminal_path: Path,
            config_path: Path,
            data_mode: TerminalDataMode,
        ) -> ProcessResult:
            self.spec.report_path.write_text(
                f"InpResearchRunId={self.spec.run_id}", encoding="utf-8"
            )
            self.spec.log_path.write_text(
                "SNIPER_CONFIG directionProfile=ALL strategyMode=3\n"
                f"SNIPER_PERFORMANCE runId={self.spec.run_id} strategyMode=3\n",
                encoding="utf-8",
            )
            return ProcessResult(0, terminal_path, data_mode)

        with self.assertRaisesRegex(ResearchRunError, "runId mismatch"):
            self._run(self._runner(launcher=launcher))

    def test_report_without_expected_run_id_is_rejected(self) -> None:
        def launcher(
            terminal_path: Path,
            config_path: Path,
            data_mode: TerminalDataMode,
        ) -> ProcessResult:
            self._write_success_artifacts(self.spec)
            self.spec.report_path.write_text(
                "InpResearchRunId=gmr-wrong-0001", encoding="utf-8"
            )
            return ProcessResult(0, terminal_path, data_mode)

        with self.assertRaisesRegex(ResearchRunError, "report runId mismatch"):
            self._run(self._runner(launcher=launcher))

    def test_set_profile_mismatch_or_nonempty_run_id_is_rejected(self) -> None:
        cases = (
            "InpStrategyMode=3\nInpDirectionProfile=2\nInpResearchRunId=\n",
            "InpStrategyMode=3\nInpDirectionProfile=0\nInpResearchRunId=old-run\n",
        )
        for source in cases:
            with self.subTest(source=source):
                self.spec.set_source_path.write_text(source, encoding="utf-8")
                with self.assertRaises(ResearchRunError):
                    self._run()
                self.assertEqual(self.launch_calls, [])
                self.assertFalse(self.spec.manifest_path.exists())

    def test_set_must_explicitly_cover_every_hashed_ea_input(self) -> None:
        with self.spec.ea_source_path.open("a", encoding="utf-8") as stream:
            stream.write("input int InpSignalValidityMinutes = 5;\n")
        self.spec.ea_binary_path.write_bytes(b"recompiled EA with validity input")
        compilation = json.loads(
            self.spec.provenance_path.read_text(encoding="utf-8")
        )["compilation"]
        Path(compilation["log_path"]).write_text(
            "Recompile result: 0 errors, 0 warnings\n", encoding="utf-8"
        )
        self._refresh_compile_provenance()

        with self.assertRaisesRegex(ResearchRunError, "InpSignalValidityMinutes"):
            self._runner().preflight(self.spec)

        self.assertEqual(self.launch_calls, [])
        self.assertFalse(self.spec.manifest_path.exists())

    def test_source_mutation_without_matching_compile_provenance_is_rejected(self) -> None:
        with self.spec.ea_source_path.open("a", encoding="utf-8") as stream:
            stream.write("// uncompiled source mutation\n")

        with self.assertRaisesRegex(ResearchRunError, "compilation evidence hashes"):
            self._runner().preflight(self.spec)

        self.assertEqual(self.launch_calls, [])

    def test_set_rejects_duplicate_unknown_and_optimization_values(self) -> None:
        baseline = self.spec.set_source_path.read_text(encoding="utf-8")
        cases = (
            (baseline + "InpStrategyMode=3\n", "duplicate"),
            (baseline + "InpUnknownResearchSwitch=true\n", "unknown"),
            (
                baseline.replace(
                    "InpBreakoutChannelBars=12",
                    "InpBreakoutChannelBars=12||12||1||20||Y",
                ),
                "optimization metadata",
            ),
        )
        for source, expected in cases:
            with self.subTest(expected=expected):
                self.spec.set_source_path.write_text(
                    source,
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ResearchRunError, expected):
                    self._runner().preflight(self.spec)

        self.assertEqual(self.launch_calls, [])
        self.assertFalse(self.spec.manifest_path.exists())

    def test_truncated_signal_lifecycle_cannot_be_verified(self) -> None:
        def launcher(
            terminal_path: Path,
            config_path: Path,
            data_mode: TerminalDataMode,
        ) -> ProcessResult:
            self.spec.report_path.write_text(
                f"InpResearchRunId={self.spec.run_id}", encoding="utf-8"
            )
            incomplete = "\n".join(
                line
                for line in self._complete_success_log(self.spec).splitlines()
                if not line.startswith("SNIPER_OUTCOME")
            )
            self.spec.log_path.write_text(incomplete + "\n", encoding="utf-8")
            return ProcessResult(0, terminal_path, data_mode)

        with self.assertRaisesRegex(ResearchRunError, "signals without outcomes"):
            self._run(self._runner(launcher=launcher))

        manifest = json.loads(self.spec.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "FAILED")
        self.assertFalse(self.spec.metrics_path.exists())

    def test_staged_input_mutation_during_launch_is_rejected(self) -> None:
        def launcher(
            terminal_path: Path,
            config_path: Path,
            data_mode: TerminalDataMode,
        ) -> ProcessResult:
            self._write_success_artifacts(self.spec)
            with self.spec.staged_set_path.open("a", encoding="utf-8") as stream:
                stream.write("InpMinimumSetupScore=1\n")
            return ProcessResult(0, terminal_path, data_mode)

        with self.assertRaisesRegex(ResearchRunError, "staged set changed"):
            self._run(self._runner(launcher=launcher))

        manifest = json.loads(self.spec.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
