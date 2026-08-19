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
    should_enter: bool = True
    optional_entry: bool = False


def august_five(server_timezone: timezone) -> tuple[EvidenceExpectation, ...]:
    def at(value: str) -> datetime:
        return datetime.fromisoformat(value).replace(tzinfo=server_timezone)

    return (
        EvidenceExpectation(
            "E1",
            at("2026-08-17T18:00"),
            RevisedSide.BUY,
            "NO_BUY",
            "production BUY must stop at nearest resistance/supply",
            False,
        ),
        EvidenceExpectation("E2", at("2026-08-18T02:15"), RevisedSide.BUY, "CORE", "valid momentum BUY"),
        EvidenceExpectation(
            "E3",
            at("2026-08-18T03:15"),
            RevisedSide.BUY,
            "NO_BUY",
            "exhausted BUY must not promote inside supply",
            False,
        ),
        EvidenceExpectation(
            "E4",
            at("2026-08-18T09:15"),
            RevisedSide.BUY,
            "SCALPER",
            "SCALPER only when its complete gate is genuinely valid",
            True,
            True,
        ),
        EvidenceExpectation(
            "E5",
            at("2026-08-18T12:45"),
            RevisedSide.BUY,
            "CORE",
            "optional BUY; no confirmation is preferable to unsafe room",
            True,
            True,
        ),
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
                item.state is RevisedState.ENTRY_READY,
                item.entry_profile == expected.expected_profile,
                item.m1_votes,
                item.retest_count,
                -abs((item.setup_trigger_time - expected.requested_time).total_seconds()),
            ),
            reverse=True,
        )
        best = ranked[0] if ranked else None
        same_side_seen = any(
            item.side is expected.expected_side for item in candidates
        )
        matching_entries = [
            item
            for item in candidates
            if item.side is expected.expected_side
            and item.state is RevisedState.ENTRY_READY
        ]
        correctly_profiled_entry = bool(
            best is not None
            and best.side is expected.expected_side
            and best.entry_profile == expected.expected_profile
            and best.state is RevisedState.ENTRY_READY
        )
        matched = bool(
            same_side_seen
            and not matching_entries
            if not expected.should_enter
            else same_side_seen
            and (not matching_entries or correctly_profiled_entry)
            if expected.optional_entry
            else correctly_profiled_entry
        )
        status = (
            "PASS"
            if matched
            else "FAIL"
            if matching_entries or not same_side_seen
            else "NEAR"
        )
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
                "should_enter": expected.should_enter,
                "optional_entry": expected.optional_entry,
                "status": status,
                "matched": matched,
                "observed": asdict(best) if best is not None else None,
                "outcome": asdict(outcome) if outcome is not None else None,
                "candidate_count": len(candidates),
            }
        )
    return results
