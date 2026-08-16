from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from goldm_signal.research_import import (  # noqa: E402
    OfflineImportError,
    load_offline_import_network_binding,
    prepare_offline_import_bundle,
    seal_offline_import_receipt,
)
from goldm_signal.research_environment import (  # noqa: E402
    ResearchEnvironmentError,
    verify_portable_research_clone,
)
from goldm_signal.research_network import (  # noqa: E402
    ResearchNetworkError,
    verify_firewall_isolation_evidence,
)
from goldm_signal.research_run import (  # noqa: E402
    ResearchRunError,
    TerminalDataMode,
    TerminalState,
    probe_windows_terminal,
)
from goldm_signal.windows_research_security import (  # noqa: E402
    WindowsResearchSecurityError,
    windows_authenticode_probe,
    windows_directory_security_probe,
    windows_firewall_rule_probe,
)


def _utc_date(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare or seal a bounded offline GoldM custom-tick import. "
            "This command never launches, closes, or attaches to MetaTrader."
        )
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    prepare = subcommands.add_parser(
        "prepare", help="Verify source evidence and stage an immutable MQL5 import bundle."
    )
    prepare.add_argument("--dataset-manifest", type=Path, required=True)
    prepare.add_argument("--symbol-spec", type=Path, required=True)
    prepare.add_argument("--terminal-root", type=Path, required=True)
    prepare.add_argument("--network-isolation-evidence", type=Path, required=True)
    prepare.add_argument("--import-id", required=True)
    prepare.add_argument("--from-date", type=_utc_date, required=True)
    prepare.add_argument("--to-date", type=_utc_date, required=True)
    prepare.add_argument("--purpose", required=True)
    prepare.add_argument("--statistical-classification", required=True)

    seal = subcommands.add_parser(
        "seal",
        help=(
            "Prove the exact portable terminal is stopped, verify MT5's raw receipt, "
            "and seal current bases/Custom inventory."
        ),
    )
    seal.add_argument("--import-plan", type=Path, required=True)
    seal.add_argument("--output", type=Path, required=True)
    for command in (prepare, seal):
        command.add_argument("--clone-manifest", type=Path, required=True)
        command.add_argument("--expected-signer-thumbprint", required=True)
        command.add_argument("--expected-file-version", required=True)
    return parser


def _exact_terminal_stopped(terminal_root: Path) -> bool:
    observation = probe_windows_terminal(
        terminal_root / "terminal64.exe",
        terminal_root,
        TerminalDataMode.PORTABLE,
    )
    if observation.state is TerminalState.UNKNOWN:
        raise OfflineImportError("exact terminal process state is UNKNOWN")
    return observation.state is TerminalState.STOPPED


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        clone = verify_portable_research_clone(
            args.clone_manifest,
            signature_probe=windows_authenticode_probe,
            expected_signer_thumbprint=args.expected_signer_thumbprint,
            expected_file_version=args.expected_file_version,
            directory_security_probe=windows_directory_security_probe,
            require_pristine=False,
        )
        if args.command == "prepare":
            terminal_root = args.terminal_root.resolve(strict=True)
            if terminal_root != clone.destination_root:
                raise OfflineImportError(
                    "import terminal root differs from the sealed offline clone"
                )
            verify_firewall_isolation_evidence(
                args.network_isolation_evidence,
                clone=clone,
                rule_probe=windows_firewall_rule_probe,
            )
            bundle = prepare_offline_import_bundle(
                dataset_manifest_path=args.dataset_manifest,
                symbol_spec_path=args.symbol_spec,
                terminal_root=args.terminal_root,
                network_isolation_evidence_path=args.network_isolation_evidence,
                import_id=args.import_id,
                expected_run_start=args.from_date,
                expected_end=args.to_date,
                expected_purpose=args.purpose,
                expected_classification=args.statistical_classification,
            )
            payload = {
                "status": "IMPORT_BUNDLE_PREPARED_MT5_NOT_LAUNCHED",
                "import_id": bundle.import_id,
                "plan_path": str(bundle.plan_path),
                "plan_sha256": bundle.plan_sha256,
                "control_path": str(bundle.control_path),
                "control_sha256": bundle.control_sha256,
                "staged_dataset_path": str(bundle.staged_dataset_path),
                "raw_receipt_path": str(bundle.raw_receipt_path),
                "next_action": (
                    "Run ImportGoldMOfflineTicks only inside the exact offline portable clone; "
                    "do not run Strategy Tester yet."
                ),
            }
        else:
            terminal_root, network_evidence = load_offline_import_network_binding(
                args.import_plan
            )
            if terminal_root != clone.destination_root:
                raise OfflineImportError(
                    "import plan terminal root differs from the sealed offline clone"
                )
            verify_firewall_isolation_evidence(
                network_evidence,
                clone=clone,
                rule_probe=windows_firewall_rule_probe,
            )
            receipt = seal_offline_import_receipt(
                import_plan_path=args.import_plan,
                output_path=args.output,
                terminal_stopped_probe=_exact_terminal_stopped,
            )
            payload = {
                "status": "OFFLINE_IMPORT_RECEIPT_SEALED_MT5_NOT_LAUNCHED",
                "receipt_path": str(receipt.receipt_path),
                "receipt_sha256": receipt.receipt_file_sha256,
                "receipt_payload_sha256": receipt.receipt_payload_sha256,
                "import_id": receipt.import_id,
                "custom_symbol": receipt.custom_symbol,
                "row_count": receipt.row_count,
                "first_time_msc": receipt.first_time_msc,
                "last_time_msc": receipt.last_time_msc,
                "cache_files": len(receipt.custom_cache_inventory),
                "next_action": (
                    "Bind this receipt in provenance schema_version 3; tester execution "
                    "remains blocked until every other Stage A gate passes."
                ),
            }
    except (
        OfflineImportError,
        ResearchEnvironmentError,
        ResearchNetworkError,
        WindowsResearchSecurityError,
        ResearchRunError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
