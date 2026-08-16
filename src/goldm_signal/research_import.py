from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .research_dataset import RegisteredTickDataset, load_registered_tick_dataset
from .research_policy import ResearchPurpose, StatisticalClassification


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,95}\Z")
_SYMBOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._#-]{1,30}\Z")
_CURRENCY = re.compile(r"[A-Z][A-Z0-9]{2,7}\Z")
_CUSTOM_GROUP = re.compile(r"[A-Za-z][A-Za-z0-9._\\-]{1,62}\Z")
_RELATIVE_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\\-]{1,239}\Z")
_DAY_NAMES = (
    "SUNDAY",
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
)
_CONTROL_HEADER = ("record_type", "key", "value", "arg1", "arg2")
_RAW_RECEIPT_HEADER = ("key", "value")
_PLAN_FIELDS = {
    "schema_version",
    "import_id",
    "created_at",
    "dataset_manifest_path",
    "dataset_manifest_sha256",
    "dataset_path",
    "dataset_sha256",
    "symbol_spec_path",
    "symbol_spec_sha256",
    "terminal_root",
    "staged_control_path",
    "staged_control_sha256",
    "staged_dataset_path",
    "staged_dataset_sha256",
    "raw_receipt_path",
    "network_isolation_evidence_path",
    "network_isolation_evidence_sha256",
    "plan_sha256",
}
_SEALED_RECEIPT_FIELDS = {
    "schema_version",
    "status",
    "sealed_at",
    "import_id",
    "custom_symbol",
    "source_symbol",
    "row_count",
    "first_time_msc",
    "last_time_msc",
    "terminal_root",
    "terminal_binaries",
    "dataset_manifest_path",
    "dataset_manifest_sha256",
    "dataset_path",
    "dataset_sha256",
    "symbol_spec_path",
    "symbol_spec_sha256",
    "import_plan_path",
    "import_plan_sha256",
    "raw_receipt_path",
    "raw_receipt_sha256",
    "network_isolation_evidence_path",
    "network_isolation_evidence_sha256",
    "custom_cache_inventory",
    "custom_cache_inventory_sha256",
    "receipt_sha256",
}


class OfflineImportError(RuntimeError):
    """Raised when offline custom-symbol import evidence is incomplete or unsafe."""


@dataclass(frozen=True, slots=True)
class SessionWindow:
    day: str
    index: int
    from_seconds: int
    to_seconds: int


@dataclass(frozen=True, slots=True)
class CustomSymbolImportSpec:
    path: Path
    sha256: str
    custom_symbol: str
    source_symbol: str
    custom_group: str
    description: str
    digits: int
    chart_mode: str
    point: float
    trade_tick_size: float
    trade_tick_value: float
    trade_tick_value_profit: float
    trade_tick_value_loss: float
    trade_contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    volume_limit: float
    trade_calc_mode: int
    trade_mode: int
    trade_execution_mode: int
    trade_stops_level: int
    trade_freeze_level: int
    spread_float: bool
    spread_points: int
    order_mode: int
    filling_mode: int
    expiration_mode: int
    swap_mode: int
    swap_long: float
    swap_short: float
    currency_base: str
    currency_profit: str
    currency_margin: str
    quote_sessions: tuple[SessionWindow, ...]
    trade_sessions: tuple[SessionWindow, ...]


@dataclass(frozen=True, slots=True)
class OfflineImportBundle:
    import_id: str
    plan_path: Path
    plan_sha256: str
    control_path: Path
    control_sha256: str
    staged_dataset_path: Path
    raw_receipt_path: Path


@dataclass(frozen=True, slots=True)
class VerifiedOfflineImport:
    receipt_path: Path
    receipt_file_sha256: str
    receipt_payload_sha256: str
    import_id: str
    custom_symbol: str
    source_symbol: str
    row_count: int
    first_time_msc: int
    last_time_msc: int
    terminal_root: Path
    dataset_manifest_path: Path
    dataset_manifest_sha256: str
    dataset_path: Path
    dataset_sha256: str
    symbol_spec_path: Path
    symbol_spec_sha256: str
    import_plan_path: Path
    import_plan_sha256: str
    raw_receipt_path: Path
    raw_receipt_sha256: str
    network_isolation_evidence_path: Path
    network_isolation_evidence_sha256: str
    custom_cache_inventory: tuple[Mapping[str, Any], ...]


def load_custom_symbol_import_spec(path: Path) -> CustomSymbolImportSpec:
    canonical = _canonical_file(path, "custom-symbol import specification")
    payload = _read_json_object(canonical, "custom-symbol import specification")
    required = {
        "schema_version",
        "custom_symbol",
        "source_symbol",
        "custom_group",
        "description",
        "digits",
        "chart_mode",
        "point",
        "trade_tick_size",
        "trade_tick_value",
        "trade_tick_value_profit",
        "trade_tick_value_loss",
        "trade_contract_size",
        "volume_min",
        "volume_max",
        "volume_step",
        "volume_limit",
        "trade_calc_mode",
        "trade_mode",
        "trade_execution_mode",
        "trade_stops_level",
        "trade_freeze_level",
        "spread_float",
        "spread_points",
        "order_mode",
        "filling_mode",
        "expiration_mode",
        "swap_mode",
        "swap_long",
        "swap_short",
        "currency_base",
        "currency_profit",
        "currency_margin",
        "quote_sessions",
        "trade_sessions",
        "spec_sha256",
    }
    if set(payload) != required or payload.get("schema_version") != 1:
        raise OfflineImportError(
            "custom-symbol import specification must use schema_version 1 with exact fields"
        )
    supplied_hash = _strict_sha256(payload["spec_sha256"], "symbol spec SHA-256")
    unsigned = dict(payload)
    unsigned.pop("spec_sha256")
    if _canonical_json_sha256(unsigned) != supplied_hash:
        raise OfflineImportError("custom-symbol import specification self-hash mismatch")

    custom_symbol = _strict_symbol(payload["custom_symbol"], "custom_symbol")
    source_symbol = _strict_symbol(payload["source_symbol"], "source_symbol")
    if custom_symbol.casefold() == source_symbol.casefold():
        raise OfflineImportError("custom symbol must be distinct from the broker source symbol")
    custom_group = payload["custom_group"]
    if not isinstance(custom_group, str) or not _CUSTOM_GROUP.fullmatch(custom_group):
        raise OfflineImportError("custom_group is not a canonical custom-symbol group")
    description = _strict_text_token(payload["description"], "description", 3, 127)
    if payload["chart_mode"] not in {"BID", "LAST"}:
        raise OfflineImportError("chart_mode must be BID or LAST")
    digits = _strict_int(payload["digits"], "digits", minimum=0, maximum=12)

    positive_floats = {}
    for field in (
        "point",
        "trade_tick_size",
        "trade_tick_value",
        "trade_tick_value_profit",
        "trade_tick_value_loss",
        "trade_contract_size",
        "volume_min",
        "volume_max",
        "volume_step",
    ):
        positive_floats[field] = _strict_float(payload[field], field, positive=True)
    volume_limit = _strict_float(payload["volume_limit"], "volume_limit", non_negative=True)
    swap_long = _strict_float(payload["swap_long"], "swap_long")
    swap_short = _strict_float(payload["swap_short"], "swap_short")
    if positive_floats["volume_min"] > positive_floats["volume_max"]:
        raise OfflineImportError("volume_min exceeds volume_max")
    if positive_floats["volume_step"] > positive_floats["volume_max"]:
        raise OfflineImportError("volume_step exceeds volume_max")
    expected_point = 10.0 ** (-digits)
    if not _nearly_equal(positive_floats["point"], expected_point):
        raise OfflineImportError("point does not match digits")
    if not _is_integer_multiple(
        positive_floats["trade_tick_size"], positive_floats["point"]
    ):
        raise OfflineImportError("trade_tick_size must be an integer multiple of point")
    for field in ("volume_min", "volume_max"):
        if not _is_integer_multiple(
            positive_floats[field], positive_floats["volume_step"]
        ):
            raise OfflineImportError(f"{field} must align to volume_step")
    if volume_limit and (
        volume_limit < positive_floats["volume_min"]
        or not _is_integer_multiple(volume_limit, positive_floats["volume_step"])
    ):
        raise OfflineImportError("volume_limit must be zero or align to the volume grid")

    integer_fields: dict[str, int] = {}
    integer_limits = {
        "trade_calc_mode": (0, 64),
        "trade_mode": (0, 8),
        "trade_execution_mode": (0, 8),
        "trade_stops_level": (0, 1_000_000),
        "trade_freeze_level": (0, 1_000_000),
        "spread_points": (0, 1_000_000),
        "order_mode": (0, 0xFFFF),
        "filling_mode": (0, 0xFFFF),
        "expiration_mode": (0, 0xFFFF),
        "swap_mode": (0, 32),
    }
    for field, (minimum, maximum) in integer_limits.items():
        integer_fields[field] = _strict_int(
            payload[field], field, minimum=minimum, maximum=maximum
        )
    if not isinstance(payload["spread_float"], bool):
        raise OfflineImportError("spread_float must be boolean")
    currencies = {}
    for field in ("currency_base", "currency_profit", "currency_margin"):
        value = payload[field]
        if not isinstance(value, str) or not _CURRENCY.fullmatch(value):
            raise OfflineImportError(f"{field} must be a canonical currency token")
        currencies[field] = value

    quote_sessions = _parse_sessions(payload["quote_sessions"], "quote_sessions")
    trade_sessions = _parse_sessions(payload["trade_sessions"], "trade_sessions")
    _validate_trade_sessions_within_quotes(quote_sessions, trade_sessions)

    return CustomSymbolImportSpec(
        path=canonical,
        sha256=_sha256(canonical),
        custom_symbol=custom_symbol,
        source_symbol=source_symbol,
        custom_group=custom_group,
        description=description,
        digits=digits,
        chart_mode=payload["chart_mode"],
        point=positive_floats["point"],
        trade_tick_size=positive_floats["trade_tick_size"],
        trade_tick_value=positive_floats["trade_tick_value"],
        trade_tick_value_profit=positive_floats["trade_tick_value_profit"],
        trade_tick_value_loss=positive_floats["trade_tick_value_loss"],
        trade_contract_size=positive_floats["trade_contract_size"],
        volume_min=positive_floats["volume_min"],
        volume_max=positive_floats["volume_max"],
        volume_step=positive_floats["volume_step"],
        volume_limit=volume_limit,
        trade_calc_mode=integer_fields["trade_calc_mode"],
        trade_mode=integer_fields["trade_mode"],
        trade_execution_mode=integer_fields["trade_execution_mode"],
        trade_stops_level=integer_fields["trade_stops_level"],
        trade_freeze_level=integer_fields["trade_freeze_level"],
        spread_float=payload["spread_float"],
        spread_points=integer_fields["spread_points"],
        order_mode=integer_fields["order_mode"],
        filling_mode=integer_fields["filling_mode"],
        expiration_mode=integer_fields["expiration_mode"],
        swap_mode=integer_fields["swap_mode"],
        swap_long=swap_long,
        swap_short=swap_short,
        currency_base=currencies["currency_base"],
        currency_profit=currencies["currency_profit"],
        currency_margin=currencies["currency_margin"],
        quote_sessions=quote_sessions,
        trade_sessions=trade_sessions,
    )


def prepare_offline_import_bundle(
    *,
    dataset_manifest_path: Path,
    symbol_spec_path: Path,
    terminal_root: Path,
    network_isolation_evidence_path: Path,
    import_id: str,
    expected_run_start: datetime,
    expected_end: datetime,
    expected_purpose: ResearchPurpose | str,
    expected_classification: StatisticalClassification | str,
    created_at: datetime | None = None,
) -> OfflineImportBundle:
    """Stage a verified import bundle, but never launch or attach to MT5."""

    if not isinstance(import_id, str) or not _TOKEN.fullmatch(import_id):
        raise OfflineImportError("import_id must be an 8-96 character structured token")
    dataset = load_registered_tick_dataset(
        dataset_manifest_path,
        expected_run_start=expected_run_start,
        expected_end=expected_end,
        expected_purpose=expected_purpose,
        expected_classification=expected_classification,
        require_source_evidence=True,
        include_rows=False,
    )
    spec = load_custom_symbol_import_spec(symbol_spec_path)
    _bind_dataset_and_spec(dataset, spec)
    terminal = assert_clean_portable_research_terminal(terminal_root)
    network_evidence = _canonical_file(
        network_isolation_evidence_path, "network-isolation evidence"
    )
    _validate_network_isolation_evidence(network_evidence, terminal)

    bundle_parent = terminal / "MQL5" / "Files" / "goldm_research"
    bundle_parent.mkdir(parents=True, exist_ok=True)
    _assert_not_reparse(bundle_parent)
    bundle_directory = bundle_parent / import_id
    if bundle_directory.exists():
        raise OfflineImportError("import bundle directory already exists; overwrite is prohibited")
    partial_directory = bundle_parent / (
        f".{import_id}.partial-{secrets.token_hex(8)}"
    )
    partial_directory.mkdir(exist_ok=False)
    staged_dataset = bundle_directory / "ticks.csv"
    raw_receipt_path = bundle_directory / "raw-receipt.csv"
    control_path = bundle_directory / "control.csv"
    plan_path = bundle_directory / "import-plan.json"
    try:
        partial_dataset = partial_directory / staged_dataset.name
        partial_control = partial_directory / control_path.name
        partial_plan = partial_directory / plan_path.name
        shutil.copyfile(dataset.dataset_path, partial_dataset)
        if _sha256(partial_dataset) != dataset.dataset_sha256:
            raise OfflineImportError("staged dataset hash mismatch")
        control_rows = _control_rows(
            import_id=import_id,
            dataset=dataset,
            spec=spec,
            raw_receipt_relative=_relative_to_mql_files(raw_receipt_path, terminal),
        )
        _write_control_csv(partial_control, control_rows)
        control_sha256 = _sha256(partial_control)
        timestamp = _canonical_utc_timestamp(created_at or datetime.now(timezone.utc))
        plan: dict[str, Any] = {
            "schema_version": 1,
            "import_id": import_id,
            "created_at": timestamp,
            "dataset_manifest_path": str(dataset.manifest_path),
            "dataset_manifest_sha256": _sha256(dataset.manifest_path),
            "dataset_path": str(dataset.dataset_path),
            "dataset_sha256": dataset.dataset_sha256,
            "symbol_spec_path": str(spec.path),
            "symbol_spec_sha256": spec.sha256,
            "terminal_root": str(terminal),
            "staged_control_path": str(control_path),
            "staged_control_sha256": control_sha256,
            "staged_dataset_path": str(staged_dataset),
            "staged_dataset_sha256": _sha256(partial_dataset),
            "raw_receipt_path": str(raw_receipt_path),
            "network_isolation_evidence_path": str(network_evidence),
            "network_isolation_evidence_sha256": _sha256(network_evidence),
        }
        plan["plan_sha256"] = _canonical_json_sha256(plan)
        _write_json_exclusive(partial_plan, plan)
        os.replace(partial_directory, bundle_directory)
    except Exception:
        if partial_directory.exists():
            shutil.rmtree(partial_directory)
        raise
    return OfflineImportBundle(
        import_id=import_id,
        plan_path=plan_path,
        plan_sha256=plan["plan_sha256"],
        control_path=control_path,
        control_sha256=control_sha256,
        staged_dataset_path=staged_dataset,
        raw_receipt_path=raw_receipt_path,
    )


def seal_offline_import_receipt(
    *,
    import_plan_path: Path,
    output_path: Path,
    terminal_stopped_probe: Callable[[Path], bool],
    sealed_at: datetime | None = None,
) -> VerifiedOfflineImport:
    """Verify MT5's raw receipt and seal current custom-cache inventory."""

    plan_path, plan = _load_import_plan(import_plan_path)
    terminal = assert_post_import_portable_research_terminal(Path(plan["terminal_root"]))
    if terminal_stopped_probe is None or terminal_stopped_probe(terminal) is not True:
        raise OfflineImportError("terminal must be proven stopped before sealing import evidence")
    dataset = _load_dataset_from_plan(plan)
    spec = load_custom_symbol_import_spec(Path(plan["symbol_spec_path"]))
    _bind_dataset_and_spec(dataset, spec)
    _verify_plan_files(plan)
    raw_receipt_path = _canonical_file(Path(plan["raw_receipt_path"]), "raw import receipt")
    raw = _read_raw_receipt(raw_receipt_path)
    expected_raw = _expected_raw_receipt(plan, dataset)
    if raw != expected_raw:
        missing = sorted(set(expected_raw) - set(raw))
        extra = sorted(set(raw) - set(expected_raw))
        mismatched = sorted(
            key for key in set(raw) & set(expected_raw) if raw[key] != expected_raw[key]
        )
        raise OfflineImportError(
            "raw import receipt mismatch "
            f"(missing={missing}, extra={extra}, mismatched={mismatched})"
        )

    inventory = _custom_cache_inventory(terminal)
    if not inventory:
        raise OfflineImportError("custom-symbol cache inventory is empty")
    terminal_binaries = _terminal_binary_inventory(terminal)
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "status": "VERIFIED_OFFLINE_CUSTOM_TICKS",
        "sealed_at": _canonical_utc_timestamp(sealed_at or datetime.now(timezone.utc)),
        "import_id": plan["import_id"],
        "custom_symbol": dataset.custom_symbol,
        "source_symbol": dataset.source_symbol,
        "row_count": dataset.row_count,
        "first_time_msc": dataset.first_time_msc,
        "last_time_msc": dataset.last_time_msc,
        "terminal_root": str(terminal),
        "terminal_binaries": terminal_binaries,
        "dataset_manifest_path": str(dataset.manifest_path),
        "dataset_manifest_sha256": _sha256(dataset.manifest_path),
        "dataset_path": str(dataset.dataset_path),
        "dataset_sha256": dataset.dataset_sha256,
        "symbol_spec_path": str(spec.path),
        "symbol_spec_sha256": spec.sha256,
        "import_plan_path": str(plan_path),
        "import_plan_sha256": _sha256(plan_path),
        "raw_receipt_path": str(raw_receipt_path),
        "raw_receipt_sha256": _sha256(raw_receipt_path),
        "network_isolation_evidence_path": plan["network_isolation_evidence_path"],
        "network_isolation_evidence_sha256": plan[
            "network_isolation_evidence_sha256"
        ],
        "custom_cache_inventory": inventory,
        "custom_cache_inventory_sha256": _canonical_json_sha256(inventory),
    }
    receipt["receipt_sha256"] = _canonical_json_sha256(receipt)
    canonical_output = _canonical_new_file(output_path, "sealed import receipt")
    _write_json_exclusive(canonical_output, receipt)
    return load_verified_offline_import(canonical_output)


def load_offline_import_network_binding(
    import_plan_path: Path,
) -> tuple[Path, Path]:
    """Load the self-hashed plan and return its exact terminal/network binding."""

    _, plan = _load_import_plan(import_plan_path)
    _verify_plan_files(plan)
    terminal = _canonical_directory(Path(plan["terminal_root"]), "plan terminal root")
    network_evidence = _canonical_file(
        Path(plan["network_isolation_evidence_path"]),
        "plan network-isolation evidence",
    )
    _validate_network_isolation_evidence(network_evidence, terminal)
    return terminal, network_evidence


def load_verified_offline_import(path: Path) -> VerifiedOfflineImport:
    canonical = _canonical_file(path, "sealed import receipt")
    payload = _read_json_object(canonical, "sealed import receipt")
    if set(payload) != _SEALED_RECEIPT_FIELDS or payload.get("schema_version") != 1:
        raise OfflineImportError("sealed import receipt must use schema_version 1 with exact fields")
    supplied_hash = _strict_sha256(payload["receipt_sha256"], "receipt SHA-256")
    unsigned = dict(payload)
    unsigned.pop("receipt_sha256")
    if _canonical_json_sha256(unsigned) != supplied_hash:
        raise OfflineImportError("sealed import receipt self-hash mismatch")
    if payload["status"] != "VERIFIED_OFFLINE_CUSTOM_TICKS":
        raise OfflineImportError("sealed import receipt status is not verified")
    _canonical_utc_timestamp(_parse_utc(payload["sealed_at"], "sealed_at"))
    import_id = payload["import_id"]
    if not isinstance(import_id, str) or not _TOKEN.fullmatch(import_id):
        raise OfflineImportError("sealed import receipt import_id is invalid")
    custom_symbol = _strict_symbol(payload["custom_symbol"], "custom_symbol")
    source_symbol = _strict_symbol(payload["source_symbol"], "source_symbol")
    if custom_symbol.casefold() == source_symbol.casefold():
        raise OfflineImportError("sealed receipt aliases the broker source symbol")
    row_count = _strict_int(payload["row_count"], "row_count", minimum=1)
    first = _strict_int(payload["first_time_msc"], "first_time_msc", minimum=0)
    last = _strict_int(payload["last_time_msc"], "last_time_msc", minimum=first)
    terminal = assert_post_import_portable_research_terminal(
        Path(payload["terminal_root"])
    )
    if payload["terminal_binaries"] != _terminal_binary_inventory(terminal):
        raise OfflineImportError("terminal binary inventory changed after receipt sealing")

    bound_files: dict[str, tuple[Path, str]] = {}
    for prefix in (
        "dataset_manifest",
        "dataset",
        "symbol_spec",
        "import_plan",
        "raw_receipt",
        "network_isolation_evidence",
    ):
        file_path = _canonical_file(Path(payload[f"{prefix}_path"]), prefix.replace("_", " "))
        file_hash = _strict_sha256(payload[f"{prefix}_sha256"], f"{prefix} SHA-256")
        if _sha256(file_path) != file_hash:
            raise OfflineImportError(f"{prefix} changed after receipt sealing")
        bound_files[prefix] = (file_path, file_hash)

    inventory = payload["custom_cache_inventory"]
    if not isinstance(inventory, list) or not inventory:
        raise OfflineImportError("sealed receipt custom cache inventory is invalid")
    if _canonical_json_sha256(inventory) != _strict_sha256(
        payload["custom_cache_inventory_sha256"], "custom cache inventory SHA-256"
    ):
        raise OfflineImportError("custom cache inventory self-hash mismatch")
    observed_inventory = _custom_cache_inventory(terminal)
    if inventory != observed_inventory:
        raise OfflineImportError("custom-symbol cache changed after receipt sealing")

    plan_path, plan = _load_import_plan(bound_files["import_plan"][0])
    plan_bindings = {
        "dataset_manifest": (
            plan["dataset_manifest_path"],
            plan["dataset_manifest_sha256"],
        ),
        "dataset": (plan["dataset_path"], plan["dataset_sha256"]),
        "symbol_spec": (plan["symbol_spec_path"], plan["symbol_spec_sha256"]),
        "raw_receipt": (plan["raw_receipt_path"], bound_files["raw_receipt"][1]),
        "network_isolation_evidence": (
            plan["network_isolation_evidence_path"],
            plan["network_isolation_evidence_sha256"],
        ),
    }
    if (
        plan["import_id"] != import_id
        or _canonical_directory(Path(plan["terminal_root"]), "plan terminal root")
        != terminal
        or any(
            str(bound_files[key][0]) != path_value
            or bound_files[key][1] != hash_value
            for key, (path_value, hash_value) in plan_bindings.items()
        )
    ):
        raise OfflineImportError("sealed receipt and import plan bindings differ")
    dataset = _load_dataset_from_plan(plan)
    if (
        dataset.custom_symbol != custom_symbol
        or dataset.source_symbol != source_symbol
        or dataset.row_count != row_count
        or dataset.first_time_msc != first
        or dataset.last_time_msc != last
        or dataset.manifest_path != bound_files["dataset_manifest"][0]
        or dataset.dataset_path != bound_files["dataset"][0]
    ):
        raise OfflineImportError("sealed receipt dataset identity mismatch")
    spec = load_custom_symbol_import_spec(bound_files["symbol_spec"][0])
    _bind_dataset_and_spec(dataset, spec)
    _verify_plan_files(plan)
    raw = _read_raw_receipt(bound_files["raw_receipt"][0])
    if raw != _expected_raw_receipt(plan, dataset):
        raise OfflineImportError("raw receipt no longer proves the sealed import")
    _validate_network_isolation_evidence(bound_files["network_isolation_evidence"][0], terminal)

    return VerifiedOfflineImport(
        receipt_path=canonical,
        receipt_file_sha256=_sha256(canonical),
        receipt_payload_sha256=supplied_hash,
        import_id=import_id,
        custom_symbol=custom_symbol,
        source_symbol=source_symbol,
        row_count=row_count,
        first_time_msc=first,
        last_time_msc=last,
        terminal_root=terminal,
        dataset_manifest_path=bound_files["dataset_manifest"][0],
        dataset_manifest_sha256=bound_files["dataset_manifest"][1],
        dataset_path=bound_files["dataset"][0],
        dataset_sha256=bound_files["dataset"][1],
        symbol_spec_path=bound_files["symbol_spec"][0],
        symbol_spec_sha256=bound_files["symbol_spec"][1],
        import_plan_path=plan_path,
        import_plan_sha256=bound_files["import_plan"][1],
        raw_receipt_path=bound_files["raw_receipt"][0],
        raw_receipt_sha256=bound_files["raw_receipt"][1],
        network_isolation_evidence_path=bound_files["network_isolation_evidence"][0],
        network_isolation_evidence_sha256=bound_files["network_isolation_evidence"][1],
        custom_cache_inventory=tuple(inventory),
    )


def assert_clean_portable_research_terminal(path: Path) -> Path:
    terminal = _canonical_directory(path, "portable research terminal")
    _assert_no_reparse_tree(terminal)
    _terminal_binary_inventory(terminal)
    forbidden = (
        terminal / "origin.txt",
        terminal / "Config" / "accounts.dat",
        terminal / "Config" / "servers.dat",
    )
    for candidate in forbidden:
        if candidate.exists():
            raise OfflineImportError(f"portable clone contains forbidden state: {candidate}")
    for directory in (
        terminal / "MQL5" / "Profiles" / "Tester",
        terminal / "MQL5" / "Logs",
        terminal / "logs",
        terminal / "reports",
        terminal / "Tester" / "cache",
        terminal / "Tester" / "logs",
    ):
        if directory.exists() and any(directory.rglob("*")):
            raise OfflineImportError(f"portable clone contains forbidden generated state: {directory}")
    bases = terminal / "bases"
    if bases.exists():
        entries = [entry for entry in bases.iterdir() if entry.name.casefold() != "custom"]
        if entries:
            raise OfflineImportError("portable clone contains broker/server bases")
        custom = bases / "Custom"
        if custom.exists() and any(custom.rglob("*")):
            raise OfflineImportError("portable clone custom-symbol cache is not empty")
    return terminal


def assert_post_import_portable_research_terminal(path: Path) -> Path:
    terminal = _canonical_directory(path, "portable research terminal")
    _assert_no_reparse_tree(terminal)
    _terminal_binary_inventory(terminal)
    for candidate in (
        terminal / "origin.txt",
        terminal / "Config" / "accounts.dat",
        terminal / "Config" / "servers.dat",
    ):
        if candidate.exists():
            raise OfflineImportError(f"portable clone contains forbidden account/server state: {candidate}")
    bases = terminal / "bases"
    if not bases.is_dir():
        raise OfflineImportError("portable clone has no custom-symbol store")
    entries = [entry for entry in bases.iterdir() if entry.name.casefold() != "custom"]
    if entries:
        raise OfflineImportError("portable clone contains broker/server bases after import")
    return terminal


def _control_rows(
    *,
    import_id: str,
    dataset: RegisteredTickDataset,
    spec: CustomSymbolImportSpec,
    raw_receipt_relative: str,
) -> tuple[tuple[str, str, str, str, str], ...]:
    scalar: list[tuple[str, str, str, str, str]] = []
    values = {
        "format": "MT5_CUSTOM_TICK_IMPORT_CONTROL_V1",
        "import_id": import_id,
        "custom_symbol": spec.custom_symbol,
        "source_symbol": spec.source_symbol,
        "custom_group": spec.custom_group,
        "description": spec.description,
        "dataset_file": "goldm_research\\" + import_id + "\\ticks.csv",
        "raw_receipt_file": raw_receipt_relative,
        "dataset_sha256": dataset.dataset_sha256,
        "dataset_manifest_sha256": _sha256(dataset.manifest_path),
        "symbol_spec_sha256": spec.sha256,
        "row_count": str(dataset.row_count),
        "first_time_msc": str(dataset.first_time_msc),
        "last_time_msc": str(dataset.last_time_msc),
        "warmup_from_msc": str(int(dataset.warmup_start.timestamp() * 1000)),
        "run_from_msc": str(int(dataset.run_start.timestamp() * 1000)),
        "to_exclusive_msc": str(int(dataset.end.timestamp() * 1000)),
        "digits": str(spec.digits),
        "chart_mode": spec.chart_mode,
        "point": _canonical_number(spec.point),
        "trade_tick_size": _canonical_number(spec.trade_tick_size),
        "trade_tick_value": _canonical_number(spec.trade_tick_value),
        "trade_tick_value_profit": _canonical_number(spec.trade_tick_value_profit),
        "trade_tick_value_loss": _canonical_number(spec.trade_tick_value_loss),
        "trade_contract_size": _canonical_number(spec.trade_contract_size),
        "volume_min": _canonical_number(spec.volume_min),
        "volume_max": _canonical_number(spec.volume_max),
        "volume_step": _canonical_number(spec.volume_step),
        "volume_limit": _canonical_number(spec.volume_limit),
        "trade_calc_mode": str(spec.trade_calc_mode),
        "trade_mode": str(spec.trade_mode),
        "trade_execution_mode": str(spec.trade_execution_mode),
        "trade_stops_level": str(spec.trade_stops_level),
        "trade_freeze_level": str(spec.trade_freeze_level),
        "spread_float": "1" if spec.spread_float else "0",
        "spread_points": str(spec.spread_points),
        "order_mode": str(spec.order_mode),
        "filling_mode": str(spec.filling_mode),
        "expiration_mode": str(spec.expiration_mode),
        "swap_mode": str(spec.swap_mode),
        "swap_long": _canonical_number(spec.swap_long),
        "swap_short": _canonical_number(spec.swap_short),
        "currency_base": spec.currency_base,
        "currency_profit": spec.currency_profit,
        "currency_margin": spec.currency_margin,
        "formula": "",
    }
    for key, value in values.items():
        scalar.append(("CONTROL", key, value, "", ""))
    for session in spec.quote_sessions:
        scalar.append(
            (
                "QUOTE_SESSION",
                session.day,
                str(session.index),
                str(session.from_seconds),
                str(session.to_seconds),
            )
        )
    for session in spec.trade_sessions:
        scalar.append(
            (
                "TRADE_SESSION",
                session.day,
                str(session.index),
                str(session.from_seconds),
                str(session.to_seconds),
            )
        )
    return tuple(scalar)


def _write_control_csv(
    path: Path, rows: Iterable[tuple[str, str, str, str, str]]
) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator="\n")
        writer.writerow(_CONTROL_HEADER)
        writer.writerows(rows)


def _load_import_plan(path: Path) -> tuple[Path, dict[str, Any]]:
    canonical = _canonical_file(path, "offline import plan")
    payload = _read_json_object(canonical, "offline import plan")
    if set(payload) != _PLAN_FIELDS or payload.get("schema_version") != 1:
        raise OfflineImportError("offline import plan must use schema_version 1 with exact fields")
    supplied_hash = _strict_sha256(payload["plan_sha256"], "import plan SHA-256")
    unsigned = dict(payload)
    unsigned.pop("plan_sha256")
    if _canonical_json_sha256(unsigned) != supplied_hash:
        raise OfflineImportError("offline import plan self-hash mismatch")
    if not isinstance(payload["import_id"], str) or not _TOKEN.fullmatch(payload["import_id"]):
        raise OfflineImportError("offline import plan import_id is invalid")
    _parse_utc(payload["created_at"], "plan created_at")
    return canonical, payload


def _load_dataset_from_plan(plan: Mapping[str, Any]) -> RegisteredTickDataset:
    manifest = _canonical_file(Path(plan["dataset_manifest_path"]), "dataset manifest")
    payload = _read_json_object(manifest, "dataset manifest")
    try:
        purpose = ResearchPurpose(payload["purpose"])
        classification = StatisticalClassification(payload["statistical_classification"])
        run_start = datetime.strptime(payload["run_from_inclusive"], "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        end = datetime.strptime(payload["to_exclusive"], "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OfflineImportError("dataset manifest identity cannot be parsed") from exc
    return load_registered_tick_dataset(
        manifest,
        expected_run_start=run_start,
        expected_end=end,
        expected_purpose=purpose,
        expected_classification=classification,
        require_source_evidence=True,
        include_rows=False,
    )


def _verify_plan_files(plan: Mapping[str, Any]) -> None:
    pairs = (
        ("dataset_manifest_path", "dataset_manifest_sha256"),
        ("dataset_path", "dataset_sha256"),
        ("symbol_spec_path", "symbol_spec_sha256"),
        ("staged_control_path", "staged_control_sha256"),
        ("staged_dataset_path", "staged_dataset_sha256"),
        ("network_isolation_evidence_path", "network_isolation_evidence_sha256"),
    )
    for path_field, hash_field in pairs:
        candidate = _canonical_file(Path(plan[path_field]), path_field.replace("_", " "))
        expected = _strict_sha256(plan[hash_field], hash_field.replace("_", " "))
        if _sha256(candidate) != expected:
            raise OfflineImportError(f"{path_field} changed after import planning")
    if plan["dataset_sha256"] != plan["staged_dataset_sha256"]:
        raise OfflineImportError("source and staged dataset hashes differ")


def _read_raw_receipt(path: Path) -> dict[str, str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, delimiter=";")
            header = next(reader, None)
            if tuple(header or ()) != _RAW_RECEIPT_HEADER:
                raise OfflineImportError("raw import receipt header is invalid")
            result: dict[str, str] = {}
            for line_number, row in enumerate(reader, start=2):
                if len(row) != 2 or not row[0] or row[0] in result:
                    raise OfflineImportError(
                        f"raw import receipt row {line_number} is malformed or duplicated"
                    )
                result[row[0]] = row[1]
    except UnicodeError as exc:
        raise OfflineImportError("raw import receipt is not valid UTF-8") from exc
    return result


def _expected_raw_receipt(
    plan: Mapping[str, Any], dataset: RegisteredTickDataset
) -> dict[str, str]:
    return {
        "format": "MT5_CUSTOM_TICK_IMPORT_RECEIPT_V1",
        "status": "VERIFIED_CACHE_MATCH",
        "import_id": str(plan["import_id"]),
        "custom_symbol": dataset.custom_symbol,
        "source_symbol": dataset.source_symbol,
        "dataset_sha256": dataset.dataset_sha256,
        "dataset_manifest_sha256": str(plan["dataset_manifest_sha256"]),
        "symbol_spec_sha256": str(plan["symbol_spec_sha256"]),
        "control_sha256": str(plan["staged_control_sha256"]),
        "row_count": str(dataset.row_count),
        "first_time_msc": str(dataset.first_time_msc),
        "last_time_msc": str(dataset.last_time_msc),
        "formula": "EMPTY",
        "origin": "NONE",
        "portable": "TRUE",
        "connected": "FALSE",
    }


def _parse_sessions(value: Any, label: str) -> tuple[SessionWindow, ...]:
    if not isinstance(value, list) or not value:
        raise OfflineImportError(f"{label} must be a non-empty list")
    result: list[SessionWindow] = []
    seen: set[tuple[str, int]] = set()
    expected_next: dict[str, int] = {}
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) != {
            "day",
            "index",
            "from_seconds",
            "to_seconds",
        }:
            raise OfflineImportError(f"{label}[{index}] fields are invalid")
        day = raw["day"]
        if day not in _DAY_NAMES:
            raise OfflineImportError(f"{label}[{index}].day is invalid")
        session_index = _strict_int(raw["index"], f"{label}[{index}].index", minimum=0, maximum=31)
        start = _strict_int(
            raw["from_seconds"], f"{label}[{index}].from_seconds", minimum=0, maximum=172799
        )
        end = _strict_int(
            raw["to_seconds"], f"{label}[{index}].to_seconds", minimum=1, maximum=172800
        )
        if start >= end:
            raise OfflineImportError(f"{label}[{index}] is empty or reversed")
        key = (day, session_index)
        if key in seen or session_index != expected_next.get(day, 0):
            raise OfflineImportError(f"{label} indices must be unique and sequential per day")
        seen.add(key)
        expected_next[day] = session_index + 1
        prior = next(
            (
                item
                for item in reversed(result)
                if item.day == day and item.index == session_index - 1
            ),
            None,
        )
        if prior is not None and start < prior.to_seconds:
            raise OfflineImportError(f"{label} sessions must not overlap")
        result.append(SessionWindow(day, session_index, start, end))
    order = {name: number for number, name in enumerate(_DAY_NAMES)}
    if result != sorted(result, key=lambda item: (order[item.day], item.index)):
        raise OfflineImportError(f"{label} must be ordered by day and index")
    return tuple(result)


def _validate_trade_sessions_within_quotes(
    quote_sessions: tuple[SessionWindow, ...],
    trade_sessions: tuple[SessionWindow, ...],
) -> None:
    quotes_by_day: dict[str, list[SessionWindow]] = {}
    for session in quote_sessions:
        quotes_by_day.setdefault(session.day, []).append(session)
    for trade in trade_sessions:
        if not any(
            quote.from_seconds <= trade.from_seconds
            and trade.to_seconds <= quote.to_seconds
            for quote in quotes_by_day.get(trade.day, ())
        ):
            raise OfflineImportError("every trade session must be contained in a quote session")


def _bind_dataset_and_spec(
    dataset: RegisteredTickDataset, spec: CustomSymbolImportSpec
) -> None:
    if dataset.custom_symbol != spec.custom_symbol or dataset.source_symbol != spec.source_symbol:
        raise OfflineImportError("dataset and custom-symbol specification identities differ")


def _validate_network_isolation_evidence(path: Path, terminal: Path) -> None:
    payload = _read_json_object(path, "network-isolation evidence")
    if payload.get("schema_version") == 2:
        _validate_network_isolation_evidence_v2(path, payload, terminal)
        return
    required = {
        "schema_version",
        "status",
        "terminal_root",
        "terminal_sha256",
        "metatester_sha256",
        "enforcement",
        "verified_at",
        "evidence_sha256",
    }
    if set(payload) != required or payload.get("schema_version") != 1:
        raise OfflineImportError("network-isolation evidence schema is invalid")
    supplied = _strict_sha256(payload["evidence_sha256"], "network evidence SHA-256")
    unsigned = dict(payload)
    unsigned.pop("evidence_sha256")
    if _canonical_json_sha256(unsigned) != supplied:
        raise OfflineImportError("network-isolation evidence self-hash mismatch")
    if payload["status"] != "ENFORCED_OFFLINE" or payload["enforcement"] not in {
        "WINDOWS_FIREWALL_BLOCK_OUTBOUND",
        "PHYSICALLY_OFFLINE_HOST",
    }:
        raise OfflineImportError("network-isolation evidence is not enforceable")
    if _canonical_directory(Path(payload["terminal_root"]), "network terminal root") != terminal:
        raise OfflineImportError("network-isolation evidence terminal root mismatch")
    binaries = _terminal_binary_inventory(terminal)
    expected = {item["name"]: item["sha256"] for item in binaries}
    if payload["terminal_sha256"] != expected["terminal64.exe"]:
        raise OfflineImportError("network evidence terminal hash mismatch")
    if payload["metatester_sha256"] != expected["metatester64.exe"]:
        raise OfflineImportError("network evidence metatester hash mismatch")
    _parse_utc(payload["verified_at"], "network verified_at")


def _validate_network_isolation_evidence_v2(
    path: Path, payload: Mapping[str, Any], terminal: Path
) -> None:
    required = {
        "schema_version",
        "status",
        "enforcement",
        "verified_at",
        "clone_manifest_path",
        "clone_manifest_sha256",
        "clone_manifest_payload_sha256",
        "terminal_root",
        "binary_sha256",
        "rules",
        "evidence_sha256",
    }
    if set(payload) != required:
        raise OfflineImportError("network-isolation evidence schema 2 is invalid")
    supplied = _strict_sha256(payload["evidence_sha256"], "network evidence SHA-256")
    unsigned = dict(payload)
    unsigned.pop("evidence_sha256")
    if _canonical_json_sha256(unsigned) != supplied:
        raise OfflineImportError("network-isolation evidence self-hash mismatch")
    if (
        payload["status"] != "ENFORCED_OFFLINE"
        or payload["enforcement"]
        != "WINDOWS_FIREWALL_BLOCK_OUTBOUND_EXACT_PROGRAMS"
    ):
        raise OfflineImportError("network-isolation evidence is not enforceable")
    _parse_utc(payload["verified_at"], "network verified_at")
    if _canonical_directory(Path(payload["terminal_root"]), "network terminal root") != terminal:
        raise OfflineImportError("network-isolation evidence terminal root mismatch")

    clone_manifest = _canonical_file(
        Path(payload["clone_manifest_path"]), "network clone manifest"
    )
    if clone_manifest.parent != terminal:
        raise OfflineImportError("network clone manifest is outside terminal root")
    if _sha256(clone_manifest) != _strict_sha256(
        payload["clone_manifest_sha256"], "clone manifest SHA-256"
    ):
        raise OfflineImportError("network clone manifest hash mismatch")
    clone_payload = _read_json_object(clone_manifest, "portable clone manifest")
    if clone_payload.get("manifest_sha256") != _strict_sha256(
        payload["clone_manifest_payload_sha256"],
        "clone manifest payload SHA-256",
    ):
        raise OfflineImportError("network clone manifest payload binding mismatch")

    binaries = _terminal_binary_inventory(terminal)
    expected_hashes = {item["name"]: item["sha256"] for item in binaries}
    if payload["binary_sha256"] != expected_hashes:
        raise OfflineImportError("network evidence terminal binary hashes mismatch")
    rules = payload["rules"]
    if not isinstance(rules, list) or len(rules) != len(expected_hashes):
        raise OfflineImportError("network evidence firewall-rule inventory is incomplete")
    prefix = payload["clone_manifest_payload_sha256"][:16]
    rule_fields = {
        "name",
        "display_name",
        "enabled",
        "direction",
        "action",
        "profile",
        "program_path",
        "protocol",
        "local_addresses",
        "remote_addresses",
        "local_ports",
        "remote_ports",
        "service",
        "interface_type",
        "policy_store_source_type",
    }
    for rule, binary_name in zip(
        rules,
        ("terminal64.exe", "metaeditor64.exe", "metatester64.exe"),
        strict=True,
    ):
        expected_program = _canonical_file(terminal / binary_name, binary_name)
        expected_name = f"GoldMResearchOffline-{prefix}-{Path(binary_name).stem}"
        if (
            not isinstance(rule, dict)
            or set(rule) != rule_fields
            or rule["name"] != expected_name
            or rule["display_name"]
            != f"GoldM Research Offline - {expected_program.name}"
            or rule["enabled"] is not True
            or rule["direction"] != "Outbound"
            or rule["action"] != "Block"
            or rule["profile"] != "Any"
            or _canonical_file(Path(rule["program_path"]), "firewall program")
            != expected_program
            or rule["protocol"] != "Any"
            or rule["local_addresses"] != ["Any"]
            or rule["remote_addresses"] != ["Any"]
            or rule["local_ports"] != ["Any"]
            or rule["remote_ports"] != ["Any"]
            or rule["service"] != "Any"
            or rule["interface_type"] != "Any"
            or rule["policy_store_source_type"] != "Local"
        ):
            raise OfflineImportError(
                f"network evidence firewall rule is not exact: {expected_name}"
            )


def _custom_cache_inventory(terminal: Path) -> list[dict[str, Any]]:
    custom = terminal / "bases" / "Custom"
    if not custom.is_dir():
        return []
    inventory = []
    for path in sorted((item for item in custom.rglob("*") if item.is_file()), key=lambda p: p.as_posix().casefold()):
        _assert_not_reparse(path)
        relative = path.relative_to(terminal).as_posix()
        inventory.append(
            {"relative_path": relative, "size": path.stat().st_size, "sha256": _sha256(path)}
        )
    return inventory


def _terminal_binary_inventory(terminal: Path) -> list[dict[str, Any]]:
    result = []
    for name in ("terminal64.exe", "metaeditor64.exe", "metatester64.exe"):
        path = _canonical_file(terminal / name, name)
        if path.parent != terminal:
            raise OfflineImportError(f"{name} escapes the portable terminal root")
        result.append({"name": name, "size": path.stat().st_size, "sha256": _sha256(path)})
    return result


def _assert_no_reparse_tree(root: Path) -> None:
    _assert_not_reparse(root)
    for path in root.rglob("*"):
        _assert_not_reparse(path)


def _assert_not_reparse(path: Path) -> None:
    if path.is_symlink():
        raise OfflineImportError(f"reparse/symlink path is prohibited: {path}")
    try:
        attributes = path.lstat().st_file_attributes
    except AttributeError:
        return
    if attributes & 0x400:
        raise OfflineImportError(f"reparse/symlink path is prohibited: {path}")


def _relative_to_mql_files(path: Path, terminal: Path) -> str:
    files_root = terminal / "MQL5" / "Files"
    try:
        relative = path.relative_to(files_root)
    except ValueError as exc:
        raise OfflineImportError("import file escapes MQL5/Files sandbox") from exc
    value = str(relative).replace("/", "\\")
    if ".." in relative.parts or not _RELATIVE_FILE.fullmatch(value):
        raise OfflineImportError("import file name is not a safe relative MQL5 path")
    return value


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OfflineImportError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise OfflineImportError(f"{label} must be a JSON object")
    return payload


def _canonical_file(path: Path, label: str) -> Path:
    try:
        canonical = path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise OfflineImportError(f"{label} does not exist: {path}") from exc
    if not canonical.is_file():
        raise OfflineImportError(f"{label} is not a regular file: {canonical}")
    _assert_not_reparse(canonical)
    return canonical


def _canonical_directory(path: Path, label: str) -> Path:
    try:
        canonical = path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise OfflineImportError(f"{label} does not exist: {path}") from exc
    if not canonical.is_dir():
        raise OfflineImportError(f"{label} is not a directory: {canonical}")
    _assert_not_reparse(canonical)
    return canonical


def _canonical_new_file(path: Path, label: str) -> Path:
    parent = _canonical_directory(path.parent, f"{label} parent")
    candidate = parent / path.name
    if candidate.exists():
        raise OfflineImportError(f"{label} already exists; overwrite is prohibited")
    return candidate


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _strict_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise OfflineImportError(f"{label} must be a lowercase SHA-256")
    return value


def _strict_symbol(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SYMBOL.fullmatch(value):
        raise OfflineImportError(f"{label} is not a canonical custom-symbol token")
    return value


def _strict_text_token(value: Any, label: str, minimum: int, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not (minimum <= len(value) <= maximum)
        or any(character in value for character in "\r\n;,=\x00")
    ):
        raise OfflineImportError(f"{label} contains unsupported characters")
    return value


def _strict_int(value: Any, label: str, *, minimum: int, maximum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise OfflineImportError(f"{label} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise OfflineImportError(f"{label} must be <= {maximum}")
    return value


def _strict_float(
    value: Any,
    label: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
        raise OfflineImportError(f"{label} must be finite")
    result = float(value)
    if positive and result <= 0.0:
        raise OfflineImportError(f"{label} must be positive")
    if non_negative and result < 0.0:
        raise OfflineImportError(f"{label} must be non-negative")
    return result


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise OfflineImportError(f"{label} must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise OfflineImportError(f"{label} is invalid") from exc
    if parsed.tzinfo != timezone.utc:
        raise OfflineImportError(f"{label} must be UTC")
    return parsed


def _canonical_utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise OfflineImportError("timestamp must be timezone-aware UTC")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_number(value: float) -> str:
    result = format(value, ".17g")
    return "0" if result == "-0" else result


def _nearly_equal(left: float, right: float) -> bool:
    scale = max(1.0, abs(left), abs(right))
    return abs(left - right) <= 1.0e-12 * scale


def _is_integer_multiple(value: float, step: float) -> bool:
    ratio = value / step
    return _nearly_equal(ratio, round(ratio))


def _canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
