from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

from gold_engine_core import load_named_profile

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "GOLDI": [
        (0.0, 0.01),
        (100.0, 0.02),
        (200.0, 0.05),
        (1000.0, 0.1),
        (2000.0, 0.2),
        (10000.0, 1.0),
        (20000.0, 2.0),
    ],
    "GOLDM": [
        (0.0, 0.1),
        (10.0, 0.2),
        (30.0, 0.5),
        (50.0, 1.0),
        (100.0, 2.0),
        (200.0, 5.0),
        (1000.0, 10.0),
        (2000.0, 20.0),
        (10000.0, 100.0),
    ],
}


def tiers(path: Path) -> list[tuple[float, float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        (float(item["minimum_balance"]), float(item["lot"]))
        for item in payload["sizing"]["balance_tiers"]
    ]


def test_engine_final_and_validation_sizing_contracts_are_identical() -> None:
    for profile_id, group in (("GOLDI", "goldi"), ("GOLDM", "goldm")):
        manifest = load_named_profile(REPOSITORY_ROOT, profile_id)
        manifest_tiers = [
            (float(item.minimum_balance), float(item.lot)) for item in manifest.sizing_tiers
        ]
        assert manifest_tiers == EXPECTED[profile_id]

        paths = [REPOSITORY_ROOT / "config" / "final" / group / "portfolio.json"]
        paths.extend(
            sorted((REPOSITORY_ROOT / "config" / "validation" / group).glob("portfolio-*.json"))
        )
        for path in paths:
            assert tiers(path) == EXPECTED[profile_id], path

        expected_total = 4.0 if profile_id == "GOLDI" else 200.0
        assert float(manifest.max_total_lot) == expected_total
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert float(payload["maximum_total_lot"]) == expected_total


def test_sizing_tiers_are_contiguous_at_every_declared_boundary() -> None:
    for values in EXPECTED.values():
        assert values[0][0] == 0.0
        assert all(current[0] < following[0] for current, following in pairwise(values))
        assert all(lot > 0 for _, lot in values)
