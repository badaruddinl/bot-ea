from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = ROOT / "scripts/g20-unattended-supervisor.ps1"
INSTALLER = ROOT / "scripts/install-g20-unattended-task.ps1"
EXAMPLE = ROOT / "config/mql5/g20-unattended.example.json"
RUNTIME = ROOT / "mt5/Include/bot-ea/GoldEngineRuntime.mqh"
EVENTS = ROOT / "src/gold_event_bridge/events.py"


def test_installer_uses_password_backed_at_startup_task_without_serializing_secret() -> None:
    value = INSTALLER.read_text(encoding="utf-8")

    assert "New-ScheduledTaskTrigger -AtStartup" in value
    assert "-User $Credential.UserName -Password $password" in value
    assert 'Principal.LogonType -ne "Password"' in value
    assert "MSFT_TaskBootTrigger" in value
    assert "AtLogOn" not in value
    assert "Export-Clixml" not in value
    assert "ConvertFrom-SecureString" not in value
    assert "SYSTEM" not in value


def test_supervisor_runs_only_native_terminals_and_optional_delivery_bridge() -> None:
    value = SUPERVISOR.read_text(encoding="utf-8")

    assert "Get-ExactProcess" in value
    assert "Get-PortableProcessId" in value
    assert "Assert-FileHash" in value
    assert "Ensure-ParentDirectory -Path $auditPath" in value
    assert 'production_real_orders -ne "DISABLED"' in value
    assert "Exactly two terminal profiles are required" in value
    assert "GOLDI,GOLDM" in value
    assert "distinct terminal installations" in value
    assert "gold_orchestrator" not in value
    assert "run-final-portfolio-worker" not in value
    assert "goldm_revised" not in value
    assert "goldm_bear" not in value


def test_example_config_is_non_secret_and_requires_certified_binary_hashes() -> None:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    assert payload["production_real_orders"] == "DISABLED"
    assert [item["profile_id"] for item in payload["terminals"]] == ["GOLDI", "GOLDM"]
    assert all("ea_sha256" in item for item in payload["terminals"])
    assert [item["expected_trade_mode"] for item in payload["terminals"]] == [0, 2]
    assert all("expected_profile_fingerprint" in item for item in payload["terminals"])
    assert all("spool_path" in item for item in payload["terminals"])
    encoded = EXAMPLE.read_text(encoding="utf-8").lower()
    assert "password" not in encoded
    assert "bot_token" not in encoded


def test_native_ea_emits_bounded_internal_health_evidence() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    events = EVENTS.read_text(encoding="utf-8")

    assert 'EmitTransition("ENGINE_HEARTBEAT"' in runtime
    assert "m_next_heartbeat_at=TimeCurrent()+60" in runtime
    assert "m_next_heartbeat_at=raw_tick.time+3600" in runtime
    assert "account_login" in runtime
    assert "account_server" in runtime
    assert "order_authority" in runtime
    assert '"ENGINE_HEARTBEAT"' in events
