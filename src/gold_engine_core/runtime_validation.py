from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .profile import ProfileManifest, canonical_json, canonical_sha256


class RuntimeValidationError(ValueError):
    """Raised when a validation binding could broaden trading authority."""


@dataclass(frozen=True, slots=True)
class RuntimeValidationManifest:
    schema_version: int
    validation_profile_id: str
    derived_profile_id: str
    derived_profile_fingerprint: str
    symbol: str
    required_trade_mode: str
    access_mode: str
    terminal_path_env: str
    login_env: str
    server_env: str
    state_namespace: str
    evidence_namespace: str
    audience: str
    production_real_authority: bool

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise RuntimeValidationError("validation schema_version must equal 1")
        for name, value in (
            ("validation_profile_id", self.validation_profile_id),
            ("derived_profile_id", self.derived_profile_id),
            ("derived_profile_fingerprint", self.derived_profile_fingerprint),
            ("symbol", self.symbol),
            ("terminal_path_env", self.terminal_path_env),
            ("login_env", self.login_env),
            ("server_env", self.server_env),
            ("state_namespace", self.state_namespace),
            ("evidence_namespace", self.evidence_namespace),
            ("audience", self.audience),
        ):
            if not value:
                raise RuntimeValidationError(f"validation manifest {name} is required")
        if len(self.derived_profile_fingerprint) != 64:
            raise RuntimeValidationError("derived profile fingerprint is invalid")
        if self.required_trade_mode not in {"demo", "real"}:
            raise RuntimeValidationError("required trade mode must be demo or real")
        if self.access_mode not in {"demo_execution", "read_only"}:
            raise RuntimeValidationError("validation access mode is invalid")
        if self.access_mode == "read_only" and self.required_trade_mode != "real":
            raise RuntimeValidationError("read-only broker validation must bind REAL mode")
        if self.access_mode == "demo_execution" and self.required_trade_mode != "demo":
            raise RuntimeValidationError("DEMO execution validation must bind DEMO mode")
        if self.production_real_authority:
            raise RuntimeValidationError("validation profile cannot carry REAL authority")
        if len({self.terminal_path_env, self.login_env, self.server_env}) != 3:
            raise RuntimeValidationError("validation environment names must be distinct")
        if self.state_namespace == self.evidence_namespace:
            raise RuntimeValidationError("validation state and evidence namespaces must differ")

    @classmethod
    def from_payload(cls, payload: object) -> RuntimeValidationManifest:
        data = _mapping(payload, "runtime_validation_manifest")
        expected = {
            "access_mode",
            "audience",
            "derived_profile_fingerprint",
            "derived_profile_id",
            "evidence_namespace",
            "login_env",
            "production_real_authority",
            "required_trade_mode",
            "schema_version",
            "server_env",
            "state_namespace",
            "symbol",
            "terminal_path_env",
            "validation_profile_id",
        }
        if set(data) != expected:
            raise RuntimeValidationError(f"validation manifest keys must be {sorted(expected)}")
        schema = data["schema_version"]
        authority = data["production_real_authority"]
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise RuntimeValidationError("schema_version must be an integer")
        if not isinstance(authority, bool):
            raise RuntimeValidationError("production_real_authority must be boolean")
        return cls(
            schema,
            _string(data["validation_profile_id"], "validation_profile_id"),
            _string(data["derived_profile_id"], "derived_profile_id"),
            _string(data["derived_profile_fingerprint"], "derived_profile_fingerprint"),
            _string(data["symbol"], "symbol"),
            _string(data["required_trade_mode"], "required_trade_mode"),
            _string(data["access_mode"], "access_mode"),
            _string(data["terminal_path_env"], "terminal_path_env"),
            _string(data["login_env"], "login_env"),
            _string(data["server_env"], "server_env"),
            _string(data["state_namespace"], "state_namespace"),
            _string(data["evidence_namespace"], "evidence_namespace"),
            _string(data["audience"], "audience"),
            authority,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "access_mode": self.access_mode,
            "audience": self.audience,
            "derived_profile_fingerprint": self.derived_profile_fingerprint,
            "derived_profile_id": self.derived_profile_id,
            "evidence_namespace": self.evidence_namespace,
            "login_env": self.login_env,
            "production_real_authority": self.production_real_authority,
            "required_trade_mode": self.required_trade_mode,
            "schema_version": self.schema_version,
            "server_env": self.server_env,
            "state_namespace": self.state_namespace,
            "symbol": self.symbol,
            "terminal_path_env": self.terminal_path_env,
            "validation_profile_id": self.validation_profile_id,
        }

    @property
    def fingerprint(self) -> str:
        return str(canonical_sha256(self.to_payload()))


@dataclass(frozen=True, slots=True)
class RuntimeValidationBinding:
    validation_profile_id: str
    terminal_path: str
    login: int
    server: str
    trade_mode: str
    symbol: str
    access_mode: str

    def __post_init__(self) -> None:
        if (
            not self.validation_profile_id
            or not self.terminal_path
            or self.login <= 0
            or not self.server
            or not self.symbol
            or not self.access_mode
        ):
            raise RuntimeValidationError("runtime validation binding is incomplete")


def validate_runtime_binding(
    manifest: RuntimeValidationManifest,
    production: ProfileManifest,
    binding: RuntimeValidationBinding,
) -> None:
    if (
        manifest.derived_profile_id != production.profile_id
        or manifest.derived_profile_fingerprint != production.fingerprint
        or manifest.symbol != production.symbol
    ):
        raise RuntimeValidationError("validation manifest does not derive from production")
    if binding.validation_profile_id != manifest.validation_profile_id:
        raise RuntimeValidationError("runtime validation profile ID mismatch")
    if binding.trade_mode != manifest.required_trade_mode:
        raise RuntimeValidationError("runtime account trade mode mismatch")
    if binding.access_mode != manifest.access_mode:
        raise RuntimeValidationError("runtime access mode mismatch")
    if binding.symbol != manifest.symbol:
        raise RuntimeValidationError("runtime symbol mismatch")
    if manifest.access_mode == "read_only":
        if production.profile_id != "GOLDM":
            raise RuntimeValidationError("REAL read-only exception is GOLDM-only")
        if manifest.audience != "admin_only":
            raise RuntimeValidationError("GOLDM read-only evidence must remain admin-only")


def load_runtime_validation_manifest(path: Path) -> RuntimeValidationManifest:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeValidationError(f"cannot read runtime validation manifest: {path}") from exc
    manifest = RuntimeValidationManifest.from_payload(payload)
    if canonical_json(manifest.to_payload()) != canonical_json(payload):
        raise RuntimeValidationError("runtime validation manifest is not canonical")
    checksum_path = path.with_suffix(".sha256")
    try:
        fields = checksum_path.read_text(encoding="ascii").strip().split()
    except OSError as exc:
        raise RuntimeValidationError(
            f"cannot read runtime validation checksum: {checksum_path}"
        ) from exc
    if len(fields) != 2 or fields[1] != path.name or fields[0] != manifest.fingerprint:
        raise RuntimeValidationError("runtime validation manifest checksum mismatch")
    return manifest


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RuntimeValidationError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeValidationError(f"{field} must be a non-empty string")
    return value
