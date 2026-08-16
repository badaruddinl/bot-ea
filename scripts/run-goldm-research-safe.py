from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from goldm_signal.research_run import (  # noqa: E402
    MT5ResearchRunner,
    ResearchRunError,
    load_research_run_spec,
    make_windows_launcher,
    make_windows_terminal_probe,
)
from goldm_signal.research_environment import (  # noqa: E402
    ResearchEnvironmentError,
    verify_portable_research_clone,
)
from goldm_signal.research_network import (  # noqa: E402
    ResearchNetworkError,
    verify_firewall_isolation_evidence,
)
from goldm_signal.research_stage_a import (  # noqa: E402
    AppendOnlyResearchRegistry,
    StageAError,
    StageAOrchestrator,
    load_stage_a_plan,
)
from goldm_signal.windows_research_security import (  # noqa: E402
    WindowsResearchSecurityError,
    windows_authenticode_probe,
    windows_directory_security_probe,
    windows_firewall_rule_probe,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed GOLDm MT5 research runner. The default mode performs "
            "read-only preflight and never launches MT5."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--spec",
        type=Path,
        help=(
            "Exact absolute path to one schema_version 1 research-run JSON spec. "
            "Execution is allowed only for Diagnostic runs; production research "
            "purposes require an orchestrated matrix."
        ),
    )
    source.add_argument(
        "--stage-a-plan",
        type=Path,
        help="Exact absolute path to an immutable Stage A 3x6 matrix plan.",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        help=(
            "Exact absolute append-only registry path. Required with "
            "--stage-a-plan --execute and unused for single-run preflight."
        ),
    )
    parser.add_argument("--clone-manifest", type=Path)
    parser.add_argument("--expected-signer-thumbprint")
    parser.add_argument("--expected-file-version")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--preflight",
        action="store_true",
        help="Validate and fingerprint only; this is the default and writes nothing.",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Explicitly stage artifacts and launch the dedicated MT5 terminal once.",
    )
    mode.add_argument(
        "--execute-smoke-a0-d1",
        action="store_true",
        help=(
            "Register the full Stage A plan but execute only A0/D1 as the "
            "strict actual-report contract smoke. The other 17 cells remain PLANNED."
        ),
    )
    mode.add_argument(
        "--recover-smoke-a0-d1",
        action="store_true",
        help=(
            "Reconcile a previously STARTED A0/D1 smoke after an exact STOPPED "
            "terminal probe; never launches or retries MT5."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=7200.0,
        help=(
            "Maximum wait for the launched terminal. A timeout never kills or "
            "terminates the process."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        network_verifier = (
            None if args.recover_smoke_a0_d1 else _make_network_verifier(args)
        )
        if args.spec is not None:
            if args.execute_smoke_a0_d1 or args.recover_smoke_a0_d1:
                raise ResearchRunError("smoke execution/recovery requires --stage-a-plan")
            if args.registry is not None:
                raise ResearchRunError("--registry is valid only with --stage-a-plan")
            spec = load_research_run_spec(args.spec)
            runner = _make_runner(spec, args.timeout_seconds, network_verifier)
            result = runner.run(spec) if args.execute else runner.preflight(spec).manifest
        else:
            plan = load_stage_a_plan(args.stage_a_plan)
            if args.execute or args.execute_smoke_a0_d1 or args.recover_smoke_a0_d1:
                if args.registry is None:
                    raise StageAError(
                        "Stage A execution/recovery requires an explicit --registry path"
                    )
                orchestrator = StageAOrchestrator(
                    runner_factory=lambda spec: _make_runner(
                        spec, args.timeout_seconds, network_verifier
                    ),
                    registry=AppendOnlyResearchRegistry(args.registry),
                )
                if args.recover_smoke_a0_d1:
                    smoke = next(
                        cell
                        for cell in plan.cells
                        if cell.candidate_id == "A0" and cell.segment_id == "D1"
                    )
                    state = orchestrator.recover_smoke_a0_d1(
                        plan,
                        terminal_probe=make_windows_terminal_probe(
                            smoke.spec.terminal_data_path,
                            smoke.spec.terminal_data_mode,
                        ),
                    )
                    result = {
                        "status": "SMOKE_RECOVERED",
                        "matrix_id": plan.matrix_id,
                        "plan_sha256": plan.plan_sha256,
                        "cell": "A0/D1",
                        "registry_state": state.value,
                    }
                elif args.execute_smoke_a0_d1:
                    result = {
                        "status": "SMOKE_EXECUTED",
                        "matrix_id": plan.matrix_id,
                        "plan_sha256": plan.plan_sha256,
                        "cell": "A0/D1",
                        "manifest": orchestrator.execute_smoke_a0_d1(plan),
                    }
                else:
                    result = {
                        "status": "MATRIX_EXECUTED",
                        "matrix_id": plan.matrix_id,
                        "plan_sha256": plan.plan_sha256,
                        "manifests": orchestrator.execute(plan),
                    }
            else:
                result = {
                    "status": "MATRIX_PREFLIGHT_OK",
                    "matrix_id": plan.matrix_id,
                    "plan_sha256": plan.plan_sha256,
                    "cells": [
                        _make_runner(cell.spec, args.timeout_seconds, network_verifier)
                        .preflight(cell.spec)
                        .manifest
                        for cell in sorted(
                            plan.cells,
                            key=lambda item: (item.candidate_id, item.segment_id),
                        )
                    ],
                }
    except (
        OSError,
        ValueError,
        ResearchEnvironmentError,
        ResearchNetworkError,
        WindowsResearchSecurityError,
        ResearchRunError,
        StageAError,
    ) as exc:
        print(f"research-run rejected: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


def _make_network_verifier(args):
    if (
        args.clone_manifest is None
        or args.expected_signer_thumbprint is None
        or args.expected_file_version is None
    ):
        raise ResearchNetworkError(
            "preflight/execution requires clone manifest, signer thumbprint, and build"
        )
    clone = verify_portable_research_clone(
        args.clone_manifest,
        signature_probe=windows_authenticode_probe,
        expected_signer_thumbprint=args.expected_signer_thumbprint,
        expected_file_version=args.expected_file_version,
        directory_security_probe=windows_directory_security_probe,
        require_pristine=False,
    )

    def verify(evidence_path: Path, terminal_root: Path) -> bool:
        if clone.destination_root != terminal_root:
            raise ResearchNetworkError(
                "run terminal data path differs from the sealed offline clone"
            )
        evidence = verify_firewall_isolation_evidence(
            evidence_path,
            clone=clone,
            rule_probe=windows_firewall_rule_probe,
        )
        return evidence.terminal_root == terminal_root

    return verify


def _make_runner(spec, timeout_seconds: float, network_verifier) -> MT5ResearchRunner:
    return MT5ResearchRunner(
        terminal_probe=make_windows_terminal_probe(
            spec.terminal_data_path,
            spec.terminal_data_mode,
        ),
        launcher=make_windows_launcher(timeout_seconds),
        network_isolation_verifier=network_verifier,
    )


if __name__ == "__main__":
    raise SystemExit(main())
