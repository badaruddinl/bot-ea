from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from goldm_signal import windows_research_security
from goldm_signal.research_environment import PortableCloneEvidence
from goldm_signal.research_network import (
    FirewallRuleSnapshot,
    ResearchNetworkError,
    build_firewall_isolation_evidence,
    expected_firewall_rule_names,
    verify_firewall_isolation_evidence,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GoldMResearchNetworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.clone_root = self.root / "goldm-mt5-portable-6090"
        self.clone_root.mkdir()
        records = []
        for name in ("terminal64.exe", "metaeditor64.exe", "metatester64.exe"):
            path = self.clone_root / name
            path.write_bytes(("signed-" + name).encode("ascii"))
            records.append({"name": name, "sha256": _sha256(path)})
        manifest = self.clone_root / "portable-clone-manifest.json"
        manifest.write_text('{"sealed":true}\n', encoding="utf-8")
        self.clone = PortableCloneEvidence(
            manifest_path=manifest,
            manifest_file_sha256=_sha256(manifest),
            manifest_payload_sha256="a" * 64,
            source_install_root=self.root / "source-install",
            destination_root=self.clone_root,
            copied_binaries=tuple(records),
        )
        self.output = self.clone_root / "network-isolation-evidence.json"
        self.rules = self._rules()

    def _rules(self) -> tuple[FirewallRuleSnapshot, ...]:
        result = []
        for rule_name, binary_name in zip(
            expected_firewall_rule_names(self.clone),
            ("terminal64.exe", "metaeditor64.exe", "metatester64.exe"),
            strict=True,
        ):
            result.append(
                FirewallRuleSnapshot(
                    name=rule_name,
                    display_name=f"GoldM Research Offline - {binary_name}",
                    enabled=True,
                    direction="Outbound",
                    action="Block",
                    profile="Any",
                    program_path=self.clone_root / binary_name,
                    protocol="Any",
                    local_addresses=("Any",),
                    remote_addresses=("Any",),
                    local_ports=("Any",),
                    remote_ports=("Any",),
                    service="Any",
                    interface_type="Any",
                    policy_store_source_type="Local",
                )
            )
        return tuple(result)

    def _probe(self, names: tuple[str, ...]) -> tuple[FirewallRuleSnapshot, ...]:
        self.assertEqual(names, expected_firewall_rule_names(self.clone))
        return self.rules

    def test_build_and_live_reverify_exact_firewall_evidence(self) -> None:
        self.assertEqual(
            expected_firewall_rule_names(self.clone),
            (
                "GoldMResearchOffline-aaaaaaaaaaaaaaaa-terminal64",
                "GoldMResearchOffline-aaaaaaaaaaaaaaaa-metaeditor64",
                "GoldMResearchOffline-aaaaaaaaaaaaaaaa-metatester64",
            ),
        )
        evidence = build_firewall_isolation_evidence(
            clone=self.clone,
            rule_probe=self._probe,
            output_path=self.output,
            verified_at=datetime(2026, 8, 15, tzinfo=UTC),
        )
        self.assertEqual(evidence.path, self.output)
        self.assertEqual(evidence.rules, self.rules)
        payload = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(
            payload["binary_sha256"]["terminal64.exe"],
            _sha256(self.clone_root / "terminal64.exe"),
        )
        self.assertEqual(
            verify_firewall_isolation_evidence(
                self.output,
                clone=self.clone,
                rule_probe=self._probe,
            ),
            evidence,
        )

    def test_missing_or_non_block_rule_is_rejected_before_evidence_write(self) -> None:
        with self.assertRaisesRegex(ResearchNetworkError, "inventory is incomplete"):
            build_firewall_isolation_evidence(
                clone=self.clone,
                rule_probe=lambda names: self.rules[:-1],
                output_path=self.output,
            )
        self.assertFalse(self.output.exists())

        wrong = (replace(self.rules[0], action="Allow"), *self.rules[1:])
        with self.assertRaisesRegex(ResearchNetworkError, "exact active outbound block"):
            build_firewall_isolation_evidence(
                clone=self.clone,
                rule_probe=lambda names: wrong,
                output_path=self.output,
            )
        self.assertFalse(self.output.exists())

    def test_program_or_active_rule_drift_fails_closed(self) -> None:
        wrong_program = self.root / "other-terminal64.exe"
        wrong_program.write_bytes(b"other")
        wrong = (replace(self.rules[0], program_path=wrong_program), *self.rules[1:])
        with self.assertRaisesRegex(ResearchNetworkError, "exact active outbound block"):
            build_firewall_isolation_evidence(
                clone=self.clone,
                rule_probe=lambda names: wrong,
                output_path=self.output,
            )

        build_firewall_isolation_evidence(
            clone=self.clone,
            rule_probe=self._probe,
            output_path=self.output,
        )
        drifted = (replace(self.rules[0], enabled=False), *self.rules[1:])
        with self.assertRaisesRegex(ResearchNetworkError, "exact active outbound block"):
            verify_firewall_isolation_evidence(
                self.output,
                clone=self.clone,
                rule_probe=lambda names: drifted,
            )

    def test_post_write_reprobe_failure_removes_only_generated_evidence(self) -> None:
        calls = 0

        def changing_probe(
            names: tuple[str, ...],
        ) -> tuple[FirewallRuleSnapshot, ...]:
            nonlocal calls
            calls += 1
            if calls == 1:
                return self.rules
            return (replace(self.rules[0], enabled=False), *self.rules[1:])

        with self.assertRaisesRegex(ResearchNetworkError, "exact active outbound block"):
            build_firewall_isolation_evidence(
                clone=self.clone,
                rule_probe=changing_probe,
                output_path=self.output,
            )
        self.assertEqual(calls, 2)
        self.assertFalse(self.output.exists())

    def test_tamper_wrong_location_and_overwrite_are_rejected(self) -> None:
        outside = self.root / "network-isolation-evidence.json"
        with self.assertRaisesRegex(ResearchNetworkError, "private clone root"):
            build_firewall_isolation_evidence(
                clone=self.clone,
                rule_probe=self._probe,
                output_path=outside,
            )

        build_firewall_isolation_evidence(
            clone=self.clone,
            rule_probe=self._probe,
            output_path=self.output,
        )
        with self.assertRaisesRegex(ResearchNetworkError, "overwrite is prohibited"):
            build_firewall_isolation_evidence(
                clone=self.clone,
                rule_probe=self._probe,
                output_path=self.output,
            )
        payload = json.loads(self.output.read_text(encoding="utf-8"))
        payload["status"] = "NOT_OFFLINE"
        self.output.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ResearchNetworkError, "self-hash mismatch"):
            verify_firewall_isolation_evidence(
                self.output,
                clone=self.clone,
                rule_probe=self._probe,
            )

    def test_network_cli_has_no_research_process_launch_or_uninstall_mode(self) -> None:
        script = (
            Path(__file__).resolve().parents[1] / "scripts" / "secure-goldm-research-network.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("Start-Process", script)
        self.assertNotIn("subprocess", script)
        self.assertNotIn('"uninstall"', script)
        self.assertIn('("install", "verify")', script)

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell parser is Windows-only")
    def test_all_embedded_windows_security_scripts_parse_without_execution(self) -> None:
        parser = r"""
$ErrorActionPreference = 'Stop'
$scripts = @($env:GOLDM_RESEARCH_PROBE_ARG0 | ConvertFrom-Json)
foreach ($script in $scripts) {
  $tokens = $null
  $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseInput(
    [string]$script,
    [ref]$tokens,
    [ref]$errors
  )
  if ($errors.Count -ne 0) {
    throw (($errors | ForEach-Object {$_.Message}) -join '; ')
  }
}
[ordered]@{ ok = $true } | ConvertTo-Json -Compress
"""
        scripts = (
            windows_research_security._SIGNATURE_SCRIPT,
            windows_research_security._DIRECTORY_SECURITY_SCRIPT,
            windows_research_security._ADMIN_SCRIPT,
            windows_research_security._RULE_EXISTS_SCRIPT,
            windows_research_security._INSTALL_RULE_SCRIPT,
            windows_research_security._REMOVE_RULE_SCRIPT,
            windows_research_security._PROBE_RULE_SCRIPT,
        )
        self.assertEqual(
            windows_research_security._single_json(
                windows_research_security._run_system_powershell(
                    parser,
                    json.dumps(scripts),
                    timeout_seconds=120,
                )
            ),
            {"ok": True},
        )


if __name__ == "__main__":
    unittest.main()
