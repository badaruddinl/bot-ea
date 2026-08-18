from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Sequence

from .engine import RevisedSide, RevisedState
from .replay import ReplayInspection, ReplayOutcome


@dataclass(frozen=True, slots=True)
class EvidenceExpectation:
    evidence_id: str
    requested_time: datetime
    expected_side: RevisedSide
    expected_profile: str
    note: str


def august_five(server_timezone: timezone) -> tuple[EvidenceExpectation, ...]:
    def at(value: str) -> datetime:
        return datetime.fromisoformat(value).replace(tzinfo=server_timezone)

    return (
        EvidenceExpectation("E1", at("2026-08-17T18:00"), RevisedSide.SELL, "CORE", "reversal SELL"),
        EvidenceExpectation("E2", at("2026-08-18T02:15"), RevisedSide.BUY, "CORE", "valid momentum BUY"),
        EvidenceExpectation("E3", at("2026-08-18T03:15"), RevisedSide.SELL, "CORE", "exhaustion reversal SELL"),
        EvidenceExpectation("E4", at("2026-08-18T09:15"), RevisedSide.BUY, "SCALPER", "valid SCALPER BUY"),
        EvidenceExpectation("E5", at("2026-08-18T12:45"), RevisedSide.BUY, "CORE", "valid BUY with buffered TP"),
    )


def validate_evidence(
    expectations: Sequence[EvidenceExpectation],
    inspections: Sequence[ReplayInspection],
    outcomes: Sequence[ReplayOutcome],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for expected in expectations:
        candidates = [
            item
            for item in inspections
            if item.requested_time == expected.requested_time
        ]
        ranked = sorted(
            candidates,
            key=lambda item: (
                item.side is expected.expected_side,
                item.entry_profile == expected.expected_profile,
                item.state is RevisedState.ENTRY_READY,
                item.m1_votes,
                item.retest_count,
                -abs((item.setup_trigger_time - expected.requested_time).total_seconds()),
            ),
            reverse=True,
        )
        best = ranked[0] if ranked else None
        matched = bool(
            best is not None
            and best.side is expected.expected_side
            and best.entry_profile == expected.expected_profile
            and best.state is RevisedState.ENTRY_READY
        )
        same_side_seen = any(
            item.side is expected.expected_side for item in candidates
        )
        status = "PASS" if matched else "NEAR" if same_side_seen else "FAIL"
        outcome = None
        if best is not None:
            outcome = next(
                (
                    item
                    for item in outcomes
                    if item.side is best.side
                    and item.trigger_time == best.setup_trigger_time
                ),
                None,
            )
        results.append(
            {
                "evidence_id": expected.evidence_id,
                "requested_time": expected.requested_time,
                "expected_side": expected.expected_side,
                "expected_profile": expected.expected_profile,
                "note": expected.note,
                "status": status,
                "matched": matched,
                "observed": asdict(best) if best is not None else None,
                "outcome": asdict(outcome) if outcome is not None else None,
                "candidate_count": len(candidates),
            }
        )
    return results
