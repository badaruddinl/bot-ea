from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from gold_engine_core import (
    BehaviorRecord,
    CorpusError,
    StateTransition,
    canonical_json,
    load_corpus,
    load_named_profile,
    write_corpus,
)
from gold_engine_core.current_behavior import (
    SCENARIOS,
    ScenarioDefinition,
    _source_evidence,
    build_current_behavior_corpus,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = REPOSITORY_ROOT / "corpus" / "current_behavior"

REQUIRED_SCENARIOS = {
    "revised.no_setup",
    "revised.m5_setup",
    "revised.reinforcement",
    "revised.opposite_cancellation",
    "revised.expiry",
    "revised.m1_range",
    "revised.m1_momentum",
    "revised.obstacle",
    "revised.psychological_context",
    "revised.supply_demand_context",
    "revised.entry_ready",
    "revised.restart",
    "bear.m15_setup",
    "bear.h1_pass_reject",
    "bear.m5_touch",
    "bear.m5_rejection",
    "bear.m5_acceptance",
    "bear.m1_confirmation",
    "bear.expiry",
    "bear.entry_ready",
    "bear.restart",
    "execution.fresh_quote",
    "execution.stale_quote",
    "execution.drift",
    "execution.spread",
    "execution.invalidation",
    "execution.duplicate",
    "execution.max_positions",
    "execution.lot_normalization",
    "execution.wrong_identity",
    "execution.broker_check_reject",
    "execution.broker_send_reject",
    "execution.fill",
    "execution.restart",
}


@pytest.fixture(scope="module")
def corpora() -> dict[str, tuple[BehaviorRecord, ...]]:
    return {
        profile_id: load_corpus(CORPUS_ROOT / f"{profile_id}.jsonl")
        for profile_id in ("GOLDI", "GOLDM")
    }


def test_required_scenarios_are_complete_and_profile_isolated(corpora) -> None:
    assert {item.scenario_id for item in SCENARIOS} == REQUIRED_SCENARIOS
    for profile_id, records in corpora.items():
        profile = load_named_profile(REPOSITORY_ROOT, profile_id)
        assert len(records) == len(REQUIRED_SCENARIOS)
        assert {record.scenario_id for record in records} == REQUIRED_SCENARIOS
        assert {record.profile_id for record in records} == {profile_id}
        assert {record.profile_fingerprint for record in records} == {profile.fingerprint}
        assert all(record.setup_id.startswith(f"{profile_id}:") for record in records)


def test_corpus_is_causal_and_strategy_inputs_are_closed(corpora) -> None:
    for records in corpora.values():
        for record in records:
            assert all(
                transition.available_at <= record.available_at
                for transition in record.state_transitions
            )
            if record.domain in {"revised", "bear"}:
                assert record.closed_bars_only is True


def test_current_wrong_execution_behavior_is_preserved(corpora) -> None:
    for records in corpora.values():
        by_id = {record.scenario_id: record for record in records}
        assert by_id["execution.stale_quote"].reason == ("BASELINE_SIGNAL_PLAN_HAS_NO_VALID_UNTIL")
        assert by_id["execution.drift"].execution_outcome == ("EXECUTED_WITH_QUOTE_CHASING")
        assert by_id["execution.spread"].execution_outcome == "UNGUARDED_BASELINE"
        assert by_id["execution.invalidation"].execution_outcome == "UNGUARDED_BASELINE"


def test_generator_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_hashes = build_current_behavior_corpus(REPOSITORY_ROOT, output_root=first)
    second_hashes = build_current_behavior_corpus(REPOSITORY_ROOT, output_root=second)

    assert first_hashes == second_hashes
    for profile_id in ("GOLDI", "GOLDM"):
        expected = (CORPUS_ROOT / f"{profile_id}.jsonl").read_bytes()
        assert (first / f"{profile_id}.jsonl").read_bytes() == expected
        assert (second / f"{profile_id}.jsonl").read_bytes() == expected


def test_source_fingerprint_normalizes_transport_line_endings(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_bytes(b"def oracle():\n    return True\n")
    lf_digest, _ = _source_evidence(tmp_path, "sample.py::oracle")
    source.write_bytes(b"def oracle():\r\n    return True\r\n")
    crlf_digest, _ = _source_evidence(tmp_path, "sample.py::oracle")

    assert crlf_digest == lf_digest


def test_corpus_loader_rejects_future_transition(tmp_path: Path, corpora) -> None:
    record = corpora["GOLDI"][0]
    payload = record.to_payload()
    payload["state_transitions"] = [
        StateTransition(record.available_at + timedelta(seconds=1), "IDLE", "WATCH").to_payload()
    ]

    with pytest.raises(CorpusError, match="after available_at"):
        BehaviorRecord.from_payload(payload)


def test_corpus_loader_rejects_cross_profile_and_duplicate_writes(tmp_path: Path, corpora) -> None:
    goldi = corpora["GOLDI"][0]
    goldm = corpora["GOLDM"][0]
    with pytest.raises(CorpusError, match="mix profiles"):
        write_corpus(tmp_path / "mixed.jsonl", (goldi, goldm))
    with pytest.raises(CorpusError, match="unique"):
        write_corpus(tmp_path / "duplicate.jsonl", (goldi, goldi))
    with pytest.raises(CorpusError, match="empty"):
        write_corpus(tmp_path / "empty.jsonl", ())


def test_corpus_loader_rejects_noncanonical_and_bad_checksum(tmp_path: Path, corpora) -> None:
    record = corpora["GOLDI"][0]
    path = tmp_path / "GOLDI.jsonl"
    canonical = canonical_json(record.to_payload()) + b"\n"
    path.write_bytes(b" " + canonical)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(".sha256").write_text(f"{digest}  GOLDI.jsonl\n", encoding="ascii")
    with pytest.raises(CorpusError, match="non-canonical"):
        load_corpus(path)

    path.write_bytes(canonical)
    path.with_suffix(".sha256").write_text(f"{'0' * 64}  GOLDI.jsonl\n", encoding="ascii")
    with pytest.raises(CorpusError, match="checksum mismatch"):
        load_corpus(path)


def test_record_boundary_mutations_fail_closed(corpora) -> None:
    record = corpora["GOLDI"][0]
    base = record.to_payload()
    mutations = (
        ({**base, "profile_id": ""}, "non-empty string"),
        ({**base, "profile_id": "OTHER"}, "unsupported profile_id"),
        ({**base, "domain": "other"}, "unsupported domain"),
        ({**base, "schema_version": 2}, "schema_version"),
        ({**base, "closed_bars_only": "true"}, "must be boolean"),
        ({**base, "state_transitions": []}, "non-empty array"),
        ({**base, "available_at": "no-time"}, "ISO-8601"),
        ({**base, "available_at": "2026-08-18T07:00:00"}, "explicit UTC offset"),
        ({**base, "input_fingerprint": "bad"}, "lowercase SHA-256"),
        ({**base, "scenario_id": "wrong-prefix"}, "start with its domain"),
        ({**base, "setup_id": "OTHER:setup"}, "profile-namespaced"),
        ({**base, "closed_bars_only": False}, "closed bars only"),
    )
    for payload, message in mutations:
        with pytest.raises(CorpusError, match=message):
            BehaviorRecord.from_payload(payload)


def test_scenario_definition_rejects_unknown_domain() -> None:
    definition = ScenarioDefinition(
        "unknown.case",
        "tests/test_quality_gate.py::test_parser_requires_base_and_defaults_head",
        "A",
        "B",
        "WAIT",
        "reason",
        "NO_ORDER",
    )
    with pytest.raises(ValueError, match="unsupported scenario domain"):
        _ = definition.domain


def test_frozen_records_cannot_be_cross_profile_rebound(corpora) -> None:
    record = corpora["GOLDI"][0]
    rebound = replace(record, profile_id="GOLDM")
    with pytest.raises(CorpusError, match="profile-namespaced"):
        BehaviorRecord.from_payload(rebound.to_payload())
