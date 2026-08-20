from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from gold_engine_core import (
    ComponentFingerprint,
    ManifestError,
    ProfileManifest,
    RuntimeIdentity,
    canonical_sha256,
    load_named_profile,
    load_profile_manifest,
    validate_profile_pair,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROFILE_ROOT = REPOSITORY_ROOT / "config" / "engine_profiles"


@pytest.fixture(scope="module")
def profiles():
    return (
        load_profile_manifest(PROFILE_ROOT / "GOLDI.json"),
        load_profile_manifest(PROFILE_ROOT / "GOLDM.json"),
    )


def test_manifests_are_canonical_hashed_and_component_bound(profiles) -> None:
    goldi, goldm = profiles

    validate_profile_pair(goldi, goldm)
    goldi.verify_component_files(REPOSITORY_ROOT)
    goldm.verify_component_files(REPOSITORY_ROOT)
    assert goldi.fingerprint != goldm.fingerprint
    assert goldi.order_authority_default == "disabled"
    assert goldm.order_authority_default == "disabled"


@pytest.mark.parametrize("profile_id", ["GOLDI", "GOLDM"])
def test_named_loader_has_no_empty_case_or_cross_profile_fallback(profile_id: str) -> None:
    manifest = load_named_profile(REPOSITORY_ROOT, profile_id)

    assert manifest.profile_id == profile_id
    for invalid in ("", profile_id.lower(), "UNKNOWN"):
        with pytest.raises(ManifestError, match="unsupported profile_id"):
            load_named_profile(REPOSITORY_ROOT, invalid)


def test_runtime_identity_rejects_cross_symbol_magic_mode_and_terminal(profiles) -> None:
    goldi, goldm = profiles
    correct = RuntimeIdentity(
        profile_id="GOLDI",
        symbol="GOLD.i#",
        trade_mode="demo",
        terminal_identity="GOLDI_DEDICATED_TERMINAL",
        magic=26081911,
    )
    goldi.validate_runtime_identity(correct)

    mutations = (
        replace(correct, symbol=goldm.symbol),
        replace(correct, magic=goldm.magic),
        replace(correct, trade_mode="real"),
        replace(correct, terminal_identity=goldm.terminal.identity),
        replace(correct, profile_id="GOLDM"),
    )
    for identity in mutations:
        with pytest.raises(ManifestError, match="runtime identity mismatch"):
            goldi.validate_runtime_identity(identity)


def test_goldm_demo_requires_explicit_engineering_authority(profiles) -> None:
    _, goldm = profiles
    identity = RuntimeIdentity(
        profile_id="GOLDM",
        symbol="GOLDm#",
        trade_mode="demo",
        terminal_identity="GOLDM_DEDICATED_TERMINAL",
        magic=26081912,
    )

    with pytest.raises(ManifestError, match="trade_mode"):
        goldm.validate_runtime_identity(identity)
    goldm.validate_runtime_identity(identity, allow_engineering_demo=True)


def test_profile_pair_rejects_shared_authority_namespaces(profiles) -> None:
    goldi, goldm = profiles
    mutations = (
        replace(goldm, symbol=goldi.symbol),
        replace(goldm, magic=goldi.magic),
        replace(goldm, state_namespace=goldi.state_namespace),
        replace(goldm, audit_namespace=goldi.audit_namespace),
        replace(goldm, terminal=replace(goldm.terminal, path_env=goldi.terminal.path_env)),
        replace(goldm, telegram_audience=goldi.telegram_audience),
    )

    for mutation in mutations:
        with pytest.raises(ManifestError):
            validate_profile_pair(goldi, mutation)


def test_component_config_swap_is_rejected(profiles) -> None:
    goldi, goldm = profiles
    swapped = replace(goldi, revised_config=goldm.revised_config)

    with pytest.raises(ManifestError, match="instrument"):
        swapped.verify_component_files(REPOSITORY_ROOT)


def test_manifest_dataclasses_are_immutable(profiles) -> None:
    goldi, _ = profiles

    with pytest.raises(FrozenInstanceError):
        goldi.magic = 1  # type: ignore[misc]


def test_unknown_or_noncanonical_manifest_keys_are_rejected(tmp_path: Path, profiles) -> None:
    goldi, _ = profiles
    payload = goldi.to_payload()
    payload["unexpected"] = True
    path = tmp_path / "GOLDI.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.with_suffix(".sha256").write_text(
        f"{canonical_sha256(payload)}  GOLDI.json\n", encoding="ascii"
    )

    with pytest.raises(ManifestError, match="manifest keys"):
        load_profile_manifest(path)


def test_boundary_types_and_scalar_contracts_are_fail_closed(profiles) -> None:
    goldi, _ = profiles
    base = goldi.to_payload()
    mutations = (
        (None, "JSON object"),
        ({**base, "profile_id": ""}, "non-empty string"),
        ({**base, "schema_version": True}, "integer"),
        ({**base, "expected_trade_mode": "paper"}, "demo.*real"),
        ({**base, "max_total_lot": 1.0}, "decimal string"),
        ({**base, "max_total_lot": "invalid"}, "valid decimal"),
        ({**base, "max_total_lot": "NaN"}, "finite"),
        ({**base, "state_namespace": "/absolute/state.json"}, "repository-relative"),
        ({**base, "order_authority_default": "enabled"}, "remain disabled"),
        ({**base, "sizing_tiers": []}, "non-empty JSON array"),
    )

    for payload, message in mutations:
        with pytest.raises(ManifestError, match=message):
            ProfileManifest.from_payload(payload)


def test_nested_contracts_reject_unknown_keys_and_unsafe_values(profiles) -> None:
    goldi, _ = profiles
    base = goldi.to_payload()

    terminal = dict(base["terminal"])
    terminal["unexpected"] = True
    with pytest.raises(ManifestError, match="terminal keys"):
        ProfileManifest.from_payload({**base, "terminal": terminal})

    for field, value, message in (
        ("path_env", "lowercase", "uppercase environment"),
        ("require_account_binding", "yes", "boolean"),
        ("require_account_binding", False, "must be true"),
    ):
        terminal = dict(base["terminal"])
        terminal[field] = value
        with pytest.raises(ManifestError, match=message):
            ProfileManifest.from_payload({**base, "terminal": terminal})

    tier = dict(base["sizing_tiers"][0])
    tier["unexpected"] = True
    with pytest.raises(ManifestError, match=r"sizing_tiers.*keys"):
        ProfileManifest.from_payload({**base, "sizing_tiers": [tier]})

    component = dict(base["revised_config"])
    component["canonical_sha256"] = "NOT-A-SHA"
    with pytest.raises(ManifestError, match="lowercase SHA-256"):
        ProfileManifest.from_payload({**base, "revised_config": component})

    with pytest.raises(ManifestError, match="keys"):
        ComponentFingerprint.from_payload({"path": "config.json"}, "component")


def test_profile_specific_and_sizing_invariants_are_fail_closed(profiles) -> None:
    goldi, goldm = profiles
    goldi_payload = goldi.to_payload()
    goldm_payload = goldm.to_payload()
    mutations = (
        ({**goldi_payload, "profile_id": "OTHER"}, "unsupported profile_id"),
        (
            {**goldi_payload, "audit_namespace": goldi.state_namespace},
            "state_namespace and audit_namespace",
        ),
        (
            {
                **goldi_payload,
                "sizing_tiers": [{"minimum_balance": "1", "lot": "0.01"}],
            },
            "first sizing tier",
        ),
        (
            {
                **goldi_payload,
                "sizing_tiers": [
                    {"minimum_balance": "0", "lot": "0.01"},
                    {"minimum_balance": "0", "lot": "0.02"},
                ],
            },
            "unique ascending",
        ),
        (
            {
                **goldi_payload,
                "sizing_tiers": [{"minimum_balance": "0", "lot": "0.05"}],
            },
            "exceeds max_total_lot",
        ),
        ({**goldi_payload, "symbol": "GOLDm#"}, "GOLDI.*locked"),
        ({**goldi_payload, "telegram_audience": "admin_only"}, "GOLDI audience"),
        ({**goldm_payload, "symbol": "GOLD.i#"}, "GOLDM production"),
        ({**goldm_payload, "engineering_trade_mode": "real"}, "engineering mode"),
        ({**goldm_payload, "telegram_audience": "goldi_approved"}, "GOLDM audience"),
    )

    for payload, message in mutations:
        with pytest.raises(ManifestError, match=message):
            ProfileManifest.from_payload(payload)


def test_checksum_and_manifest_read_failures_are_rejected(tmp_path: Path, profiles) -> None:
    goldi, _ = profiles
    path = tmp_path / "GOLDI.json"

    with pytest.raises(ManifestError, match="cannot read profile manifest"):
        load_profile_manifest(path)
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ManifestError, match="cannot read profile manifest"):
        load_profile_manifest(path)

    payload = goldi.to_payload()
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManifestError, match="cannot read manifest checksum"):
        load_profile_manifest(path)

    checksum = path.with_suffix(".sha256")
    checksum.write_text("invalid\n", encoding="ascii")
    with pytest.raises(ManifestError, match="checksum sidecar"):
        load_profile_manifest(path)
    checksum.write_text(f"{'0' * 64}  GOLDI.json\n", encoding="ascii")
    with pytest.raises(ManifestError, match="canonical SHA-256 mismatch"):
        load_profile_manifest(path)


def test_component_read_and_fingerprint_failures_are_rejected(tmp_path: Path, profiles) -> None:
    goldi, _ = profiles
    missing = replace(
        goldi,
        revised_config=replace(goldi.revised_config, path="config/missing.json"),
    )
    with pytest.raises(ManifestError, match="cannot read revised_config"):
        missing.verify_component_files(tmp_path)

    config = tmp_path / "config"
    config.mkdir()
    component_path = config / "revised.json"
    component_path.write_text('{"instrument":"GOLD.i#"}', encoding="utf-8")
    wrong_hash = replace(
        goldi,
        revised_config=replace(
            goldi.revised_config,
            path="config/revised.json",
            canonical_sha256="0" * 64,
        ),
        bear_config=replace(goldi.bear_config, path="config/missing-bear.json"),
    )
    with pytest.raises(ManifestError, match="fingerprint mismatch"):
        wrong_hash.verify_component_files(tmp_path)


def test_pair_and_named_loader_reject_wrong_profile_identity(tmp_path: Path, profiles) -> None:
    goldi, goldm = profiles
    with pytest.raises(ManifestError, match="exactly GOLDI and GOLDM"):
        validate_profile_pair(goldi, goldi)

    profile_dir = tmp_path / "config" / "engine_profiles"
    profile_dir.mkdir(parents=True)
    payload = goldm.to_payload()
    path = profile_dir / "GOLDI.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.with_suffix(".sha256").write_text(
        f"{canonical_sha256(payload)}  GOLDI.json\n", encoding="ascii"
    )
    with pytest.raises(ManifestError, match="does not match requested profile"):
        load_named_profile(tmp_path, "GOLDI")


def test_canonical_json_rejects_non_json_values() -> None:
    with pytest.raises(ManifestError, match="canonical JSON"):
        canonical_sha256({"bad": object()})
