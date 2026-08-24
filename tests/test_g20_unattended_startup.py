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
CONTROL_RUNNER = ROOT / "scripts/run-g20-telegram-control.py"
SECRET_INSTALLER = ROOT / "scripts/set-g20-telegram-secret.ps1"
CHAT_INSPECTOR = ROOT / "scripts/inspect-g20-telegram-chats.ps1"
INTERACTIVE_INSTALLER = ROOT / "scripts/install-g20-interactive-tasks.ps1"
LOCK_SCRIPT = ROOT / "scripts/g20-lock-workstation.ps1"
AUTOLOGON_VERIFIER = ROOT / "scripts/verify-g20-autologon-tool.ps1"
CHART_REPAIR = ROOT / "scripts/repair-g20-startup-chart.ps1"
RUNTIME = ROOT / "mt5/Include/bot-ea/GoldEngineRuntime.mqh"
GOLDI_ENTRYPOINT = ROOT / "mt5/Experts/bot-ea/GoldEngine-GOLDi.mq5"
GOLDM_ENTRYPOINT = ROOT / "mt5/Experts/bot-ea/GoldEngine-GOLDm.mq5"
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
    assert "telegram_control" in value
    assert 'order_authority = "NONE"' in value
    assert "Start-TelegramProcess" in value
    assert "Get-ExactManagedProcess" in value


def test_example_config_is_non_secret_and_requires_certified_binary_hashes() -> None:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    assert payload["production_real_orders"] == "DISABLED"
    assert payload["startup_mode"] == "PASSWORD_AT_STARTUP"
    assert [item["profile_id"] for item in payload["terminals"]] == ["GOLDI", "GOLDM"]
    assert all("ea_sha256" in item for item in payload["terminals"])
    assert [item["expected_trade_mode"] for item in payload["terminals"]] == [0, 2]
    assert [item["expected_order_authority"] for item in payload["terminals"]] == [
        "ENABLED",
        "DISABLED",
    ]
    assert all("expected_profile_fingerprint" in item for item in payload["terminals"])
    assert all("spool_path" in item for item in payload["terminals"])
    assert payload["schema_version"] == 2
    assert payload["telegram_control"]["order_authority"] == "NONE"
    assert payload["bridge"]["runner_path"].endswith("run-gold-event-bridge.py")
    assert payload["telegram_control"]["runner_path"].endswith("run-g20-telegram-control.py")
    encoded = EXAMPLE.read_text(encoding="utf-8").lower()
    assert '"password":' not in encoded
    assert "defaultpassword" not in encoded
    assert "bot_token" not in encoded


def test_native_ea_emits_bounded_internal_health_evidence() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    events = EVENTS.read_text(encoding="utf-8")
    entrypoints = [
        GOLDI_ENTRYPOINT.read_text(encoding="utf-8"),
        GOLDM_ENTRYPOINT.read_text(encoding="utf-8"),
    ]

    assert 'EmitTransition("ENGINE_HEARTBEAT"' in runtime
    assert "m_next_heartbeat_due_ms=GetTickCount64()+60000" in runtime
    assert "m_next_heartbeat_due_ms=now_ms+3600000" in runtime
    assert "EventSetTimer(1)" in runtime
    assert "EventKillTimer()" in runtime
    assert "void OnTimer(void)" in runtime
    assert "MaybeEmitHeartbeat(TimeCurrent())" in runtime
    assert all("void OnTimer(void)" in source for source in entrypoints)
    assert all("Runtime.OnTimer();" in source for source in entrypoints)
    assert "account_login" in runtime
    assert "account_server" in runtime
    assert "order_authority" in runtime
    assert '"ENGINE_HEARTBEAT"' in events


def test_supervisor_performs_only_one_profile_locked_startup_repair_restart() -> None:
    supervisor = SUPERVISOR.read_text(encoding="utf-8")

    assert "$startupRepairAttempts = @{ GOLDI = 0; GOLDM = 0 }" in supervisor
    assert "[bool]$terminal.startup_chart_repair" in supervisor
    assert "[int]$startupRepairAttempts[$profileId] -lt 1" in supervisor
    assert "Stop-Process -Id ([int]$processId) -Force -ErrorAction Stop" in supervisor
    assert "$state = 'REPAIR_RESTART_QUEUED'" in supervisor
    assert "startup_repair_attempts" in supervisor
    assert "$profileId PROFILE_EA_STARTUP_RECEIPT_MISSING" in supervisor


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
    control_runner = CONTROL_RUNNER.read_text(encoding="utf-8")

    assert "GoldEngine-GOLDi.ex5" in value
    assert "GoldEngine-GOLDm.ex5" in value
    assert 'order_authority = "ENABLED"' in value
    assert 'order_authority = "DISABLED"' in value
    assert "TelegramSecretPath" in value
    assert "TelegramAdminChatIds" in value
    assert "TelegramExpectedBotUsername" in value
    assert "TelegramSubscriberStatePath" in value
    assert "--subscriber-state" in value
    assert "run-gold-event-bridge.py" in value
    assert "gold_orchestrator" not in value
    assert "goldm_revised" not in value
    assert "goldm_bear" not in value
    assert "from gold_event_bridge.cli import main" in runner
    assert "from gold_orchestrator.g20_control import main" in control_runner
    assert "telegram_control" in value
    assert 'order_authority = "NONE"' in value


def test_bridge_token_uses_current_user_dpapi_and_never_enters_process_arguments() -> None:
    supervisor = SUPERVISOR.read_text(encoding="utf-8")
    secret_installer = SECRET_INSTALLER.read_text(encoding="utf-8")

    assert "SecureStringToBSTR" in supervisor
    assert "ZeroFreeBSTR" in supervisor
    assert ").Trim()" in supervisor
    assert "token_secret_path" in supervisor
    assert "TELEGRAM_BOT_TOKEN" in supervisor
    assert "TELEGRAM_EXPECTED_BOT_USERNAME" in supervisor
    assert "expected_bot_username" in supervisor
    assert "subscriber_state_path" in supervisor
    assert "Read-Host" in secret_installer
    assert "-AsSecureString" in secret_installer
    assert "ConvertFrom-SecureString" in secret_installer
    assert "SetAccessRuleProtection" in secret_installer
    assert "Token=" not in secret_installer


def test_capture_classifies_script_and_module_bridge_names() -> None:
    capture = (ROOT / "scripts/capture-g20-unattended-evidence.ps1").read_text(encoding="utf-8")

    assert "gold_event_bridge|run-gold-event-bridge" in capture
    assert "Get-Location).Path" in capture
    assert "resolvedOutputPath = Resolve-ConfiguredPath $OutputPath" in capture
    assert "resolvedPrebootPath = Resolve-ConfiguredPath $PrebootPath" in capture
    assert "last_task_result = [long]$info.LastTaskResult" in capture
    assert "last_task_result = [int]$info.LastTaskResult" not in capture


def test_chat_inspector_never_accepts_or_prints_plaintext_token() -> None:
    value = CHAT_INSPECTOR.read_text(encoding="utf-8")

    assert "token_secret_path" not in value
    assert "ConvertTo-SecureString" in value
    assert "ZeroFreeBSTR" in value
    assert "getUpdates" in value
    assert "chat_id" in value
    assert "Write-Output $token" not in value
    assert "param(\n    [string]$SecretPath" in value


def test_autologon_path_is_explicit_interactive_and_immediately_locked() -> None:
    installer = INTERACTIVE_INSTALLER.read_text(encoding="utf-8")
    lock_script = LOCK_SCRIPT.read_text(encoding="utf-8")
    verifier = AUTOLOGON_VERIFIER.read_text(encoding="utf-8")

    assert "AcknowledgeLsaSecretRisk" in installer
    assert "AUTOLOGON_LOCKED_INTERACTIVE" in installer
    assert "New-ScheduledTaskTrigger -AtLogOn" in installer
    assert "-LogonType Interactive" in installer
    assert installer.count("-WindowStyle Hidden") == 2
    assert "MSFT_TaskLogonTrigger" in installer
    assert "DefaultPassword is forbidden" in installer
    assert "Autologon domain does not match" in installer
    assert "-Password" not in installer
    assert "LockWorkStation" in lock_script
    assert "lock-marker.json" in lock_script
    assert "Get-AuthenticodeSignature" in verifier
    assert "CN=Microsoft Corporation" in verifier


def test_real_disabled_profile_has_only_the_manual_intervention_boot_exception() -> None:
    preparer = PREPARE.read_text(encoding="utf-8")
    supervisor = SUPERVISOR.read_text(encoding="utf-8")

    assert 'allowed_postboot_engine_error_reasons = @("MANUAL_INTERVENTION_DETECTED")' in preparer
    assert "PSObject.Properties['allowed_postboot_engine_error_reasons']" in supervisor
    assert (
        "Postboot ENGINE_ERROR exceptions require GOLDM REAL with authority DISABLED" in supervisor
    )


def test_chart_profile_repair_is_explicit_recoverable_and_terminal_safe() -> None:
    value = CHART_REPAIR.read_text(encoding="utf-8")

    assert "AcknowledgeProfileRepair" in value
    assert "terminal must be stopped before chart-profile repair" in value
    assert "STARTUP_CHART_OPEN_FAILED" in value
    assert "BACKED_UP_FOR_REGENERATION" in value
    assert "[Security.Cryptography.SHA256]::Create()" in value
    assert "backup hash mismatch" in value
    assert "Move-Item -LiteralPath $chartPath -Destination $backupPath" in value
    assert "Remove-Item" not in value
    assert "production_real_orders = 'DISABLED'" in value


def test_supervisor_requires_profile_receipt_not_only_terminal_process() -> None:
    supervisor = SUPERVISOR.read_text(encoding="utf-8")
    preparer = PREPARE.read_text(encoding="utf-8")

    assert "Get-EaReceiptEvidence" in supervisor
    assert "receipt_after_process_start" in supervisor
    assert "PROFILE_EA_STARTUP_RECEIPT_MISSING" in supervisor
    assert "PROFILE_EA_HEARTBEAT_STALE" in supervisor
    assert '$state = "STARTING"' in supervisor
    assert "Stop-Process -Name" not in supervisor
    assert "Stop-Process -Id ([int]$processId) -Force -ErrorAction Stop" in supervisor
    assert "Get-ExactProcess -ExecutablePath $terminalPath" in supervisor
    assert "ea_startup_grace_seconds = 180" in preparer
    assert "ea_heartbeat_stale_seconds = 3900" in preparer


def test_startup_chart_repair_is_profile_locked_and_recoverable() -> None:
    supervisor = SUPERVISOR.read_text(encoding="utf-8")
    preparer = PREPARE.read_text(encoding="utf-8")
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    assert "Repair-StartupChartIfConfigured" in supervisor
    assert "repair-g20-startup-chart.ps1" in supervisor
    assert "AcknowledgeProfileRepair" in supervisor
    assert "Startup chart repair may only be enabled for GOLDI" in supervisor
    assert "startup_chart_repair = $true" in preparer
    assert "startup_chart_repair = $false" in preparer
    assert example["terminals"][0]["startup_chart_repair"] is True
    assert example["terminals"][1]["startup_chart_repair"] is False
    assert all("data_path" in item for item in example["terminals"])
