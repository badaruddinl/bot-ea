from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from .research_metrics import (
    BrokerCostEvidence,
    ResearchMetricsError,
    broker_cost_r,
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
    superior_predictive_ability,
)
from .research_policy import ResearchPurpose, StatisticalClassification
from .research_run import (
    MT5ResearchRunner,
    ResearchRunError,
    ResearchRunSpec,
    TerminalDataMode,
    TerminalProbeResult,
    TerminalState,
    _issue_matrix_execution_authorization,
    load_research_run_spec,
    validate_research_run_spec,
)


DEVELOPMENT_SEGMENTS: Mapping[str, tuple[str, str]] = {
    "D1": ("2022-02-28", "2022-06-28"),
    "D2": ("2022-06-28", "2022-10-28"),
    "D3": ("2022-10-28", "2023-02-28"),
    "D4": ("2023-02-28", "2023-06-28"),
    "D5": ("2023-06-28", "2023-10-28"),
    "D6": ("2023-10-28", "2024-02-28"),
}

STAGE_A_CANDIDATES: Mapping[str, str] = {
    "A0": "ALL",
    "A1": "BULL_ONLY",
    "A2": "BEAR_ONLY",
}

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,95}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class StageAError(RuntimeError):
    """Raised when a Stage A plan, registry, or evidence set is unsafe."""


class RegistryState(StrEnum):
    PLANNED = "PLANNED"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class StageACell:
    candidate_id: str
    segment_id: str
    spec_path: Path
    spec_sha256: str
    spec: ResearchRunSpec


@dataclass(frozen=True, slots=True)
class BaselineBinding:
    segment_id: str
    metrics_path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class StageAPlan:
    matrix_id: str
    created_at: str
    additional_cost_stress_r: float
    cells: tuple[StageACell, ...]
    baseline_bindings: tuple[BaselineBinding, ...]
    plan_sha256: str
    source_path: Path | None = None


@dataclass(frozen=True, slots=True)
class RegistryRecord:
    sequence: int
    recorded_at: str
    matrix_id: str
    plan_sha256: str
    run_id: str
    candidate_id: str
    segment_id: str
    state: RegistryState
    manifest_path: str | None
    manifest_sha256: str | None
    failure: str | None
    execution_proof: Mapping[str, Any] | None
    reconciliation: Mapping[str, Any] | None
    previous_record_sha256: str | None
    record_sha256: str


@dataclass(frozen=True, slots=True)
class GateFinding:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class CandidateGateMetrics:
    candidate_id: str
    direction_profile: str
    trades: int
    net_total_r: float
    net_expectancy_r: float | None
    positive_segments: int
    maximum_positive_segment_contribution: float | None
    average_broker_cost_r: float | None


@dataclass(frozen=True, slots=True)
class StageAGateReport:
    matrix_id: str
    plan_sha256: str
    status: GateStatus
    blockers: tuple[GateFinding, ...]
    failures: tuple[GateFinding, ...]
    candidates: tuple[CandidateGateMetrics, ...]
    selection_bias_diagnostics: Mapping[str, Any]


RunnerFactory = Callable[[ResearchRunSpec], MT5ResearchRunner]


def load_stage_a_plan(path: Path) -> StageAPlan:
    plan_path = _canonical_file(path, "Stage A plan")
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StageAError(f"Stage A plan is not valid UTF-8 JSON: {plan_path}") from exc
    if not isinstance(payload, dict):
        raise StageAError("Stage A plan must be a JSON object")
    required = {
        "schema_version",
        "matrix_id",
        "created_at",
        "additional_cost_stress_r",
        "cells",
        "baseline_bindings",
        "plan_sha256",
    }
    if set(payload) != required or payload.get("schema_version") != 1:
        raise StageAError(
            "Stage A plan must use schema_version 1 with exact declared fields"
        )
    supplied_digest = payload["plan_sha256"]
    if not isinstance(supplied_digest, str) or not _SHA256.fullmatch(supplied_digest):
        raise StageAError("Stage A plan_sha256 must be a lowercase SHA-256")
    digest_payload = dict(payload)
    digest_payload.pop("plan_sha256")
    calculated_digest = _canonical_sha256(digest_payload)
    if calculated_digest != supplied_digest:
        raise StageAError("Stage A plan_sha256 does not match the immutable plan payload")

    if not isinstance(payload["cells"], list):
        raise StageAError("Stage A cells must be a list")
    cells: list[StageACell] = []
    for index, raw in enumerate(payload["cells"]):
        if not isinstance(raw, dict) or set(raw) != {
            "candidate_id",
            "segment_id",
            "spec_path",
            "spec_sha256",
        }:
            raise StageAError(f"Stage A cell {index} has invalid fields")
        candidate_id = raw["candidate_id"]
        segment_id = raw["segment_id"]
        if not isinstance(candidate_id, str) or not isinstance(segment_id, str):
            raise StageAError(f"Stage A cell {index} identifiers must be strings")
        spec_path = _canonical_file(Path(raw["spec_path"]), f"Stage A cell {index} spec")
        spec_sha256 = raw["spec_sha256"]
        if not isinstance(spec_sha256, str) or not _SHA256.fullmatch(spec_sha256):
            raise StageAError(f"Stage A cell {index} spec_sha256 is invalid")
        if _sha256_file(spec_path) != spec_sha256:
            raise StageAError(f"Stage A cell {index} spec hash mismatch")
        try:
            spec = load_research_run_spec(spec_path)
        except (OSError, ValueError, ResearchRunError) as exc:
            raise StageAError(f"Stage A cell {index} spec is invalid: {exc}") from exc
        cells.append(
            StageACell(
                candidate_id=candidate_id,
                segment_id=segment_id,
                spec_path=spec_path,
                spec_sha256=spec_sha256,
                spec=spec,
            )
        )

    if not isinstance(payload["baseline_bindings"], list):
        raise StageAError("Stage A baseline_bindings must be a list")
    bindings: list[BaselineBinding] = []
    for index, raw in enumerate(payload["baseline_bindings"]):
        if not isinstance(raw, dict) or set(raw) != {
            "segment_id",
            "metrics_path",
            "sha256",
        }:
            raise StageAError(f"Stage A baseline binding {index} has invalid fields")
        digest = raw["sha256"]
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise StageAError(f"Stage A baseline binding {index} has invalid SHA-256")
        metrics_path = _canonical_file(
            Path(raw["metrics_path"]), f"Stage A baseline binding {index} metrics"
        )
        if _sha256_file(metrics_path) != digest:
            raise StageAError(
                f"Stage A baseline binding {index} does not match its metrics hash"
            )
        bindings.append(
            BaselineBinding(
                segment_id=str(raw["segment_id"]),
                metrics_path=metrics_path,
                sha256=digest,
            )
        )

    plan = StageAPlan(
        matrix_id=str(payload["matrix_id"]),
        created_at=str(payload["created_at"]),
        additional_cost_stress_r=payload["additional_cost_stress_r"],
        cells=tuple(cells),
        baseline_bindings=tuple(bindings),
        plan_sha256=supplied_digest,
        source_path=plan_path,
    )
    validate_stage_a_plan(plan)
    return plan


def validate_stage_a_plan(plan: StageAPlan) -> None:
    if not isinstance(plan.matrix_id, str) or not _TOKEN.fullmatch(plan.matrix_id):
        raise StageAError("Stage A matrix_id must be a structured token")
    _parse_utc(plan.created_at, "Stage A created_at")
    if (
        not isinstance(plan.additional_cost_stress_r, (int, float))
        or isinstance(plan.additional_cost_stress_r, bool)
        or not math.isfinite(plan.additional_cost_stress_r)
        or plan.additional_cost_stress_r < 0.0
    ):
        raise StageAError(
            "Stage A additional_cost_stress_r must be finite and non-negative"
        )
    if not isinstance(plan.plan_sha256, str) or not _SHA256.fullmatch(plan.plan_sha256):
        raise StageAError("Stage A plan_sha256 must be a lowercase SHA-256")
    if _canonical_sha256(_plan_digest_payload(plan)) != plan.plan_sha256:
        raise StageAError("Stage A plan_sha256 does not match the immutable plan object")

    expected_cells = {
        (candidate_id, segment_id)
        for candidate_id in STAGE_A_CANDIDATES
        for segment_id in DEVELOPMENT_SEGMENTS
    }
    observed_cells = [(cell.candidate_id, cell.segment_id) for cell in plan.cells]
    if len(observed_cells) != len(expected_cells) or set(observed_cells) != expected_cells:
        missing = sorted(expected_cells.difference(observed_cells))
        duplicate_count = len(observed_cells) - len(set(observed_cells))
        unknown = sorted(set(observed_cells).difference(expected_cells))
        raise StageAError(
            "Stage A must contain exactly the immutable 3x6 matrix; "
            f"missing={missing!r} unknown={unknown!r} duplicate_count={duplicate_count}"
        )

    run_ids: set[str] = set()
    spec_paths: set[Path] = set()
    output_paths: set[Path] = set()
    lineage: set[tuple[Any, ...]] = set()
    for cell in plan.cells:
        if not _SHA256.fullmatch(cell.spec_sha256):
            raise StageAError("Stage A cell spec_sha256 must be a lowercase SHA-256")
        canonical_spec = _canonical_file(cell.spec_path, "Stage A cell spec")
        if _sha256_file(canonical_spec) != cell.spec_sha256:
            raise StageAError(f"Stage A spec changed after plan registration: {cell.spec_path}")
        try:
            loaded_spec = load_research_run_spec(canonical_spec)
        except (OSError, ValueError, ResearchRunError) as exc:
            raise StageAError(f"Stage A cell spec cannot be reloaded: {exc}") from exc
        if loaded_spec != cell.spec:
            raise StageAError("Stage A in-memory spec differs from its hashed spec file")
        try:
            approved = validate_research_run_spec(cell.spec)
        except (OSError, ValueError, ResearchRunError) as exc:
            raise StageAError(
                f"Stage A {cell.candidate_id}/{cell.segment_id} spec rejected: {exc}"
            ) from exc
        expected_profile = STAGE_A_CANDIDATES[cell.candidate_id]
        expected_range = DEVELOPMENT_SEGMENTS[cell.segment_id]
        if cell.spec.direction_profile != expected_profile:
            raise StageAError(
                f"Stage A {cell.candidate_id} must use direction profile {expected_profile}"
            )
        if (cell.spec.from_date, cell.spec.to_date) != expected_range:
            raise StageAError(
                f"Stage A {cell.segment_id} must use exact half-open range {expected_range!r}"
            )
        if approved.purpose is not ResearchPurpose.DEVELOPMENT or (
            approved.statistical_classification
            is not StatisticalClassification.DEVELOPMENT_SELECTION
        ):
            raise StageAError("Stage A cells must be DEVELOPMENT_SELECTION runs")
        if cell.spec.terminal_data_mode is not TerminalDataMode.PORTABLE:
            raise StageAError("Stage A execution requires PORTABLE terminal data mode")
        if cell.spec.run_id in run_ids or cell.spec_path in spec_paths:
            raise StageAError("Stage A run IDs and spec paths must be unique")
        run_ids.add(cell.spec.run_id)
        spec_paths.add(cell.spec_path)
        for output in (
            cell.spec.staged_set_path,
            cell.spec.config_path,
            cell.spec.report_path,
            cell.spec.metrics_path,
            cell.spec.manifest_path,
        ):
            if output in output_paths:
                raise StageAError(f"Stage A output path is reused across cells: {output}")
            output_paths.add(output)
        lineage.add(
            (
                cell.spec.repository_root,
                cell.spec.terminal_path,
                cell.spec.terminal_data_path,
                cell.spec.terminal_build,
                cell.spec.ea_source_path,
                cell.spec.ea_binary_path,
                cell.spec.symbol,
                cell.spec.timeframe,
                cell.spec.strategy_mode,
                cell.spec.execution_profile,
                cell.spec.costs,
                cell.spec.tester,
            )
        )
    if len(lineage) != 1:
        raise StageAError(
            "Stage A cells must share terminal, EA, market, strategy, tester, and cost lineage"
        )

    binding_segments = [binding.segment_id for binding in plan.baseline_bindings]
    if len(binding_segments) != len(set(binding_segments)):
        raise StageAError("Stage A baseline bindings contain duplicate segment IDs")
    if any(segment not in DEVELOPMENT_SEGMENTS for segment in binding_segments):
        raise StageAError("Stage A baseline bindings contain an unknown segment ID")


class AppendOnlyResearchRegistry:
    def __init__(self, path: Path, *, lock_timeout_seconds: float = 5.0) -> None:
        if not isinstance(path, Path) or not path.is_absolute() or not path.parent.is_dir():
            raise StageAError("registry path must have an explicit existing absolute parent")
        if path.parent.resolve(strict=True) != path.parent:
            raise StageAError("registry parent must be canonical")
        if not math.isfinite(lock_timeout_seconds) or lock_timeout_seconds <= 0.0:
            raise StageAError("registry lock timeout must be finite and positive")
        self.path = path
        self.lock_path = path.with_name(path.name + ".lock")
        self.lock_timeout_seconds = float(lock_timeout_seconds)

    def records(self) -> tuple[RegistryRecord, ...]:
        with _exclusive_lock(self.lock_path, timeout_seconds=self.lock_timeout_seconds):
            return self._read_unlocked()

    def plan_matrix(self, plan: StageAPlan, *, recorded_at: str | None = None) -> None:
        validate_stage_a_plan(plan)
        timestamp = recorded_at or _utc_now()
        _parse_utc(timestamp, "registry recorded_at")
        with _exclusive_lock(self.lock_path, timeout_seconds=self.lock_timeout_seconds):
            records = list(self._read_unlocked())
            existing_runs = {record.run_id for record in records}
            collisions = sorted(
                cell.spec.run_id for cell in plan.cells if cell.spec.run_id in existing_runs
            )
            if collisions:
                raise StageAError(
                    f"registry forbids immutable run ID reuse: {collisions!r}"
                )
            additions: list[dict[str, Any]] = []
            previous_hash = records[-1].record_sha256 if records else None
            sequence = len(records)
            for cell in sorted(
                plan.cells, key=lambda item: (item.candidate_id, item.segment_id)
            ):
                sequence += 1
                record = self._new_record(
                    sequence=sequence,
                    recorded_at=timestamp,
                    plan=plan,
                    cell=cell,
                    state=RegistryState.PLANNED,
                    manifest_path=None,
                    manifest_sha256=None,
                    failure=None,
                    execution_proof=None,
                    reconciliation=None,
                    previous_hash=previous_hash,
                )
                additions.append(record)
                previous_hash = record["record_sha256"]
            self._append_unlocked(additions)

    def start(
        self,
        plan: StageAPlan,
        cell: StageACell,
        *,
        execution_proof: Mapping[str, Any],
        recorded_at: str | None = None,
    ) -> None:
        validate_stage_a_plan(plan)
        timestamp = recorded_at or _utc_now()
        _parse_utc(timestamp, "registry recorded_at")
        proof = _canonical_execution_proof(execution_proof)
        with _exclusive_lock(self.lock_path, timeout_seconds=self.lock_timeout_seconds):
            records = list(self._read_unlocked())
            run_records = [record for record in records if record.run_id == cell.spec.run_id]
            if len(run_records) != 1 or run_records[-1].state is not RegistryState.PLANNED:
                raise StageAError("registry STARTED transition requires unfinished PLANNED")
            record = self._new_record(
                sequence=len(records) + 1,
                recorded_at=timestamp,
                plan=plan,
                cell=cell,
                state=RegistryState.STARTED,
                manifest_path=None,
                manifest_sha256=None,
                failure=None,
                execution_proof=proof,
                reconciliation=None,
                previous_hash=records[-1].record_sha256,
            )
            self._append_unlocked([record])

    def complete(
        self,
        plan: StageAPlan,
        cell: StageACell,
        *,
        manifest_path: Path,
        execution_proof: Mapping[str, Any],
        reconciliation: Mapping[str, Any] | None = None,
        recorded_at: str | None = None,
    ) -> None:
        manifest = _load_json_object(_canonical_file(manifest_path, "verified manifest"))
        if manifest.get("status") != "VERIFIED" or manifest.get("run_id") != cell.spec.run_id:
            raise StageAError("completed registry record requires the exact VERIFIED manifest")
        self._finish(
            plan,
            cell,
            state=RegistryState.COMPLETED,
            manifest_path=manifest_path,
            failure=None,
            execution_proof=execution_proof,
            reconciliation=reconciliation,
            recorded_at=recorded_at,
        )

    def fail(
        self,
        plan: StageAPlan,
        cell: StageACell,
        *,
        failure: str,
        manifest_path: Path | None = None,
        execution_proof: Mapping[str, Any] | None = None,
        reconciliation: Mapping[str, Any] | None = None,
        recorded_at: str | None = None,
    ) -> None:
        if not isinstance(failure, str) or not failure.strip():
            raise StageAError("failed registry record requires a non-empty failure")
        if manifest_path is not None:
            manifest = _load_json_object(_canonical_file(manifest_path, "failed manifest"))
            if manifest.get("status") != "FAILED" or manifest.get("run_id") != cell.spec.run_id:
                raise StageAError("failed registry record manifest identity/status mismatch")
        self._finish(
            plan,
            cell,
            state=RegistryState.FAILED,
            manifest_path=manifest_path,
            failure=failure.strip(),
            execution_proof=execution_proof,
            reconciliation=reconciliation,
            recorded_at=recorded_at,
        )

    def reconcile_unfinished(
        self,
        plan: StageAPlan,
        cell: StageACell,
        *,
        terminal_probe: Callable[[Path], TerminalProbeResult],
        recorded_at: str | None = None,
    ) -> RegistryState:
        """Append a final recovery decision without rewriting prior records."""

        validate_stage_a_plan(plan)
        with portable_execution_lease(
            cell.spec.terminal_path,
            cell.spec.terminal_data_path,
        ):
            return self._reconcile_unfinished_while_leased(
                plan,
                cell,
                terminal_probe=terminal_probe,
                recorded_at=recorded_at,
            )

    def _reconcile_unfinished_while_leased(
        self,
        plan: StageAPlan,
        cell: StageACell,
        *,
        terminal_probe: Callable[[Path], TerminalProbeResult],
        recorded_at: str | None,
    ) -> RegistryState:
        observation = terminal_probe(cell.spec.terminal_path)
        if not isinstance(observation, TerminalProbeResult):
            raise StageAError("recovery terminal probe returned invalid evidence")
        if (
            observation.state is not TerminalState.STOPPED
            or observation.executable_path != cell.spec.terminal_path
            or observation.data_path != cell.spec.terminal_data_path
            or observation.data_mode is not cell.spec.terminal_data_mode
            or observation.build != cell.spec.terminal_build
        ):
            raise StageAError(
                "recovery requires exact STOPPED terminal/tester path and build evidence"
            )
        records = self.records()
        run_records = [record for record in records if record.run_id == cell.spec.run_id]
        if not run_records or run_records[-1].state not in {
            RegistryState.PLANNED,
            RegistryState.STARTED,
        }:
            raise StageAError("registry run is not unfinished and cannot be reconciled")
        previous = run_records[-1]
        timestamp = recorded_at or _utc_now()
        reconciliation = {
            "schema_version": 1,
            "reason": "CRASH_RECOVERY",
            "observed_at": timestamp,
            "prior_state": previous.state.value,
            "terminal_state": observation.state.value,
            "terminal_path": str(observation.executable_path),
            "terminal_data_path": str(observation.data_path),
            "terminal_data_mode": observation.data_mode.value,
            "terminal_build": observation.build,
            "detail": observation.detail,
        }
        manifest_path = cell.spec.manifest_path
        manifest = _load_json_object(manifest_path) if manifest_path.is_file() else None
        if (
            previous.state is RegistryState.STARTED
            and manifest is not None
            and _verified_manifest_is_recovery_bound(manifest, previous, cell)
        ):
            self.complete(
                plan,
                cell,
                manifest_path=manifest_path,
                execution_proof=previous.execution_proof or {},
                reconciliation=reconciliation,
                recorded_at=timestamp,
            )
            return RegistryState.COMPLETED
        if manifest is not None and manifest.get("status") == "FAILED" and (
            manifest.get("run_id") == cell.spec.run_id
        ):
            failure = str(manifest.get("failure") or "runner recorded FAILED")
            self.fail(
                plan,
                cell,
                failure=f"CRASH_RECOVERY: {failure}",
                manifest_path=manifest_path,
                execution_proof=previous.execution_proof,
                reconciliation=reconciliation,
                recorded_at=timestamp,
            )
        else:
            self.fail(
                plan,
                cell,
                failure=(
                    "CRASH_RECOVERY: no authoritative VERIFIED artifact bound to a "
                    f"STARTED run (prior={previous.state.value})"
                ),
                execution_proof=previous.execution_proof,
                reconciliation=reconciliation,
                recorded_at=timestamp,
            )
        return RegistryState.FAILED

    def _finish(
        self,
        plan: StageAPlan,
        cell: StageACell,
        *,
        state: RegistryState,
        manifest_path: Path | None,
        failure: str | None,
        execution_proof: Mapping[str, Any] | None,
        reconciliation: Mapping[str, Any] | None,
        recorded_at: str | None,
    ) -> None:
        validate_stage_a_plan(plan)
        if cell not in plan.cells:
            raise StageAError("registry cell is not part of the immutable Stage A plan")
        timestamp = recorded_at or _utc_now()
        _parse_utc(timestamp, "registry recorded_at")
        canonical_manifest = (
            _canonical_file(manifest_path, "registry manifest")
            if manifest_path is not None
            else None
        )
        with _exclusive_lock(self.lock_path, timeout_seconds=self.lock_timeout_seconds):
            records = list(self._read_unlocked())
            run_records = [record for record in records if record.run_id == cell.spec.run_id]
            previous_state = run_records[-1].state if run_records else None
            allowed = (
                previous_state is RegistryState.STARTED
                if state is RegistryState.COMPLETED
                else previous_state in {RegistryState.PLANNED, RegistryState.STARTED}
            )
            if not allowed:
                raise StageAError(
                    "registry final transition does not follow an unfinished run state"
                )
            inherited_proof = (
                run_records[-1].execution_proof
                if previous_state is RegistryState.STARTED
                else None
            )
            record = self._new_record(
                sequence=len(records) + 1,
                recorded_at=timestamp,
                plan=plan,
                cell=cell,
                state=state,
                manifest_path=str(canonical_manifest) if canonical_manifest else None,
                manifest_sha256=(
                    _sha256_file(canonical_manifest) if canonical_manifest else None
                ),
                failure=failure,
                execution_proof=(
                    _canonical_execution_proof(execution_proof or inherited_proof)
                    if execution_proof is not None or inherited_proof is not None
                    else None
                ),
                reconciliation=(dict(reconciliation) if reconciliation is not None else None),
                previous_hash=records[-1].record_sha256 if records else None,
            )
            self._append_unlocked([record])

    def _new_record(
        self,
        *,
        sequence: int,
        recorded_at: str,
        plan: StageAPlan,
        cell: StageACell,
        state: RegistryState,
        manifest_path: str | None,
        manifest_sha256: str | None,
        failure: str | None,
        execution_proof: Mapping[str, Any] | None,
        reconciliation: Mapping[str, Any] | None,
        previous_hash: str | None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "schema_version": 1,
            "sequence": sequence,
            "recorded_at": recorded_at,
            "matrix_id": plan.matrix_id,
            "plan_sha256": plan.plan_sha256,
            "run_id": cell.spec.run_id,
            "candidate_id": cell.candidate_id,
            "segment_id": cell.segment_id,
            "state": state.value,
            "manifest_path": manifest_path,
            "manifest_sha256": manifest_sha256,
            "failure": failure,
            "execution_proof": execution_proof,
            "reconciliation": reconciliation,
            "previous_record_sha256": previous_hash,
        }
        record["record_sha256"] = _canonical_sha256(record)
        return record

    def _read_unlocked(self) -> tuple[RegistryRecord, ...]:
        if not self.path.exists():
            return ()
        if not self.path.is_file():
            raise StageAError("registry path exists but is not a regular file")
        try:
            text = self.path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise StageAError("registry is not valid UTF-8") from exc
        if text and not text.endswith("\n"):
            raise StageAError("registry is truncated: final record lacks newline commit marker")
        records: list[RegistryRecord] = []
        run_states: dict[str, RegistryState] = {}
        previous_hash: str | None = None
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                raise StageAError(f"registry contains a blank line at {line_number}")
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise StageAError(f"registry line {line_number} is truncated or invalid") from exc
            record = _parse_registry_record(raw, line_number=line_number)
            if record.sequence != line_number:
                raise StageAError("registry sequence is not contiguous")
            if record.previous_record_sha256 != previous_hash:
                raise StageAError("registry hash chain is broken")
            previous_state = run_states.get(record.run_id)
            if record.state is RegistryState.PLANNED:
                if previous_state is not None:
                    raise StageAError("registry contains duplicate PLANNED run IDs")
            elif record.state is RegistryState.STARTED:
                if previous_state is not RegistryState.PLANNED:
                    raise StageAError("registry STARTED state does not follow PLANNED")
            elif previous_state not in {RegistryState.PLANNED, RegistryState.STARTED}:
                raise StageAError("registry final state does not follow an unfinished state")
            run_states[record.run_id] = record.state
            previous_hash = record.record_sha256
            records.append(record)
        return tuple(records)

    def _append_unlocked(self, records: Sequence[Mapping[str, Any]]) -> None:
        if not records:
            return
        with self.path.open("ab") as stream:
            for record in records:
                stream.write(_canonical_json(record).encode("utf-8") + b"\n")
            stream.flush()
            os.fsync(stream.fileno())


@contextmanager
def portable_execution_lease(
    terminal_path: Path,
    terminal_data_path: Path,
    *,
    timeout_seconds: float = 0.1,
) -> Iterator[Mapping[str, Any]]:
    terminal = _canonical_file(terminal_path, "portable terminal")
    data_path = _canonical_directory(terminal_data_path, "portable terminal data")
    if terminal.parent != data_path:
        raise StageAError(
            "portable execution lease requires terminal_data_path == terminal installation"
        )
    lock_path = data_path / ".goldm-stage-a-execution.lock"
    with _exclusive_lock(lock_path, timeout_seconds=timeout_seconds):
        yield {
            "schema_version": 1,
            "mode": "PORTABLE_EXCLUSIVE_PATH_LOCK",
            "lock_path": str(lock_path),
            "terminal_path": str(terminal),
            "terminal_data_path": str(data_path),
        }


class StageAOrchestrator:
    def __init__(
        self,
        *,
        runner_factory: RunnerFactory,
        registry: AppendOnlyResearchRegistry,
    ) -> None:
        if runner_factory is None:
            raise StageAError("Stage A runner_factory must be explicit")
        self._runner_factory = runner_factory
        self._registry = registry

    def execute(self, plan: StageAPlan) -> tuple[Mapping[str, Any], ...]:
        """Run or resume the immutable matrix sequentially without retrying a run ID."""

        self._ensure_matrix_registered(plan)
        results: list[Mapping[str, Any]] = []
        for cell in sorted(plan.cells, key=lambda item: (item.candidate_id, item.segment_id)):
            state = self._latest_state(cell)
            if state is RegistryState.COMPLETED:
                results.append(self._load_completed_manifest(cell))
                continue
            if state is RegistryState.STARTED:
                raise StageAError(
                    f"Stage A {cell.candidate_id}/{cell.segment_id} is STARTED; "
                    "explicit stopped-terminal recovery is required before resume"
                )
            if state is RegistryState.FAILED:
                raise StageAError(
                    f"Stage A {cell.candidate_id}/{cell.segment_id} is FAILED; "
                    "immutable run IDs are never retried"
                )
            results.append(self._execute_cell(plan, cell))
        return tuple(results)

    def execute_smoke_a0_d1(self, plan: StageAPlan) -> Mapping[str, Any]:
        """Execute only registered A0/D1 as the actual-report contract smoke.

        The full immutable 3x6 plan is registered first. The remaining 17 cells
        stay PLANNED and cannot be mistaken for a completed Stage A matrix.
        """

        self._ensure_matrix_registered(plan)
        cell = self._cell(plan, "A0", "D1")
        state = self._latest_state(cell)
        if state is RegistryState.COMPLETED:
            return self._load_completed_manifest(cell)
        if state is RegistryState.STARTED:
            raise StageAError(
                "A0/D1 smoke is STARTED; use explicit recovery after proving the exact terminal STOPPED"
            )
        if state is RegistryState.FAILED:
            raise StageAError("A0/D1 smoke is FAILED and its immutable run ID cannot be retried")
        return self._execute_cell(plan, cell)

    def recover_smoke_a0_d1(
        self,
        plan: StageAPlan,
        *,
        terminal_probe: Callable[[Path], TerminalProbeResult],
    ) -> RegistryState:
        """Reconcile a crashed A0/D1 smoke without launching or retrying MT5."""

        validate_stage_a_plan(plan)
        cell = self._cell(plan, "A0", "D1")
        if not self._related_records(plan):
            raise StageAError("A0/D1 recovery requires a previously registered full matrix")
        return self._registry.reconcile_unfinished(
            plan,
            cell,
            terminal_probe=terminal_probe,
        )

    def _execute_cell(self, plan: StageAPlan, cell: StageACell) -> Mapping[str, Any]:
        proof: Mapping[str, Any] | None = None
        try:
            with portable_execution_lease(
                cell.spec.terminal_path, cell.spec.terminal_data_path
            ) as proof:
                self._registry.start(plan, cell, execution_proof=proof)
                authorization = _issue_matrix_execution_authorization(
                    matrix_id=plan.matrix_id,
                    plan_sha256=plan.plan_sha256,
                    spec_path=cell.spec_path,
                    spec_sha256=cell.spec_sha256,
                    spec=cell.spec,
                )
                result = self._runner_factory(cell.spec).run(
                    cell.spec,
                    _matrix_authorization=authorization,
                )
            self._registry.complete(
                plan,
                cell,
                manifest_path=cell.spec.manifest_path,
                execution_proof=proof,
            )
            return result
        except Exception as exc:
            failed_manifest = (
                cell.spec.manifest_path
                if cell.spec.manifest_path.is_file()
                and _safe_manifest_status(cell.spec.manifest_path) == "FAILED"
                else None
            )
            self._registry.fail(
                plan,
                cell,
                failure=str(exc),
                manifest_path=failed_manifest,
                execution_proof=proof,
            )
            raise StageAError(
                f"Stage A stopped at {cell.candidate_id}/{cell.segment_id}: {exc}"
            ) from exc

    def _ensure_matrix_registered(self, plan: StageAPlan) -> None:
        validate_stage_a_plan(plan)
        related = self._related_records(plan)
        if not related:
            self._registry.plan_matrix(plan)
            return
        first_by_run = {record.run_id: record for record in related if record.state is RegistryState.PLANNED}
        expected = {cell.spec.run_id: cell for cell in plan.cells}
        if set(first_by_run) != set(expected):
            raise StageAError("registry contains a partial or mismatched Stage A registration")
        for run_id, record in first_by_run.items():
            cell = expected[run_id]
            if (
                record.matrix_id != plan.matrix_id
                or record.plan_sha256 != plan.plan_sha256
                or record.candidate_id != cell.candidate_id
                or record.segment_id != cell.segment_id
            ):
                raise StageAError("registry Stage A registration identity does not match the plan")

    def _related_records(self, plan: StageAPlan) -> tuple[RegistryRecord, ...]:
        run_ids = {cell.spec.run_id for cell in plan.cells}
        return tuple(
            record for record in self._registry.records() if record.run_id in run_ids
        )

    def _latest_state(self, cell: StageACell) -> RegistryState:
        records = [
            record
            for record in self._registry.records()
            if record.run_id == cell.spec.run_id
        ]
        if not records:
            raise StageAError(f"registry is missing planned run {cell.spec.run_id}")
        return records[-1].state

    def _load_completed_manifest(self, cell: StageACell) -> Mapping[str, Any]:
        records = [
            record
            for record in self._registry.records()
            if record.run_id == cell.spec.run_id
        ]
        final = records[-1]
        if final.state is not RegistryState.COMPLETED or not final.manifest_path:
            raise StageAError("completed manifest lookup requires a COMPLETED registry record")
        path = _canonical_file(Path(final.manifest_path), "completed manifest")
        if _sha256_file(path) != final.manifest_sha256:
            raise StageAError("completed manifest hash differs from the registry")
        manifest = _load_json_object(path)
        if manifest.get("status") != "VERIFIED" or manifest.get("run_id") != cell.spec.run_id:
            raise StageAError("completed manifest identity/status mismatch")
        return manifest

    @staticmethod
    def _cell(plan: StageAPlan, candidate_id: str, segment_id: str) -> StageACell:
        matches = [
            cell
            for cell in plan.cells
            if cell.candidate_id == candidate_id and cell.segment_id == segment_id
        ]
        if len(matches) != 1:
            raise StageAError(f"plan does not contain exactly one {candidate_id}/{segment_id} cell")
        return matches[0]


def evaluate_stage_a(
    plan: StageAPlan,
    registry: AppendOnlyResearchRegistry,
) -> StageAGateReport:
    validate_stage_a_plan(plan)
    blockers: list[GateFinding] = []
    failures: list[GateFinding] = []
    records = registry.records()
    records_by_run: dict[str, list[RegistryRecord]] = {}
    for record in records:
        records_by_run.setdefault(record.run_id, []).append(record)

    evidence: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for cell in plan.cells:
        run_records = records_by_run.get(cell.spec.run_id, [])
        if not run_records:
            blockers.append(
                GateFinding("MISSING_REGISTRY_RECORD", f"{cell.spec.run_id} is not registered")
            )
            continue
        if any(
            record.matrix_id != plan.matrix_id
            or record.plan_sha256 != plan.plan_sha256
            or record.candidate_id != cell.candidate_id
            or record.segment_id != cell.segment_id
            for record in run_records
        ):
            failures.append(
                GateFinding("REGISTRY_IDENTITY_MISMATCH", cell.spec.run_id)
            )
            continue
        final = run_records[-1]
        if final.state in {RegistryState.PLANNED, RegistryState.STARTED}:
            blockers.append(GateFinding("RUN_UNFINISHED", cell.spec.run_id))
            continue
        if final.state is RegistryState.FAILED:
            failures.append(
                GateFinding("RUN_FAILED", f"{cell.spec.run_id}: {final.failure}")
            )
            continue
        if final.execution_proof is None or final.execution_proof.get("mode") != (
            "PORTABLE_EXCLUSIVE_PATH_LOCK"
        ):
            blockers.append(
                GateFinding("PORTABLE_LOCK_PROOF_MISSING", cell.spec.run_id)
            )
            continue
        try:
            manifest_path = _canonical_file(
                Path(final.manifest_path or ""), "completed manifest"
            )
            if _sha256_file(manifest_path) != final.manifest_sha256:
                raise StageAError("manifest hash differs from registry")
            manifest = _load_json_object(manifest_path)
            metrics_path = _canonical_file(
                Path(manifest["artifacts"]["metrics"]["path"]), "metrics artifact"
            )
            if _sha256_file(metrics_path) != manifest["artifacts"]["metrics"]["sha256"]:
                raise StageAError("metrics hash differs from manifest")
            metrics = _load_json_object(metrics_path)
            missing_provenance = _missing_protocol_provenance(manifest)
            if missing_provenance:
                blockers.append(
                    GateFinding(
                        "PROVENANCE_INCOMPLETE",
                        f"{cell.spec.run_id}: missing {missing_provenance!r}",
                    )
                )
                continue
            _validate_cell_evidence(cell, manifest, metrics)
            evidence[(cell.candidate_id, cell.segment_id)] = (manifest, metrics)
        except (KeyError, TypeError, ValueError, OSError, StageAError) as exc:
            failures.append(
                GateFinding("EVIDENCE_MISMATCH", f"{cell.spec.run_id}: {exc}")
            )

    expected_count = len(STAGE_A_CANDIDATES) * len(DEVELOPMENT_SEGMENTS)
    if len(evidence) != expected_count:
        blockers.append(
            GateFinding(
                "MATRIX_INCOMPLETE",
                f"verified protocol-complete cells={len(evidence)}/{expected_count}",
            )
        )

    baseline_by_segment = {
        binding.segment_id: binding for binding in plan.baseline_bindings
    }
    missing_baselines = sorted(set(DEVELOPMENT_SEGMENTS).difference(baseline_by_segment))
    if missing_baselines:
        blockers.append(
            GateFinding(
                "BASELINE_ARTIFACTS_MISSING",
                f"A0 parity has no immutable baseline for {missing_baselines!r}",
            )
        )
    else:
        for segment_id, binding in baseline_by_segment.items():
            current = evidence.get(("A0", segment_id))
            if current is None:
                continue
            try:
                if _sha256_file(binding.metrics_path) != binding.sha256:
                    raise StageAError("baseline artifact hash differs from plan binding")
                baseline = _load_json_object(binding.metrics_path)
                _assert_a0_parity(current[1], baseline, segment_id=segment_id)
            except (KeyError, TypeError, ValueError, OSError, StageAError) as exc:
                failures.append(
                    GateFinding("A0_PARITY_FAILED", f"{segment_id}: {exc}")
                )

    candidate_metrics: list[CandidateGateMetrics] = []
    candidate_segment_returns: dict[str, list[float]] = {}
    candidate_trade_returns: dict[str, list[float]] = {}
    cost_evidence_failed = False
    if len(evidence) == expected_count:
        for segment_id in DEVELOPMENT_SEGMENTS:
            observations = {
                _canonical_json(
                    evidence[(candidate_id, segment_id)][0]["market"]
                    ["history_observation"]
                )
                for candidate_id in STAGE_A_CANDIDATES
            }
            if len(observations) != 1:
                failures.append(
                    GateFinding(
                        "HISTORY_OBSERVATION_MISMATCH",
                        f"{segment_id}: A0/A1/A2 did not use an identical tester history observation",
                    )
                )
        for candidate_id, direction in STAGE_A_CANDIDATES.items():
            segment_totals: list[float] = []
            net_trade_returns: list[float] = []
            broker_costs: list[float] = []
            total_trades = 0
            for segment_id in DEVELOPMENT_SEGMENTS:
                manifest, metrics_artifact = evidence[(candidate_id, segment_id)]
                trades = metrics_artifact["trades"]
                if not isinstance(trades, list):
                    failures.append(
                        GateFinding(
                            "TRADE_ARTIFACT_INVALID",
                            f"{candidate_id}/{segment_id} trades is not a list",
                        )
                    )
                    trades = []
                try:
                    cost_evidence = _broker_cost_evidence(manifest)
                    segment_net: list[float] = []
                    for item in trades:
                        outcome = _finite_number(item.get("outcome_r"), "outcome_r")
                        converted_cost = broker_cost_r(
                            entry=_finite_number(item.get("entry"), "entry"),
                            initial_stop=_finite_number(
                                item.get("initial_stop"), "initial_stop"
                            ),
                            evidence=cost_evidence,
                        )
                        broker_costs.append(converted_cost)
                        segment_net.append(
                            outcome
                            - converted_cost
                            - plan.additional_cost_stress_r
                        )
                    segment_totals.append(math.fsum(segment_net))
                    net_trade_returns.extend(segment_net)
                    total_trades += len(segment_net)
                except (KeyError, TypeError, ValueError, ResearchMetricsError) as exc:
                    cost_evidence_failed = True
                    blockers.append(
                        GateFinding(
                            "BROKER_COST_EVIDENCE_INCOMPLETE",
                            f"{candidate_id}/{segment_id}: {exc}",
                        )
                    )
                    segment_totals.append(0.0)
            net_total = math.fsum(segment_totals)
            positive = [value for value in segment_totals if value > 0.0]
            positive_total = math.fsum(positive)
            concentration = (
                max(positive) / positive_total if positive_total > 0.0 else None
            )
            aggregate = CandidateGateMetrics(
                candidate_id=candidate_id,
                direction_profile=direction,
                trades=total_trades,
                net_total_r=net_total,
                net_expectancy_r=(net_total / total_trades if total_trades else None),
                positive_segments=len(positive),
                maximum_positive_segment_contribution=concentration,
                average_broker_cost_r=(
                    statistics.fmean(broker_costs) if broker_costs else None
                ),
            )
            candidate_metrics.append(aggregate)
            candidate_segment_returns[candidate_id] = segment_totals
            candidate_trade_returns[candidate_id] = net_trade_returns
            minimum_trades = 60 if candidate_id == "A0" else 30
            if total_trades < minimum_trades:
                failures.append(
                    GateFinding(
                        "MINIMUM_TRADES_FAILED",
                        f"{candidate_id}: {total_trades} < {minimum_trades}",
                    )
                )
            if net_total <= 0.0:
                failures.append(
                    GateFinding("NET_EXPECTANCY_FAILED", f"{candidate_id}: {net_total:g}R")
                )
            if len(positive) < 4:
                failures.append(
                    GateFinding(
                        "POSITIVE_SEGMENTS_FAILED",
                        f"{candidate_id}: {len(positive)}/6",
                    )
                )
            if concentration is not None and concentration > 0.5 + 1e-12:
                failures.append(
                    GateFinding(
                        "SEGMENT_CONCENTRATION_FAILED",
                        f"{candidate_id}: {concentration:.6f}",
                    )
                )

    diagnostic_payload: dict[str, Any] = {}
    if len(evidence) == expected_count and not cost_evidence_failed:
        pbo = probability_of_backtest_overfitting(candidate_segment_returns)
        diagnostic_payload["PBO"] = asdict(pbo)
        dsr_results = {
            candidate_id: deflated_sharpe_ratio(
                outcomes,
                candidate_trials=len(STAGE_A_CANDIDATES),
            )
            for candidate_id, outcomes in candidate_trade_returns.items()
        }
        diagnostic_payload["DSR"] = {
            candidate_id: asdict(result)
            for candidate_id, result in dsr_results.items()
        }
        a0_segments = candidate_segment_returns["A0"]
        spa = superior_predictive_ability(
            {
                candidate_id: [
                    value - baseline
                    for value, baseline in zip(
                        candidate_segment_returns[candidate_id],
                        a0_segments,
                        strict=True,
                    )
                ]
                for candidate_id in ("A1", "A2")
            },
            block_size=2,
            seed=0,
        )
        diagnostic_payload["SPA"] = asdict(spa)
        blocked_diagnostics = [pbo, spa, *dsr_results.values()]
        for diagnostic in blocked_diagnostics:
            if diagnostic.status == "BLOCKED":
                blockers.append(
                    GateFinding(
                        f"SELECTION_BIAS_{diagnostic.name}_BLOCKED",
                        diagnostic.reason or "selection-bias diagnostic is unavailable",
                    )
                )

    status = (
        GateStatus.BLOCKED
        if blockers
        else GateStatus.FAIL
        if failures
        else GateStatus.PASS
    )
    return StageAGateReport(
        matrix_id=plan.matrix_id,
        plan_sha256=plan.plan_sha256,
        status=status,
        blockers=tuple(blockers),
        failures=tuple(failures),
        candidates=tuple(candidate_metrics),
        selection_bias_diagnostics=diagnostic_payload,
    )


def _validate_cell_evidence(
    cell: StageACell,
    manifest: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> None:
    expected_range = DEVELOPMENT_SEGMENTS[cell.segment_id]
    checks = (
        (manifest.get("status"), "VERIFIED", "manifest status"),
        (manifest.get("run_id"), cell.spec.run_id, "manifest run_id"),
        (manifest.get("profile", {}).get("direction"), cell.spec.direction_profile, "manifest direction"),
        (manifest.get("profile", {}).get("strategy_mode"), cell.spec.strategy_mode, "manifest strategy mode"),
        (manifest.get("profile", {}).get("execution"), cell.spec.execution_profile, "manifest execution profile"),
        (manifest.get("market", {}).get("symbol"), cell.spec.symbol, "manifest symbol"),
        (manifest.get("market", {}).get("timeframe"), cell.spec.timeframe, "manifest timeframe"),
        (manifest.get("market", {}).get("from_inclusive"), expected_range[0], "manifest from"),
        (manifest.get("market", {}).get("to_exclusive"), expected_range[1], "manifest to"),
        (
            manifest.get("market", {}).get("statistical_classification"),
            StatisticalClassification.DEVELOPMENT_SELECTION.value,
            "manifest statistical classification",
        ),
        (manifest.get("terminal", {}).get("path"), str(cell.spec.terminal_path), "terminal path"),
        (manifest.get("terminal", {}).get("data_path"), str(cell.spec.terminal_data_path), "terminal data path"),
        (manifest.get("terminal", {}).get("data_mode"), cell.spec.terminal_data_mode.value, "terminal data mode"),
        (manifest.get("terminal", {}).get("build"), cell.spec.terminal_build, "terminal build"),
        (manifest.get("costs"), asdict(cell.spec.costs), "manifest broker costs"),
        (
            manifest.get("broker_cost_evidence", {}).get("costs"),
            asdict(cell.spec.costs),
            "broker cost evidence values",
        ),
        (manifest.get("tester_settings"), asdict(cell.spec.tester), "manifest tester settings"),
        (metrics.get("run_id"), cell.spec.run_id, "metrics run_id"),
        (metrics.get("lineage", {}).get("direction_profile"), cell.spec.direction_profile, "metrics direction"),
        (
            metrics.get("history_observation"),
            manifest.get("market", {}).get("history_observation"),
            "post-run history observation",
        ),
        (
            metrics.get("report_contract", {}).get(
                "strict_actual_report_verified"
            ),
            True,
            "actual report contract",
        ),
    )
    for observed, expected, label in checks:
        if observed != expected:
            raise StageAError(f"{label} mismatch: {observed!r} != {expected!r}")
    immutable_inputs = (
        ("ea_source", cell.spec.ea_source_path),
        ("ea_binary", cell.spec.ea_binary_path),
        ("set_source", cell.spec.set_source_path),
        ("provenance_evidence", cell.spec.provenance_path),
    )
    for label, path in immutable_inputs:
        evidence = manifest.get("inputs", {}).get(label, {})
        if evidence.get("path") != str(path) or evidence.get("sha256") != _sha256_file(path):
            raise StageAError(f"manifest {label} path/hash does not bind the immutable input")
    trades = metrics.get("trades")
    if not isinstance(trades, list):
        raise StageAError("metrics trades must be a list")
    allowed_side = {
        "ALL": {"BUY", "SELL"},
        "BULL_ONLY": {"BUY"},
        "BEAR_ONLY": {"SELL"},
    }[cell.spec.direction_profile]
    setup_ids: set[str] = set()
    for index, trade in enumerate(trades):
        if not isinstance(trade, dict):
            raise StageAError(f"trade {index} is not an object")
        setup_id = trade.get("setup_id")
        if not isinstance(setup_id, str) or not setup_id or setup_id in setup_ids:
            raise StageAError(f"trade {index} has missing/duplicate setup_id")
        setup_ids.add(setup_id)
        if trade.get("side") not in allowed_side:
            raise StageAError(f"trade {setup_id} leaks direction")
        _finite_number(trade.get("outcome_r"), f"trade {setup_id} outcome_r")


def _broker_cost_evidence(manifest: Mapping[str, Any]) -> BrokerCostEvidence:
    costs = manifest["costs"]
    symbol = manifest["market"]["symbol_specification"]
    if not isinstance(costs, Mapping) or not isinstance(symbol, Mapping):
        raise StageAError("broker costs and symbol specification must be objects")
    return BrokerCostEvidence(
        volume_lots=_finite_number(
            costs.get("reference_volume_lots"), "reference_volume_lots"
        ),
        point=_finite_number(symbol.get("point"), "symbol point"),
        tick_size=_finite_number(
            symbol.get("trade_tick_size"), "symbol trade_tick_size"
        ),
        tick_value=_finite_number(
            symbol.get("trade_tick_value"), "symbol trade_tick_value"
        ),
        spread_points=_finite_number(costs.get("spread_points"), "spread_points"),
        commission_per_lot_round_turn=_finite_number(
            costs.get("commission_per_lot_round_turn"),
            "commission_per_lot_round_turn",
        ),
        swap_per_lot_round_turn=_finite_number(
            costs.get("swap_per_lot_round_turn"), "swap_per_lot_round_turn"
        ),
        slippage_points=_finite_number(
            costs.get("slippage_points"), "slippage_points"
        ),
    )


def _missing_protocol_provenance(manifest: Mapping[str, Any]) -> list[str]:
    required_paths = {
        "repository.commit": ("repository", "commit"),
        "repository.dirty": ("repository", "dirty"),
        "inputs.ea_source.sha256": ("inputs", "ea_source", "sha256"),
        "inputs.ea_binary.sha256": ("inputs", "ea_binary", "sha256"),
        "inputs.set_source.sha256": ("inputs", "set_source", "sha256"),
        "inputs.provenance_evidence.sha256": (
            "inputs",
            "provenance_evidence",
            "sha256",
        ),
        "profile.strategy": ("profile", "strategy"),
        "profile.strategy_version": ("profile", "strategy_version"),
        "profile.management_policy_version": (
            "profile",
            "management_policy_version",
        ),
        "market.broker_server": ("market", "broker_server"),
        "market.symbol_specification": ("market", "symbol_specification"),
        "market.history_declaration": ("market", "history_declaration"),
        "market.history_observation": ("market", "history_observation"),
        "inputs.symbol_spec_evidence.sha256": (
            "inputs",
            "symbol_spec_evidence",
            "sha256",
        ),
        "inputs.bounded_history_evidence.sha256": (
            "inputs",
            "bounded_history_evidence",
            "sha256",
        ),
        "inputs.bounded_history_manifest.sha256": (
            "inputs",
            "bounded_history_manifest",
            "sha256",
        ),
        "inputs.network_isolation_evidence.sha256": (
            "inputs",
            "network_isolation_evidence",
            "sha256",
        ),
        "inputs.broker_cost_source.sha256": (
            "inputs",
            "broker_cost_source",
            "sha256",
        ),
        "broker_cost_evidence": ("broker_cost_evidence",),
        "report_contract.strict_actual_report_verified": (
            "report_contract",
            "strict_actual_report_verified",
        ),
        "terminal.path": ("terminal", "path"),
        "terminal.data_path": ("terminal", "data_path"),
        "terminal.build": ("terminal", "build"),
        "compilation.status": ("compilation", "status"),
        "compilation.log_sha256": ("compilation", "log_sha256"),
        "costs.reference_volume_lots": ("costs", "reference_volume_lots"),
        "costs.spread_points": ("costs", "spread_points"),
        "costs.slippage_points": ("costs", "slippage_points"),
        "costs.commission_per_lot_round_turn": (
            "costs",
            "commission_per_lot_round_turn",
        ),
        "costs.swap_per_lot_round_turn": (
            "costs",
            "swap_per_lot_round_turn",
        ),
        "artifacts.report.sha256": ("artifacts", "report", "sha256"),
        "artifacts.log.sha256": ("artifacts", "log", "sha256"),
    }
    missing: list[str] = []
    for label, path in required_paths.items():
        value: Any = manifest
        for component in path:
            if not isinstance(value, Mapping) or component not in value:
                value = None
                break
            value = value[component]
        if value is None or value == "" or value == {}:
            missing.append(label)
    if manifest.get("terminal", {}).get("data_mode") != TerminalDataMode.PORTABLE.value:
        missing.append("terminal.data_mode=PORTABLE")
    if manifest.get("compilation", {}).get("status") != "SUCCESS_ZERO_ERRORS_ZERO_WARNINGS":
        missing.append("compilation.zero_errors_zero_warnings")
    return sorted(set(missing))


def _assert_a0_parity(
    current: Mapping[str, Any], baseline: Mapping[str, Any], *, segment_id: str
) -> None:
    current_trades = current.get("trades")
    baseline_trades = baseline.get("trades")
    if not isinstance(current_trades, list) or not isinstance(baseline_trades, list):
        raise StageAError("parity artifacts must contain canonical trade lists")
    if len(current_trades) != len(baseline_trades):
        raise StageAError(
            f"{segment_id} total trades differ: {len(current_trades)} != {len(baseline_trades)}"
        )
    fields = (
        "setup_id",
        "side",
        "entry",
        "result",
        "outcome_r",
        "hit_r1",
        "hit_r2",
        "hit_r3",
        "mfe_r",
        "mae_r",
    )
    for index, (observed, expected) in enumerate(
        zip(current_trades, baseline_trades, strict=True)
    ):
        if not isinstance(observed, dict) or not isinstance(expected, dict):
            raise StageAError("parity trade rows must be objects")
        for field in fields:
            left = observed.get(field)
            right = expected.get(field)
            if field in {"entry", "outcome_r", "mfe_r", "mae_r"}:
                left = _finite_number(left, f"parity {field}")
                right = _finite_number(right, f"baseline {field}")
                equal = math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
            else:
                equal = left == right
            if not equal:
                raise StageAError(
                    f"trade {index} field {field} differs: {left!r} != {right!r}"
                )


def _parse_registry_record(raw: Any, *, line_number: int) -> RegistryRecord:
    fields = {
        "schema_version",
        "sequence",
        "recorded_at",
        "matrix_id",
        "plan_sha256",
        "run_id",
        "candidate_id",
        "segment_id",
        "state",
        "manifest_path",
        "manifest_sha256",
        "failure",
        "execution_proof",
        "reconciliation",
        "previous_record_sha256",
        "record_sha256",
    }
    if not isinstance(raw, dict) or set(raw) != fields or raw.get("schema_version") != 1:
        raise StageAError(f"registry line {line_number} has invalid schema")
    supplied_hash = raw.get("record_sha256")
    digest_payload = dict(raw)
    digest_payload.pop("record_sha256")
    if not isinstance(supplied_hash, str) or _canonical_sha256(digest_payload) != supplied_hash:
        raise StageAError(f"registry line {line_number} hash mismatch")
    try:
        state = RegistryState(raw["state"])
    except (TypeError, ValueError) as exc:
        raise StageAError(f"registry line {line_number} has invalid state") from exc
    _parse_utc(raw["recorded_at"], f"registry line {line_number} recorded_at")
    if not isinstance(raw["sequence"], int) or isinstance(raw["sequence"], bool):
        raise StageAError(f"registry line {line_number} sequence is invalid")
    if state is RegistryState.PLANNED:
        if any(
            raw[name] is not None
            for name in (
                "manifest_path",
                "manifest_sha256",
                "failure",
                "execution_proof",
                "reconciliation",
            )
        ):
            raise StageAError("PLANNED registry records cannot claim execution evidence")
    elif state is RegistryState.STARTED:
        if (
            raw["manifest_path"] is not None
            or raw["manifest_sha256"] is not None
            or raw["failure"] is not None
            or not isinstance(raw["execution_proof"], dict)
            or raw["reconciliation"] is not None
        ):
            raise StageAError("STARTED registry record requires only execution proof")
    elif state is RegistryState.COMPLETED:
        if (
            not raw["manifest_path"]
            or not _SHA256.fullmatch(str(raw["manifest_sha256"]))
            or raw["failure"] is not None
            or not isinstance(raw["execution_proof"], dict)
        ):
            raise StageAError("COMPLETED registry record is incomplete")
    elif not isinstance(raw["failure"], str) or not raw["failure"].strip():
        raise StageAError("FAILED registry record is missing its failure")
    if raw["reconciliation"] is not None and not isinstance(raw["reconciliation"], dict):
        raise StageAError("registry reconciliation evidence must be an object")
    return RegistryRecord(
        sequence=raw["sequence"],
        recorded_at=raw["recorded_at"],
        matrix_id=raw["matrix_id"],
        plan_sha256=raw["plan_sha256"],
        run_id=raw["run_id"],
        candidate_id=raw["candidate_id"],
        segment_id=raw["segment_id"],
        state=state,
        manifest_path=raw["manifest_path"],
        manifest_sha256=raw["manifest_sha256"],
        failure=raw["failure"],
        execution_proof=raw["execution_proof"],
        reconciliation=raw["reconciliation"],
        previous_record_sha256=raw["previous_record_sha256"],
        record_sha256=supplied_hash,
    )


def _canonical_execution_proof(proof: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "mode",
        "lock_path",
        "terminal_path",
        "terminal_data_path",
    }
    if not isinstance(proof, Mapping) or set(proof) != required:
        raise StageAError("execution proof has invalid fields")
    if proof.get("schema_version") != 1 or proof.get("mode") != (
        "PORTABLE_EXCLUSIVE_PATH_LOCK"
    ):
        raise StageAError("execution proof does not establish a portable path lock")
    terminal = _canonical_file(Path(str(proof["terminal_path"])), "proof terminal")
    data_path = _canonical_directory(
        Path(str(proof["terminal_data_path"])), "proof terminal data"
    )
    lock_path = Path(str(proof["lock_path"]))
    if terminal.parent != data_path or lock_path != data_path / (
        ".goldm-stage-a-execution.lock"
    ):
        raise StageAError("execution proof portable paths do not bind")
    return dict(proof)


def _plan_digest_payload(plan: StageAPlan) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "matrix_id": plan.matrix_id,
        "created_at": plan.created_at,
        "additional_cost_stress_r": plan.additional_cost_stress_r,
        "cells": [
            {
                "candidate_id": cell.candidate_id,
                "segment_id": cell.segment_id,
                "spec_path": str(cell.spec_path),
                "spec_sha256": cell.spec_sha256,
            }
            for cell in plan.cells
        ],
        "baseline_bindings": [
            {
                "segment_id": binding.segment_id,
                "metrics_path": str(binding.metrics_path),
                "sha256": binding.sha256,
            }
            for binding in plan.baseline_bindings
        ],
    }


@contextmanager
def _exclusive_lock(path: Path, *, timeout_seconds: float) -> Iterator[None]:
    if not path.is_absolute() or not path.parent.is_dir():
        raise StageAError("lock path must have an explicit existing absolute parent")
    deadline = time.monotonic() + timeout_seconds
    with path.open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    raise StageAError(f"exclusive lock is busy: {path}")
                time.sleep(0.01)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StageAError(f"invalid UTF-8 JSON artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise StageAError(f"JSON artifact must be an object: {path}")
    return payload


def _safe_manifest_status(path: Path) -> str | None:
    try:
        return _load_json_object(path).get("status")
    except (OSError, StageAError):
        return None


def _verified_manifest_is_recovery_bound(
    manifest: Mapping[str, Any],
    started_record: RegistryRecord,
    cell: StageACell,
) -> bool:
    """Reject a stale VERIFIED file that predates the immutable STARTED record."""

    try:
        started_at = _parse_utc(manifest.get("started_at"), "manifest started_at")
        completed_at = _parse_utc(
            manifest.get("completed_at"), "manifest completed_at"
        )
        registered_at = _parse_utc(
            started_record.recorded_at, "registry STARTED recorded_at"
        )
    except StageAError:
        return False
    return (
        manifest.get("status") == "VERIFIED"
        and manifest.get("run_id") == cell.spec.run_id
        and started_at >= registered_at
        and completed_at >= started_at
        and manifest.get("terminal", {}).get("path") == str(cell.spec.terminal_path)
        and manifest.get("terminal", {}).get("data_path")
        == str(cell.spec.terminal_data_path)
        and manifest.get("terminal", {}).get("build") == cell.spec.terminal_build
        and manifest.get("profile", {}).get("direction")
        == cell.spec.direction_profile
        and manifest.get("market", {}).get("from_inclusive") == cell.spec.from_date
        and manifest.get("market", {}).get("to_exclusive") == cell.spec.to_date
    )


def _canonical_file(path: Path, label: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or not path.is_file():
        raise StageAError(f"{label} must be an explicit existing absolute file")
    return path.resolve(strict=True)


def _canonical_directory(path: Path, label: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or not path.is_dir():
        raise StageAError(f"{label} must be an explicit existing absolute directory")
    return path.resolve(strict=True)


def _finite_number(value: Any, label: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise StageAError(f"{label} must be finite")
    return float(value)


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise StageAError(f"{label} must be an explicit UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise StageAError(f"{label} is invalid") from exc
    if parsed.tzinfo != timezone.utc:
        raise StageAError(f"{label} must be UTC")
    return parsed


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
