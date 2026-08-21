from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/verify_g17_e2e.py"
SPEC = importlib.util.spec_from_file_location("verify_g17_e2e", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture_root(tmp_path: Path, *, telegram: bool = True) -> Path:
    native = tmp_path / "evidence/G17-happy-path-e2e/native"
    common = {"production_real_orders": "DISABLED"}
    write(
        native / "goldi-e2e.json",
        {
            **common,
            "profile_id": "GOLDI",
            "account_mode": "DEMO",
            "account_login": 108098316,
            "positions_before": 0,
            "positions_after": 0,
            "event_count": 6,
            "chain_id": "G17|GOLDI|1",
        },
    )
    write(
        native / "goldm-e2e.json",
        {
            **common,
            "profile_id": "GOLDM",
            "account_mode": "STRATEGY_TESTER",
            "positions_before": 0,
            "positions_after": 0,
            "event_count": 6,
            "chain_id": "G17|GOLDM|1",
        },
    )
    write(
        native / "goldm_refusal-e2e.json",
        {
            **common,
            "wrong_account_refused": True,
            "wrong_server_refused": True,
            "demo_mode_refused": True,
            "magic": 26081912,
            "order_authority": "DISABLED",
        },
    )
    write(
        native / "bridge-live-demo.json",
        {
            **common,
            "status": "PASS",
            "database_event_count": 12,
            "delivery_calls": 9,
            "goldm_approved_leak_count": 0,
            "telegram_mode": "CAPTURE_SENDER",
            "profiles": {
                "GOLDI": {"chain_id": "G17|GOLDI|1"},
                "GOLDM": {"chain_id": "G17|GOLDM|1"},
            },
        },
    )
    if telegram:
        write(
            native / "telegram-e2e.json",
            {
                **common,
                "status": "PASS",
                "transport": "TELEGRAM_BOT_API",
                "delivery_calls": 9,
                "failed_calls": 0,
                "goldm_approved_leak_count": 0,
                "receipts": [{} for _ in range(9)],
            },
        )
    return tmp_path


def test_verifier_requires_actual_telegram_receipts(tmp_path: Path) -> None:
    with pytest.raises(MODULE.G17VerificationError, match=r"telegram-e2e\.json"):
        MODULE.build_report(fixture_root(tmp_path, telegram=False))


def test_complete_strict_matrix_passes(tmp_path: Path) -> None:
    report = MODULE.build_report(fixture_root(tmp_path))

    assert report["status"] == "PASS"
    assert report["telegram_delivery_calls"] == 9
    assert report["goldm_approved_leak_count"] == 0
    assert report["production_real_orders"] == "DISABLED"
