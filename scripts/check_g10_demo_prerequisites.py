from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import sys
from datetime import datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from gold_engine_core import (  # noqa: E402
    DemoRuntimeBinding,
    RuntimeValidationBinding,
    load_demo_validation_manifest,
    load_named_profile,
    load_runtime_validation_manifest,
    validate_demo_binding,
    validate_runtime_binding,
)


def build_report(repository_root: Path) -> dict[str, object]:
    profiles: list[dict[str, object]] = []
    errors: list[str] = []
    definitions = (
        ("GOLDI", "demo_execution", "GOLDI_DEMO.json"),
        ("GOLDM", "read_only", "GOLDM_REAL_READ_ONLY.json"),
    )
    for profile_id, access_mode, filename in definitions:
        manifest_path = repository_root / "config" / "validation_profiles" / filename
        if profile_id == "GOLDI":
            demo_manifest = load_demo_validation_manifest(manifest_path)
            manifest = demo_manifest
        else:
            read_only_manifest = load_runtime_validation_manifest(manifest_path)
            manifest = read_only_manifest
        production = load_named_profile(repository_root, profile_id)
        path_value = os.environ.get(manifest.terminal_path_env, "").strip()
        login_value = os.environ.get(manifest.login_env, "").strip()
        server_value = os.environ.get(manifest.server_env, "").strip()
        path_present = bool(path_value)
        path_exists = bool(path_value and Path(path_value).is_file())
        login_present = login_value.isascii() and login_value.isdecimal()
        server_present = bool(server_value)
        terminal_path_sha256 = (
            hashlib.sha256(str(Path(path_value).resolve()).casefold().encode("utf-8")).hexdigest()
            if path_exists
            else None
        )
        binding_valid = False
        if path_exists and login_present and server_present:
            try:
                if profile_id == "GOLDI":
                    production_login_value = os.environ.get(
                        production.terminal.expected_login_env, ""
                    ).strip()
                    production_login = (
                        int(production_login_value) if production_login_value.isdecimal() else None
                    )
                    validate_demo_binding(
                        demo_manifest,
                        production,
                        DemoRuntimeBinding(
                            manifest.validation_profile_id,
                            path_value,
                            int(login_value),
                            server_value,
                            "demo",
                            manifest.symbol,
                        ),
                        production_login=production_login,
                    )
                else:
                    validate_runtime_binding(
                        read_only_manifest,
                        production,
                        RuntimeValidationBinding(
                            manifest.validation_profile_id,
                            path_value,
                            int(login_value),
                            server_value,
                            "real",
                            manifest.symbol,
                            access_mode,
                        ),
                    )
                binding_valid = True
            except ValueError as exc:
                errors.append(f"{profile_id}:{type(exc).__name__}:{exc}")
        for label, passed in (
            ("terminal_path_env_present", path_present),
            ("terminal_path_exists", path_exists),
            ("login_env_present", login_present),
            ("server_env_present", server_present),
            ("binding_valid", binding_valid),
        ):
            if not passed:
                errors.append(f"{profile_id}:{label}=false")
        profiles.append(
            {
                "audience": manifest.audience,
                "access_mode": access_mode,
                "binding_valid": binding_valid,
                "derived_profile_fingerprint": manifest.derived_profile_fingerprint,
                "login_env_present": login_present,
                "production_real_authority": manifest.production_real_authority,
                "profile_id": profile_id,
                "server_env_present": server_present,
                "symbol": manifest.symbol,
                "terminal_path_env_present": path_present,
                "terminal_path_exists": path_exists,
                "terminal_path_sha256": terminal_path_sha256,
                "validation_profile_id": manifest.validation_profile_id,
            }
        )
    path_hashes = [
        profile["terminal_path_sha256"]
        for profile in profiles
        if profile["terminal_path_sha256"] is not None
    ]
    if len(path_hashes) == 2 and len(set(path_hashes)) != 2:
        errors.append("validation_terminal_paths_are_not_distinct")
    mt5_module_available = importlib.util.find_spec("MetaTrader5") is not None
    if not mt5_module_available:
        errors.append("MetaTrader5_module_available=false")
    return {
        "captured_at": datetime.now().astimezone().isoformat(),
        "host": {
            "machine": platform.machine(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "mt5_module_available": mt5_module_available,
        "profiles": profiles,
        "production_real_orders": "DISABLED",
        "ready": not errors,
        "errors": sorted(set(errors)),
    }


def main() -> int:
    output_root = REPOSITORY_ROOT / "evidence" / "G10-reference-live-validation"
    output_root.mkdir(parents=True, exist_ok=True)
    report = build_report(REPOSITORY_ROOT)
    raw = (
        json.dumps(report, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    path = output_root / "prerequisites.json"
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    path.with_suffix(".sha256").write_bytes(f"{digest}  {path.name}\n".encode("ascii"))
    print(f"ready={str(bool(report['ready'])).lower()} sha256={digest}")
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
