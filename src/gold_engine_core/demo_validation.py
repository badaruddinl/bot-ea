from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .profile import ProfileManifest, canonical_json, canonical_sha256


class DemoValidationError(ValueError):
    """Raised when a DEMO validation profile could reach production authority."""


@dataclass(frozen=True, slots=True)
class DemoValidationManifest:
    schema_version: int
    validation_profile_id: str
    derived_profile_id: str
    derived_profile_fingerprint: str
    symbol: str
    required_trade_mode: str
    terminal_path_env: str
    login_env: str
    server_env: str
    state_namespace: str
    evidence_namespace: str
    audience: str
    production_real_authority: bool

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise DemoValidationError("demo manifest schema_version must equal 1")
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
                raise DemoValidationError(f"demo manifest {name} is required")
        if len(self.derived_profile_fingerprint) != 64:
            raise DemoValidationError("derived profile fingerprint is invalid")
        if self.required_trade_mode != "demo":
            raise DemoValidationError("validation trade mode must be demo")
        if self.production_real_authority:
            raise DemoValidationError("validation profile cannot carry REAL authority")
        env_names = (self.terminal_path_env, self.login_env, self.server_env)
        if len(set(env_names)) != len(env_names):
            raise DemoValidationError("validation environment names must be distinct")
        if self.state_namespace == self.evidence_namespace:
            raise DemoValidationError("validation state and evidence namespaces must differ")

    @classmethod
    def from_payload(cls, payload: object) -> DemoValidationManifest:
        data = _mapping(payload, "demo_validation_manifest")
        expected = {
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
            raise DemoValidationError(f"demo manifest keys must be {sorted(expected)}")
        schema = data["schema_version"]
        authority = data["production_real_authority"]
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise DemoValidationError("schema_version must be an integer")
        if not isinstance(authority, bool):
            raise DemoValidationError("production_real_authority must be boolean")
        return cls(
            schema,
            _string(data["validation_profile_id"], "validation_profile_id"),
            _string(data["derived_profile_id"], "derived_profile_id"),
            _string(data["derived_profile_fingerprint"], "derived_profile_fingerprint"),
            _string(data["symbol"], "symbol"),
            _string(data["required_trade_mode"], "required_trade_mode"),
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
class DemoRuntimeBinding:
    validation_profile_id: str
    terminal_path: str
    login: int
    server: str
    trade_mode: str
    symbol: str

    def __post_init__(self) -> None:
        if (
            not self.validation_profile_id
            or not self.terminal_path
            or self.login <= 0
            or not self.server
            or not self.symbol
        ):
            raise DemoValidationError("DEMO runtime binding is incomplete")


def validate_demo_binding(
    manifest: DemoValidationManifest,
    production: ProfileManifest,
    binding: DemoRuntimeBinding,
    *,
    production_login: int | None = None,
) -> None:
    if (
        manifest.derived_profile_id != production.profile_id
        or manifest.derived_profile_fingerprint != production.fingerprint
        or manifest.symbol != production.symbol
    ):
        raise DemoValidationError("DEMO manifest does not derive from production fingerprint")
    if binding.validation_profile_id != manifest.validation_profile_id:
        raise DemoValidationError("runtime validation profile ID mismatch")
    if binding.trade_mode != "demo":
        raise DemoValidationError("runtime account is not DEMO")
    if binding.symbol != manifest.symbol:
        raise DemoValidationError("runtime symbol mismatch")
    if (
        production.profile_id == "GOLDM"
        and production_login is not None
        and binding.login == production_login
    ):
        raise DemoValidationError("DEMO validation login equals production login")
    production_envs = {
        production.terminal.path_env,
        production.terminal.expected_login_env,
        production.terminal.expected_server_env,
    }
    validation_envs = {
        manifest.terminal_path_env,
        manifest.login_env,
        manifest.server_env,
    }
    if production.profile_id == "GOLDM" and production_envs & validation_envs:
        raise DemoValidationError("GOLDM DEMO reuses production environment binding")
    if production.profile_id == "GOLDM" and manifest.audience != "admin_only":
        raise DemoValidationError("GOLDM DEMO evidence must remain admin-only")


def load_demo_validation_manifest(path: Path) -> DemoValidationManifest:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DemoValidationError(f"cannot read DEMO validation manifest: {path}") from exc
    manifest = DemoValidationManifest.from_payload(payload)
    if canonical_json(manifest.to_payload()) != canonical_json(payload):
        raise DemoValidationError("DEMO validation manifest is not canonical")
    checksum_path = path.with_suffix(".sha256")
    try:
        fields = checksum_path.read_text(encoding="ascii").strip().split()
    except OSError as exc:
        raise DemoValidationError(f"cannot read DEMO manifest checksum: {checksum_path}") from exc
    if len(fields) != 2 or fields[1] != path.name or fields[0] != manifest.fingerprint:
        raise DemoValidationError("DEMO validation manifest checksum mismatch")
    return manifest


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DemoValidationError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DemoValidationError(f"{field} must be a non-empty string")
    return value
