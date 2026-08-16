from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_THUMBPRINT = re.compile(r"[0-9A-F]{40,64}\Z")
_CLONE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{3,95}\Z")
_BINARY_NAMES = ("terminal64.exe", "metaeditor64.exe", "metatester64.exe")
_MANIFEST_NAME = "portable-clone-manifest.json"
_MANIFEST_FIELDS = {
    "schema_version",
    "status",
    "created_at",
    "source_install_root",
    "destination_root",
    "expected_signer_thumbprint",
    "expected_file_version",
    "directory_security",
    "copied_binaries",
    "excluded_source_state",
    "launch_performed",
    "manifest_sha256",
}


class ResearchEnvironmentError(RuntimeError):
    """Raised when a research terminal environment cannot be proven isolated."""


@dataclass(frozen=True, slots=True)
class AuthenticodeSnapshot:
    status: str
    signer_subject: str
    signer_thumbprint: str
    timestamp_subject: str
    file_version: str


@dataclass(frozen=True, slots=True)
class DirectorySecuritySnapshot:
    owner_sid: str
    current_user_sid: str
    inheritance_protected: bool
    allowed_sids: tuple[str, ...]
    denied_sids: tuple[str, ...]
    full_control_sids: tuple[str, ...]
    non_full_control_rule_count: int
    sddl: str


@dataclass(frozen=True, slots=True)
class PortableCloneEvidence:
    manifest_path: Path
    manifest_file_sha256: str
    manifest_payload_sha256: str
    source_install_root: Path
    destination_root: Path
    copied_binaries: tuple[Mapping[str, Any], ...]


SignatureProbe = Callable[[Path], AuthenticodeSnapshot]
PrivateDirectoryCreator = Callable[[Path], DirectorySecuritySnapshot]
DirectorySecurityProbe = Callable[[Path], DirectorySecuritySnapshot]


def assemble_portable_research_clone(
    *,
    source_install_root: Path,
    destination_root: Path,
    signature_probe: SignatureProbe,
    expected_signer_thumbprint: str,
    expected_file_version: str,
    private_directory_creator: PrivateDirectoryCreator,
    directory_security_probe: DirectorySecurityProbe,
    created_at: datetime | None = None,
) -> PortableCloneEvidence:
    """Copy only signed MT5 binaries into a new clone; never launch them."""

    source = _canonical_directory(source_install_root, "source MT5 installation")
    if signature_probe is None or directory_security_probe is None:
        raise ResearchEnvironmentError("signature and directory-security probes are required")
    if private_directory_creator is None:
        raise ResearchEnvironmentError("atomic private-directory creator is required")
    expected_thumbprint = _strict_thumbprint(expected_signer_thumbprint)
    expected_version = _strict_file_version(expected_file_version)
    destination = _validate_new_destination(destination_root)
    sources = tuple(_canonical_binary(source / name, name) for name in _BINARY_NAMES)
    source_records = tuple(
        _binary_record(
            path,
            signature_probe(path),
            source_path=path,
            expected_signer_thumbprint=expected_thumbprint,
            expected_file_version=expected_version,
        )
        for path in sources
    )
    signer_thumbprints = {record["authenticode"]["signer_thumbprint"] for record in source_records}
    if len(signer_thumbprints) != 1:
        raise ResearchEnvironmentError("MT5 binaries are not signed by one exact certificate")

    parent = _canonical_directory(destination.parent, "clone destination parent")
    partial = parent / f".{destination.name}.partial-{secrets.token_hex(8)}"
    try:
        partial_security = private_directory_creator(partial)
        _validate_directory_security(partial_security)
        if not partial.is_dir() or _is_reparse(partial):
            raise ResearchEnvironmentError(
                "private clone staging directory was not created safely"
            )
        copied_records: list[dict[str, Any]] = []
        for source_path, source_record in zip(sources, source_records, strict=True):
            copied_path = partial / source_path.name
            shutil.copyfile(source_path, copied_path)
            copied_record = _binary_record(
                copied_path,
                signature_probe(copied_path),
                source_path=source_path,
                expected_signer_thumbprint=expected_thumbprint,
                expected_file_version=expected_version,
            )
            if (
                copied_record["sha256"] != source_record["sha256"]
                or copied_record["size"] != source_record["size"]
                or copied_record["authenticode"] != source_record["authenticode"]
            ):
                raise ResearchEnvironmentError(
                    f"copied MT5 binary differs from signed source: {source_path.name}"
                )
            copied_records.append(copied_record)

        manifest_path = partial / _MANIFEST_NAME
        final_manifest_path = destination / _MANIFEST_NAME
        payload: dict[str, Any] = {
            "schema_version": 2,
            "status": "CLEAN_PORTABLE_CLONE_ASSEMBLED_NOT_LAUNCHED",
            "created_at": _utc_timestamp(created_at or datetime.now(timezone.utc)),
            "source_install_root": str(source),
            "destination_root": str(destination),
            "expected_signer_thumbprint": expected_thumbprint,
            "expected_file_version": expected_version,
            "directory_security": _directory_security_record(partial_security),
            "copied_binaries": copied_records,
            "excluded_source_state": [
                "Bases",
                "Config",
                "Profiles",
                "Sounds",
                "uninstall.exe",
                "%APPDATA%\\MetaQuotes\\Terminal",
            ],
            "launch_performed": False,
        }
        payload["manifest_sha256"] = _canonical_json_sha256(payload)
        _write_json_exclusive(manifest_path, payload)
        os.rename(partial, destination)
        if not final_manifest_path.is_file():
            raise ResearchEnvironmentError("clone manifest disappeared after atomic publish")
    except Exception:
        if partial.exists():
            shutil.rmtree(partial)
        raise
    return verify_portable_research_clone(
        destination / _MANIFEST_NAME,
        signature_probe=signature_probe,
        expected_signer_thumbprint=expected_thumbprint,
        expected_file_version=expected_version,
        directory_security_probe=directory_security_probe,
        require_pristine=True,
        require_source_unchanged=True,
    )


def verify_portable_research_clone(
    manifest_path: Path,
    *,
    signature_probe: SignatureProbe,
    expected_signer_thumbprint: str,
    expected_file_version: str,
    directory_security_probe: DirectorySecurityProbe,
    require_pristine: bool,
    require_source_unchanged: bool = False,
) -> PortableCloneEvidence:
    manifest = _canonical_file(manifest_path, "portable clone manifest")
    payload = _read_json_object(manifest, "portable clone manifest")
    if set(payload) != _MANIFEST_FIELDS or payload.get("schema_version") != 2:
        raise ResearchEnvironmentError(
            "portable clone manifest must use schema_version 2 with exact fields"
        )
    supplied_hash = _strict_sha256(payload["manifest_sha256"], "manifest SHA-256")
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256")
    if _canonical_json_sha256(unsigned) != supplied_hash:
        raise ResearchEnvironmentError("portable clone manifest self-hash mismatch")
    if payload["status"] != "CLEAN_PORTABLE_CLONE_ASSEMBLED_NOT_LAUNCHED":
        raise ResearchEnvironmentError("portable clone manifest status is invalid")
    if payload["launch_performed"] is not False:
        raise ResearchEnvironmentError("portable clone assembly cannot claim a launch")
    _parse_utc(payload["created_at"], "clone created_at")

    source = _absolute_path_without_resolution(
        Path(payload["source_install_root"]), "manifest source MT5 installation"
    )
    destination = _canonical_directory(
        Path(payload["destination_root"]), "manifest destination root"
    )
    if manifest.parent != destination:
        raise ResearchEnvironmentError("portable clone manifest is outside its destination root")
    if (
        source == destination
        or destination.is_relative_to(source)
        or source.is_relative_to(destination)
    ):
        raise ResearchEnvironmentError("source and destination clone roots overlap")
    if signature_probe is None or directory_security_probe is None:
        raise ResearchEnvironmentError("signature and directory-security probes are required")
    expected_thumbprint = _strict_thumbprint(expected_signer_thumbprint)
    expected_version = _strict_file_version(expected_file_version)
    if payload["expected_signer_thumbprint"] != expected_thumbprint:
        raise ResearchEnvironmentError("portable clone signer trust anchor mismatch")
    if payload["expected_file_version"] != expected_version:
        raise ResearchEnvironmentError("portable clone build trust anchor mismatch")
    security = directory_security_probe(destination)
    _validate_directory_security(security)
    if payload["directory_security"] != _directory_security_record(security):
        raise ResearchEnvironmentError("portable clone directory security changed")

    records = payload["copied_binaries"]
    if not isinstance(records, list) or len(records) != len(_BINARY_NAMES):
        raise ResearchEnvironmentError("portable clone binary inventory is incomplete")
    if [record.get("name") for record in records if isinstance(record, dict)] != list(
        _BINARY_NAMES
    ):
        raise ResearchEnvironmentError("portable clone binary inventory order/names are invalid")
    verified_records: list[dict[str, Any]] = []
    for record, name in zip(records, _BINARY_NAMES, strict=True):
        if not isinstance(record, dict) or set(record) != {
            "name",
            "source_path",
            "size",
            "sha256",
            "authenticode",
        }:
            raise ResearchEnvironmentError("portable clone binary record fields are invalid")
        source_path = _absolute_path_without_resolution(
            Path(record["source_path"]), f"source {name}"
        )
        if source_path != source / name:
            raise ResearchEnvironmentError("portable clone source binary path mismatch")
        copied_path = _canonical_binary(destination / name, f"copied {name}")
        observed = _binary_record(
            copied_path,
            signature_probe(copied_path),
            source_path=source_path,
            expected_signer_thumbprint=expected_thumbprint,
            expected_file_version=expected_version,
        )
        if record != observed:
            raise ResearchEnvironmentError(f"portable clone binary changed: {name}")
        if require_source_unchanged:
            source_current = _canonical_binary(source_path, f"source {name}")
            source_observed = _binary_record(
                source_current,
                signature_probe(source_current),
                source_path=source_path,
                expected_signer_thumbprint=expected_thumbprint,
                expected_file_version=expected_version,
            )
            if source_observed != observed:
                raise ResearchEnvironmentError(f"signed source binary changed: {name}")
        verified_records.append(observed)
    if {
        record["authenticode"]["signer_thumbprint"] for record in verified_records
    } != {expected_thumbprint}:
        raise ResearchEnvironmentError("portable clone binaries do not share the trust anchor")

    excluded = payload["excluded_source_state"]
    if excluded != [
        "Bases",
        "Config",
        "Profiles",
        "Sounds",
        "uninstall.exe",
        "%APPDATA%\\MetaQuotes\\Terminal",
    ]:
        raise ResearchEnvironmentError("portable clone excluded-state declaration changed")
    if require_pristine:
        observed_entries = sorted(item.name.casefold() for item in destination.iterdir())
        expected_entries = sorted((*_BINARY_NAMES, _MANIFEST_NAME))
        if observed_entries != expected_entries:
            raise ResearchEnvironmentError(
                "pristine portable clone contains undeclared files or directories"
            )
    for forbidden in (
        destination / "origin.txt",
        destination / "Config",
        destination / "Bases",
        destination / "Profiles",
        destination / "MQL5",
        destination / "Tester",
    ):
        if require_pristine and forbidden.exists():
            raise ResearchEnvironmentError(f"pristine clone contains forbidden state: {forbidden}")
    return PortableCloneEvidence(
        manifest_path=manifest,
        manifest_file_sha256=_sha256(manifest),
        manifest_payload_sha256=supplied_hash,
        source_install_root=source,
        destination_root=destination,
        copied_binaries=tuple(verified_records),
    )


def _binary_record(
    path: Path,
    signature: AuthenticodeSnapshot,
    *,
    source_path: Path,
    expected_signer_thumbprint: str,
    expected_file_version: str,
) -> dict[str, Any]:
    _validate_signature(
        signature,
        path.name,
        expected_signer_thumbprint=expected_signer_thumbprint,
        expected_file_version=expected_file_version,
    )
    return {
        "name": path.name.casefold(),
        "source_path": str(source_path),
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "authenticode": {
            "status": signature.status,
            "signer_subject": signature.signer_subject,
            "signer_thumbprint": signature.signer_thumbprint,
            "timestamp_subject": signature.timestamp_subject,
            "file_version": signature.file_version,
        },
    }


def _validate_signature(
    signature: AuthenticodeSnapshot,
    name: str,
    *,
    expected_signer_thumbprint: str,
    expected_file_version: str,
) -> None:
    if not isinstance(signature, AuthenticodeSnapshot):
        raise ResearchEnvironmentError(f"signature probe returned invalid data for {name}")
    if signature.status != "Valid":
        raise ResearchEnvironmentError(f"Authenticode signature is not valid for {name}")
    if signature.signer_subject != (
        "CN=MetaQuotes Ltd., O=MetaQuotes Ltd., S=Lemesos, C=CY"
    ):
        raise ResearchEnvironmentError(f"Authenticode signer is not MetaQuotes for {name}")
    if signature.signer_thumbprint != expected_signer_thumbprint:
        raise ResearchEnvironmentError(f"Authenticode thumbprint mismatch for {name}")
    if not signature.timestamp_subject or signature.file_version != expected_file_version:
        raise ResearchEnvironmentError(f"signature/version evidence is incomplete for {name}")


def _validate_directory_security(snapshot: DirectorySecuritySnapshot) -> None:
    if not isinstance(snapshot, DirectorySecuritySnapshot):
        raise ResearchEnvironmentError("directory-security probe returned invalid data")
    allowed = set(snapshot.allowed_sids)
    required = {snapshot.current_user_sid, "S-1-5-18", "S-1-5-32-544"}
    if (
        not snapshot.inheritance_protected
        or snapshot.owner_sid != snapshot.current_user_sid
        or allowed != required
        or snapshot.denied_sids
        or set(snapshot.full_control_sids) != required
        or snapshot.non_full_control_rule_count != 0
        or not snapshot.sddl
    ):
        raise ResearchEnvironmentError("portable clone directory ACL is not exact/private")


def _directory_security_record(snapshot: DirectorySecuritySnapshot) -> dict[str, Any]:
    return {
        "owner_sid": snapshot.owner_sid,
        "current_user_sid": snapshot.current_user_sid,
        "inheritance_protected": snapshot.inheritance_protected,
        "allowed_sids": list(snapshot.allowed_sids),
        "denied_sids": list(snapshot.denied_sids),
        "full_control_sids": list(snapshot.full_control_sids),
        "non_full_control_rule_count": snapshot.non_full_control_rule_count,
        "sddl": snapshot.sddl,
    }


def _validate_new_destination(path: Path) -> Path:
    if not path.is_absolute() or not _CLONE_NAME.fullmatch(path.name):
        raise ResearchEnvironmentError(
            "clone destination must be an absolute, new, structured leaf directory"
        )
    _assert_no_reparse_ancestors(path.parent)
    parent = _canonical_directory(path.parent, "clone destination parent")
    destination = parent / path.name
    if destination.exists():
        raise ResearchEnvironmentError("clone destination already exists; overwrite is prohibited")
    return destination


def _canonical_binary(path: Path, label: str) -> Path:
    candidate = _canonical_file(path, label)
    if candidate.name.casefold() not in _BINARY_NAMES:
        raise ResearchEnvironmentError(f"{label} is not an approved MT5 executable")
    return candidate


def _canonical_file(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ResearchEnvironmentError(f"{label} must be an absolute path")
    _assert_no_reparse_ancestors(path)
    try:
        canonical = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ResearchEnvironmentError(f"{label} does not exist: {path}") from exc
    if not canonical.is_file() or _is_reparse(canonical):
        raise ResearchEnvironmentError(f"{label} is not a regular non-reparse file")
    return canonical


def _canonical_directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ResearchEnvironmentError(f"{label} must be an absolute path")
    _assert_no_reparse_ancestors(path)
    try:
        canonical = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ResearchEnvironmentError(f"{label} does not exist: {path}") from exc
    if not canonical.is_dir() or _is_reparse(canonical):
        raise ResearchEnvironmentError(f"{label} is not a non-reparse directory")
    return canonical


def _absolute_path_without_resolution(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ResearchEnvironmentError(f"{label} must be an absolute path")
    return Path(os.path.abspath(path))


def _assert_no_reparse_ancestors(path: Path) -> None:
    current = path
    while True:
        if current.exists() and _is_reparse(current):
            raise ResearchEnvironmentError(f"reparse/symlink path is prohibited: {current}")
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


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchEnvironmentError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ResearchEnvironmentError(f"{label} must be a JSON object")
    return payload


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


def _parse_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ResearchEnvironmentError(f"{label} must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ResearchEnvironmentError(f"{label} is invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ResearchEnvironmentError(f"{label} must be UTC")
    return parsed


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ResearchEnvironmentError("clone timestamp must be timezone-aware UTC")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _strict_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ResearchEnvironmentError(f"{label} must be a lowercase SHA-256")
    return value


def _strict_thumbprint(value: Any) -> str:
    if not isinstance(value, str):
        raise ResearchEnvironmentError("signer thumbprint must be a string")
    normalized = value.upper()
    if not _THUMBPRINT.fullmatch(normalized):
        raise ResearchEnvironmentError("signer thumbprint is invalid")
    return normalized


def _strict_file_version(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", value):
        raise ResearchEnvironmentError("MT5 file version must contain four numeric parts")
    return value


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
