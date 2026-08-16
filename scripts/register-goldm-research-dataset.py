from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from goldm_signal.research_dataset import (
    ResearchDatasetError,
    register_offline_tick_dataset,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Register an already-approved, bounded offline GoldM tick export. "
            "This command never initializes MT5 and never fetches broker data."
        )
    )
    parser.add_argument("--source-evidence", type=Path, required=True)
    parser.add_argument(
        "--expected-source-evidence-sha256",
        required=True,
        help="Out-of-band approved lowercase SHA-256 of the source evidence file.",
    )
    parser.add_argument("--destination-dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--custom-symbol", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        registered = register_offline_tick_dataset(
            source_evidence_path=args.source_evidence,
            expected_source_evidence_sha256=(
                args.expected_source_evidence_sha256
            ),
            destination_dataset_path=args.destination_dataset,
            manifest_path=args.manifest,
            dataset_id=args.dataset_id,
            custom_symbol=args.custom_symbol,
        )
    except (ResearchDatasetError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "BLOCKED", "error": str(exc)},
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": "REGISTERED_OFFLINE_DATASET",
                "dataset_id": registered.dataset_id,
                "manifest_path": str(registered.manifest_path),
                "manifest_sha256": registered.manifest_sha256,
                "dataset_path": str(registered.dataset_path),
                "dataset_sha256": registered.dataset_sha256,
                "source_evidence_path": str(registered.source_evidence_path),
                "source_evidence_sha256": registered.source_evidence_sha256,
                "row_count": registered.row_count,
                "from_inclusive": registered.run_start.date().isoformat(),
                "to_exclusive": registered.end.date().isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
