from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .research_environment import AuthenticodeSnapshot, DirectorySecuritySnapshot
from .research_network import FirewallRuleSnapshot


class WindowsResearchSecurityError(RuntimeError):
    """Raised when a trusted Windows security probe or mutation fails."""


_SIGNATURE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$path = [System.IO.Path]::GetFullPath([string]$env:GOLDM_RESEARCH_PROBE_ARG0)
$signature = Get-AuthenticodeSignature -LiteralPath $path
$item = Get-Item -LiteralPath $path
[ordered]@{
  status = [string]$signature.Status
  signer_subject = [string]$signature.SignerCertificate.Subject
  signer_thumbprint = [string]$signature.SignerCertificate.Thumbprint
  timestamp_subject = [string]$signature.TimeStamperCertificate.Subject
  file_version = [string]$item.VersionInfo.FileVersion
} | ConvertTo-Json -Compress
"""

_DIRECTORY_SECURITY_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$mode = [string]$env:GOLDM_RESEARCH_PROBE_ARG0
$path = [System.IO.Path]::GetFullPath([string]$env:GOLDM_RESEARCH_PROBE_ARG1)
$current = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$system = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')
$admins = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
if ($mode -eq 'create') {
  if ([System.IO.Directory]::Exists($path) -or [System.IO.File]::Exists($path)) {
    throw 'private directory target already exists'
  }
  $security = New-Object System.Security.AccessControl.DirectorySecurity
  $security.SetOwner($current)
  $security.SetAccessRuleProtection($true, $false)
  foreach ($sid in @($current, $system, $admins)) {
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
      $sid,
      [System.Security.AccessControl.FileSystemRights]::FullControl,
      [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit',
      [System.Security.AccessControl.PropagationFlags]::None,
      [System.Security.AccessControl.AccessControlType]::Allow
    )
    [void]$security.AddAccessRule($rule)
  }
  [void][System.IO.Directory]::CreateDirectory($path, $security)
} elseif ($mode -ne 'probe') {
  throw 'invalid directory-security mode'
}
$item = Get-Item -LiteralPath $path -Force
if (-not $item.PSIsContainer -or (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)) {
  throw 'directory is missing or is a reparse point'
}
$acl = Get-Acl -LiteralPath $path
$rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
$allow = @($rules | Where-Object AccessControlType -eq Allow | ForEach-Object {$_.IdentityReference.Value} | Sort-Object -Unique)
$deny = @($rules | Where-Object AccessControlType -eq Deny | ForEach-Object {$_.IdentityReference.Value} | Sort-Object -Unique)
$full = @($rules | Where-Object {
  $_.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow -and
  $_.FileSystemRights -eq [System.Security.AccessControl.FileSystemRights]::FullControl -and
  $_.InheritanceFlags -eq ([System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit) -and
  $_.PropagationFlags -eq [System.Security.AccessControl.PropagationFlags]::None -and
  -not $_.IsInherited
} | ForEach-Object {$_.IdentityReference.Value} | Sort-Object -Unique)
$nonFull = @($rules | Where-Object {
  -not (
    $_.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow -and
    $_.FileSystemRights -eq [System.Security.AccessControl.FileSystemRights]::FullControl -and
    $_.InheritanceFlags -eq ([System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit) -and
    $_.PropagationFlags -eq [System.Security.AccessControl.PropagationFlags]::None -and
    -not $_.IsInherited
  )
})
[ordered]@{
  owner_sid = $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
  current_user_sid = $current.Value
  inheritance_protected = [bool]$acl.AreAccessRulesProtected
  allowed_sids = @($allow)
  denied_sids = @($deny)
  full_control_sids = @($full)
  non_full_control_rule_count = [int]$nonFull.Count
  sddl = $acl.GetSecurityDescriptorSddlForm([System.Security.AccessControl.AccessControlSections]::All)
} | ConvertTo-Json -Compress
"""

_ADMIN_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$principal = New-Object System.Security.Principal.WindowsPrincipal(
  [System.Security.Principal.WindowsIdentity]::GetCurrent()
)
[ordered]@{
  is_administrator = [bool]$principal.IsInRole(
    [System.Security.Principal.WindowsBuiltInRole]::Administrator
  )
} | ConvertTo-Json -Compress
"""

_RULE_EXISTS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$name = [string]$env:GOLDM_RESEARCH_PROBE_ARG0
$rule = Get-NetFirewallRule -PolicyStore ActiveStore -Name $name -ErrorAction SilentlyContinue
[ordered]@{ exists = [bool]($null -ne $rule) } | ConvertTo-Json -Compress
"""

_INSTALL_RULE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$name = [string]$env:GOLDM_RESEARCH_PROBE_ARG0
$display = [string]$env:GOLDM_RESEARCH_PROBE_ARG1
$program = [System.IO.Path]::GetFullPath([string]$env:GOLDM_RESEARCH_PROBE_ARG2)
$existing = Get-NetFirewallRule -PolicyStore ActiveStore -Name $name -ErrorAction SilentlyContinue
if ($null -ne $existing) { throw 'firewall rule already exists' }
$rule = New-NetFirewallRule -PolicyStore PersistentStore -Name $name `
  -DisplayName $display -Group 'GoldM Research Offline' -Enabled True `
  -Direction Outbound -Action Block -Profile Any -Program $program `
  -Protocol Any -LocalAddress Any -RemoteAddress Any -LocalPort Any `
  -RemotePort Any -InterfaceType Any
[ordered]@{ name = [string]$rule.Name } | ConvertTo-Json -Compress
"""

_REMOVE_RULE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$name = [string]$env:GOLDM_RESEARCH_PROBE_ARG0
$rule = Get-NetFirewallRule -PolicyStore PersistentStore -Name $name -ErrorAction SilentlyContinue
if ($null -ne $rule) {
  Remove-NetFirewallRule -PolicyStore PersistentStore -Name $name -ErrorAction Stop
}
[ordered]@{ absent = [bool]($null -eq (Get-NetFirewallRule -PolicyStore ActiveStore -Name $name -ErrorAction SilentlyContinue)) } | ConvertTo-Json -Compress
"""

_PROBE_RULE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$name = [string]$env:GOLDM_RESEARCH_PROBE_ARG0
$rule = @(Get-NetFirewallRule -PolicyStore ActiveStore -Name $name -ErrorAction Stop)
if ($rule.Count -ne 1) { throw 'firewall rule identity is missing or ambiguous' }
$app = @(Get-NetFirewallApplicationFilter -AssociatedNetFirewallRule $rule[0])
$protocol = @(Get-NetFirewallPortFilter -AssociatedNetFirewallRule $rule[0])
$address = @(Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule[0])
$service = @(Get-NetFirewallServiceFilter -AssociatedNetFirewallRule $rule[0])
if ($app.Count -ne 1 -or $protocol.Count -ne 1 -or $address.Count -ne 1 -or $service.Count -ne 1) {
  throw 'firewall rule filters are missing or ambiguous'
}
[ordered]@{
  name = [string]$rule[0].Name
  display_name = [string]$rule[0].DisplayName
  enabled = [bool]($rule[0].Enabled -eq 'True')
  direction = [string]$rule[0].Direction
  action = [string]$rule[0].Action
  profile = [string]$rule[0].Profile
  program_path = [string]$app[0].Program
  protocol = [string]$protocol[0].Protocol
  local_addresses = @($address[0].LocalAddress)
  remote_addresses = @($address[0].RemoteAddress)
  local_ports = @($protocol[0].LocalPort)
  remote_ports = @($protocol[0].RemotePort)
  service = [string]$service[0].Service
  interface_type = [string]$rule[0].InterfaceType
  policy_store_source_type = [string]$rule[0].PolicyStoreSourceType
} | ConvertTo-Json -Compress -Depth 4
"""


def windows_authenticode_probe(path: Path) -> AuthenticodeSnapshot:
    payload = _single_json(_run_system_powershell(_SIGNATURE_SCRIPT, str(path)))
    expected = {
        "status",
        "signer_subject",
        "signer_thumbprint",
        "timestamp_subject",
        "file_version",
    }
    if set(payload) != expected:
        raise WindowsResearchSecurityError("Authenticode probe fields are incomplete")
    return AuthenticodeSnapshot(**payload)


def windows_private_directory_creator(path: Path) -> DirectorySecuritySnapshot:
    return _windows_directory_security("create", path)


def windows_directory_security_probe(path: Path) -> DirectorySecuritySnapshot:
    return _windows_directory_security("probe", path)


def install_exact_outbound_block_rules(
    rules: tuple[tuple[str, str, Path], ...],
) -> tuple[str, ...]:
    admin = _single_json(_run_system_powershell(_ADMIN_SCRIPT))
    if admin != {"is_administrator": True}:
        raise WindowsResearchSecurityError(
            "installing research firewall rules requires an elevated administrator process"
        )
    names = tuple(rule[0] for rule in rules)
    if len(names) != len(set(names)):
        raise WindowsResearchSecurityError("firewall rule names must be unique")
    for name in names:
        exists = _single_json(_run_system_powershell(_RULE_EXISTS_SCRIPT, name))
        if exists != {"exists": False}:
            raise WindowsResearchSecurityError(
                f"firewall rule already exists or cannot be proven absent: {name}"
            )
    created: list[str] = []
    try:
        for name, display_name, program in rules:
            result = _single_json(
                _run_system_powershell(
                    _INSTALL_RULE_SCRIPT, name, display_name, str(program)
                )
            )
            if result != {"name": name}:
                raise WindowsResearchSecurityError("firewall rule creation result mismatch")
            created.append(name)
    except Exception:
        for name in reversed(created):
            _remove_exact_rule(name)
        raise
    return tuple(created)


def windows_firewall_rule_probe(
    names: tuple[str, ...],
) -> tuple[FirewallRuleSnapshot, ...]:
    result = []
    for name in names:
        payload = _single_json(_run_system_powershell(_PROBE_RULE_SCRIPT, name))
        expected = {
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
        if set(payload) != expected:
            raise WindowsResearchSecurityError("firewall probe fields are incomplete")
        for field in (
            "local_addresses",
            "remote_addresses",
            "local_ports",
            "remote_ports",
        ):
            payload[field] = _string_tuple(payload[field], field)
        payload["program_path"] = Path(payload["program_path"])
        result.append(FirewallRuleSnapshot(**payload))
    return tuple(result)


def rollback_exact_outbound_block_rules(names: tuple[str, ...]) -> None:
    """Rollback only rule names created by the current failed install attempt."""

    for name in reversed(names):
        _remove_exact_rule(name)


def _remove_exact_rule(name: str) -> None:
    result = _single_json(_run_system_powershell(_REMOVE_RULE_SCRIPT, name))
    if result != {"absent": True}:
        raise WindowsResearchSecurityError(
            f"partial firewall rollback did not remove exact rule: {name}"
        )


def _windows_directory_security(mode: str, path: Path) -> DirectorySecuritySnapshot:
    payload = _single_json(
        _run_system_powershell(_DIRECTORY_SECURITY_SCRIPT, mode, str(path))
    )
    expected = {
        "owner_sid",
        "current_user_sid",
        "inheritance_protected",
        "allowed_sids",
        "denied_sids",
        "full_control_sids",
        "non_full_control_rule_count",
        "sddl",
    }
    if set(payload) != expected:
        raise WindowsResearchSecurityError("directory-security probe fields are incomplete")
    for field in ("allowed_sids", "denied_sids", "full_control_sids"):
        payload[field] = _string_tuple(payload[field], field)
    return DirectorySecuritySnapshot(**payload)


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise WindowsResearchSecurityError(f"Windows probe field is invalid: {field}")
    return tuple(value)


def _single_json(lines: list[str]) -> dict[str, object]:
    if len(lines) != 1:
        raise WindowsResearchSecurityError("Windows security probe returned ambiguous output")
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise WindowsResearchSecurityError(
            "Windows security probe returned invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise WindowsResearchSecurityError("Windows security probe did not return an object")
    return payload


def _run_system_powershell(script: str, *arguments: str) -> list[str]:
    if os.name != "nt":
        raise WindowsResearchSecurityError("Windows security operations are Windows-only")
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not powershell.is_file():
        raise WindowsResearchSecurityError(
            "trusted Windows PowerShell executable is unavailable"
        )
    system_root = powershell.parents[3]
    child_environment = {
        "SystemRoot": str(system_root),
        "WINDIR": str(system_root),
        "COMSPEC": str(system_root / "System32" / "cmd.exe"),
        "PATH": str(system_root / "System32"),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "PSModulePath": str(
            system_root / "System32" / "WindowsPowerShell" / "v1.0" / "Modules"
        ),
    }
    for index, argument in enumerate(arguments):
        child_environment[f"GOLDM_RESEARCH_PROBE_ARG{index}"] = argument
    completed = subprocess.run(
        [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=30,
        env=child_environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or completed.stderr.strip():
        raise WindowsResearchSecurityError(
            "trusted Windows PowerShell operation failed: "
            + (completed.stderr.strip() or "unknown error")
        )
    return [line for line in completed.stdout.splitlines() if line.strip()]
