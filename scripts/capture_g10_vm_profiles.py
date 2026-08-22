from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_g10_demo_prerequisites import build_report  # noqa: E402
from run_g10_profile_probe import probe  # noqa: E402

_ENV_FIELDS = {
    "GOLDI": {
        "GOLDI_MT5_TERMINAL_PATH": "terminal_path",
        "GOLDI_MT5_LOGIN": "expected_account_login",
        "GOLDI_MT5_SERVER": "expected_account_server",
    },
    "GOLDM": {
        "GOLDM_REAL_MT5_TERMINAL_PATH": "terminal_path",
        "GOLDM_REAL_MT5_LOGIN": "expected_account_login",
        "GOLDM_REAL_MT5_SERVER": "expected_account_server",
    },
}


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_evidence(path: Path, value: object) -> None:
    raw = _canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.with_suffix(".sha256").write_text(
        f"{hashlib.sha256(raw).hexdigest()}  {path.name}\n",
        encoding="ascii",
    )


def _load_bindings(config_path: Path) -> dict[str, dict[str, object]]:
    value: object = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("G20 config must be an object")
    if value.get("production_real_orders") != "DISABLED":
        raise ValueError("G20 config does not prove REAL orders disabled")
    terminals = value.get("terminals")
    if not isinstance(terminals, list):
        raise ValueError("G20 config terminals must be an array")
    bindings: dict[str, dict[str, object]] = {}
    for item in terminals:
        if not isinstance(item, dict):
            raise ValueError("G20 terminal binding must be an object")
        profile_id = item.get("profile_id")
        if profile_id in _ENV_FIELDS:
            bindings[cast(str, profile_id)] = cast(dict[str, object], item)
    if set(bindings) != set(_ENV_FIELDS):
        raise ValueError("G20 config must contain exactly GOLDI and GOLDM bindings")
    paths = [str(bindings[name].get("terminal_path", "")).casefold() for name in _ENV_FIELDS]
    if not all(paths) or len(set(paths)) != 2:
        raise ValueError("G10 validation terminal paths must be distinct")
    return bindings


@contextmanager
def _validation_environment(bindings: Mapping[str, Mapping[str, object]]):
    previous: dict[str, str | None] = {}
    try:
        for profile_id, fields in _ENV_FIELDS.items():
            binding = bindings[profile_id]
            for env_name, field_name in fields.items():
                value = str(binding.get(field_name, "")).strip()
                if not value:
                    raise ValueError(f"{profile_id} binding is missing {field_name}")
                previous[env_name] = os.environ.get(env_name)
                os.environ[env_name] = value
        yield
    finally:
        for env_name, value in previous.items():
            if value is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = value


def capture(
    config_path: Path,
    output_root: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    report_builder: Callable[[Path], dict[str, object]] = build_report,
    profile_probe: Callable[[str, Path], dict[str, object]] = probe,
) -> dict[str, object]:
    bindings = _load_bindings(config_path)
    with _validation_environment(bindings):
        prerequisites = report_builder(repository_root)
        if prerequisites.get("ready") is not True:
            raise RuntimeError(
                "G10 prerequisites failed: "
                + ",".join(str(item) for item in prerequisites.get("errors", []))
            )
        _write_evidence(output_root / "prerequisites.json", prerequisites)
        probes = {
            profile_id: profile_probe(profile_id, output_root / f"{profile_id}-probe.json")
            for profile_id in ("GOLDI", "GOLDM")
        }
    summary = {
        "profiles": ["GOLDI", "GOLDM"],
        "production_real_orders": "DISABLED",
        "ready": True,
        "orders_sent": {
            profile_id: int(value.get("orders_sent", -1))
            for profile_id, value in probes.items()
        },
    }
    _write_evidence(output_root / "capture-summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture actual dual-profile G10 VM probes")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    summary = capture(args.config, args.output_root)
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
