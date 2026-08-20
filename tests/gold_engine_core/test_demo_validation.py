from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from gold_engine_core import (
    DemoRuntimeBinding,
    DemoValidationError,
    DemoValidationManifest,
    load_demo_validation_manifest,
    load_named_profile,
    validate_demo_binding,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_ROOT = REPOSITORY_ROOT / "config" / "validation_profiles"


def manifest(profile_id: str) -> DemoValidationManifest:
    filename = "GOLDI_DEMO.json" if profile_id == "GOLDI" else "GOLDM_DEMO_VALIDATION.json"
    return load_demo_validation_manifest(VALIDATION_ROOT / filename)


def binding(profile_id: str) -> DemoRuntimeBinding:
    value = manifest(profile_id)
    return DemoRuntimeBinding(
        value.validation_profile_id,
        f"C:/{profile_id}-demo/terminal64.exe",
        123456 if profile_id == "GOLDI" else 654321,
        f"{profile_id}-DEMO-SERVER",
        "demo",
        value.symbol,
    )


@pytest.mark.parametrize("profile_id", ["GOLDI", "GOLDM"])
def test_demo_manifest_is_canonical_derived_and_real_authority_disabled(
    profile_id: str,
) -> None:
    value = manifest(profile_id)
    production = load_named_profile(REPOSITORY_ROOT, profile_id)

    validate_demo_binding(value, production, binding(profile_id), production_login=999999)
    assert value.derived_profile_fingerprint == production.fingerprint
    assert value.required_trade_mode == "demo"
    assert value.production_real_authority is False
    if profile_id == "GOLDM":
        assert value.validation_profile_id == "GOLDM_DEMO_VALIDATION"
        assert value.audience == "admin_only"
        assert "REAL" not in value.terminal_path_env
        assert value.login_env != production.terminal.expected_login_env


def test_goldm_demo_rejects_real_mode_production_login_and_env_reuse() -> None:
    value = manifest("GOLDM")
    production = load_named_profile(REPOSITORY_ROOT, "GOLDM")
    demo = binding("GOLDM")

    with pytest.raises(DemoValidationError, match="not DEMO"):
        validate_demo_binding(value, production, replace(demo, trade_mode="real"))
    with pytest.raises(DemoValidationError, match="equals production"):
        validate_demo_binding(value, production, demo, production_login=demo.login)
    with pytest.raises(DemoValidationError, match="production environment"):
        validate_demo_binding(
            replace(value, terminal_path_env=production.terminal.path_env),
            production,
            demo,
        )
    with pytest.raises(DemoValidationError, match="admin-only"):
        validate_demo_binding(replace(value, audience="subscriber"), production, demo)


def test_profile_fingerprint_symbol_and_validation_id_swap_are_rejected() -> None:
    goldi = manifest("GOLDI")
    goldm = load_named_profile(REPOSITORY_ROOT, "GOLDM")
    demo = binding("GOLDI")

    with pytest.raises(DemoValidationError, match="derive"):
        validate_demo_binding(goldi, goldm, demo)
    with pytest.raises(DemoValidationError, match="profile ID"):
        validate_demo_binding(
            goldi,
            load_named_profile(REPOSITORY_ROOT, "GOLDI"),
            replace(demo, validation_profile_id="OTHER"),
        )
    with pytest.raises(DemoValidationError, match="symbol"):
        validate_demo_binding(
            goldi,
            load_named_profile(REPOSITORY_ROOT, "GOLDI"),
            replace(demo, symbol="GOLDm#"),
        )


def test_demo_manifest_checksum_and_boundary_mutations_fail_closed(tmp_path: Path) -> None:
    value = manifest("GOLDI")
    path = tmp_path / "GOLDI_DEMO.json"
    path.write_text(json.dumps(value.to_payload()), encoding="utf-8")
    path.with_suffix(".sha256").write_text(f"{'0' * 64}  GOLDI_DEMO.json\n", encoding="ascii")
    with pytest.raises(DemoValidationError, match="checksum"):
        load_demo_validation_manifest(path)

    with pytest.raises(DemoValidationError, match="REAL authority"):
        replace(value, production_real_authority=True)
    with pytest.raises(DemoValidationError, match="trade mode"):
        replace(value, required_trade_mode="real")
    with pytest.raises(DemoValidationError, match="incomplete"):
        replace(binding("GOLDI"), terminal_path="")
