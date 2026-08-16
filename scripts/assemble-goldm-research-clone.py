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
    assemble_portable_research_clone,
    verify_portable_research_clone,
)
from goldm_signal.windows_research_security import (  # noqa: E402
    WindowsResearchSecurityError,
    windows_authenticode_probe,
    windows_directory_security_probe,
    windows_private_directory_creator,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Assemble or verify a signed, state-free MT5 portable research clone. "
            "This utility never launches MetaTrader and never reads broker history."
        )
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    assemble = subcommands.add_parser("assemble")
    assemble.add_argument("--source-install-root", type=Path, required=True)
    assemble.add_argument("--destination-root", type=Path, required=True)
    assemble.add_argument("--expected-signer-thumbprint", required=True)
    assemble.add_argument("--expected-file-version", required=True)
    verify = subcommands.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--expected-signer-thumbprint", required=True)
    verify.add_argument("--expected-file-version", required=True)
    verify.add_argument(
        "--allow-initialized-clone",
        action="store_true",
        help="Allow expected post-assembly terminal directories; binary evidence remains exact.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "assemble":
            evidence = assemble_portable_research_clone(
                source_install_root=args.source_install_root,
                destination_root=args.destination_root,
                signature_probe=windows_authenticode_probe,
                expected_signer_thumbprint=args.expected_signer_thumbprint,
                expected_file_version=args.expected_file_version,
                private_directory_creator=windows_private_directory_creator,
                directory_security_probe=windows_directory_security_probe,
                created_at=datetime.now(timezone.utc),
            )
        else:
            evidence = verify_portable_research_clone(
                args.manifest,
                signature_probe=windows_authenticode_probe,
                expected_signer_thumbprint=args.expected_signer_thumbprint,
                expected_file_version=args.expected_file_version,
                directory_security_probe=windows_directory_security_probe,
                require_pristine=not args.allow_initialized_clone,
            )
    except (ResearchEnvironmentError, WindowsResearchSecurityError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "CLEAN_PORTABLE_CLONE_VERIFIED_NOT_LAUNCHED",
                "manifest_path": str(evidence.manifest_path),
                "manifest_sha256": evidence.manifest_file_sha256,
                "manifest_payload_sha256": evidence.manifest_payload_sha256,
                "source_install_root": str(evidence.source_install_root),
                "destination_root": str(evidence.destination_root),
                "binary_count": len(evidence.copied_binaries),
                "next_action": (
                    "Apply and independently verify exact outbound isolation before any "
                    "MetaEditor, importer, or terminal launch."
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
