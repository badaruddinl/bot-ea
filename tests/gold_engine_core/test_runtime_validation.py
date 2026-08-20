from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from gold_engine_core import (
    RuntimeValidationBinding,
    RuntimeValidationError,
    load_named_profile,
    load_runtime_validation_manifest,
    validate_runtime_binding,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPOSITORY_ROOT / "config" / "validation_profiles" / "GOLDM_REAL_READ_ONLY.json"


def manifest():
    return load_runtime_validation_manifest(MANIFEST_PATH)


def binding() -> RuntimeValidationBinding:
    value = manifest()
    return RuntimeValidationBinding(
        value.validation_profile_id,
        "C:/Program Files/MetaTrader 5/terminal64.exe",
        391425346,
        "XMGlobal-MT5 14",
        "real",
        value.symbol,
        "read_only",
    )


def test_goldm_real_binding_is_read_only_and_canonical() -> None:
    value = manifest()
    production = load_named_profile(REPOSITORY_ROOT, "GOLDM")

    validate_runtime_binding(value, production, binding())

    assert value.validation_profile_id == "GOLDM_REAL_READ_ONLY"
    assert value.required_trade_mode == "real"
    assert value.access_mode == "read_only"
    assert value.production_real_authority is False
    assert value.audience == "admin_only"
    assert value.derived_profile_fingerprint == production.fingerprint


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"trade_mode": "demo"}, "trade mode"),
        ({"access_mode": "demo_execution"}, "access mode"),
        ({"symbol": "GOLD.i#"}, "symbol"),
        ({"validation_profile_id": "GOLDM_PRODUCTION"}, "profile ID"),
    ],
)
def test_goldm_read_only_binding_mutations_fail_closed(
    mutation: dict[str, object],
    message: str,
) -> None:
    value = binding()
    with pytest.raises(RuntimeValidationError, match=message):
        validate_runtime_binding(
            manifest(),
            load_named_profile(REPOSITORY_ROOT, "GOLDM"),
            replace(value, **mutation),
        )


def test_read_only_manifest_cannot_gain_real_authority_or_subscriber_audience() -> None:
    value = manifest()
    production = load_named_profile(REPOSITORY_ROOT, "GOLDM")

    with pytest.raises(RuntimeValidationError, match="REAL authority"):
        replace(value, production_real_authority=True)
    with pytest.raises(RuntimeValidationError, match="admin-only"):
        validate_runtime_binding(
            replace(value, audience="subscriber"),
            production,
            binding(),
        )


def test_read_only_probe_source_contains_no_order_mutation_api() -> None:
    source = (REPOSITORY_ROOT / "scripts" / "run_g10_profile_probe.py").read_text(encoding="utf-8")
    forbidden = (
        "order_send",
        "order_check",
        "TRADE_ACTION_",
        "position_close",
        "position_modify",
        "PositionOpen",
    )
    assert not [name for name in forbidden if name in source]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"schema_version": 2}, "schema_version"),
        ({"validation_profile_id": ""}, "validation_profile_id"),
        ({"derived_profile_fingerprint": "short"}, "fingerprint"),
        ({"required_trade_mode": "contest"}, "trade mode"),
        ({"access_mode": "write"}, "access mode"),
        (
            {"required_trade_mode": "demo", "access_mode": "read_only"},
            "read-only broker",
        ),
        (
            {"required_trade_mode": "real", "access_mode": "demo_execution"},
            "DEMO execution",
        ),
        ({"terminal_path_env": "GOLDM_REAL_MT5_LOGIN"}, "environment names"),
        (
            {"state_namespace": "runtime_data/validation/goldm_read_only/evidence.jsonl"},
            "namespaces",
        ),
    ],
)
def test_manifest_boundary_mutations_fail_closed(
    mutation: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(RuntimeValidationError, match=message):
        replace(manifest(), **mutation)


def test_manifest_loader_rejects_invalid_json_and_checksum(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(RuntimeValidationError, match="cannot read"):
        load_runtime_validation_manifest(invalid)

    value = manifest()
    copied = tmp_path / "GOLDM_REAL_READ_ONLY.json"
    copied.write_text(json.dumps(value.to_payload()), encoding="utf-8")
    copied.with_suffix(".sha256").write_text(
        f"{'0' * 64}  {copied.name}\n",
        encoding="ascii",
    )
    with pytest.raises(RuntimeValidationError, match="checksum"):
        load_runtime_validation_manifest(copied)


def test_runtime_binding_and_derivation_boundaries_fail_closed() -> None:
    value = manifest()
    production = load_named_profile(REPOSITORY_ROOT, "GOLDM")

    with pytest.raises(RuntimeValidationError, match="incomplete"):
        replace(binding(), terminal_path="")
    with pytest.raises(RuntimeValidationError, match="derive"):
        validate_runtime_binding(
            replace(value, derived_profile_fingerprint="0" * 64),
            production,
            binding(),
        )

    goldi = load_named_profile(REPOSITORY_ROOT, "GOLDI")
    goldi_read_only = replace(
        value,
        derived_profile_id=goldi.profile_id,
        derived_profile_fingerprint=goldi.fingerprint,
        symbol=goldi.symbol,
    )
    goldi_binding = replace(binding(), symbol=goldi.symbol)
    with pytest.raises(RuntimeValidationError, match="GOLDM-only"):
        validate_runtime_binding(goldi_read_only, goldi, goldi_binding)
