from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/g18-windows-restart-probe.ps1"


def test_probe_requires_real_boot_change_and_post_boot_heartbeats() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Win32_OperatingSystem" in source
    assert "LastBootUpTime" in source
    assert "preparedBootTime" in source
    assert "currentBootTime" in source
    assert 'throw "Windows/VM boot ID did not change"' in source
    assert "heartbeat was not written after reboot" in source
    assert "process identity did not change across reboot" in source
    assert "runtime_id" in source
    assert "$profile.runtime_id -eq [string]$before.runtime_id" in source
    assert "$profile.chart_id -eq [long]$before.chart_id" not in source
    assert "fingerprint changed across reboot" in source
    assert "binding changed across reboot" in source


def test_probe_never_reboots_or_enables_order_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for forbidden in ("Restart-Computer", "shutdown.exe", "Stop-Computer", "Enabled=1"):
        assert forbidden not in source
    assert 'production_real_orders = "DISABLED"' in source
    assert 'order_authority = "DISABLED"' in source
    assert "Write-JsonAtomic" in source


def test_probe_uses_windows_server_2019_compatible_path_validation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "[System.IO.Path]::IsPathRooted($Path)" in source
    assert "[System.IO.Path]::IsPathFullyQualified($Path)" not in source
