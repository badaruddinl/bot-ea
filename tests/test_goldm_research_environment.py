from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from goldm_signal.research_environment import (
    AuthenticodeSnapshot,
    DirectorySecuritySnapshot,
    ResearchEnvironmentError,
    assemble_portable_research_clone,
    verify_portable_research_clone,
)


class GoldMResearchEnvironmentTests(unittest.TestCase):
    THUMBPRINT = "A" * 40
    FILE_VERSION = "5.0.0.6090"
    USER_SID = "S-1-5-21-1000"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "MetaTrader-5-install"
        self.source.mkdir()
        for name in ("terminal64.exe", "metaeditor64.exe", "metatester64.exe"):
            (self.source / name).write_bytes(("signed-" + name).encode("ascii"))
        for directory in ("Bases", "Config", "Profiles", "Sounds"):
            path = self.source / directory
            path.mkdir()
            (path / "must-not-copy.dat").write_bytes(b"source state")
        (self.source / "uninstall.exe").write_bytes(b"not part of clone")
        self.destination = self.root / "goldm-mt5-portable-6090"

    @staticmethod
    def _signature(
        _path: Path,
        *,
        status: str = "Valid",
        thumbprint: str = THUMBPRINT,
    ) -> AuthenticodeSnapshot:
        return AuthenticodeSnapshot(
            status=status,
            signer_subject="CN=MetaQuotes Ltd., O=MetaQuotes Ltd., S=Lemesos, C=CY",
            signer_thumbprint=thumbprint,
            timestamp_subject="CN=Trusted Timestamp",
            file_version=GoldMResearchEnvironmentTests.FILE_VERSION,
        )

    @classmethod
    def _security(cls, _path: Path) -> DirectorySecuritySnapshot:
        allowed = tuple(sorted((cls.USER_SID, "S-1-5-18", "S-1-5-32-544")))
        return DirectorySecuritySnapshot(
            owner_sid=cls.USER_SID,
            current_user_sid=cls.USER_SID,
            inheritance_protected=True,
            allowed_sids=allowed,
            denied_sids=(),
            full_control_sids=allowed,
            non_full_control_rule_count=0,
            sddl="O:S-1-5-21-1000D:PAI",
        )

    @classmethod
    def _private_creator(cls, path: Path) -> DirectorySecuritySnapshot:
        path.mkdir(exist_ok=False)
        return cls._security(path)

    def _assemble(self):
        return assemble_portable_research_clone(
            source_install_root=self.source,
            destination_root=self.destination,
            signature_probe=self._signature,
            expected_signer_thumbprint=self.THUMBPRINT,
            expected_file_version=self.FILE_VERSION,
            private_directory_creator=self._private_creator,
            directory_security_probe=self._security,
            created_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        )

    def test_assembler_copies_only_three_signed_binaries_and_never_state(self) -> None:
        evidence = self._assemble()
        self.assertEqual(evidence.destination_root, self.destination)
        self.assertEqual(
            sorted(item.name for item in self.destination.iterdir()),
            sorted(
                (
                    "terminal64.exe",
                    "metaeditor64.exe",
                    "metatester64.exe",
                    "portable-clone-manifest.json",
                )
            ),
        )
        self.assertFalse((self.destination / "Bases").exists())
        self.assertFalse((self.destination / "Config").exists())
        self.assertFalse((self.destination / "Profiles").exists())
        self.assertEqual(len(evidence.copied_binaries), 3)
        payload = json.loads(evidence.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["expected_signer_thumbprint"], self.THUMBPRINT)
        self.assertTrue(payload["directory_security"]["inheritance_protected"])
        self.assertEqual(
            verify_portable_research_clone(
                evidence.manifest_path,
                signature_probe=self._signature,
                expected_signer_thumbprint=self.THUMBPRINT,
                expected_file_version=self.FILE_VERSION,
                directory_security_probe=self._security,
                require_pristine=True,
            ),
            evidence,
        )

    def test_later_verification_is_bound_to_clone_not_mutable_source_install(self) -> None:
        evidence = self._assemble()
        self.source.rename(self.root / "source-install-updated")
        self.assertEqual(
            verify_portable_research_clone(
                evidence.manifest_path,
                signature_probe=self._signature,
                expected_signer_thumbprint=self.THUMBPRINT,
                expected_file_version=self.FILE_VERSION,
                directory_security_probe=self._security,
                require_pristine=True,
                require_source_unchanged=False,
            ),
            evidence,
        )
        with self.assertRaisesRegex(ResearchEnvironmentError, "does not exist"):
            verify_portable_research_clone(
                evidence.manifest_path,
                signature_probe=self._signature,
                expected_signer_thumbprint=self.THUMBPRINT,
                expected_file_version=self.FILE_VERSION,
                directory_security_probe=self._security,
                require_pristine=True,
                require_source_unchanged=True,
            )

    def test_acl_and_external_trust_anchor_changes_fail_closed(self) -> None:
        evidence = self._assemble()
        with self.assertRaisesRegex(ResearchEnvironmentError, "ACL is not exact/private"):
            verify_portable_research_clone(
                evidence.manifest_path,
                signature_probe=self._signature,
                expected_signer_thumbprint=self.THUMBPRINT,
                expected_file_version=self.FILE_VERSION,
                directory_security_probe=lambda path: replace(
                    self._security(path), inheritance_protected=False
                ),
                require_pristine=True,
            )
        with self.assertRaisesRegex(ResearchEnvironmentError, "trust anchor mismatch"):
            verify_portable_research_clone(
                evidence.manifest_path,
                signature_probe=self._signature,
                expected_signer_thumbprint="B" * 40,
                expected_file_version=self.FILE_VERSION,
                directory_security_probe=self._security,
                require_pristine=True,
            )

    def test_failed_private_acl_validation_removes_only_partial_staging_leaf(self) -> None:
        def insecure_creator(path: Path) -> DirectorySecuritySnapshot:
            path.mkdir(exist_ok=False)
            return replace(self._security(path), inheritance_protected=False)

        with self.assertRaisesRegex(ResearchEnvironmentError, "ACL is not exact/private"):
            assemble_portable_research_clone(
                source_install_root=self.source,
                destination_root=self.destination,
                signature_probe=self._signature,
                expected_signer_thumbprint=self.THUMBPRINT,
                expected_file_version=self.FILE_VERSION,
                private_directory_creator=insecure_creator,
                directory_security_probe=self._security,
            )
        self.assertFalse(self.destination.exists())
        self.assertFalse(any(item.name.startswith(".goldm-mt5") for item in self.root.iterdir()))

    def test_binary_or_manifest_tampering_fails_closed(self) -> None:
        evidence = self._assemble()
        (self.destination / "terminal64.exe").write_bytes(b"tampered")
        with self.assertRaisesRegex(ResearchEnvironmentError, "binary changed"):
            verify_portable_research_clone(
                evidence.manifest_path,
                signature_probe=self._signature,
                expected_signer_thumbprint=self.THUMBPRINT,
                expected_file_version=self.FILE_VERSION,
                directory_security_probe=self._security,
                require_pristine=True,
            )

        (self.destination / "terminal64.exe").write_bytes(b"signed-terminal64.exe")
        payload = json.loads(evidence.manifest_path.read_text(encoding="utf-8"))
        payload["launch_performed"] = True
        evidence.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ResearchEnvironmentError, "self-hash mismatch"):
            verify_portable_research_clone(
                evidence.manifest_path,
                signature_probe=self._signature,
                expected_signer_thumbprint=self.THUMBPRINT,
                expected_file_version=self.FILE_VERSION,
                directory_security_probe=self._security,
                require_pristine=True,
            )

    def test_invalid_or_mixed_signatures_and_existing_destination_are_rejected(self) -> None:
        with self.assertRaisesRegex(ResearchEnvironmentError, "not valid"):
            assemble_portable_research_clone(
                source_install_root=self.source,
                destination_root=self.destination,
                signature_probe=lambda path: self._signature(path, status="NotSigned"),
                expected_signer_thumbprint=self.THUMBPRINT,
                expected_file_version=self.FILE_VERSION,
                private_directory_creator=self._private_creator,
                directory_security_probe=self._security,
            )
        self.assertFalse(self.destination.exists())

        def mixed(path: Path) -> AuthenticodeSnapshot:
            thumbprint = "B" * 40 if path.name.casefold() == "metatester64.exe" else "A" * 40
            return self._signature(path, thumbprint=thumbprint)

        with self.assertRaisesRegex(ResearchEnvironmentError, "thumbprint mismatch"):
            assemble_portable_research_clone(
                source_install_root=self.source,
                destination_root=self.destination,
                signature_probe=mixed,
                expected_signer_thumbprint=self.THUMBPRINT,
                expected_file_version=self.FILE_VERSION,
                private_directory_creator=self._private_creator,
                directory_security_probe=self._security,
            )
        self.destination.mkdir()
        with self.assertRaisesRegex(ResearchEnvironmentError, "already exists"):
            self._assemble()

    def test_pristine_verifier_rejects_any_undeclared_entry(self) -> None:
        evidence = self._assemble()
        (self.destination / "origin.txt").write_text("forbidden", encoding="utf-8")
        with self.assertRaisesRegex(
            ResearchEnvironmentError, "undeclared files|forbidden state"
        ):
            verify_portable_research_clone(
                evidence.manifest_path,
                signature_probe=self._signature,
                expected_signer_thumbprint=self.THUMBPRINT,
                expected_file_version=self.FILE_VERSION,
                directory_security_probe=self._security,
                require_pristine=True,
            )

    def test_cli_has_no_terminal_launch_capability(self) -> None:
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "assemble-goldm-research-clone.py"
        ).read_text(encoding="utf-8")
        security_module = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "goldm_signal"
            / "windows_research_security.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Get-AuthenticodeSignature", security_module)
        self.assertNotIn("Start-Process", script)
        self.assertNotIn("terminal64.exe\"", script)
        self.assertNotIn("Popen", script)
        self.assertNotIn("ExecutionPolicy", script)
        self.assertNotIn("ExecutionPolicy", security_module)
        self.assertIn("--expected-signer-thumbprint", script)


if __name__ == "__main__":
    unittest.main()
