from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Literal, cast

TradeMode = Literal["demo", "real"]
OrderAuthority = Literal["disabled"]
_PROFILE_IDS = frozenset({"GOLDI", "GOLDM"})
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ENV_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+$")


class ManifestError(ValueError):
    """Raised when a profile manifest violates its immutable contract."""


def canonical_json(payload: object) -> bytes:
    try:
        value = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ManifestError("payload cannot be encoded as canonical JSON") from exc
    return value.encode("utf-8")


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ManifestError(f"{field} must be a JSON object with string keys")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ManifestError(f"{field} must be an integer >= {minimum}")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ManifestError(f"{field} must be a boolean")
    return value


def _decimal(value: object, field: str, *, allow_zero: bool) -> Decimal:
    if not isinstance(value, str):
        raise ManifestError(f"{field} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ManifestError(f"{field} is not a valid decimal") from exc
    if not parsed.is_finite():
        raise ManifestError(f"{field} must be finite")
    minimum_ok = parsed >= 0 if allow_zero else parsed > 0
    if not minimum_ok:
        relation = ">= 0" if allow_zero else "> 0"
        raise ManifestError(f"{field} must be {relation}")
    return parsed


def _trade_mode(value: object, field: str) -> TradeMode:
    if value not in {"demo", "real"}:
        raise ManifestError(f"{field} must be 'demo' or 'real'")
    return value


def _relative_path(value: object, field: str) -> str:
    path = _string(value, field)
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or "\\" in path:
        raise ManifestError(f"{field} must be a normalized repository-relative POSIX path")
    return path


@dataclass(frozen=True, slots=True)
class SizingTier:
    minimum_balance: Decimal
    lot: Decimal

    @classmethod
    def from_payload(cls, payload: object, field: str) -> SizingTier:
        data = _mapping(payload, field)
        expected = {"minimum_balance", "lot"}
        if set(data) != expected:
            raise ManifestError(f"{field} keys must be {sorted(expected)}")
        return cls(
            minimum_balance=_decimal(
                data["minimum_balance"], f"{field}.minimum_balance", allow_zero=True
            ),
            lot=_decimal(data["lot"], f"{field}.lot", allow_zero=False),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "lot": str(self.lot),
            "minimum_balance": str(self.minimum_balance),
        }


@dataclass(frozen=True, slots=True)
class TerminalContract:
    identity: str
    path_env: str
    expected_login_env: str
    expected_server_env: str
    require_account_binding: bool

    @classmethod
    def from_payload(cls, payload: object) -> TerminalContract:
        data = _mapping(payload, "terminal")
        expected = {
            "expected_login_env",
            "expected_server_env",
            "identity",
            "path_env",
            "require_account_binding",
        }
        if set(data) != expected:
            raise ManifestError(f"terminal keys must be {sorted(expected)}")
        contract = cls(
            identity=_string(data["identity"], "terminal.identity"),
            path_env=_string(data["path_env"], "terminal.path_env"),
            expected_login_env=_string(data["expected_login_env"], "terminal.expected_login_env"),
            expected_server_env=_string(
                data["expected_server_env"], "terminal.expected_server_env"
            ),
            require_account_binding=_boolean(
                data["require_account_binding"], "terminal.require_account_binding"
            ),
        )
        for field, value in (
            ("path_env", contract.path_env),
            ("expected_login_env", contract.expected_login_env),
            ("expected_server_env", contract.expected_server_env),
        ):
            if not _ENV_PATTERN.fullmatch(value):
                raise ManifestError(f"terminal.{field} must be an uppercase environment name")
        if not contract.require_account_binding:
            raise ManifestError("terminal.require_account_binding must be true")
        return contract

    def to_payload(self) -> dict[str, object]:
        return {
            "expected_login_env": self.expected_login_env,
            "expected_server_env": self.expected_server_env,
            "identity": self.identity,
            "path_env": self.path_env,
            "require_account_binding": self.require_account_binding,
        }


@dataclass(frozen=True, slots=True)
class ComponentFingerprint:
    path: str
    canonical_sha256: str

    @classmethod
    def from_payload(cls, payload: object, field: str) -> ComponentFingerprint:
        data = _mapping(payload, field)
        expected = {"canonical_sha256", "path"}
        if set(data) != expected:
            raise ManifestError(f"{field} keys must be {sorted(expected)}")
        fingerprint = cls(
            path=_relative_path(data["path"], f"{field}.path"),
            canonical_sha256=_string(data["canonical_sha256"], f"{field}.canonical_sha256"),
        )
        if not _SHA256_PATTERN.fullmatch(fingerprint.canonical_sha256):
            raise ManifestError(f"{field}.canonical_sha256 must be lowercase SHA-256")
        return fingerprint

    def to_payload(self) -> dict[str, object]:
        return {"canonical_sha256": self.canonical_sha256, "path": self.path}


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    profile_id: str
    symbol: str
    trade_mode: TradeMode
    terminal_identity: str
    magic: int


@dataclass(frozen=True, slots=True)
class ProfileManifest:
    schema_version: int
    profile_id: str
    profile_version: str
    strategy_version: str
    symbol: str
    expected_trade_mode: TradeMode
    engineering_trade_mode: TradeMode
    order_authority_default: OrderAuthority
    terminal: TerminalContract
    magic: int
    sizing_tiers: tuple[SizingTier, ...]
    max_positions: int
    max_total_lot: Decimal
    deviation_points: int
    revised_config: ComponentFingerprint
    bear_config: ComponentFingerprint
    state_namespace: str
    audit_namespace: str
    telegram_audience: str
    event_privacy: str

    @classmethod
    def from_payload(cls, payload: object) -> ProfileManifest:
        data = _mapping(payload, "manifest")
        expected = {
            "audit_namespace",
            "bear_config",
            "deviation_points",
            "engineering_trade_mode",
            "event_privacy",
            "expected_trade_mode",
            "magic",
            "max_positions",
            "max_total_lot",
            "order_authority_default",
            "profile_id",
            "profile_version",
            "revised_config",
            "schema_version",
            "sizing_tiers",
            "state_namespace",
            "strategy_version",
            "symbol",
            "telegram_audience",
            "terminal",
        }
        if set(data) != expected:
            raise ManifestError(f"manifest keys must be {sorted(expected)}")
        tiers_payload = data["sizing_tiers"]
        if not isinstance(tiers_payload, list) or not tiers_payload:
            raise ManifestError("sizing_tiers must be a non-empty JSON array")
        authority = data["order_authority_default"]
        if authority != "disabled":
            raise ManifestError("order_authority_default must remain disabled")
        manifest = cls(
            schema_version=_integer(data["schema_version"], "schema_version", minimum=1),
            profile_id=_string(data["profile_id"], "profile_id"),
            profile_version=_string(data["profile_version"], "profile_version"),
            strategy_version=_string(data["strategy_version"], "strategy_version"),
            symbol=_string(data["symbol"], "symbol"),
            expected_trade_mode=_trade_mode(data["expected_trade_mode"], "expected_trade_mode"),
            engineering_trade_mode=_trade_mode(
                data["engineering_trade_mode"], "engineering_trade_mode"
            ),
            order_authority_default=authority,
            terminal=TerminalContract.from_payload(data["terminal"]),
            magic=_integer(data["magic"], "magic", minimum=1),
            sizing_tiers=tuple(
                SizingTier.from_payload(item, f"sizing_tiers[{index}]")
                for index, item in enumerate(tiers_payload)
            ),
            max_positions=_integer(data["max_positions"], "max_positions", minimum=1),
            max_total_lot=_decimal(data["max_total_lot"], "max_total_lot", allow_zero=False),
            deviation_points=_integer(data["deviation_points"], "deviation_points", minimum=0),
            revised_config=ComponentFingerprint.from_payload(
                data["revised_config"], "revised_config"
            ),
            bear_config=ComponentFingerprint.from_payload(data["bear_config"], "bear_config"),
            state_namespace=_relative_path(data["state_namespace"], "state_namespace"),
            audit_namespace=_relative_path(data["audit_namespace"], "audit_namespace"),
            telegram_audience=_string(data["telegram_audience"], "telegram_audience"),
            event_privacy=_string(data["event_privacy"], "event_privacy"),
        )
        manifest._validate_invariants()
        return manifest

    def _validate_invariants(self) -> None:
        if self.profile_id not in _PROFILE_IDS:
            raise ManifestError(f"unsupported profile_id: {self.profile_id!r}")
        if self.state_namespace == self.audit_namespace:
            raise ManifestError("state_namespace and audit_namespace must differ")
        if self.sizing_tiers[0].minimum_balance != 0:
            raise ManifestError("first sizing tier must start at balance zero")
        balances = tuple(tier.minimum_balance for tier in self.sizing_tiers)
        if balances != tuple(sorted(set(balances))):
            raise ManifestError("sizing tiers must have unique ascending minimum balances")
        if max(tier.lot for tier in self.sizing_tiers) > self.max_total_lot:
            raise ManifestError("a sizing tier lot exceeds max_total_lot")
        if self.profile_id == "GOLDI":
            if self.symbol != "GOLD.i#" or self.expected_trade_mode != "demo":
                raise ManifestError("GOLDI must be locked to GOLD.i# DEMO")
            if self.telegram_audience != "goldi_approved":
                raise ManifestError("GOLDI audience must be goldi_approved")
        if self.profile_id == "GOLDM":
            if self.symbol != "GOLDm#" or self.expected_trade_mode != "real":
                raise ManifestError("GOLDM production contract must be locked to GOLDm# REAL")
            if self.engineering_trade_mode != "demo":
                raise ManifestError("GOLDM engineering mode must be demo")
            if self.telegram_audience != "admin_only":
                raise ManifestError("GOLDM audience must be admin_only")

    def to_payload(self) -> dict[str, object]:
        return {
            "audit_namespace": self.audit_namespace,
            "bear_config": self.bear_config.to_payload(),
            "deviation_points": self.deviation_points,
            "engineering_trade_mode": self.engineering_trade_mode,
            "event_privacy": self.event_privacy,
            "expected_trade_mode": self.expected_trade_mode,
            "magic": self.magic,
            "max_positions": self.max_positions,
            "max_total_lot": str(self.max_total_lot),
            "order_authority_default": self.order_authority_default,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "revised_config": self.revised_config.to_payload(),
            "schema_version": self.schema_version,
            "sizing_tiers": [tier.to_payload() for tier in self.sizing_tiers],
            "state_namespace": self.state_namespace,
            "strategy_version": self.strategy_version,
            "symbol": self.symbol,
            "telegram_audience": self.telegram_audience,
            "terminal": self.terminal.to_payload(),
        }

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.to_payload())

    def validate_runtime_identity(
        self, identity: RuntimeIdentity, *, allow_engineering_demo: bool = False
    ) -> None:
        expected_modes = {self.expected_trade_mode}
        if allow_engineering_demo:
            expected_modes.add(self.engineering_trade_mode)
        mismatches: list[str] = []
        if identity.profile_id != self.profile_id:
            mismatches.append("profile_id")
        if identity.symbol != self.symbol:
            mismatches.append("symbol")
        if identity.trade_mode not in expected_modes:
            mismatches.append("trade_mode")
        if identity.terminal_identity != self.terminal.identity:
            mismatches.append("terminal_identity")
        if identity.magic != self.magic:
            mismatches.append("magic")
        if mismatches:
            raise ManifestError(f"runtime identity mismatch: {', '.join(mismatches)}")

    def verify_component_files(self, repository_root: Path) -> None:
        root = repository_root.resolve()
        for name, component in (
            ("revised_config", self.revised_config),
            ("bear_config", self.bear_config),
        ):
            path = (root / component.path).resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ManifestError(f"{name} escapes repository root") from exc
            try:
                payload: object = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ManifestError(f"cannot read {name}: {component.path}") from exc
            data = _mapping(payload, name)
            actual = canonical_sha256(data)
            if actual != component.canonical_sha256:
                raise ManifestError(f"{name} fingerprint mismatch")
            if data.get("instrument") != self.symbol:
                raise ManifestError(f"{name} instrument does not match profile symbol")


def load_profile_manifest(path: Path) -> ProfileManifest:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read profile manifest: {path}") from exc
    data = _mapping(payload, "manifest")
    manifest = ProfileManifest.from_payload(data)
    if canonical_json(data) != canonical_json(manifest.to_payload()):
        raise ManifestError("manifest is not in canonical normalized form")
    checksum_path = path.with_suffix(".sha256")
    try:
        checksum_fields = checksum_path.read_text(encoding="ascii").strip().split()
    except OSError as exc:
        raise ManifestError(f"cannot read manifest checksum: {checksum_path}") from exc
    if len(checksum_fields) != 2 or checksum_fields[1] != path.name:
        raise ManifestError("manifest checksum sidecar must contain '<sha256>  <filename>'")
    if checksum_fields[0] != manifest.fingerprint:
        raise ManifestError("manifest canonical SHA-256 mismatch")
    return manifest


def load_named_profile(repository_root: Path, profile_id: str) -> ProfileManifest:
    if profile_id not in _PROFILE_IDS:
        raise ManifestError(f"unsupported profile_id: {profile_id!r}")
    path = repository_root / "config" / "engine_profiles" / f"{profile_id}.json"
    manifest = load_profile_manifest(path)
    if manifest.profile_id != profile_id:
        raise ManifestError("manifest profile_id does not match requested profile")
    return manifest


def validate_profile_pair(goldi: ProfileManifest, goldm: ProfileManifest) -> None:
    if {goldi.profile_id, goldm.profile_id} != _PROFILE_IDS:
        raise ManifestError("profile pair must contain exactly GOLDI and GOLDM")
    fields = {
        "symbol": (goldi.symbol, goldm.symbol),
        "magic": (goldi.magic, goldm.magic),
        "state_namespace": (goldi.state_namespace, goldm.state_namespace),
        "audit_namespace": (goldi.audit_namespace, goldm.audit_namespace),
        "terminal.identity": (goldi.terminal.identity, goldm.terminal.identity),
        "terminal.path_env": (goldi.terminal.path_env, goldm.terminal.path_env),
        "telegram_audience": (goldi.telegram_audience, goldm.telegram_audience),
        "event_privacy": (goldi.event_privacy, goldm.event_privacy),
        "revised_config": (
            goldi.revised_config.canonical_sha256,
            goldm.revised_config.canonical_sha256,
        ),
        "bear_config": (
            goldi.bear_config.canonical_sha256,
            goldm.bear_config.canonical_sha256,
        ),
    }
    shared = [name for name, values in fields.items() if values[0] == values[1]]
    if shared:
        raise ManifestError(f"cross-profile fields must differ: {', '.join(shared)}")
