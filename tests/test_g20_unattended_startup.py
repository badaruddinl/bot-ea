from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = ROOT / "scripts/g20-unattended-supervisor.ps1"
INSTALLER = ROOT / "scripts/install-g20-unattended-task.ps1"
EXAMPLE = ROOT / "config/mql5/g20-unattended.example.json"
GOLDI_STARTUP = ROOT / "config/mql5/startup/GOLDI.ini"
GOLDM_STARTUP = ROOT / "config/mql5/startup/GOLDM.ini"
GOLDI_PRESET = ROOT / "config/mql5/presets/G20-GOLDI.set"
GOLDM_PRESET = ROOT / "config/mql5/presets/G20-GOLDM.set"
PREPARE = ROOT / "scripts/prepare-g20-vm.ps1"
BRIDGE_RUNNER = ROOT / "scripts/run-gold-event-bridge.py"
SECRET_INSTALLER = ROOT / "scripts/set-g20-telegram-secret.ps1"
CHAT_INSPECTOR = ROOT / "scripts/inspect-g20-telegram-chats.ps1"
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
    assert [item["expected_order_authority"] for item in payload["terminals"]] == [
        "ENABLED",
        "DISABLED",
    ]
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


def test_startup_configs_enable_demo_execution_only_and_keep_real_disabled() -> None:
    goldi = GOLDI_STARTUP.read_text(encoding="utf-8")
    goldm = GOLDM_STARTUP.read_text(encoding="utf-8")
    goldi_preset = GOLDI_PRESET.read_text(encoding="utf-8")
    goldm_preset = GOLDM_PRESET.read_text(encoding="utf-8")

    assert "AllowLiveTrading=1" in goldi
    assert "InpEnableOrderAuthority=true" in goldi_preset
    assert "AllowLiveTrading=0" in goldm
    assert "InpEnableOrderAuthority=false" in goldm_preset
    assert "Expert=bot-ea\\GoldEngine-GOLDi" in goldi
    assert "Expert=bot-ea\\GoldEngine-GOLDm" in goldm


def test_vm_preparer_installs_only_native_engines_and_optional_bridge() -> None:
    value = PREPARE.read_text(encoding="utf-8")
    runner = BRIDGE_RUNNER.read_text(encoding="utf-8")

    assert "GoldEngine-GOLDi.ex5" in value
    assert "GoldEngine-GOLDm.ex5" in value
    assert 'order_authority = "ENABLED"' in value
    assert 'order_authority = "DISABLED"' in value
    assert "TelegramSecretPath" in value
    assert "TelegramAdminChatIds" in value
    assert "run-gold-event-bridge.py" in value
    assert "gold_orchestrator" not in value
    assert "goldm_revised" not in value
    assert "goldm_bear" not in value
    assert "from gold_event_bridge.cli import main" in runner


def test_bridge_token_uses_current_user_dpapi_and_never_enters_process_arguments() -> None:
    supervisor = SUPERVISOR.read_text(encoding="utf-8")
    secret_installer = SECRET_INSTALLER.read_text(encoding="utf-8")

    assert "SecureStringToBSTR" in supervisor
    assert "ZeroFreeBSTR" in supervisor
    assert ").Trim()" in supervisor
    assert "token_secret_path" in supervisor
    assert "TELEGRAM_BOT_TOKEN" in supervisor
    assert "Read-Host" in secret_installer
    assert "-AsSecureString" in secret_installer
    assert "ConvertFrom-SecureString" in secret_installer
    assert "SetAccessRuleProtection" in secret_installer
    assert "Token=" not in secret_installer


def test_capture_classifies_script_and_module_bridge_names() -> None:
    capture = (ROOT / "scripts/capture-g20-unattended-evidence.ps1").read_text(encoding="utf-8")

    assert "gold_event_bridge|run-gold-event-bridge" in capture


def test_chat_inspector_never_accepts_or_prints_plaintext_token() -> None:
    value = CHAT_INSPECTOR.read_text(encoding="utf-8")

    assert "token_secret_path" not in value
    assert "ConvertTo-SecureString" in value
    assert "ZeroFreeBSTR" in value
    assert "getUpdates" in value
    assert "chat_id" in value
    assert "Write-Output $token" not in value
    assert "param(\n    [string]$SecretPath" in value
