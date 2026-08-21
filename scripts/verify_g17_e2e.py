from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class G17VerificationError(RuntimeError):
    pass


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise G17VerificationError(f"required G17 evidence missing: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise G17VerificationError(f"G17 evidence must be an object: {path.name}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise G17VerificationError(message)


def build_report(root: Path) -> dict[str, Any]:
    native = root / "evidence/G17-happy-path-e2e/native"
    paths = {
        "goldi": native / "goldi-e2e.json",
        "goldm": native / "goldm-e2e.json",
        "goldm_refusal": native / "goldm_refusal-e2e.json",
        "bridge": native / "bridge-live-demo.json",
        "telegram": native / "telegram-e2e.json",
    }
    values = {key: _json(path) for key, path in paths.items()}
    goldi = values["goldi"]
    goldm = values["goldm"]
    refusal = values["goldm_refusal"]
    bridge = values["bridge"]
    telegram = values["telegram"]

    _require(
        goldi.get("profile_id") == "GOLDI"
        and goldi.get("account_mode") == "DEMO"
        and goldi.get("account_login") == 108098316
        and goldi.get("positions_before") == goldi.get("positions_after") == 0
        and goldi.get("event_count") == 6,
        "GOLDI actual DEMO chain is incomplete",
    )
    _require(
        goldm.get("profile_id") == "GOLDM"
        and goldm.get("account_mode") == "STRATEGY_TESTER"
        and goldm.get("positions_before") == goldm.get("positions_after") == 0
        and goldm.get("event_count") == 6,
        "GOLDM tester chain is incomplete",
    )
    _require(
        refusal.get("wrong_account_refused") is True
        and refusal.get("wrong_server_refused") is True
        and refusal.get("demo_mode_refused") is True
        and refusal.get("magic") == 26081912
        and refusal.get("order_authority") == "DISABLED",
        "GOLDM refusal matrix is incomplete",
    )
    _require(
        bridge.get("status") == "PASS"
        and bridge.get("database_event_count") == 12
        and bridge.get("delivery_calls") == 9
        and bridge.get("goldm_approved_leak_count") == 0
        and bridge.get("telegram_mode") == "CAPTURE_SENDER",
        "spool/database/capture-sender chain is incomplete",
    )
    profiles = bridge.get("profiles") or {}
    _require(
        profiles.get("GOLDI", {}).get("chain_id") == goldi.get("chain_id")
        and profiles.get("GOLDM", {}).get("chain_id") == goldm.get("chain_id"),
        "DB chain IDs do not match native lifecycle IDs",
    )
    _require(
        telegram.get("status") == "PASS"
        and telegram.get("transport") == "TELEGRAM_BOT_API"
        and telegram.get("delivery_calls") == 9
        and telegram.get("failed_calls") == 0
        and telegram.get("goldm_approved_leak_count") == 0
        and len(telegram.get("receipts") or []) == 9,
        "actual Telegram receipt matrix is incomplete",
    )
    for value in values.values():
        _require(
            value.get("production_real_orders") == "DISABLED",
            "production REAL authority was not disabled in every evidence source",
        )
    return {
        "schema_version": 1,
        "gate": "G17",
        "status": "PASS",
        "chains": {"GOLDI": goldi["chain_id"], "GOLDM": goldm["chain_id"]},
        "database_event_count": 12,
        "telegram_delivery_calls": 9,
        "goldm_approved_leak_count": 0,
        "input_sha256": {key: _sha256(path) for key, path in paths.items()},
        "production_real_orders": "DISABLED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify strict G17 E2E evidence")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(args.root.resolve())
    encoded = (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(encoded)
        args.output.with_suffix(".sha256").write_text(
            f"{hashlib.sha256(encoded).hexdigest()}  {args.output.name}\n", encoding="ascii"
        )
    print(encoded.decode().strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
