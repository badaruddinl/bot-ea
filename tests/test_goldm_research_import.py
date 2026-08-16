from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from goldm_signal.research_import import (
    OfflineImportError,
    assert_clean_portable_research_terminal,
    load_custom_symbol_import_spec,
    load_verified_offline_import,
    prepare_offline_import_bundle,
    seal_offline_import_receipt,
)
from goldm_signal.research_dataset import ResearchDatasetError


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


class GoldMResearchImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.terminal = self.root / "portable-terminal"
        self.terminal.mkdir()
        for name in ("terminal64.exe", "metaeditor64.exe", "metatester64.exe"):
            (self.terminal / name).write_bytes(("sealed-" + name).encode("ascii"))
        self.dataset = self.root / "ticks.csv"
        self.dataset_manifest = self.root / "dataset.json"
        self.dataset_source_evidence = self.root / "dataset-source-evidence.json"
        self.dataset_authority = self.root / "dataset-authority.txt"
        self.dataset_authority.write_text("approved test export\n", encoding="utf-8")
        self.symbol_spec = self.root / "symbol-spec.json"
        self.network_evidence = self.root / "network-evidence.json"
        self._write_dataset()
        self._write_symbol_spec()
        self._write_network_evidence()

    def _write_dataset(self) -> None:
        warmup = datetime(2021, 1, 1, tzinfo=timezone.utc)
        run_start = datetime(2022, 2, 28, tzinfo=timezone.utc)
        rows = [
            int((warmup + timedelta(days=index)).timestamp() * 1000)
            for index in range((run_start.date() - warmup.date()).days)
        ]
        rows.extend(
            (
                int(run_start.timestamp() * 1000),
                int(datetime(2022, 6, 27, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000),
            )
        )
        lines = ["time_msc,bid,ask,last,volume,flags,volume_real"]
        lines.extend(f"{stamp},1999.9,2000.1,0,1,6,1" for stamp in rows)
        self.dataset.write_text("\n".join(lines) + "\n", encoding="utf-8")
        source_payload: dict[str, object] = {
            "schema_version": 1,
            "status": "APPROVED_BOUNDED_OFFLINE_SOURCE",
            "evidence_id": "approved-goldm-import-source",
            "attested_at": "2026-08-15T00:00:00Z",
            "provenance_kind": "SEALED_OFFLINE_EXPORT",
            "authority": "GoldM test authority",
            "capture_method": "EXACT_BOUNDED_TICK_EXPORT",
            "purpose": "Development",
            "statistical_classification": "DEVELOPMENT_SELECTION",
            "source_symbol": "GOLD.i#",
            "warmup_from_inclusive": "2021-01-01",
            "run_from_inclusive": "2022-02-28",
            "to_exclusive": "2022-06-28",
            "dataset_path": str(self.dataset),
            "dataset_sha256": _sha256(self.dataset),
            "authority_artifact_path": str(self.dataset_authority),
            "authority_artifact_sha256": _sha256(self.dataset_authority),
        }
        source_payload["evidence_sha256"] = _canonical_sha256(source_payload)
        self.dataset_source_evidence.write_text(
            json.dumps(source_payload, sort_keys=True), encoding="utf-8"
        )
        payload: dict[str, object] = {
            "schema_version": 2,
            "dataset_id": "goldm-offline-import-d1",
            "registered_at": "2026-08-15T00:00:00Z",
            "purpose": "Development",
            "statistical_classification": "DEVELOPMENT_SELECTION",
            "custom_symbol": "GOLD_i_DEV_D1",
            "source_symbol": "GOLD.i#",
            "warmup_from_inclusive": "2021-01-01",
            "run_from_inclusive": "2022-02-28",
            "to_exclusive": "2022-06-28",
            "format": "MT5_TICKS_CSV_V1",
            "time_semantics": "UTC_HALF_OPEN",
            "row_count": len(rows),
            "first_time_msc": rows[0],
            "last_time_msc": rows[-1],
            "dataset_path": str(self.dataset),
            "dataset_sha256": _sha256(self.dataset),
            "source_evidence_path": str(self.dataset_source_evidence),
            "source_evidence_sha256": _sha256(self.dataset_source_evidence),
        }
        payload["manifest_sha256"] = _canonical_sha256(payload)
        self.dataset_manifest.write_text(json.dumps(payload), encoding="utf-8")

    def _symbol_payload(self) -> dict[str, object]:
        sessions = [
            {"day": day, "index": 0, "from_seconds": 0, "to_seconds": 86400}
            for day in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")
        ]
        payload: dict[str, object] = {
            "schema_version": 1,
            "custom_symbol": "GOLD_i_DEV_D1",
            "source_symbol": "GOLD.i#",
            "custom_group": "GoldMOffline",
            "description": "GoldM sealed Development ticks",
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
        payload["spec_sha256"] = _canonical_sha256(payload)
        return payload

    def _write_symbol_spec(self, payload: dict[str, object] | None = None) -> None:
        self.symbol_spec.write_text(
            json.dumps(payload or self._symbol_payload()), encoding="utf-8"
        )

    def _write_network_evidence(self) -> None:
        payload: dict[str, object] = {
            "schema_version": 1,
            "status": "ENFORCED_OFFLINE",
            "terminal_root": str(self.terminal),
            "terminal_sha256": _sha256(self.terminal / "terminal64.exe"),
            "metatester_sha256": _sha256(self.terminal / "metatester64.exe"),
            "enforcement": "WINDOWS_FIREWALL_BLOCK_OUTBOUND",
            "verified_at": "2026-08-15T00:00:00Z",
        }
        payload["evidence_sha256"] = _canonical_sha256(payload)
        self.network_evidence.write_text(json.dumps(payload), encoding="utf-8")

    def _write_network_evidence_v2(self, *, action: str = "Block") -> None:
        clone_manifest = self.terminal / "portable-clone-manifest.json"
        clone_manifest.write_text(
            json.dumps({"manifest_sha256": "b" * 64}), encoding="utf-8"
        )
        binary_names = ("terminal64.exe", "metaeditor64.exe", "metatester64.exe")
        rules = []
        for binary_name in binary_names:
            program = (self.terminal / binary_name).resolve(strict=True)
            rules.append(
                {
                    "name": (
                        "GoldMResearchOffline-bbbbbbbbbbbbbbbb-"
                        + Path(binary_name).stem
                    ),
                    "display_name": f"GoldM Research Offline - {program.name}",
                    "enabled": True,
                    "direction": "Outbound",
                    "action": action,
                    "profile": "Any",
                    "program_path": str(program),
                    "protocol": "Any",
                    "local_addresses": ["Any"],
                    "remote_addresses": ["Any"],
                    "local_ports": ["Any"],
                    "remote_ports": ["Any"],
                    "service": "Any",
                    "interface_type": "Any",
                    "policy_store_source_type": "Local",
                }
            )
        payload: dict[str, object] = {
            "schema_version": 2,
            "status": "ENFORCED_OFFLINE",
            "enforcement": "WINDOWS_FIREWALL_BLOCK_OUTBOUND_EXACT_PROGRAMS",
            "verified_at": "2026-08-15T00:00:00Z",
            "clone_manifest_path": str(clone_manifest),
            "clone_manifest_sha256": _sha256(clone_manifest),
            "clone_manifest_payload_sha256": "b" * 64,
            "terminal_root": str(self.terminal),
            "binary_sha256": {
                name: _sha256(self.terminal / name) for name in binary_names
            },
            "rules": rules,
        }
        payload["evidence_sha256"] = _canonical_sha256(payload)
        self.network_evidence.write_text(json.dumps(payload), encoding="utf-8")

    def _prepare(self):
        return prepare_offline_import_bundle(
            dataset_manifest_path=self.dataset_manifest,
            symbol_spec_path=self.symbol_spec,
            terminal_root=self.terminal,
            network_isolation_evidence_path=self.network_evidence,
            import_id="goldm-d1-import-0001",
            expected_run_start=datetime(2022, 2, 28, tzinfo=timezone.utc),
            expected_end=datetime(2022, 6, 28, tzinfo=timezone.utc),
            expected_purpose="Development",
            expected_classification="DEVELOPMENT_SELECTION",
            created_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        )

    def test_schema2_exact_firewall_structure_is_required(self) -> None:
        self._write_network_evidence_v2()
        self.assertEqual(self._prepare().import_id, "goldm-d1-import-0001")

    def test_schema2_allow_rule_is_rejected(self) -> None:
        self._write_network_evidence_v2(action="Allow")
        with self.assertRaisesRegex(OfflineImportError, "firewall rule is not exact"):
            self._prepare()

    def _write_raw_receipt_and_cache(self, bundle) -> None:
        plan = json.loads(bundle.plan_path.read_text(encoding="utf-8"))
        dataset = json.loads(self.dataset_manifest.read_text(encoding="utf-8"))
        rows = {
            "format": "MT5_CUSTOM_TICK_IMPORT_RECEIPT_V1",
            "status": "VERIFIED_CACHE_MATCH",
            "import_id": "goldm-d1-import-0001",
            "custom_symbol": "GOLD_i_DEV_D1",
            "source_symbol": "GOLD.i#",
            "dataset_sha256": dataset["dataset_sha256"],
            "dataset_manifest_sha256": _sha256(self.dataset_manifest),
            "symbol_spec_sha256": _sha256(self.symbol_spec),
            "control_sha256": plan["staged_control_sha256"],
            "row_count": str(dataset["row_count"]),
            "first_time_msc": str(dataset["first_time_msc"]),
            "last_time_msc": str(dataset["last_time_msc"]),
            "formula": "EMPTY",
            "origin": "NONE",
            "portable": "TRUE",
            "connected": "FALSE",
        }
        bundle.raw_receipt_path.write_text(
            "key;value\n" + "".join(f"{key};{value}\n" for key, value in rows.items()),
            encoding="utf-8",
        )
        cache = self.terminal / "bases" / "Custom" / "GoldMOffline" / "ticks.hcc"
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"simulated custom tick cache")

    def test_spec_is_self_hashed_and_sessions_are_bounded(self) -> None:
        spec = load_custom_symbol_import_spec(self.symbol_spec)
        self.assertEqual(spec.custom_symbol, "GOLD_i_DEV_D1")
        self.assertEqual(len(spec.quote_sessions), 5)

        payload = self._symbol_payload()
        payload["trade_sessions"] = [dict(item) for item in payload["trade_sessions"]]
        payload["trade_sessions"][0]["to_seconds"] = 90000
        payload["spec_sha256"] = _canonical_sha256(
            {key: value for key, value in payload.items() if key != "spec_sha256"}
        )
        self._write_symbol_spec(payload)
        with self.assertRaisesRegex(OfflineImportError, "contained in a quote"):
            load_custom_symbol_import_spec(self.symbol_spec)

    def test_prepare_stages_exact_hashes_but_never_launches_terminal(self) -> None:
        bundle = self._prepare()
        self.assertEqual(bundle.staged_dataset_path.read_bytes(), self.dataset.read_bytes())
        self.assertEqual(bundle.control_sha256, _sha256(bundle.control_path))
        control = bundle.control_path.read_text(encoding="utf-8")
        self.assertIn("CONTROL;formula;;;", control)
        self.assertIn("QUOTE_SESSION;MONDAY;0;0;86400", control)
        self.assertFalse(bundle.raw_receipt_path.exists())

    def test_prepare_rejects_account_state_broker_bases_and_replay(self) -> None:
        accounts = self.terminal / "Config" / "accounts.dat"
        accounts.parent.mkdir()
        accounts.write_bytes(b"forbidden")
        with self.assertRaisesRegex(OfflineImportError, "forbidden state"):
            self._prepare()
        accounts.unlink()

        broker_base = self.terminal / "bases" / "Broker-Demo"
        broker_base.mkdir(parents=True)
        with self.assertRaisesRegex(OfflineImportError, "broker/server bases"):
            self._prepare()
        broker_base.rmdir()
        bundle = self._prepare()
        self.assertTrue(bundle.plan_path.is_file())
        with self.assertRaisesRegex(OfflineImportError, "custom-symbol cache is not empty|already exists"):
            self._prepare()

    def test_success_receipt_binds_dataset_plan_terminal_and_cache(self) -> None:
        bundle = self._prepare()
        self._write_raw_receipt_and_cache(bundle)
        output = self.root / "sealed-receipt.json"
        receipt = seal_offline_import_receipt(
            import_plan_path=bundle.plan_path,
            output_path=output,
            terminal_stopped_probe=lambda terminal: terminal == self.terminal,
            sealed_at=datetime(2026, 8, 15, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(receipt.custom_symbol, "GOLD_i_DEV_D1")
        self.assertEqual(receipt.row_count, json.loads(self.dataset_manifest.read_text())["row_count"])
        self.assertEqual(load_verified_offline_import(output), receipt)

        cache_path = self.terminal / receipt.custom_cache_inventory[0]["relative_path"]
        cache_path.write_bytes(b"tampered cache")
        with self.assertRaisesRegex(OfflineImportError, "cache changed"):
            load_verified_offline_import(output)

    def test_sealing_fails_for_running_terminal_or_false_raw_receipt(self) -> None:
        bundle = self._prepare()
        self._write_raw_receipt_and_cache(bundle)
        with self.assertRaisesRegex(OfflineImportError, "proven stopped"):
            seal_offline_import_receipt(
                import_plan_path=bundle.plan_path,
                output_path=self.root / "never.json",
                terminal_stopped_probe=lambda _terminal: False,
            )
        raw = bundle.raw_receipt_path.read_text(encoding="utf-8").replace(
            "VERIFIED_CACHE_MATCH", "FAILED"
        )
        bundle.raw_receipt_path.write_text(raw, encoding="utf-8")
        with self.assertRaisesRegex(OfflineImportError, "raw import receipt mismatch"):
            seal_offline_import_receipt(
                import_plan_path=bundle.plan_path,
                output_path=self.root / "bad.json",
                terminal_stopped_probe=lambda _terminal: True,
            )

    def test_dataset_integer_values_must_fit_mqltick(self) -> None:
        text = self.dataset.read_text(encoding="utf-8")
        self.dataset.write_text(
            text.replace(",1,6,1\n", ",18446744073709551616,6,1\n", 1),
            encoding="utf-8",
        )
        manifest = json.loads(self.dataset_manifest.read_text(encoding="utf-8"))
        manifest["dataset_sha256"] = _sha256(self.dataset)
        source_evidence = json.loads(
            self.dataset_source_evidence.read_text(encoding="utf-8")
        )
        source_evidence["dataset_sha256"] = _sha256(self.dataset)
        source_evidence["evidence_sha256"] = _canonical_sha256(
            {
                key: value
                for key, value in source_evidence.items()
                if key != "evidence_sha256"
            }
        )
        self.dataset_source_evidence.write_text(
            json.dumps(source_evidence), encoding="utf-8"
        )
        manifest["source_evidence_sha256"] = _sha256(
            self.dataset_source_evidence
        )
        manifest["manifest_sha256"] = _canonical_sha256(
            {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        )
        self.dataset_manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(Exception, "MqlTick bounds"):
            self._prepare()

    def test_prepare_rejects_legacy_dataset_without_source_lineage(self) -> None:
        manifest = json.loads(self.dataset_manifest.read_text(encoding="utf-8"))
        manifest["schema_version"] = 1
        manifest.pop("source_evidence_path")
        manifest.pop("source_evidence_sha256")
        manifest["manifest_sha256"] = _canonical_sha256(
            {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        )
        self.dataset_manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ResearchDatasetError, "schema_version 2"):
            self._prepare()

    def test_static_importer_contract_rejects_online_and_quarantine(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "mt5"
            / "Scripts"
            / "bot-ea"
            / "ImportGoldMOfflineTicks.mq5"
        ).read_text(encoding="utf-8")
        self.assertIn("TerminalInfoInteger(TERMINAL_CONNECTED)", source)
        self.assertIn("TerminalInfoString(TERMINAL_PATH)", source)
        self.assertIn("CustomSymbolCreate(control.custom_symbol,control.custom_group,NULL)", source)
        self.assertIn("CustomTicksReplace", source)
        self.assertIn("CopyTicksRange", source)
        self.assertIn("QUARANTINE_FROM_MSC 1772236800000", source)
        self.assertIn("QUARANTINE_TO_MSC   1782864000000", source)
        self.assertNotIn("CustomRatesReplace", source)


if __name__ == "__main__":
    unittest.main()
