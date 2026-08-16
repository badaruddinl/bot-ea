from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from html.parser import HTMLParser
from math import isfinite
from pathlib import Path
from typing import Any

from .research_dataset import (
    ResearchDatasetError,
    load_registered_tick_dataset,
)
from .research_import import (
    OfflineImportError,
    VerifiedOfflineImport,
    load_custom_symbol_import_spec,
    load_verified_offline_import,
)
from .research_metrics import ResearchMetricsError, parse_research_log
from .research_policy import (
    ResearchPurpose,
    ResearchRange,
    StatisticalClassification,
    assert_research_range,
    load_research_policy,
    parse_research_date,
)


_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,95}\Z")
_EVIDENCE_METHOD_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{2,95}\Z")
_PROFILE_VALUES = {"ALL": "0", "BULL_ONLY": "1", "BEAR_ONLY": "2"}
_EA_INPUT_DECLARATION = re.compile(
    r"^\s*input\s+[A-Za-z_][A-Za-z0-9_]*\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*.+?;\s*(?://.*)?$"
)
class ResearchRunError(RuntimeError):
    """Raised when a research run cannot be proven safe and correlated."""


class TerminalState(StrEnum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    UNKNOWN = "UNKNOWN"


class TerminalDataMode(StrEnum):
    """How the exact MT5 executable resolves its data directory."""

    PORTABLE = "PORTABLE"
    STANDARD = "STANDARD"


@dataclass(frozen=True, slots=True)
class TerminalProbeResult:
    state: TerminalState
    executable_path: Path
    data_path: Path
    data_mode: TerminalDataMode
    build: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_code: int
    executable_path: Path
    data_mode: TerminalDataMode


@dataclass(frozen=True, slots=True)
class WindowsProcessSnapshot:
    executable_paths: tuple[Path, ...]
    unresolved_matching_processes: int = 0


@dataclass(frozen=True, slots=True)
class RepositoryState:
    commit: str
    dirty: bool
    dirty_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchCosts:
    spread_model: str
    commission_model: str
    swap_model: str
    slippage_model: str
    execution_delay_ms: int
    commission_per_lot_round_turn: float | None = None
    slippage_points: float | None = None
    spread_points: float | None = None
    swap_per_lot_round_turn: float | None = None
    reference_volume_lots: float | None = None

    def validate(self) -> None:
        for field_name in (
            "spread_model",
            "commission_model",
            "swap_model",
            "slippage_model",
        ):
            if not isinstance(getattr(self, field_name), str) or not getattr(
                self, field_name
            ).strip():
                raise ResearchRunError(f"costs.{field_name} must be explicit")
        if (
            not isinstance(self.execution_delay_ms, int)
            or isinstance(self.execution_delay_ms, bool)
            or self.execution_delay_ms < 0
        ):
            raise ResearchRunError(
                "costs.execution_delay_ms must be a non-negative integer"
            )
        for field_name in (
            "commission_per_lot_round_turn",
            "slippage_points",
            "spread_points",
            "swap_per_lot_round_turn",
            "reference_volume_lots",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(value)
                or value < 0
            ):
                raise ResearchRunError(
                    f"costs.{field_name} must be finite and non-negative"
                )
        if self.reference_volume_lots == 0.0:
            raise ResearchRunError("costs.reference_volume_lots must be positive")


@dataclass(frozen=True, slots=True)
class TesterSettings:
    model: int
    deposit: float
    currency: str
    leverage: str
    news_enabled: bool
    use_local: bool = True
    use_remote: bool = False
    use_cloud: bool = False
    visual: bool = False
    optimization: bool = False

    def validate(self) -> None:
        if (
            not isinstance(self.model, int)
            or isinstance(self.model, bool)
            or self.model < 0
        ):
            raise ResearchRunError("tester.model must be a non-negative integer")
        if (
            not isinstance(self.deposit, (int, float))
            or isinstance(self.deposit, bool)
            or not isfinite(self.deposit)
            or self.deposit <= 0
        ):
            raise ResearchRunError("tester.deposit must be finite and positive")
        if not isinstance(self.currency, str) or not re.fullmatch(
            r"[A-Z]{3,8}", self.currency
        ):
            raise ResearchRunError("tester.currency must be an uppercase currency code")
        if not isinstance(self.leverage, str) or not re.fullmatch(
            r"1:[1-9][0-9]*", self.leverage
        ):
            raise ResearchRunError("tester.leverage must use the form 1:N")
        for field_name in (
            "news_enabled",
            "use_local",
            "use_remote",
            "use_cloud",
            "visual",
            "optimization",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ResearchRunError(f"tester.{field_name} must be a boolean")
        if not self.use_local or self.use_remote or self.use_cloud:
            raise ResearchRunError(
                "research runs must use only the explicitly addressed local tester"
            )
        if self.visual or self.optimization:
            raise ResearchRunError("visual and optimization modes are not supported")


@dataclass(frozen=True, slots=True)
class ResearchProvenance:
    evidence_path: Path
    evidence_sha256: str
    captured_at: str
    broker_server: str
    management_policy_version: str
    symbol_specification: dict[str, Any]
    symbol_spec_evidence_path: Path
    symbol_spec_evidence_sha256: str
    history_declaration: dict[str, Any]
    history_evidence_path: Path
    history_evidence_sha256: str
    dataset_manifest_path: Path
    dataset_manifest_sha256: str
    network_isolation_evidence_path: Path
    network_isolation_evidence_sha256: str
    custom_symbol_import: dict[str, Any] | None
    import_receipt_path: Path | None
    import_receipt_sha256: str | None
    broker_cost_evidence: dict[str, Any]
    broker_cost_source_path: Path
    broker_cost_source_sha256: str
    compilation: dict[str, Any]
    compile_log_path: Path


@dataclass(frozen=True, slots=True)
class _MatrixExecutionAuthorization:
    matrix_id: str
    plan_sha256: str
    run_id: str
    purpose: ResearchPurpose
    spec_path: Path
    spec_sha256: str
    spec_fingerprint: str


@dataclass(frozen=True, slots=True)
class ResearchRunSpec:
    run_id: str
    repository_root: Path
    terminal_path: Path
    terminal_data_path: Path
    terminal_data_mode: TerminalDataMode
    terminal_build: str
    ea_source_path: Path
    ea_binary_path: Path
    set_source_path: Path
    staged_set_path: Path
    config_path: Path
    report_path: Path
    log_path: Path
    metrics_path: Path
    manifest_path: Path
    expert_name: str
    symbol: str
    timeframe: str
    from_date: str
    to_date: str
    purpose: ResearchPurpose | str
    statistical_classification: StatisticalClassification
    direction_profile: str
    strategy_mode: int
    execution_profile: str
    costs: ResearchCosts
    tester: TesterSettings
    provenance_path: Path


@dataclass(frozen=True, slots=True)
class PreparedResearchRun:
    spec: ResearchRunSpec
    approved_range: ResearchRange
    repository_state: RepositoryState
    manifest: dict[str, Any]
    log_offset: int
    log_prefix_sha256: str | None
    staged_set_text: str


@dataclass(frozen=True, slots=True)
class VerifiedResearchArtifacts:
    correlation: dict[str, Any]
    manifest_result: dict[str, Any]
    metrics_artifact: dict[str, Any]


TerminalProbe = Callable[[Path], TerminalProbeResult]
ProcessLauncher = Callable[[Path, Path, TerminalDataMode], ProcessResult]
RepositoryStateLoader = Callable[[Path], RepositoryState]
Clock = Callable[[], datetime]
NetworkIsolationVerifier = Callable[[Path, Path], bool]


class MT5ResearchRunner:
    """Fail-closed runner for a dedicated, explicitly addressed MT5 terminal.

    Process discovery and launch are injected deliberately.  The runner has no
    process-close or process-kill capability: if the terminal is running, or
    its state cannot be proven, the run is rejected.
    """

    def __init__(
        self,
        *,
        terminal_probe: TerminalProbe,
        launcher: ProcessLauncher,
        network_isolation_verifier: NetworkIsolationVerifier,
        repository_state_loader: RepositoryStateLoader | None = None,
        clock: Clock | None = None,
    ) -> None:
        if (
            terminal_probe is None
            or launcher is None
            or network_isolation_verifier is None
        ):
            raise ResearchRunError(
                "terminal probe, launcher, and live network verifier must be explicit"
            )
        self._terminal_probe = terminal_probe
        self._launcher = launcher
        self._network_isolation_verifier = network_isolation_verifier
        self._repository_state_loader = (
            repository_state_loader or collect_repository_state
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def preflight(self, spec: ResearchRunSpec) -> PreparedResearchRun:
        """Validate and fingerprint a run without writing files or launching MT5."""

        approved_range = validate_research_run_spec(spec)
        self._assert_terminal_available(spec)
        self._assert_network_isolation(spec)
        _reject_existing_outputs(spec)

        repository_state = self._repository_state_loader(spec.repository_root)
        _validate_repository_state(repository_state)
        source_set_text, set_values = _load_and_validate_set(spec)
        staged_set_text = _inject_run_id(source_set_text, spec.run_id)
        log_offset = spec.log_path.stat().st_size if spec.log_path.exists() else 0
        log_prefix_sha256 = (
            _sha256_prefix(spec.log_path, log_offset) if log_offset else None
        )

        manifest = _build_manifest(
            spec,
            approved_range=approved_range,
            repository_state=repository_state,
            set_values=set_values,
            staged_set_text=staged_set_text,
            log_offset=log_offset,
            log_prefix_sha256=log_prefix_sha256,
            status="PREFLIGHT_OK",
            created_at=_utc_iso(self._clock()),
        )
        return PreparedResearchRun(
            spec=spec,
            approved_range=approved_range,
            repository_state=repository_state,
            manifest=manifest,
            log_offset=log_offset,
            log_prefix_sha256=log_prefix_sha256,
            staged_set_text=staged_set_text,
        )

    def prepare(self, spec: ResearchRunSpec) -> PreparedResearchRun:
        _assert_offline_import_evidence_for_execution(spec)
        return self._materialize_prepared(self.preflight(spec))

    def _materialize_prepared(
        self, prepared: PreparedResearchRun
    ) -> PreparedResearchRun:
        spec = prepared.spec
        manifest = dict(prepared.manifest)
        manifest["status"] = "PREPARED"
        spec.staged_set_path.write_text(
            prepared.staged_set_text, encoding="utf-8", newline="\n"
        )
        spec.config_path.write_bytes(_build_tester_config(spec).encode("ascii"))
        _write_json_atomic(spec.manifest_path, manifest, allow_replace=False)
        return PreparedResearchRun(
            spec=prepared.spec,
            approved_range=prepared.approved_range,
            repository_state=prepared.repository_state,
            manifest=manifest,
            log_offset=prepared.log_offset,
            log_prefix_sha256=prepared.log_prefix_sha256,
            staged_set_text=prepared.staged_set_text,
        )

    def run(
        self,
        spec: ResearchRunSpec,
        *,
        _matrix_authorization: _MatrixExecutionAuthorization | None = None,
    ) -> dict[str, Any]:
        _assert_execution_authorized(spec, _matrix_authorization)
        _assert_offline_import_evidence_for_execution(spec)
        preflight = self.preflight(spec)
        prepared = self._materialize_prepared(preflight)
        started_at = self._clock()
        started_ns = int(_as_utc(started_at).timestamp() * 1_000_000_000)
        manifest = dict(prepared.manifest)
        manifest["status"] = "RUNNING"
        manifest["started_at"] = _utc_iso(started_at)
        _write_json_atomic(spec.manifest_path, manifest, allow_replace=True)

        try:
            self._assert_terminal_available(spec)
            _assert_manifest_inputs_unchanged(spec, manifest)
            self._assert_network_isolation(spec)
            process_result = self._launcher(
                spec.terminal_path,
                spec.config_path,
                spec.terminal_data_mode,
            )
            launched_path = _canonical_existing_file(
                process_result.executable_path, "launched terminal"
            )
            if launched_path != spec.terminal_path:
                raise ResearchRunError(
                    "launcher used a terminal path different from the approved path"
                )
            if process_result.data_mode is not spec.terminal_data_mode:
                raise ResearchRunError(
                    "launcher used a terminal data mode different from the approved mode"
                )
            if process_result.exit_code != 0:
                raise ResearchRunError(
                    f"MT5 terminal exited with code {process_result.exit_code}"
                )
            self._assert_network_isolation(spec)
            self._assert_terminal_available(spec)
            correlation = verify_research_artifacts(
                spec,
                log_offset=prepared.log_offset,
                log_prefix_sha256=prepared.log_prefix_sha256,
                started_ns=started_ns,
            )
            _assert_manifest_inputs_unchanged(spec, manifest)
            _write_json_atomic(
                spec.metrics_path,
                correlation.metrics_artifact,
                allow_replace=False,
            )
        except Exception as exc:
            manifest["status"] = "FAILED"
            manifest["completed_at"] = _utc_iso(self._clock())
            manifest["failure"] = str(exc)
            _write_json_atomic(spec.manifest_path, manifest, allow_replace=True)
            if isinstance(exc, ResearchRunError):
                raise
            raise ResearchRunError(f"research run failed closed: {exc}") from exc

        manifest["status"] = "VERIFIED"
        manifest["completed_at"] = _utc_iso(self._clock())
        manifest["correlation"] = correlation.correlation
        manifest["result"] = correlation.manifest_result
        manifest["profile"]["strategy"] = correlation.manifest_result["lineage"][
            "strategy"
        ]
        manifest["profile"]["strategy_version"] = correlation.manifest_result[
            "lineage"
        ]["strategy_version"]
        manifest["market"]["history_observation"] = correlation.manifest_result[
            "history_observation"
        ]
        manifest["report_contract"] = correlation.manifest_result[
            "report_contract"
        ]
        manifest["artifacts"]["report"]["sha256"] = _sha256_file(spec.report_path)
        manifest["artifacts"]["log"]["sha256"] = _sha256_file(spec.log_path)
        manifest["artifacts"]["metrics"]["sha256"] = _sha256_file(spec.metrics_path)
        _write_json_atomic(spec.manifest_path, manifest, allow_replace=True)
        return manifest

    def _assert_terminal_available(self, spec: ResearchRunSpec) -> None:
        observation = self._terminal_probe(spec.terminal_path)
        if not isinstance(observation, TerminalProbeResult):
            raise ResearchRunError("terminal probe returned an invalid result")
        if not isinstance(observation.state, TerminalState):
            raise ResearchRunError("terminal probe returned an invalid state")
        observed_path = _canonical_existing_file(
            observation.executable_path, "terminal probe executable"
        )
        if observed_path != spec.terminal_path:
            raise ResearchRunError("terminal probe did not inspect the exact configured path")
        observed_data_path = _canonical_existing_directory(
            observation.data_path, "terminal probe data path"
        )
        if observed_data_path != spec.terminal_data_path:
            raise ResearchRunError(
                "terminal probe data path does not match the configured data path"
            )
        if observation.data_mode is not spec.terminal_data_mode:
            raise ResearchRunError(
                "terminal probe data mode does not match the configured mode"
            )
        if observation.build != spec.terminal_build:
            raise ResearchRunError(
                f"terminal build mismatch: expected {spec.terminal_build!r}, "
                f"observed {observation.build!r}"
            )
        if observation.state is not TerminalState.STOPPED:
            detail = f": {observation.detail}" if observation.detail else ""
            raise ResearchRunError(
                f"terminal state is {observation.state.value}; "
                f"refusing to close or reuse it{detail}"
            )

    def _assert_network_isolation(self, spec: ResearchRunSpec) -> None:
        provenance = _load_research_provenance(spec)
        try:
            verified = self._network_isolation_verifier(
                provenance.network_isolation_evidence_path,
                spec.terminal_data_path,
            )
        except Exception as exc:
            raise ResearchRunError(
                f"live network isolation verification failed: {exc}"
            ) from exc
        if verified is not True:
            raise ResearchRunError(
                "live network isolation verifier did not return an exact success"
            )


def validate_research_run_spec(spec: ResearchRunSpec) -> ResearchRange:
    if not isinstance(spec.run_id, str):
        raise ResearchRunError("run_id must be a string")
    if not _RUN_ID_PATTERN.fullmatch(spec.run_id):
        raise ResearchRunError(
            "run_id must be 8-96 characters using only letters, digits, dot, dash, or underscore"
        )
    if not isinstance(spec.direction_profile, str) or spec.direction_profile not in _PROFILE_VALUES:
        raise ResearchRunError("direction_profile must be ALL, BULL_ONLY, or BEAR_ONLY")
    if (
        not isinstance(spec.strategy_mode, int)
        or isinstance(spec.strategy_mode, bool)
        or spec.strategy_mode not in {0, 1, 2, 3}
    ):
        raise ResearchRunError("strategy_mode must be one of 0, 1, 2, or 3")
    if not isinstance(spec.terminal_data_mode, TerminalDataMode):
        raise ResearchRunError(
            "terminal_data_mode must be explicit: PORTABLE or STANDARD"
        )
    for label, value in (
        ("terminal_build", spec.terminal_build),
        ("expert_name", spec.expert_name),
        ("symbol", spec.symbol),
        ("timeframe", spec.timeframe),
        ("execution_profile", spec.execution_profile),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ResearchRunError(f"{label} must be explicit")
        if "\r" in value or "\n" in value:
            raise ResearchRunError(f"{label} cannot contain line breaks")
    for label, value in (("from_date", spec.from_date), ("to_date", spec.to_date)):
        if not isinstance(value, str):
            raise ResearchRunError(f"{label} must be a YYYY-MM-DD string")
    if not isinstance(spec.purpose, (ResearchPurpose, str)):
        raise ResearchRunError("purpose must be an explicit research purpose string")
    if not isinstance(
        spec.statistical_classification,
        StatisticalClassification,
    ):
        raise ResearchRunError(
            "statistical_classification must be an explicit supported classification"
        )
    for field_name in (
        "repository_root",
        "terminal_path",
        "terminal_data_path",
        "ea_source_path",
        "ea_binary_path",
        "set_source_path",
        "provenance_path",
        "staged_set_path",
        "config_path",
        "report_path",
        "log_path",
        "metrics_path",
        "manifest_path",
    ):
        if not isinstance(getattr(spec, field_name), Path):
            raise ResearchRunError(f"{field_name} must be an explicit Path")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", spec.terminal_build):
        raise ResearchRunError("terminal_build must be an explicit numeric build")
    if not re.fullmatch(r"[A-Za-z0-9_.\\/-]+", spec.expert_name):
        raise ResearchRunError("expert_name contains unsupported characters")
    if not re.fullmatch(r"[A-Za-z0-9._#-]+", spec.symbol):
        raise ResearchRunError("symbol contains unsupported characters")
    if not re.fullmatch(r"[A-Z][A-Z0-9]*", spec.timeframe):
        raise ResearchRunError("timeframe must be an uppercase MT5 period token")
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{1,95}", spec.execution_profile
    ):
        raise ResearchRunError("execution_profile must be a structured token")
    if any(character.isspace() or character == "=" for character in spec.run_id):
        raise ResearchRunError("run_id is not safe for MT5 structured events")

    spec.costs.validate()
    spec.tester.validate()
    approved_range = assert_research_range(
        spec.from_date,
        spec.to_date,
        purpose=spec.purpose,
        statistical_classification=spec.statistical_classification,
        label=spec.run_id,
    )
    if approved_range.purpose is not ResearchPurpose.DIAGNOSTIC:
        missing_costs = [
            field_name
            for field_name in (
                "commission_per_lot_round_turn",
                "slippage_points",
                "spread_points",
                "swap_per_lot_round_turn",
                "reference_volume_lots",
            )
            if getattr(spec.costs, field_name) is None
        ]
        if missing_costs:
            raise ResearchRunError(
                f"matrix research requires numeric broker cost evidence: {missing_costs!r}"
            )

    canonical_inputs = {
        "repository_root": _canonical_existing_directory(
            spec.repository_root, "repository_root"
        ),
        "terminal_path": _canonical_existing_file(spec.terminal_path, "terminal_path"),
        "terminal_data_path": _canonical_existing_directory(
            spec.terminal_data_path, "terminal_data_path"
        ),
        "ea_source_path": _canonical_existing_file(
            spec.ea_source_path, "ea_source_path"
        ),
        "ea_binary_path": _canonical_existing_file(
            spec.ea_binary_path, "ea_binary_path"
        ),
        "set_source_path": _canonical_existing_file(
            spec.set_source_path, "set_source_path"
        ),
        "provenance_path": _canonical_existing_file(
            spec.provenance_path, "provenance_path"
        ),
    }
    for name, canonical in canonical_inputs.items():
        if canonical != getattr(spec, name):
            raise ResearchRunError(f"{name} must be an exact canonical absolute path")
    if (
        spec.terminal_data_mode is TerminalDataMode.PORTABLE
        and spec.terminal_data_path != spec.terminal_path.parent
    ):
        raise ResearchRunError(
            "PORTABLE terminal_data_path must equal the exact terminal installation directory"
        )
    if spec.terminal_data_mode is TerminalDataMode.PORTABLE and (
        spec.terminal_data_path / "Config" / "accounts.dat"
    ).exists():
        raise ResearchRunError(
            "portable research clone must not contain Config/accounts.dat; broker-online account reuse is prohibited"
        )

    for name in (
        "staged_set_path",
        "config_path",
        "report_path",
        "log_path",
        "metrics_path",
        "manifest_path",
    ):
        value = getattr(spec, name)
        if "\r" in str(value) or "\n" in str(value):
            raise ResearchRunError(f"{name} cannot contain line breaks")
        if not value.is_absolute() or not value.parent.exists():
            raise ResearchRunError(f"{name} must have an explicit existing absolute parent")
        if value.parent.resolve(strict=True) != value.parent:
            raise ResearchRunError(f"{name} parent must be canonical")
        if name != "log_path" and spec.run_id not in value.name:
            raise ResearchRunError(f"{name} filename must contain run_id")

    if not spec.ea_source_path.is_relative_to(spec.repository_root):
        raise ResearchRunError("ea_source_path must be inside repository_root")
    if not spec.set_source_path.is_relative_to(spec.repository_root):
        raise ResearchRunError("set_source_path must be inside repository_root")
    expert_root = spec.terminal_data_path / "MQL5" / "Experts"
    # MetaQuotes documents Tester ExpertParameters as installation-relative,
    # including in STANDARD mode. In PORTABLE mode installation=data path.
    profile_root = spec.terminal_path.parent / "MQL5" / "Profiles" / "Tester"
    if not spec.ea_binary_path.is_relative_to(expert_root):
        raise ResearchRunError("ea_binary_path must be inside terminal_data_path/MQL5/Experts")
    if not spec.staged_set_path.is_relative_to(profile_root):
        raise ResearchRunError(
            "staged_set_path must be inside terminal installation/MQL5/Profiles/Tester"
        )
    tester_log_root = spec.terminal_data_path / "Tester" / "logs"
    if spec.log_path.parent != tester_log_root or spec.log_path.suffix.casefold() != ".log":
        raise ResearchRunError(
            "log_path must identify one exact file in terminal_data_path/Tester/logs"
        )
    if spec.ea_source_path.suffix.lower() != ".mq5":
        raise ResearchRunError("ea_source_path must identify an MQ5 source file")
    if spec.ea_binary_path.suffix.lower() != ".ex5":
        raise ResearchRunError("ea_binary_path must identify an EX5 binary")
    if spec.ea_source_path.stem.casefold() != spec.ea_binary_path.stem.casefold():
        raise ResearchRunError("EA source and binary names do not match")
    expected_expert_name = str(
        spec.ea_binary_path.relative_to(expert_root).with_suffix("")
    ).replace("/", "\\")
    if spec.expert_name.casefold() != expected_expert_name.casefold():
        raise ResearchRunError(
            "expert_name does not address the exact hashed EA binary"
        )
    output_paths = {
        spec.staged_set_path,
        spec.config_path,
        spec.report_path,
        spec.metrics_path,
        spec.manifest_path,
    }
    if len(output_paths) != 5:
        raise ResearchRunError("research output paths must be distinct")
    _tester_report_config_path(spec)
    _load_research_provenance(spec)
    return approved_range


def _issue_matrix_execution_authorization(
    *,
    matrix_id: str,
    plan_sha256: str,
    spec_path: Path,
    spec_sha256: str,
    spec: ResearchRunSpec,
) -> _MatrixExecutionAuthorization:
    canonical_spec = _canonical_existing_file(spec_path, "matrix research spec")
    if not re.fullmatch(r"[0-9a-f]{64}", plan_sha256):
        raise ResearchRunError("matrix plan SHA-256 is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", spec_sha256) or (
        _sha256_file(canonical_spec) != spec_sha256
    ):
        raise ResearchRunError("matrix spec SHA-256 does not match its file")
    loaded = load_research_run_spec(canonical_spec)
    if loaded != spec:
        raise ResearchRunError("matrix authorization spec differs from its hashed file")
    try:
        purpose = ResearchPurpose(spec.purpose)
    except (TypeError, ValueError) as exc:
        raise ResearchRunError("matrix authorization purpose is invalid") from exc
    return _MatrixExecutionAuthorization(
        matrix_id=matrix_id,
        plan_sha256=plan_sha256,
        run_id=spec.run_id,
        purpose=purpose,
        spec_path=canonical_spec,
        spec_sha256=spec_sha256,
        spec_fingerprint=_research_spec_fingerprint(spec),
    )


def _assert_execution_authorized(
    spec: ResearchRunSpec,
    authorization: _MatrixExecutionAuthorization | None,
) -> None:
    try:
        purpose = ResearchPurpose(spec.purpose)
    except (TypeError, ValueError) as exc:
        raise ResearchRunError("execution purpose is invalid") from exc
    if purpose is ResearchPurpose.DIAGNOSTIC:
        if authorization is not None:
            raise ResearchRunError("Diagnostic single-run execution cannot claim matrix authority")
        return
    if authorization is None:
        raise ResearchRunError(
            f"{purpose.value} execution is matrix-only; single-run execution is prohibited"
        )
    if (
        authorization.run_id != spec.run_id
        or authorization.purpose is not purpose
        or authorization.spec_fingerprint != _research_spec_fingerprint(spec)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,95}", authorization.matrix_id)
        or not re.fullmatch(r"[0-9a-f]{64}", authorization.plan_sha256)
    ):
        raise ResearchRunError("matrix execution authorization does not bind this run")
    canonical_spec = _canonical_existing_file(
        authorization.spec_path, "authorized matrix research spec"
    )
    if _sha256_file(canonical_spec) != authorization.spec_sha256:
        raise ResearchRunError("authorized matrix spec changed after plan registration")
    if load_research_run_spec(canonical_spec) != spec:
        raise ResearchRunError("authorized matrix spec no longer matches the run")


def _assert_offline_import_evidence_for_execution(spec: ResearchRunSpec) -> None:
    # Preserve the normal fail-closed ordering: malformed paths, protected
    # ranges, and invalid provenance are rejected before any process probe.
    validate_research_run_spec(spec)
    if spec.terminal_data_mode is not TerminalDataMode.PORTABLE:
        raise ResearchRunError(
            "MT5 research execution requires a receipt-bound PORTABLE custom-symbol terminal"
        )
    provenance = _load_research_provenance(spec)
    if provenance.import_receipt_path is None or provenance.import_receipt_sha256 is None:
        raise ResearchRunError(
            "MT5 research execution is blocked until a verified custom-symbol import receipt exists"
        )


def _research_spec_fingerprint(spec: ResearchRunSpec) -> str:
    def normalize(value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, Mapping):
            return {str(key): normalize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        if isinstance(value, StrEnum):
            return value.value
        return value

    payload = normalize(asdict(spec))
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def collect_repository_state(repository_root: Path) -> RepositoryState:
    repository_root = _canonical_existing_directory(repository_root, "repository_root")
    commit_result = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if commit_result.returncode != 0:
        raise ResearchRunError(
            f"cannot resolve repository commit: {commit_result.stderr.strip()}"
        )
    commit = commit_result.stdout.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
        raise ResearchRunError("repository returned an invalid commit identifier")
    status_result = subprocess.run(
        ["git", "-C", str(repository_root), "status", "--porcelain=v1", "--untracked-files=all"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if status_result.returncode != 0:
        raise ResearchRunError(
            f"cannot resolve repository dirty state: {status_result.stderr.strip()}"
        )
    dirty_files = tuple(
        line.rstrip() for line in status_result.stdout.splitlines() if line.strip()
    )
    return RepositoryState(commit=commit.lower(), dirty=bool(dirty_files), dirty_files=dirty_files)


def load_research_run_spec(path: Path) -> ResearchRunSpec:
    spec_path = _canonical_existing_file(path, "research spec")
    try:
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchRunError(f"research spec is not valid UTF-8 JSON: {spec_path}") from exc
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("schema_version"), int)
        or isinstance(payload.get("schema_version"), bool)
        or payload.get("schema_version") != 1
    ):
        raise ResearchRunError("research spec must be a schema_version 1 object")
    fields = {
        "run_id",
        "repository_root",
        "terminal_path",
        "terminal_data_path",
        "terminal_data_mode",
        "terminal_build",
        "ea_source_path",
        "ea_binary_path",
        "set_source_path",
        "provenance_path",
        "staged_set_path",
        "config_path",
        "report_path",
        "log_path",
        "metrics_path",
        "manifest_path",
        "expert_name",
        "symbol",
        "timeframe",
        "from_date",
        "to_date",
        "purpose",
        "statistical_classification",
        "direction_profile",
        "strategy_mode",
        "execution_profile",
        "costs",
        "tester",
    }
    unknown = set(payload).difference(fields | {"schema_version"})
    missing = fields.difference(payload)
    if unknown or missing:
        raise ResearchRunError(
            f"research spec fields mismatch; missing={sorted(missing)!r} "
            f"unknown={sorted(unknown)!r}"
        )
    if not isinstance(payload["costs"], dict) or not isinstance(payload["tester"], dict):
        raise ResearchRunError("research spec costs and tester must be objects")
    string_fields = fields.difference(
        {"costs", "tester", "strategy_mode"}
    )
    for field_name in string_fields:
        if not isinstance(payload[field_name], str):
            raise ResearchRunError(
                f"research spec field {field_name!r} must be a string"
            )
    if not isinstance(payload["strategy_mode"], int) or isinstance(
        payload["strategy_mode"], bool
    ):
        raise ResearchRunError("research spec strategy_mode must be an integer")
    try:
        costs = ResearchCosts(**payload["costs"])
        tester = TesterSettings(**payload["tester"])
    except TypeError as exc:
        raise ResearchRunError(f"invalid costs or tester fields: {exc}") from exc
    costs.validate()
    tester.validate()
    path_fields = {
        "repository_root",
        "terminal_path",
        "terminal_data_path",
        "ea_source_path",
        "ea_binary_path",
        "set_source_path",
        "provenance_path",
        "staged_set_path",
        "config_path",
        "report_path",
        "log_path",
        "metrics_path",
        "manifest_path",
    }
    values = {
        name: Path(payload[name]) if name in path_fields else payload[name]
        for name in fields.difference(
            {
                "costs",
                "tester",
                "terminal_data_mode",
                "statistical_classification",
            }
        )
    }
    try:
        terminal_data_mode = TerminalDataMode(payload["terminal_data_mode"])
    except (TypeError, ValueError) as exc:
        raise ResearchRunError(
            "terminal_data_mode must be explicit: PORTABLE or STANDARD"
        ) from exc
    try:
        statistical_classification = StatisticalClassification(
            payload["statistical_classification"]
        )
    except (TypeError, ValueError) as exc:
        raise ResearchRunError(
            "statistical_classification must be an explicit supported classification"
        ) from exc
    return ResearchRunSpec(
        **values,
        terminal_data_mode=terminal_data_mode,
        statistical_classification=statistical_classification,
        costs=costs,
        tester=tester,
    )


def probe_windows_terminal(
    terminal_path: Path,
    terminal_data_path: Path,
    terminal_data_mode: TerminalDataMode,
    *,
    process_snapshot_loader: Callable[[str], WindowsProcessSnapshot] | None = None,
    build_loader: Callable[[Path], str] | None = None,
    platform: str | None = None,
) -> TerminalProbeResult:
    resolved_platform = platform or os.name
    if resolved_platform != "nt":
        raise ResearchRunError("Windows terminal probe is only available on Windows")
    if not isinstance(terminal_data_mode, TerminalDataMode):
        raise ResearchRunError(
            "terminal_data_mode must be explicit: PORTABLE or STANDARD"
        )
    terminal = _canonical_existing_file(terminal_path, "terminal_path")
    data_path = _canonical_existing_directory(terminal_data_path, "terminal_data_path")
    if terminal_data_mode is TerminalDataMode.PORTABLE:
        if data_path != terminal.parent:
            raise ResearchRunError(
                "PORTABLE terminal data path must equal the terminal installation directory"
            )
    else:
        _assert_terminal_data_origin(terminal, data_path)
    snapshot_loader = process_snapshot_loader or _windows_process_snapshot
    terminal_snapshot = snapshot_loader(terminal.name)
    tester_snapshot = snapshot_loader("metatester64.exe")
    if not isinstance(terminal_snapshot, WindowsProcessSnapshot) or not isinstance(
        tester_snapshot, WindowsProcessSnapshot
    ):
        raise ResearchRunError("Windows process probe returned an invalid snapshot")
    target_key = _windows_path_key(terminal)
    terminal_running = any(
        _windows_path_key(_canonical_existing_file(path, "running terminal"))
        == target_key
        for path in terminal_snapshot.executable_paths
    )
    tester_paths = tuple(
        _canonical_existing_file(path, "running MetaTester64")
        for path in tester_snapshot.executable_paths
    )
    scoped_tester_paths = tuple(
        path
        for path in tester_paths
        if path.is_relative_to(data_path) or path.is_relative_to(terminal.parent)
    )
    if terminal_running:
        state = TerminalState.RUNNING
        detail = "exact terminal executable is already running"
    elif scoped_tester_paths:
        state = TerminalState.RUNNING
        detail = (
            "MetaTester64 process is already running inside the exact terminal/data path: "
            + ", ".join(str(path) for path in scoped_tester_paths)
        )
    elif (
        terminal_snapshot.unresolved_matching_processes
        or tester_snapshot.unresolved_matching_processes
    ):
        state = TerminalState.UNKNOWN
        detail = (
            "cannot resolve all matching terminal64/MetaTester64 process paths"
        )
    else:
        state = TerminalState.STOPPED
        detail = "exact terminal executable is not running"
    observed_build = (build_loader or _windows_file_version)(terminal)
    if not observed_build:
        raise ResearchRunError("terminal file version is unavailable")
    return TerminalProbeResult(
        state=state,
        executable_path=terminal,
        data_path=data_path,
        data_mode=terminal_data_mode,
        build=observed_build,
        detail=detail,
    )


def make_windows_terminal_probe(
    terminal_data_path: Path,
    terminal_data_mode: TerminalDataMode,
) -> TerminalProbe:
    data_path = _canonical_existing_directory(terminal_data_path, "terminal_data_path")
    if not isinstance(terminal_data_mode, TerminalDataMode):
        raise ResearchRunError(
            "terminal_data_mode must be explicit: PORTABLE or STANDARD"
        )

    def probe(terminal_path: Path) -> TerminalProbeResult:
        return probe_windows_terminal(terminal_path, data_path, terminal_data_mode)

    return probe


def launch_windows_terminal_once(
    terminal_path: Path,
    config_path: Path,
    terminal_data_mode: TerminalDataMode,
    *,
    timeout_seconds: float,
    popen_factory: Callable[..., Any] | None = None,
    platform: str | None = None,
) -> ProcessResult:
    resolved_platform = platform or os.name
    if resolved_platform != "nt":
        raise ResearchRunError("Windows terminal launcher is only available on Windows")
    if not isinstance(terminal_data_mode, TerminalDataMode):
        raise ResearchRunError(
            "terminal_data_mode must be explicit: PORTABLE or STANDARD"
        )
    terminal = _canonical_existing_file(terminal_path, "terminal_path")
    config = _canonical_existing_file(config_path, "tester config")
    if not isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ResearchRunError("terminal wait timeout must be finite and positive")
    process_factory = popen_factory or subprocess.Popen
    creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    arguments = [str(terminal), f"/config:{config}"]
    if terminal_data_mode is TerminalDataMode.PORTABLE:
        arguments.append("/portable")
    try:
        process = process_factory(
            arguments,
            cwd=str(terminal.parent),
            shell=False,
            close_fds=True,
            creationflags=creation_flags,
        )
    except Exception as exc:
        raise ResearchRunError(f"terminal launch failed before process creation: {exc}") from exc
    try:
        exit_code = int(process.wait(timeout=timeout_seconds))
    except subprocess.TimeoutExpired as exc:
        pid = getattr(process, "pid", "unknown")
        # Do not call terminate() or kill(): a timed-out broker/tester process is
        # external state that must be inspected and reconciled by the operator.
        raise ResearchRunError(
            f"terminal wait timed out with pid={pid}; process was left running and must be inspected"
        ) from exc
    except Exception as exc:
        pid = getattr(process, "pid", "unknown")
        raise ResearchRunError(
            f"terminal wait failed with pid={pid}; process was left untouched: {exc}"
        ) from exc
    return ProcessResult(
        exit_code=exit_code,
        executable_path=terminal,
        data_mode=terminal_data_mode,
    )


def make_windows_launcher(timeout_seconds: float) -> ProcessLauncher:
    if not isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ResearchRunError("terminal wait timeout must be finite and positive")

    def launch(
        terminal_path: Path,
        config_path: Path,
        terminal_data_mode: TerminalDataMode,
    ) -> ProcessResult:
        return launch_windows_terminal_once(
            terminal_path,
            config_path,
            terminal_data_mode,
            timeout_seconds=timeout_seconds,
        )

    return launch


def _assert_terminal_data_origin(terminal_path: Path, terminal_data_path: Path) -> None:
    origin_path = terminal_data_path / "origin.txt"
    if not origin_path.is_file():
        raise ResearchRunError(
            f"terminal data path is missing origin.txt association: {origin_path}"
        )
    origin_text = _decode_mt5_text(origin_path.read_bytes()).replace("\x00", "")
    origin_lines = [line.strip() for line in origin_text.splitlines() if line.strip()]
    if len(origin_lines) != 1:
        raise ResearchRunError("terminal data origin.txt must contain exactly one path")
    origin = Path(origin_lines[0])
    if not origin.is_absolute():
        raise ResearchRunError("terminal data origin.txt must contain an absolute path")
    origin = origin.resolve(strict=True)
    expected = terminal_path.parent
    if origin.is_file():
        origin = origin.parent
    if _windows_path_key(origin) != _windows_path_key(expected):
        raise ResearchRunError(
            "terminal data path origin does not match the configured terminal installation"
        )


def _windows_path_key(path: Path) -> str:
    return str(path.resolve(strict=True)).replace("/", "\\").casefold().rstrip("\\")


def _windows_process_snapshot(executable_name: str) -> WindowsProcessSnapshot:
    if os.name != "nt":
        raise ResearchRunError("Windows process enumeration is only available on Windows")
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    th32cs_snapprocess = 0x00000002
    invalid_handle_value = ctypes.c_void_p(-1).value

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32W),
    ]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32W),
    ]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot_handle = kernel32.CreateToolhelp32Snapshot(th32cs_snapprocess, 0)
    if snapshot_handle == invalid_handle_value:
        raise ResearchRunError("CreateToolhelp32Snapshot failed")
    paths: list[Path] = []
    unresolved = 0
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(ProcessEntry32W)
        has_entry = bool(kernel32.Process32FirstW(snapshot_handle, ctypes.byref(entry)))
        while has_entry:
            if str(entry.szExeFile).casefold() == executable_name.casefold():
                process_handle = kernel32.OpenProcess(
                    process_query_limited_information,
                    False,
                    entry.th32ProcessID,
                )
                if not process_handle:
                    unresolved += 1
                else:
                    try:
                        buffer = ctypes.create_unicode_buffer(32768)
                        size = wintypes.DWORD(len(buffer))
                        if kernel32.QueryFullProcessImageNameW(
                            process_handle, 0, buffer, ctypes.byref(size)
                        ):
                            paths.append(Path(buffer.value))
                        else:
                            unresolved += 1
                    finally:
                        kernel32.CloseHandle(process_handle)
            has_entry = bool(kernel32.Process32NextW(snapshot_handle, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot_handle)
    return WindowsProcessSnapshot(tuple(paths), unresolved)


def _windows_file_version(path: Path) -> str:
    if os.name != "nt":
        raise ResearchRunError("Windows file version is only available on Windows")
    import ctypes
    from ctypes import wintypes

    class FixedFileInfo(ctypes.Structure):
        _fields_ = [
            ("dwSignature", wintypes.DWORD),
            ("dwStrucVersion", wintypes.DWORD),
            ("dwFileVersionMS", wintypes.DWORD),
            ("dwFileVersionLS", wintypes.DWORD),
            ("dwProductVersionMS", wintypes.DWORD),
            ("dwProductVersionLS", wintypes.DWORD),
            ("dwFileFlagsMask", wintypes.DWORD),
            ("dwFileFlags", wintypes.DWORD),
            ("dwFileOS", wintypes.DWORD),
            ("dwFileType", wintypes.DWORD),
            ("dwFileSubtype", wintypes.DWORD),
            ("dwFileDateMS", wintypes.DWORD),
            ("dwFileDateLS", wintypes.DWORD),
        ]

    version = ctypes.WinDLL("version", use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    version.GetFileVersionInfoW.restype = wintypes.BOOL
    version.VerQueryValueW.argtypes = [
        wintypes.LPCVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.UINT),
    ]
    version.VerQueryValueW.restype = wintypes.BOOL
    ignored = wintypes.DWORD(0)
    size = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(ignored))
    if not size:
        raise ResearchRunError(f"cannot read terminal file version: {path}")
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        raise ResearchRunError(f"GetFileVersionInfoW failed: {path}")
    value_pointer = ctypes.c_void_p()
    value_length = wintypes.UINT(0)
    if not version.VerQueryValueW(
        buffer,
        "\\",
        ctypes.byref(value_pointer),
        ctypes.byref(value_length),
    ):
        raise ResearchRunError(f"VerQueryValueW failed: {path}")
    info = ctypes.cast(value_pointer, ctypes.POINTER(FixedFileInfo)).contents
    if info.dwSignature != 0xFEEF04BD:
        raise ResearchRunError(f"terminal file version signature is invalid: {path}")
    parts = (
        info.dwFileVersionMS >> 16,
        info.dwFileVersionMS & 0xFFFF,
        info.dwFileVersionLS >> 16,
        info.dwFileVersionLS & 0xFFFF,
    )
    return ".".join(str(part) for part in parts)


class _MT5ReportTableParser(HTMLParser):
    """Small structural reader for the HTML table format documented by MetaQuotes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, ...]] = []
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        lowered = tag.casefold()
        if lowered == "tr":
            self._row = []
        elif lowered in {"td", "th"} and self._row is not None:
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"td", "th"} and self._cell_parts is not None:
            if self._row is not None:
                self._row.append(" ".join("".join(self._cell_parts).split()))
            self._cell_parts = None
        elif lowered == "tr" and self._row is not None:
            self.rows.append(tuple(self._row))
            self._row = None
            self._cell_parts = None


def _validate_mt5_report_identity(
    report_text: str,
    *,
    spec: ResearchRunSpec,
    provenance: ResearchProvenance,
) -> dict[str, Any]:
    """Validate documented MT5 HTML settings/results fields.

    The generic table shape is based on MetaQuotes' published tester-report
    parser.  A GoldM report fixture is intentionally still required before a
    production matrix: absent, localized, or structurally changed fields fail
    closed instead of being inferred from the requested tester config.
    """

    parser = _MT5ReportTableParser()
    try:
        parser.feed(report_text)
        parser.close()
    except Exception as exc:
        raise ResearchRunError(f"MT5 report HTML cannot be parsed: {exc}") from exc
    if not parser.rows:
        raise ResearchRunError("MT5 report contains no auditable HTML table rows")
    flattened = [cell for row in parser.rows for cell in row]
    if not any("strategy test" in cell.casefold() for cell in flattened):
        raise ResearchRunError("report is not identified as an MT5 Strategy Test report")

    labels: dict[str, set[str]] = {}
    for row in parser.rows:
        for index in range(0, len(row) - 1, 2):
            label = row[index].strip().rstrip(":").casefold()
            value = row[index + 1].strip()
            if label and value:
                labels.setdefault(label, set()).add(value)

    def one(label: str, *aliases: str) -> str:
        values: set[str] = set()
        for candidate in (label, *aliases):
            values.update(labels.get(candidate.casefold(), set()))
        if len(values) != 1:
            raise ResearchRunError(
                f"report field {label!r} must occur once with one unambiguous value; "
                f"observed={sorted(values)!r}"
            )
        return next(iter(values))

    expert = one("Expert Advisor", "Expert")
    if Path(expert.replace("\\", "/")).stem.casefold() != spec.ea_source_path.stem.casefold():
        raise ResearchRunError(f"report Expert Advisor mismatch: {expert!r}")
    symbol = one("Symbol")
    if symbol != spec.symbol:
        raise ResearchRunError(f"report symbol mismatch: {symbol!r}")
    period = one("Period")
    period_match = re.fullmatch(
        r"(?P<timeframe>[A-Z][A-Z0-9]*)\s*\(\s*"
        r"(?P<from>\d{4}[.-]\d{2}[.-]\d{2})\s*-\s*"
        r"(?P<to>\d{4}[.-]\d{2}[.-]\d{2})\s*\)",
        period,
    )
    if period_match is None:
        raise ResearchRunError(f"report period/range format is unsupported: {period!r}")
    observed_from = period_match.group("from").replace(".", "-")
    observed_to = period_match.group("to").replace(".", "-")
    if (
        period_match.group("timeframe") != spec.timeframe
        or observed_from != spec.from_date
        or observed_to != spec.to_date
    ):
        raise ResearchRunError(
            "report timeframe or half-open tester boundaries do not match the run"
        )
    broker = one("Broker")
    if broker != provenance.broker_server:
        raise ResearchRunError(f"report broker mismatch: {broker!r}")
    history_quality = one("History Quality")
    quality_match = re.fullmatch(r"(?P<quality>\d+(?:\.\d+)?)%", history_quality)
    if quality_match is None or float(quality_match.group("quality")) <= 0.0:
        raise ResearchRunError(
            f"report History Quality is missing or invalid: {history_quality!r}"
        )

    def integer_field(label: str) -> int:
        raw = one(label).replace(" ", "").replace(",", "")
        if not re.fullmatch(r"\d+", raw) or int(raw) <= 0:
            raise ResearchRunError(f"report {label} must be a positive integer")
        return int(raw)

    bars = integer_field("Bars")
    ticks = integer_field("Ticks")
    # Bars/Ticks are post-run observations. Requiring their exact values in a
    # pre-run provenance file is circular for the first controlled smoke run.
    # The immutable bounded dataset declares row bounds and a source hash; the
    # actual tester observations are persisted only after the report exists.
    if provenance.history_declaration["from_inclusive"] > observed_from or (
        provenance.history_declaration["to_exclusive"] < observed_to
    ):
        raise ResearchRunError("report range is not covered by the bounded dataset")
    return {
        "contract_id": "MT5_STRATEGY_TEST_HTML_EN_V1",
        "expert": expert,
        "symbol": symbol,
        "timeframe": period_match.group("timeframe"),
        "from_inclusive": observed_from,
        "to_exclusive": observed_to,
        "broker_server": broker,
        "history_quality": history_quality,
        "bars": bars,
        "ticks": ticks,
    }


def verify_research_artifacts(
    spec: ResearchRunSpec,
    *,
    log_offset: int,
    log_prefix_sha256: str | None,
    started_ns: int,
) -> VerifiedResearchArtifacts:
    _assert_fresh_nonempty_file(spec.report_path, "report", started_ns=started_ns)
    _assert_fresh_nonempty_file(spec.log_path, "log", started_ns=started_ns)
    if spec.log_path.stat().st_size < log_offset:
        raise ResearchRunError("MT5 log was truncated or rotated during the run")
    if spec.log_path.stat().st_size == log_offset:
        raise ResearchRunError("MT5 log has no bytes appended for this run")
    if log_offset and _sha256_prefix(spec.log_path, log_offset) != log_prefix_sha256:
        raise ResearchRunError("MT5 log prefix changed; rotation or replacement detected")

    with spec.log_path.open("rb") as stream:
        stream.seek(log_offset)
        appended_log = stream.read()
        log_text = _decode_mt5_text(appended_log)
    if not log_text.strip():
        raise ResearchRunError("MT5 appended log segment is empty")
    try:
        parsed = parse_research_log(
            log_text,
            expected_run_id=spec.run_id,
            expected_direction_profile=spec.direction_profile,
            expected_strategy_mode=spec.strategy_mode,
        )
        raw_metrics = parsed.metrics(per_trade_cost_r=0.0)
    except ResearchMetricsError as exc:
        raise ResearchRunError(f"research log lifecycle is invalid: {exc}") from exc

    report_text = html.unescape(_decode_mt5_text(spec.report_path.read_bytes()))
    report_plain_text = re.sub(r"<[^>]*>", " ", report_text)
    explicit_report_ids = set(
        re.findall(
            r"(?:InpResearchRunId|runId)(?:\s*[=:]\s*|\s+)([A-Za-z0-9._-]+)",
            report_plain_text,
        )
    )
    if not explicit_report_ids:
        raise ResearchRunError("fresh report is missing an explicit runId")
    if explicit_report_ids != {spec.run_id}:
        raise ResearchRunError(
            f"report runId mismatch: observed {sorted(explicit_report_ids)!r}"
        )
    provenance = _load_research_provenance(spec)
    report_identity = _validate_mt5_report_identity(
        report_text,
        spec=spec,
        provenance=provenance,
    )
    history_observation = {
        key: report_identity[key]
        for key in (
            "contract_id",
            "symbol",
            "timeframe",
            "from_inclusive",
            "to_exclusive",
            "broker_server",
            "history_quality",
            "bars",
            "ticks",
        )
    }
    appended_log_sha256 = hashlib.sha256(appended_log).hexdigest()
    trades = [asdict(trade) for trade in parsed.trades]
    metrics = asdict(raw_metrics)
    lineage = {
        "strategy": parsed.strategy,
        "strategy_version": parsed.strategy_version,
        "direction_profile": parsed.direction_profile,
        "strategy_mode": parsed.strategy_mode,
    }
    metrics_artifact = {
        "schema_version": 2,
        "run_id": spec.run_id,
        "metric_basis": "RAW_MODEL_R_NO_ADDITIONAL_COST",
        "statistical_classification": spec.statistical_classification.value,
        "lineage": lineage,
        "source_log": {
            "path": str(spec.log_path),
            "append_start_offset": log_offset,
            "appended_sha256": appended_log_sha256,
        },
        "report_contract": {
            "contract_id": report_identity["contract_id"],
            "strict_actual_report_verified": True,
            "report_path": str(spec.report_path),
        },
        "history_observation": history_observation,
        "performance_fields": dict(sorted(parsed.performance_fields.items())),
        "trades": trades,
        "metrics": metrics,
    }
    correlation = {
        "run_id": spec.run_id,
        "report_fresh": True,
        "report_run_id_verified": True,
        "report_identity_verified": True,
        "report_identity": report_identity,
        "log_fresh": True,
        "log_start_offset": log_offset,
        "appended_log_sha256": appended_log_sha256,
        "config_events": 1,
        "performance_event_verified": True,
        "lifecycle_verified": True,
    }
    manifest_result = {
        "metric_basis": "RAW_MODEL_R_NO_ADDITIONAL_COST",
        "statistical_classification": spec.statistical_classification.value,
        "lineage": lineage,
        "trade_count": len(parsed.trades),
        "raw_metrics": metrics,
        "history_observation": history_observation,
        "report_contract": {
            "contract_id": report_identity["contract_id"],
            "strict_actual_report_verified": True,
        },
    }
    return VerifiedResearchArtifacts(
        correlation=correlation,
        manifest_result=manifest_result,
        metrics_artifact=metrics_artifact,
    )


def _load_research_provenance(spec: ResearchRunSpec) -> ResearchProvenance:
    path = _canonical_existing_file(spec.provenance_path, "provenance evidence")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchRunError(
            f"provenance evidence is not valid UTF-8 JSON: {path}"
        ) from exc
    required = {
        "schema_version",
        "captured_at",
        "broker_server",
        "management_policy_version",
        "symbol_specification",
        "history_declaration",
        "broker_cost_evidence",
        "compilation",
    }
    if not isinstance(payload, dict):
        raise ResearchRunError("provenance evidence must be a JSON object")
    schema_version = payload.get("schema_version")
    if schema_version == 2:
        expected_fields = required
    elif schema_version == 3:
        expected_fields = required | {"custom_symbol_import"}
    else:
        raise ResearchRunError("provenance evidence must use schema_version 2 or 3")
    if set(payload) != expected_fields:
        raise ResearchRunError(
            f"provenance evidence fields do not match schema_version {schema_version}"
        )
    captured_at = _strict_utc_timestamp(payload["captured_at"], "provenance captured_at")
    broker_server = payload["broker_server"]
    management_policy_version = payload["management_policy_version"]
    for label, value in (
        ("broker_server", broker_server),
        ("management_policy_version", management_policy_version),
    ):
        if (
            not isinstance(value, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]{1,127}", value)
        ):
            raise ResearchRunError(f"provenance {label} must be an explicit token")

    symbol_specification = payload["symbol_specification"]
    symbol_fields = {
        "symbol",
        "source_symbol",
        "is_custom",
        "captured_at",
        "capture_method",
        "source_path",
        "source_sha256",
        "digits",
        "point",
        "trade_tick_size",
        "trade_tick_value",
        "trade_contract_size",
        "volume_min",
        "volume_max",
        "volume_step",
        "currency_profit",
        "currency_margin",
    }
    if not isinstance(symbol_specification, dict) or set(symbol_specification) != (
        symbol_fields
    ):
        raise ResearchRunError("provenance symbol_specification fields are incomplete")
    if symbol_specification["symbol"] != spec.symbol:
        raise ResearchRunError("provenance symbol specification does not match run symbol")
    if (
        not isinstance(symbol_specification["source_symbol"], str)
        or not re.fullmatch(r"[A-Za-z0-9._#-]+", symbol_specification["source_symbol"])
    ):
        raise ResearchRunError("provenance source_symbol is invalid")
    if symbol_specification["is_custom"] is not True:
        raise ResearchRunError(
            "research requires a bounded offline custom symbol; broker-online symbols are prohibited"
        )
    if symbol_specification["symbol"].casefold() == symbol_specification[
        "source_symbol"
    ].casefold():
        raise ResearchRunError(
            "offline custom symbol must use an alias distinct from the broker source symbol"
        )
    _strict_utc_timestamp(
        symbol_specification["captured_at"], "symbol specification captured_at"
    )
    if not isinstance(symbol_specification["capture_method"], str) or not _EVIDENCE_METHOD_PATTERN.fullmatch(
        symbol_specification["capture_method"]
    ):
        raise ResearchRunError("symbol specification capture_method is invalid")
    symbol_spec_evidence_path = _bound_evidence_file(
        symbol_specification["source_path"],
        symbol_specification["source_sha256"],
        "symbol specification source",
        forbidden_paths=(path,),
    )
    digits = symbol_specification["digits"]
    if (
        not isinstance(digits, int)
        or isinstance(digits, bool)
        or digits < 0
        or digits > 12
    ):
        raise ResearchRunError("provenance symbol digits must be within [0, 12]")
    for field_name in (
        "point",
        "trade_tick_size",
        "trade_tick_value",
        "trade_contract_size",
        "volume_min",
        "volume_max",
        "volume_step",
    ):
        value = symbol_specification[field_name]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not isfinite(value)
            or value <= 0.0
        ):
            raise ResearchRunError(
                f"provenance symbol_specification.{field_name} must be finite and positive"
            )
    if symbol_specification["volume_min"] > symbol_specification["volume_max"]:
        raise ResearchRunError("provenance symbol volume_min exceeds volume_max")
    for field_name in ("currency_profit", "currency_margin"):
        if not isinstance(symbol_specification[field_name], str) or not re.fullmatch(
            r"[A-Z]{3,8}", symbol_specification[field_name]
        ):
            raise ResearchRunError(
                f"provenance symbol_specification.{field_name} is invalid"
            )

    history = payload["history_declaration"]
    history_fields = {
        "symbol",
        "source_symbol",
        "data_kind",
        "warmup_from_inclusive",
        "from_inclusive",
        "to_exclusive",
        "row_count",
        "first_timestamp_utc",
        "last_timestamp_utc",
        "integrity_verified",
        "captured_at",
        "capture_method",
        "source_path",
        "source_sha256",
        "dataset_manifest_path",
        "dataset_manifest_sha256",
        "access_mode",
        "network_isolation_evidence_path",
        "network_isolation_evidence_sha256",
    }
    if not isinstance(history, dict) or set(history) != history_fields:
        raise ResearchRunError("provenance history_declaration fields are incomplete")
    if history["symbol"] != spec.symbol or history["source_symbol"] != (
        symbol_specification["source_symbol"]
    ):
        raise ResearchRunError("provenance history identity does not match the custom/source symbol")
    if history["data_kind"] != "TICKS_UTC":
        raise ResearchRunError("research history must be an explicit bounded UTC tick dataset")
    if history["access_mode"] != "OFFLINE_BOUNDED_DATASET":
        raise ResearchRunError(
            "research history access must be OFFLINE_BOUNDED_DATASET; online tester sync is prohibited"
        )
    for field_name in (
        "warmup_from_inclusive",
        "from_inclusive",
        "to_exclusive",
    ):
        if not isinstance(history[field_name], str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", history[field_name]
        ):
            raise ResearchRunError(
                f"provenance history_declaration.{field_name} must be YYYY-MM-DD"
            )
        try:
            datetime.strptime(history[field_name], "%Y-%m-%d")
        except ValueError as exc:
            raise ResearchRunError(
                f"provenance history_declaration.{field_name} is not a calendar date"
            ) from exc
    if history["from_inclusive"] > spec.from_date or history["to_exclusive"] < (
        spec.to_date
    ):
        raise ResearchRunError("provenance history does not cover the complete run range")
    if history["from_inclusive"] >= history["to_exclusive"]:
        raise ResearchRunError("provenance history coverage range is empty or reversed")
    policy = load_research_policy()
    quarantine_from = parse_research_date(
        policy["quarantine"]["from"], field="quarantine.from"
    )
    quarantine_to = parse_research_date(
        policy["quarantine"]["to"], field="quarantine.to"
    )
    history_from = parse_research_date(
        history["from_inclusive"], field="history_declaration.from_inclusive"
    )
    history_warmup_from = parse_research_date(
        history["warmup_from_inclusive"],
        field="history_declaration.warmup_from_inclusive",
    )
    history_to = parse_research_date(
        history["to_exclusive"], field="history_declaration.to_exclusive"
    )
    if history_warmup_from > history_from:
        raise ResearchRunError("bounded history warmup begins after its run range")
    if history_warmup_from < quarantine_to and history_to > quarantine_from:
        raise ResearchRunError(
            "bounded offline dataset intersects the protected quarantine"
        )
    row_count = history["row_count"]
    if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count <= 0:
        raise ResearchRunError("history_declaration.row_count must be a positive integer")
    first_timestamp = _strict_utc_datetime(
        history["first_timestamp_utc"], "history first_timestamp_utc"
    )
    last_timestamp = _strict_utc_datetime(
        history["last_timestamp_utc"], "history last_timestamp_utc"
    )
    if not (
        history_warmup_from <= first_timestamp <= last_timestamp < history_to
    ):
        raise ResearchRunError(
            "history row timestamp bounds must stay inside the declared half-open dataset"
        )
    if history["integrity_verified"] is not True:
        raise ResearchRunError("bounded history integrity must be explicitly verified")
    _strict_utc_timestamp(history["captured_at"], "history captured_at")
    if not isinstance(history["capture_method"], str) or not (
        _EVIDENCE_METHOD_PATTERN.fullmatch(history["capture_method"])
    ):
        raise ResearchRunError("history capture_method is invalid")
    history_evidence_path = _bound_evidence_file(
        history["source_path"],
        history["source_sha256"],
        "bounded history source",
        forbidden_paths=(path,),
    )
    dataset_manifest_path = _bound_evidence_file(
        history["dataset_manifest_path"],
        history["dataset_manifest_sha256"],
        "bounded history dataset manifest",
        forbidden_paths=(path, history_evidence_path),
    )
    try:
        registered_dataset = load_registered_tick_dataset(
            dataset_manifest_path,
            expected_run_start=parse_research_date(
                spec.from_date, field="spec.from_date"
            ),
            expected_end=parse_research_date(spec.to_date, field="spec.to_date"),
            expected_purpose=spec.purpose,
            expected_classification=spec.statistical_classification,
            require_exact_run_range=False,
            require_source_evidence=True,
            include_rows=False,
        )
    except (ResearchDatasetError, TypeError, ValueError) as exc:
        raise ResearchRunError(
            f"bounded offline dataset manifest failed verification: {exc}"
        ) from exc
    if (
        registered_dataset.custom_symbol != spec.symbol
        or registered_dataset.source_symbol != symbol_specification["source_symbol"]
        or registered_dataset.dataset_path != history_evidence_path
        or registered_dataset.dataset_sha256 != history["source_sha256"]
        or registered_dataset.row_count != row_count
        or registered_dataset.warmup_start != history_warmup_from
        or registered_dataset.run_start != history_from
        or registered_dataset.end != history_to
        or registered_dataset.first_time_msc != int(first_timestamp.timestamp() * 1000)
        or registered_dataset.last_time_msc != int(last_timestamp.timestamp() * 1000)
    ):
        raise ResearchRunError(
            "history declaration does not exactly match its registered offline dataset"
        )
    network_isolation_evidence_path = _bound_evidence_file(
        history["network_isolation_evidence_path"],
        history["network_isolation_evidence_sha256"],
        "network isolation evidence",
        forbidden_paths=(path, history_evidence_path, dataset_manifest_path),
    )

    custom_symbol_import: dict[str, Any] | None = None
    import_receipt_path: Path | None = None
    import_receipt_sha256: str | None = None
    if schema_version == 3:
        custom_symbol_import = payload["custom_symbol_import"]
        if not isinstance(custom_symbol_import, dict) or set(custom_symbol_import) != {
            "receipt_path",
            "receipt_sha256",
        }:
            raise ResearchRunError("custom_symbol_import fields are incomplete")
        import_receipt_path = _bound_evidence_file(
            custom_symbol_import["receipt_path"],
            custom_symbol_import["receipt_sha256"],
            "custom-symbol import receipt",
            forbidden_paths=(
                path,
                history_evidence_path,
                dataset_manifest_path,
                network_isolation_evidence_path,
            ),
        )
        import_receipt_sha256 = _sha256_file(import_receipt_path)
        try:
            verified_import: VerifiedOfflineImport = load_verified_offline_import(
                import_receipt_path
            )
            import_specification = load_custom_symbol_import_spec(
                verified_import.symbol_spec_path
            )
        except (OfflineImportError, OSError, TypeError, ValueError) as exc:
            raise ResearchRunError(
                f"custom-symbol import receipt failed verification: {exc}"
            ) from exc
        if (
            verified_import.custom_symbol != spec.symbol
            or verified_import.source_symbol != symbol_specification["source_symbol"]
            or verified_import.terminal_root != spec.terminal_data_path
            or verified_import.dataset_manifest_path != dataset_manifest_path
            or verified_import.dataset_manifest_sha256
            != _sha256_file(dataset_manifest_path)
            or verified_import.dataset_path != history_evidence_path
            or verified_import.dataset_sha256 != history["source_sha256"]
            or verified_import.network_isolation_evidence_path
            != network_isolation_evidence_path
            or verified_import.network_isolation_evidence_sha256
            != _sha256_file(network_isolation_evidence_path)
            or verified_import.row_count != registered_dataset.row_count
            or verified_import.first_time_msc != registered_dataset.first_time_msc
            or verified_import.last_time_msc != registered_dataset.last_time_msc
        ):
            raise ResearchRunError(
                "custom-symbol import receipt identity does not match the run provenance"
            )
        comparable_symbol_properties = {
            "digits": import_specification.digits,
            "point": import_specification.point,
            "trade_tick_size": import_specification.trade_tick_size,
            "trade_tick_value": import_specification.trade_tick_value,
            "trade_contract_size": import_specification.trade_contract_size,
            "volume_min": import_specification.volume_min,
            "volume_max": import_specification.volume_max,
            "volume_step": import_specification.volume_step,
            "currency_profit": import_specification.currency_profit,
            "currency_margin": import_specification.currency_margin,
        }
        if any(
            symbol_specification[field] != value
            for field, value in comparable_symbol_properties.items()
        ):
            raise ResearchRunError(
                "imported custom-symbol properties differ from provenance"
            )

    broker_cost_evidence = payload["broker_cost_evidence"]
    cost_fields = {
        "captured_at",
        "capture_method",
        "account_scope",
        "broker_server",
        "symbol",
        "source_symbol",
        "source_path",
        "source_sha256",
        "costs",
    }
    if not isinstance(broker_cost_evidence, dict) or set(broker_cost_evidence) != (
        cost_fields
    ):
        raise ResearchRunError("broker_cost_evidence fields are incomplete")
    _strict_utc_timestamp(
        broker_cost_evidence["captured_at"], "broker cost evidence captured_at"
    )
    if not isinstance(broker_cost_evidence["capture_method"], str) or not (
        _EVIDENCE_METHOD_PATTERN.fullmatch(broker_cost_evidence["capture_method"])
    ):
        raise ResearchRunError("broker cost capture_method is invalid")
    if broker_cost_evidence["account_scope"] != "DEMO":
        raise ResearchRunError("broker cost evidence must be captured from a DEMO scope")
    if (
        broker_cost_evidence["broker_server"] != broker_server
        or broker_cost_evidence["symbol"] != spec.symbol
        or broker_cost_evidence["source_symbol"]
        != symbol_specification["source_symbol"]
    ):
        raise ResearchRunError("broker cost evidence identity does not match the run")
    if broker_cost_evidence["costs"] != asdict(spec.costs):
        raise ResearchRunError("broker cost evidence values do not exactly match the run spec")
    broker_cost_source_path = _bound_evidence_file(
        broker_cost_evidence["source_path"],
        broker_cost_evidence["source_sha256"],
        "broker cost source",
        forbidden_paths=(
            path,
            history_evidence_path,
            dataset_manifest_path,
            network_isolation_evidence_path,
        ),
    )

    compilation = payload["compilation"]
    compilation_fields = {
        "status",
        "exit_code",
        "errors",
        "warnings",
        "source_path",
        "source_sha256",
        "binary_path",
        "binary_sha256",
        "log_path",
        "log_sha256",
    }
    if not isinstance(compilation, dict) or set(compilation) != compilation_fields:
        raise ResearchRunError("provenance compilation fields are incomplete")
    integer_results = tuple(
        compilation[field_name] for field_name in ("exit_code", "errors", "warnings")
    )
    if (
        compilation["status"] != "SUCCESS_ZERO_ERRORS_ZERO_WARNINGS"
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value != 0
            for value in integer_results
        )
    ):
        raise ResearchRunError("EA compilation evidence is not zero-error/zero-warning")
    expected_source = str(spec.ea_source_path)
    expected_binary = str(spec.ea_binary_path)
    if compilation["source_path"] != expected_source or compilation["binary_path"] != (
        expected_binary
    ):
        raise ResearchRunError("EA compilation evidence paths do not match the run")
    if compilation["source_sha256"] != _sha256_file(spec.ea_source_path) or (
        compilation["binary_sha256"] != _sha256_file(spec.ea_binary_path)
    ):
        raise ResearchRunError("EA compilation evidence hashes do not match source/binary")
    compile_log_path = _canonical_existing_file(
        Path(str(compilation["log_path"])), "EA compile log"
    )
    if str(compile_log_path) != compilation["log_path"]:
        raise ResearchRunError("EA compile log path must be exact and canonical")
    if compilation["log_sha256"] != _sha256_file(compile_log_path):
        raise ResearchRunError("EA compile log hash does not match provenance evidence")
    return ResearchProvenance(
        evidence_path=path,
        evidence_sha256=_sha256_file(path),
        captured_at=captured_at,
        broker_server=broker_server,
        management_policy_version=management_policy_version,
        symbol_specification=dict(symbol_specification),
        symbol_spec_evidence_path=symbol_spec_evidence_path,
        symbol_spec_evidence_sha256=_sha256_file(symbol_spec_evidence_path),
        history_declaration=dict(history),
        history_evidence_path=history_evidence_path,
        history_evidence_sha256=_sha256_file(history_evidence_path),
        dataset_manifest_path=dataset_manifest_path,
        dataset_manifest_sha256=_sha256_file(dataset_manifest_path),
        network_isolation_evidence_path=network_isolation_evidence_path,
        network_isolation_evidence_sha256=_sha256_file(
            network_isolation_evidence_path
        ),
        custom_symbol_import=(
            dict(custom_symbol_import) if custom_symbol_import is not None else None
        ),
        import_receipt_path=import_receipt_path,
        import_receipt_sha256=import_receipt_sha256,
        broker_cost_evidence=dict(broker_cost_evidence),
        broker_cost_source_path=broker_cost_source_path,
        broker_cost_source_sha256=_sha256_file(broker_cost_source_path),
        compilation=dict(compilation),
        compile_log_path=compile_log_path,
    )


def _load_and_validate_set(spec: ResearchRunSpec) -> tuple[str, dict[str, str]]:
    try:
        text = spec.set_source_path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise ResearchRunError("set source must be UTF-8 text") from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            raise ResearchRunError(f"malformed set line: {line!r}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in values:
            raise ResearchRunError(f"duplicate or empty set key: {key!r}")
        normalized_value = value.strip()
        if "||" in normalized_value:
            raise ResearchRunError(
                f"set key {key!r} uses optimization metadata; scalar values are required"
            )
        values[key] = normalized_value
    declared_inputs = _load_ea_input_names(spec.ea_source_path)
    missing_inputs = declared_inputs.difference(values)
    unknown_inputs = set(values).difference(declared_inputs)
    if missing_inputs or unknown_inputs:
        raise ResearchRunError(
            "set inputs do not exactly match EA declarations; "
            f"missing={sorted(missing_inputs)!r} unknown={sorted(unknown_inputs)!r}"
        )
    required = {"InpResearchRunId", "InpDirectionProfile", "InpStrategyMode"}
    missing = required.difference(values)
    if missing:
        raise ResearchRunError(f"set source is missing required keys: {sorted(missing)!r}")
    if values["InpResearchRunId"]:
        raise ResearchRunError("set source must have an empty InpResearchRunId template")
    if values["InpDirectionProfile"] != _PROFILE_VALUES[spec.direction_profile]:
        raise ResearchRunError("set direction profile does not match run specification")
    if values["InpStrategyMode"] != str(spec.strategy_mode):
        raise ResearchRunError("set strategy mode does not match run specification")
    if values.get("InpExpectedSymbol") not in {None, spec.symbol}:
        raise ResearchRunError("set expected symbol does not match run specification")
    return text, values


def _load_ea_input_names(path: Path) -> set[str]:
    try:
        source = path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise ResearchRunError("EA source must be UTF-8 text") from exc
    names: set[str] = set()
    for line_number, line in enumerate(source.splitlines(), start=1):
        if not re.match(r"^\s*input\b", line):
            continue
        match = _EA_INPUT_DECLARATION.fullmatch(line)
        if match is None:
            raise ResearchRunError(
                f"unsupported EA input declaration at line {line_number}: {line.strip()!r}"
            )
        name = match.group("name")
        if name in names:
            raise ResearchRunError(f"duplicate EA input declaration: {name!r}")
        names.add(name)
    if not names:
        raise ResearchRunError("EA source declares no auditable input parameters")
    return names


def _inject_run_id(source: str, run_id: str) -> str:
    replaced, count = re.subn(
        r"(?m)^InpResearchRunId=\s*$",
        f"InpResearchRunId={run_id}",
        source,
    )
    if count != 1:
        raise ResearchRunError("expected exactly one empty InpResearchRunId assignment")
    return replaced.rstrip("\r\n") + "\n"


def _build_tester_config(spec: ResearchRunSpec) -> str:
    enabled = lambda value: "1" if value else "0"
    report_config_path = _tester_report_config_path(spec)
    return "\r\n".join(
        (
            "[Common]",
            f"NewsEnable={enabled(spec.tester.news_enabled)}",
            "",
            "[Experts]",
            "AllowLiveTrading=0",
            "AllowDllImport=0",
            "Enabled=1",
            "Account=0",
            "Profile=0",
            "",
            "[Tester]",
            f"Expert={spec.expert_name}",
            f"ExpertParameters={spec.staged_set_path.name}",
            f"Symbol={spec.symbol}",
            f"Period={spec.timeframe}",
            f"Model={spec.tester.model}",
            f"ExecutionMode={spec.costs.execution_delay_ms}",
            f"Optimization={enabled(spec.tester.optimization)}",
            f"FromDate={spec.from_date.replace('-', '.')}",
            # Strategy Tester already treats ToDate as exclusive.  Inclusive
            # endpoint translation is only for MT5 Python rates/ticks APIs.
            f"ToDate={spec.to_date.replace('-', '.')}",
            "ForwardMode=0",
            f"Deposit={spec.tester.deposit:g}",
            f"Currency={spec.tester.currency}",
            f"Leverage={spec.tester.leverage}",
            f"UseLocal={enabled(spec.tester.use_local)}",
            f"UseRemote={enabled(spec.tester.use_remote)}",
            f"UseCloud={enabled(spec.tester.use_cloud)}",
            f"Visual={enabled(spec.tester.visual)}",
            f"Report={report_config_path}",
            "ReplaceReport=0",
            # This only exits the dedicated process launched after two STOPPED
            # probes.  The runner never closes or kills a pre-existing process.
            "ShutdownTerminal=1",
            "",
        )
    )


def _tester_report_config_path(spec: ResearchRunSpec) -> str:
    if spec.report_path.suffix.casefold() not in {".htm", ".html"}:
        raise ResearchRunError("report_path must have an explicit .htm or .html extension")
    installation_root = spec.terminal_path.parent
    try:
        relative = spec.report_path.relative_to(installation_root)
    except ValueError as exc:
        raise ResearchRunError(
            "report_path must be inside the exact terminal installation directory"
        ) from exc
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ResearchRunError("report_path cannot escape the terminal installation")
    return str(relative).replace("/", "\\")


def _build_manifest(
    spec: ResearchRunSpec,
    *,
    approved_range: ResearchRange,
    repository_state: RepositoryState,
    set_values: Mapping[str, str],
    staged_set_text: str,
    log_offset: int,
    log_prefix_sha256: str | None,
    status: str,
    created_at: str,
) -> dict[str, Any]:
    provenance = _load_research_provenance(spec)
    manifest = {
        "schema_version": 2,
        "status": status,
        "run_id": spec.run_id,
        "created_at": created_at,
        "repository": {
            "path": str(spec.repository_root),
            "commit": repository_state.commit,
            "dirty": repository_state.dirty,
            "dirty_files": list(repository_state.dirty_files),
        },
        "inputs": {
            "ea_source": {
                "path": str(spec.ea_source_path),
                "sha256": _sha256_file(spec.ea_source_path),
            },
            "ea_binary": {
                "path": str(spec.ea_binary_path),
                "sha256": _sha256_file(spec.ea_binary_path),
            },
            "set_source": {
                "path": str(spec.set_source_path),
                "sha256": _sha256_file(spec.set_source_path),
            },
            "provenance_evidence": {
                "path": str(provenance.evidence_path),
                "sha256": provenance.evidence_sha256,
                "captured_at": provenance.captured_at,
            },
            "symbol_spec_evidence": {
                "path": str(provenance.symbol_spec_evidence_path),
                "sha256": provenance.symbol_spec_evidence_sha256,
            },
            "bounded_history_evidence": {
                "path": str(provenance.history_evidence_path),
                "sha256": provenance.history_evidence_sha256,
            },
            "bounded_history_manifest": {
                "path": str(provenance.dataset_manifest_path),
                "sha256": provenance.dataset_manifest_sha256,
            },
            "network_isolation_evidence": {
                "path": str(provenance.network_isolation_evidence_path),
                "sha256": provenance.network_isolation_evidence_sha256,
            },
            "broker_cost_source": {
                "path": str(provenance.broker_cost_source_path),
                "sha256": provenance.broker_cost_source_sha256,
            },
            "staged_set": {
                "path": str(spec.staged_set_path),
                "sha256": hashlib.sha256(staged_set_text.encode("utf-8")).hexdigest(),
            },
            "set_values": {
                **dict(sorted(set_values.items())),
                "InpResearchRunId": spec.run_id,
            },
        },
        "profile": {
            "direction": spec.direction_profile,
            "strategy_mode": spec.strategy_mode,
            "execution": spec.execution_profile,
            "strategy": None,
            "strategy_version": None,
            "management_policy_version": provenance.management_policy_version,
        },
        "market": {
            "symbol": spec.symbol,
            "timeframe": spec.timeframe,
            "from_inclusive": approved_range.start.date().isoformat(),
            "to_exclusive": approved_range.end.date().isoformat(),
            "range_semantics": "half-open [from, to)",
            "purpose": approved_range.purpose.value,
            "statistical_classification": (
                approved_range.statistical_classification.value
            ),
            "broker_server": provenance.broker_server,
            "symbol_specification": provenance.symbol_specification,
            "history_declaration": provenance.history_declaration,
            "history_observation": None,
        },
        "terminal": {
            "path": str(spec.terminal_path),
            "data_path": str(spec.terminal_data_path),
            "data_mode": spec.terminal_data_mode.value,
            "data_path_binding": (
                "PORTABLE_INSTALL_DIRECTORY"
                if spec.terminal_data_mode is TerminalDataMode.PORTABLE
                else "STANDARD_ORIGIN_TXT_BOUND_NOT_ISOLATED"
            ),
            "build": spec.terminal_build,
            "sha256": _sha256_file(spec.terminal_path),
            "dedicated_process_required": True,
            "preexisting_process_policy": "REJECT_NEVER_CLOSE",
            "network_policy": "OFFLINE_BOUNDED_DATASET_ONLY",
        },
        "compilation": {
            **provenance.compilation,
            "log_path": str(provenance.compile_log_path),
            "log_sha256": _sha256_file(provenance.compile_log_path),
        },
        "costs": asdict(spec.costs),
        "broker_cost_evidence": provenance.broker_cost_evidence,
        "tester_settings": asdict(spec.tester),
        "artifacts": {
            "manifest": {"path": str(spec.manifest_path)},
            "config": {
                "path": str(spec.config_path),
                "sha256": hashlib.sha256(
                    _build_tester_config(spec).encode("ascii")
                ).hexdigest(),
            },
            "report": {"path": str(spec.report_path), "sha256": None},
            "log": {
                "path": str(spec.log_path),
                "start_offset": log_offset,
                "prefix_sha256": log_prefix_sha256,
                "sha256": None,
            },
            "metrics": {"path": str(spec.metrics_path), "sha256": None},
        },
    }
    if (
        provenance.import_receipt_path is not None
        and provenance.import_receipt_sha256 is not None
    ):
        manifest["inputs"]["custom_symbol_import_receipt"] = {
            "path": str(provenance.import_receipt_path),
            "sha256": provenance.import_receipt_sha256,
        }
    return manifest


def _reject_existing_outputs(spec: ResearchRunSpec) -> None:
    for label, path in (
        ("staged set", spec.staged_set_path),
        ("tester config", spec.config_path),
        ("report", spec.report_path),
        ("metrics", spec.metrics_path),
        ("manifest", spec.manifest_path),
    ):
        if path.exists():
            raise ResearchRunError(
                f"{label} already exists; run_id reuse and stale artifacts are forbidden: {path}"
            )


def _assert_manifest_inputs_unchanged(
    spec: ResearchRunSpec, manifest: Mapping[str, Any]
) -> None:
    expected_paths = [
        (
            "terminal binary",
            spec.terminal_path,
            manifest["terminal"]["sha256"],
        ),
        (
            "EA source",
            spec.ea_source_path,
            manifest["inputs"]["ea_source"]["sha256"],
        ),
        (
            "EA binary",
            spec.ea_binary_path,
            manifest["inputs"]["ea_binary"]["sha256"],
        ),
        (
            "set source",
            spec.set_source_path,
            manifest["inputs"]["set_source"]["sha256"],
        ),
        (
            "provenance evidence",
            spec.provenance_path,
            manifest["inputs"]["provenance_evidence"]["sha256"],
        ),
        *(
            (
                label,
                Path(manifest["inputs"][key]["path"]),
                manifest["inputs"][key]["sha256"],
            )
            for label, key in (
                ("symbol specification evidence", "symbol_spec_evidence"),
                ("bounded history evidence", "bounded_history_evidence"),
                ("bounded history manifest", "bounded_history_manifest"),
                ("network isolation evidence", "network_isolation_evidence"),
                ("broker cost source", "broker_cost_source"),
            )
        ),
        (
            "EA compile log",
            Path(manifest["compilation"]["log_path"]),
            manifest["compilation"]["log_sha256"],
        ),
        (
            "staged set",
            spec.staged_set_path,
            manifest["inputs"]["staged_set"]["sha256"],
        ),
        (
            "tester config",
            spec.config_path,
            manifest["artifacts"]["config"]["sha256"],
        ),
    ]
    import_receipt = manifest["inputs"].get("custom_symbol_import_receipt")
    if import_receipt is not None:
        expected_paths.append(
            (
                "custom-symbol import receipt",
                Path(import_receipt["path"]),
                import_receipt["sha256"],
            )
        )
    for label, path, expected_hash in expected_paths:
        if not path.is_file():
            raise ResearchRunError(f"{label} disappeared before verification: {path}")
        if _sha256_file(path) != expected_hash:
            raise ResearchRunError(f"{label} changed after manifest preparation: {path}")
    # The sealed receipt binds mutable custom-symbol cache files, not only the
    # receipt JSON itself. Re-run the complete provenance verification at every
    # pre/post-launch fence so cache replacement cannot retain a green receipt.
    _load_research_provenance(spec)


def _assert_fresh_nonempty_file(path: Path, label: str, *, started_ns: int) -> None:
    if not path.is_file():
        raise ResearchRunError(f"missing {label}: {path}")
    stat = path.stat()
    if stat.st_size <= 0:
        raise ResearchRunError(f"{label} is empty: {path}")
    if stat.st_mtime_ns < started_ns:
        raise ResearchRunError(f"{label} is stale: {path}")


def _decode_mt5_text(payload: bytes) -> str:
    if not payload:
        return ""
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        return payload.decode("utf-16")
    if len(payload) >= 4 and payload[1::2].count(0) > len(payload) // 8:
        return payload.decode("utf-16-le")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ResearchRunError("artifact text encoding is unsupported")


def _validate_repository_state(state: RepositoryState) -> None:
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", state.commit):
        raise ResearchRunError("repository commit must be a full hexadecimal object id")
    if state.dirty != bool(state.dirty_files):
        raise ResearchRunError("repository dirty flag and dirty file list disagree")


def _canonical_existing_file(path: Path, label: str) -> Path:
    if not path.is_absolute() or not path.is_file():
        raise ResearchRunError(f"{label} must be an explicit existing absolute file")
    return path.resolve(strict=True)


def _canonical_existing_directory(path: Path, label: str) -> Path:
    if not path.is_absolute() or not path.is_dir():
        raise ResearchRunError(f"{label} must be an explicit existing absolute directory")
    return path.resolve(strict=True)


def _bound_evidence_file(
    raw_path: Any,
    raw_sha256: Any,
    label: str,
    *,
    forbidden_paths: tuple[Path, ...] = (),
) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ResearchRunError(f"{label} path must be an explicit canonical string")
    path = _canonical_existing_file(Path(raw_path), label)
    if str(path) != raw_path:
        raise ResearchRunError(f"{label} path must be exact and canonical")
    if path in forbidden_paths:
        raise ResearchRunError(f"{label} must be a distinct immutable artifact")
    if not isinstance(raw_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", raw_sha256):
        raise ResearchRunError(f"{label} SHA-256 must be lowercase hexadecimal")
    if path.stat().st_size <= 0 or _sha256_file(path) != raw_sha256:
        raise ResearchRunError(f"{label} hash does not match its immutable artifact")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_prefix(path: Path, size: int) -> str:
    digest = hashlib.sha256()
    remaining = size
    with path.open("rb") as stream:
        while remaining:
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ResearchRunError("file ended before the recorded prefix length")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any], *, allow_replace: bool) -> None:
    if path.exists() and not allow_replace:
        raise ResearchRunError(f"refusing to replace existing manifest: {path}")
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_name = stream.name
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _strict_utc_timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ResearchRunError(f"{label} must be an explicit UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ResearchRunError(f"{label} is invalid") from exc
    if parsed.tzinfo != timezone.utc:
        raise ResearchRunError(f"{label} must be UTC")
    return value


def _strict_utc_datetime(value: Any, label: str) -> datetime:
    _strict_utc_timestamp(value, label)
    return datetime.fromisoformat(str(value)[:-1] + "+00:00")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ResearchRunError("runner clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")
