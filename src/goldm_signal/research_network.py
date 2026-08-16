from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .research_environment import PortableCloneEvidence


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RULE_NAME = re.compile(r"GoldMResearchOffline-[0-9a-f]{16}-[a-z0-9]{3,32}\Z")
_EVIDENCE_FIELDS = {
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
_BINARY_NAMES = ("terminal64.exe", "metaeditor64.exe", "metatester64.exe")


class ResearchNetworkError(RuntimeError):
    """Raised when exact process-level offline enforcement is not proven."""


@dataclass(frozen=True, slots=True)
class FirewallRuleSnapshot:
    name: str
    display_name: str
    enabled: bool
    direction: str
    action: str
    profile: str
    program_path: Path
    protocol: str
    local_addresses: tuple[str, ...]
    remote_addresses: tuple[str, ...]
    local_ports: tuple[str, ...]
    remote_ports: tuple[str, ...]
    service: str
    interface_type: str
    policy_store_source_type: str


@dataclass(frozen=True, slots=True)
class NetworkIsolationEvidence:
    path: Path
    file_sha256: str
    payload_sha256: str
    clone_manifest_path: Path
    clone_manifest_sha256: str
    clone_manifest_payload_sha256: str
    terminal_root: Path
    rules: tuple[FirewallRuleSnapshot, ...]


FirewallRuleProbe = Callable[[tuple[str, ...]], tuple[FirewallRuleSnapshot, ...]]


def expected_firewall_rule_names(clone: PortableCloneEvidence) -> tuple[str, ...]:
    prefix = _strict_sha256(
        clone.manifest_payload_sha256, "clone manifest payload SHA-256"
    )[:16]
    return tuple(
        f"GoldMResearchOffline-{prefix}-{Path(name).stem}" for name in _BINARY_NAMES
    )


def build_firewall_isolation_evidence(
    *,
    clone: PortableCloneEvidence,
    rule_probe: FirewallRuleProbe,
    output_path: Path,
    verified_at: datetime | None = None,
) -> NetworkIsolationEvidence:
    """Probe active firewall rules and write new immutable evidence."""

    output = _canonical_new_evidence_path(output_path, clone.destination_root)
    rules = _probe_and_validate_rules(clone, rule_probe)
    binary_sha256 = _clone_binary_hashes(clone)
    payload: dict[str, Any] = {
        "schema_version": 2,
        "status": "ENFORCED_OFFLINE",
        "enforcement": "WINDOWS_FIREWALL_BLOCK_OUTBOUND_EXACT_PROGRAMS",
        "verified_at": _utc_timestamp(verified_at or datetime.now(timezone.utc)),
        "clone_manifest_path": str(clone.manifest_path),
        "clone_manifest_sha256": clone.manifest_file_sha256,
        "clone_manifest_payload_sha256": clone.manifest_payload_sha256,
        "terminal_root": str(clone.destination_root),
        "binary_sha256": binary_sha256,
        "rules": [_rule_record(rule) for rule in rules],
    }
    payload["evidence_sha256"] = _canonical_json_sha256(payload)
    _write_json_exclusive(output, payload)
    try:
        return verify_firewall_isolation_evidence(
            output,
            clone=clone,
            rule_probe=rule_probe,
        )
    except Exception:
        if output.is_file() and not _is_reparse(output):
            output.unlink()
        raise


def verify_firewall_isolation_evidence(
    path: Path,
    *,
    clone: PortableCloneEvidence,
    rule_probe: FirewallRuleProbe,
) -> NetworkIsolationEvidence:
    """Re-probe ActiveStore and compare it with sealed evidence."""

    evidence = _canonical_file(path, "network-isolation evidence")
    if evidence.parent != clone.destination_root:
        raise ResearchNetworkError(
            "network-isolation evidence must be stored in the private clone root"
        )
    payload = _read_json_object(evidence)
    if set(payload) != _EVIDENCE_FIELDS or payload.get("schema_version") != 2:
        raise ResearchNetworkError(
            "network-isolation evidence must use schema_version 2 with exact fields"
        )
    supplied = _strict_sha256(payload["evidence_sha256"], "evidence SHA-256")
    unsigned = dict(payload)
    unsigned.pop("evidence_sha256")
    if _canonical_json_sha256(unsigned) != supplied:
        raise ResearchNetworkError("network-isolation evidence self-hash mismatch")
    if (
        payload["status"] != "ENFORCED_OFFLINE"
        or payload["enforcement"]
        != "WINDOWS_FIREWALL_BLOCK_OUTBOUND_EXACT_PROGRAMS"
    ):
        raise ResearchNetworkError("network-isolation evidence status is invalid")
    _parse_utc(payload["verified_at"], "network verified_at")
    if (
        _canonical_file(
            Path(payload["clone_manifest_path"]), "bound clone manifest"
        )
        != clone.manifest_path
        or payload["clone_manifest_sha256"] != clone.manifest_file_sha256
        or payload["clone_manifest_payload_sha256"]
        != clone.manifest_payload_sha256
        or _canonical_directory(Path(payload["terminal_root"]), "terminal root")
        != clone.destination_root
    ):
        raise ResearchNetworkError("network evidence clone binding mismatch")
    if payload["binary_sha256"] != _clone_binary_hashes(clone):
        raise ResearchNetworkError("network evidence binary binding mismatch")

    sealed_rules = _load_rule_records(payload["rules"])
    current_rules = _probe_and_validate_rules(clone, rule_probe)
    if sealed_rules != current_rules:
        raise ResearchNetworkError("active firewall rules changed after evidence sealing")
    return NetworkIsolationEvidence(
        path=evidence,
        file_sha256=_sha256(evidence),
        payload_sha256=supplied,
        clone_manifest_path=clone.manifest_path,
        clone_manifest_sha256=clone.manifest_file_sha256,
        clone_manifest_payload_sha256=clone.manifest_payload_sha256,
        terminal_root=clone.destination_root,
        rules=current_rules,
    )


def _probe_and_validate_rules(
    clone: PortableCloneEvidence, rule_probe: FirewallRuleProbe
) -> tuple[FirewallRuleSnapshot, ...]:
    if rule_probe is None:
        raise ResearchNetworkError("active firewall-rule probe is required")
    names = expected_firewall_rule_names(clone)
    rules = rule_probe(names)
    if not isinstance(rules, tuple) or len(rules) != len(names):
        raise ResearchNetworkError("active firewall-rule inventory is incomplete")
    expected_programs = tuple(
        _canonical_file(clone.destination_root / name, f"clone {name}")
        for name in _BINARY_NAMES
    )
    for rule, name, program in zip(rules, names, expected_programs, strict=True):
        _validate_rule(rule, expected_name=name, expected_program=program)
    return rules


def _validate_rule(
    rule: FirewallRuleSnapshot, *, expected_name: str, expected_program: Path
) -> None:
    if not isinstance(rule, FirewallRuleSnapshot):
        raise ResearchNetworkError("firewall probe returned an invalid rule")
    program = _canonical_file(rule.program_path, "firewall program")
    if (
        rule.name != expected_name
        or not _RULE_NAME.fullmatch(rule.name)
        or rule.display_name != f"GoldM Research Offline - {expected_program.name}"
        or rule.enabled is not True
        or rule.direction != "Outbound"
        or rule.action != "Block"
        or rule.profile != "Any"
        or program != expected_program
        or rule.protocol != "Any"
        or rule.local_addresses != ("Any",)
        or rule.remote_addresses != ("Any",)
        or rule.local_ports != ("Any",)
        or rule.remote_ports != ("Any",)
        or rule.service != "Any"
        or rule.interface_type != "Any"
        or rule.policy_store_source_type != "Local"
    ):
        raise ResearchNetworkError(
            f"firewall rule is not an exact active outbound block: {expected_name}"
        )


def _clone_binary_hashes(clone: PortableCloneEvidence) -> dict[str, str]:
    records = tuple(clone.copied_binaries)
    if len(records) != len(_BINARY_NAMES):
        raise ResearchNetworkError("clone binary inventory is incomplete")
    result: dict[str, str] = {}
    for record, name in zip(records, _BINARY_NAMES, strict=True):
        if record.get("name") != name:
            raise ResearchNetworkError("clone binary inventory order changed")
        result[name] = _strict_sha256(record.get("sha256"), f"{name} SHA-256")
    return result


def _load_rule_records(value: Any) -> tuple[FirewallRuleSnapshot, ...]:
    if not isinstance(value, list):
        raise ResearchNetworkError("network evidence rules must be a list")
    fields = {
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
    result: list[FirewallRuleSnapshot] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != fields:
            raise ResearchNetworkError("network evidence firewall-rule fields are invalid")
        converted = dict(item)
        converted["program_path"] = Path(converted["program_path"])
        for key in (
            "local_addresses",
            "remote_addresses",
            "local_ports",
            "remote_ports",
        ):
            entries = converted[key]
            if not isinstance(entries, list) or not all(
                isinstance(entry, str) for entry in entries
            ):
                raise ResearchNetworkError("network evidence firewall filters are invalid")
            converted[key] = tuple(entries)
        result.append(FirewallRuleSnapshot(**converted))
    return tuple(result)


def _rule_record(rule: FirewallRuleSnapshot) -> dict[str, Any]:
    return {
        "name": rule.name,
        "display_name": rule.display_name,
        "enabled": rule.enabled,
        "direction": rule.direction,
        "action": rule.action,
        "profile": rule.profile,
        "program_path": str(rule.program_path),
        "protocol": rule.protocol,
        "local_addresses": list(rule.local_addresses),
        "remote_addresses": list(rule.remote_addresses),
        "local_ports": list(rule.local_ports),
        "remote_ports": list(rule.remote_ports),
        "service": rule.service,
        "interface_type": rule.interface_type,
        "policy_store_source_type": rule.policy_store_source_type,
    }


def _canonical_new_evidence_path(path: Path, terminal_root: Path) -> Path:
    if not path.is_absolute() or path.name != "network-isolation-evidence.json":
        raise ResearchNetworkError(
            "network evidence must use the fixed absolute clone-root filename"
        )
    parent = _canonical_directory(path.parent, "network evidence parent")
    if parent != terminal_root:
        raise ResearchNetworkError("network evidence parent must be the private clone root")
    candidate = parent / path.name
    if candidate.exists():
        raise ResearchNetworkError("network evidence already exists; overwrite is prohibited")
    return candidate


def _canonical_file(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ResearchNetworkError(f"{label} must be an absolute path")
    _assert_no_reparse_ancestors(path)
    try:
        canonical = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ResearchNetworkError(f"{label} does not exist: {path}") from exc
    if not canonical.is_file() or _is_reparse(canonical):
        raise ResearchNetworkError(f"{label} is not a regular non-reparse file")
    return canonical


def _canonical_directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ResearchNetworkError(f"{label} must be an absolute path")
    _assert_no_reparse_ancestors(path)
    try:
        canonical = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ResearchNetworkError(f"{label} does not exist: {path}") from exc
    if not canonical.is_dir() or _is_reparse(canonical):
        raise ResearchNetworkError(f"{label} is not a non-reparse directory")
    return canonical


def _assert_no_reparse_ancestors(path: Path) -> None:
    current = path
    while True:
        if current.exists() and _is_reparse(current):
            raise ResearchNetworkError(f"reparse/symlink path is prohibited: {current}")
        if current.parent == current:
            return
        current = current.parent


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(path.lstat().st_file_attributes & 0x400)
    except AttributeError:
        return False


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchNetworkError("network evidence is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ResearchNetworkError("network evidence must be a JSON object")
    return value


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                payload,
                sort_keys=True,
                indent=2,
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        )


def _strict_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ResearchNetworkError(f"{label} must be a lowercase SHA-256")
    return value


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ResearchNetworkError(f"{label} must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ResearchNetworkError(f"{label} is invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ResearchNetworkError(f"{label} must be UTC")
    return parsed


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ResearchNetworkError("network timestamp must be timezone-aware UTC")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


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
