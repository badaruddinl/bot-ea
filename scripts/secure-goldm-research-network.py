from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from goldm_signal.research_environment import (  # noqa: E402
    ResearchEnvironmentError,
    verify_portable_research_clone,
)
from goldm_signal.research_network import (  # noqa: E402
    ResearchNetworkError,
    build_firewall_isolation_evidence,
    expected_firewall_rule_names,
    verify_firewall_isolation_evidence,
)
from goldm_signal.windows_research_security import (  # noqa: E402
    WindowsResearchSecurityError,
    install_exact_outbound_block_rules,
    rollback_exact_outbound_block_rules,
    windows_authenticode_probe,
    windows_directory_security_probe,
    windows_firewall_rule_probe,
)


_BINARY_NAMES = ("terminal64.exe", "metaeditor64.exe", "metatester64.exe")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Install or live-verify exact outbound block rules for one sealed GoldM "
            "research clone. This utility never launches MetaTrader."
        )
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command in ("install", "verify"):
        child = subcommands.add_parser(command)
        child.add_argument("--clone-manifest", type=Path, required=True)
        child.add_argument("--expected-signer-thumbprint", required=True)
        child.add_argument("--expected-file-version", required=True)
        child.add_argument("--evidence", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    installed: tuple[str, ...] = ()
    try:
        clone = verify_portable_research_clone(
            args.clone_manifest,
            signature_probe=windows_authenticode_probe,
            expected_signer_thumbprint=args.expected_signer_thumbprint,
            expected_file_version=args.expected_file_version,
            directory_security_probe=windows_directory_security_probe,
            require_pristine=args.command == "install",
        )
        if args.command == "install":
            names = expected_firewall_rule_names(clone)
            specifications = []
            for name, binary_name in zip(names, _BINARY_NAMES, strict=True):
                # Preserve the on-disk filename casing. Windows resolves
                # metaeditor64.exe to MetaEditor64.exe, and the sealed rule
                # identity intentionally includes that exact display name.
                program = (clone.destination_root / binary_name).resolve(strict=True)
                specifications.append(
                    (
                        name,
                        f"GoldM Research Offline - {program.name}",
                        program,
                    )
                )
            installed = install_exact_outbound_block_rules(tuple(specifications))
            try:
                evidence = build_firewall_isolation_evidence(
                    clone=clone,
                    rule_probe=windows_firewall_rule_probe,
                    output_path=args.evidence,
                    verified_at=datetime.now(timezone.utc),
                )
            except Exception:
                rollback_exact_outbound_block_rules(installed)
                installed = ()
                raise
        else:
            evidence = verify_firewall_isolation_evidence(
                args.evidence,
                clone=clone,
                rule_probe=windows_firewall_rule_probe,
            )
    except (
        ResearchEnvironmentError,
        ResearchNetworkError,
        WindowsResearchSecurityError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "error": str(exc),
                    "partial_firewall_rules_retained": bool(installed),
                },
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": "ENFORCED_OFFLINE_VERIFIED",
                "terminal_root": str(evidence.terminal_root),
                "evidence_path": str(evidence.path),
                "evidence_sha256": evidence.file_sha256,
                "evidence_payload_sha256": evidence.payload_sha256,
                "active_rule_names": [rule.name for rule in evidence.rules],
                "next_action": (
                    "Bind this evidence to the offline import plan and re-probe it "
                    "immediately before every research-process launch."
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
