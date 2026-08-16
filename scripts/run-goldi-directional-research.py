from __future__ import annotations

import argparse
import json
from pathlib import Path

from goldm_signal.directional_research import (
    DirectionalResearchError,
    load_candidate_plan,
    load_registered_bar_dataset,
    run_directional_research,
    write_report,
)
from goldm_signal.research_folds import load_registered_fold_plan
from goldm_signal.research_policy import (
    ResearchPurpose,
    StatisticalClassification,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run registered, bar-model-only independent GoldI BULL/BEAR research."
    )
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--fold-plan", type=Path, required=True)
    parser.add_argument("--candidate-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        dataset = load_registered_bar_dataset(args.dataset_manifest.resolve(strict=True))
        folds = load_registered_fold_plan(
            args.fold_plan.resolve(strict=True),
            expected_start=dataset.run_start,
            expected_end=dataset.end,
            expected_purpose=ResearchPurpose.DEVELOPMENT,
            expected_classification=StatisticalClassification.DEVELOPMENT_SELECTION,
        )
        candidate_plan = load_candidate_plan(args.candidate_plan.resolve(strict=True))
        report = run_directional_research(dataset, folds, candidate_plan)
        write_report(args.output.resolve(), report)
    except (DirectionalResearchError, ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({
        "status": report["status"],
        "report_sha256": report["report_sha256"],
        "output": str(args.output.resolve()),
        "selected": {
            side: details["selected_candidate"]
            for side, details in report["sides"].items()
        },
        "promotion": {
            side: details["promotion_status"]
            for side, details in report["sides"].items()
        },
    }, sort_keys=True))


if __name__ == "__main__":
    main()
