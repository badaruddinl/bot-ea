from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from gold_portfolio.config import load_worker_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def bind_demo_env(monkeypatch) -> None:
    monkeypatch.setenv("GOLDI_MT5_TERMINAL_PATH", "C:/GoldiDemo/terminal64.exe")
    monkeypatch.setenv("GOLDI_MT5_LOGIN", "123456")
    monkeypatch.setenv("GOLDI_MT5_SERVER", "GOLDI-DEMO")
    monkeypatch.setenv("GOLDM_DEMO_MT5_TERMINAL_PATH", "C:/GoldmDemo/terminal64.exe")
    monkeypatch.setenv("GOLDM_DEMO_MT5_LOGIN", "654321")
    monkeypatch.setenv("GOLDM_DEMO_MT5_SERVER", "GOLDM-DEMO")


@pytest.mark.parametrize("profile", ["goldi", "goldm"])
def test_shadow_and_guarded_demo_configs_are_separate_and_profile_bound(
    monkeypatch,
    profile: str,
) -> None:
    bind_demo_env(monkeypatch)
    root = REPOSITORY_ROOT / "config" / "validation" / profile
    shadow = load_worker_config(root / "worker-shadow.json")
    demo = load_worker_config(root / "worker-demo.json")

    assert shadow.group == demo.group == profile
    assert shadow.symbol == demo.symbol
    assert shadow.execution_mode == "signal_only"
    assert shadow.orders_enabled is False
    assert demo.execution_mode == "demo"
    assert demo.orders_enabled is True
    assert demo.terminal.expected_trade_mode == "demo"
    assert shadow.state_path != demo.state_path
    assert shadow.audit_path != demo.audit_path
    assert shadow.telegram.audience == demo.telegram.audience == "admin_only"
    if profile == "goldm":
        assert demo.terminal.path == "C:/GoldmDemo/terminal64.exe"
        assert demo.terminal.expected_login == 654321
        portfolio_source = (root / "portfolio-demo.json").read_text(encoding="utf-8")
        assert "GOLDM_REAL_" not in portfolio_source
        assert demo.magic == 26081912
    else:
        assert demo.terminal.path == "C:/GoldiDemo/terminal64.exe"
        assert demo.magic == 26081911


def test_validation_config_never_changes_goldm_production_contract(monkeypatch) -> None:
    bind_demo_env(monkeypatch)
    monkeypatch.setenv("GOLDM_REAL_MT5_TERMINAL_PATH", "C:/GoldmReal/terminal64.exe")
    monkeypatch.setenv("GOLDM_REAL_MT5_LOGIN", "999999")
    monkeypatch.setenv("GOLDM_REAL_MT5_SERVER", "GOLDM-REAL")
    validation = load_worker_config(
        REPOSITORY_ROOT / "config" / "validation" / "goldm" / "worker-demo.json"
    )
    production = load_worker_config(REPOSITORY_ROOT / "config" / "final" / "goldm" / "worker.json")

    assert validation.terminal.path != production.terminal.path
    assert validation.terminal.expected_login != production.terminal.expected_login
    assert validation.execution_mode == "demo"
    assert production.execution_mode == "real"
    assert validation.state_path != production.state_path


def test_g10_probe_is_read_only_and_preflight_never_persists_bindings(monkeypatch) -> None:
    probe_source = (REPOSITORY_ROOT / "scripts" / "run_g10_profile_probe.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "order_send(",
        "order_check(",
        "positions_get(",
        "TRADE_ACTION_",
    ):
        assert forbidden not in probe_source

    sentinel_login = "812345678"
    sentinel_server = "PRIVATE-DEMO-SERVER-SENTINEL"
    monkeypatch.setenv("GOLDM_DEMO_MT5_LOGIN", sentinel_login)
    monkeypatch.setenv("GOLDM_DEMO_MT5_SERVER", sentinel_server)
    report_builder = runpy.run_path(
        str(REPOSITORY_ROOT / "scripts" / "check_g10_demo_prerequisites.py")
    )["build_report"]
    report = report_builder(REPOSITORY_ROOT)
    report_text = str(report)

    assert sentinel_login not in report_text
    assert sentinel_server not in report_text
    assert report["production_real_orders"] == "DISABLED"
