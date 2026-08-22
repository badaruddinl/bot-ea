from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "repair-g20-startup-chart.ps1"

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="PowerShell/Win32 contract")


def _invoke(
    *, data_path: Path, terminal_path: Path, output_path: Path, acknowledge: bool
) -> subprocess.CompletedProcess[str]:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        "-ProfileId",
        "GOLDI",
        "-DataPath",
        str(data_path),
        "-TerminalPath",
        str(terminal_path),
        "-OutputPath",
        str(output_path),
    ]
    if acknowledge:
        command.append("-AcknowledgeProfileRepair")
    return subprocess.run(command, check=False, capture_output=True, text=True)


def test_chart_repair_backs_up_exact_bytes_and_writes_receipt(tmp_path: Path) -> None:
    data_path = tmp_path / "terminal-data"
    chart_root = data_path / "MQL5" / "Profiles" / "Charts" / "Default"
    chart_root.mkdir(parents=True)
    chart_path = chart_root / "chart01.chr"
    original = b"deterministic-corrupt-chart\x00payload"
    chart_path.write_bytes(original)
    terminal_path = tmp_path / "terminal64.exe"
    terminal_path.write_bytes(b"test-terminal-placeholder")
    output_path = tmp_path / "receipt.json"

    result = _invoke(
        data_path=data_path,
        terminal_path=terminal_path,
        output_path=output_path,
        acknowledge=True,
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads(output_path.read_text(encoding="utf-8-sig"))
    backup = Path(receipt["backup_path"])
    assert receipt["result"] == "BACKED_UP_FOR_REGENERATION"
    assert receipt["production_real_orders"] == "DISABLED"
    assert receipt["original_sha256"] == hashlib.sha256(original).hexdigest()
    assert receipt["original_size_bytes"] == len(original)
    assert not chart_path.exists()
    assert backup.read_bytes() == original


def test_chart_repair_requires_acknowledgement_and_missing_chart_is_noop(tmp_path: Path) -> None:
    data_path = tmp_path / "terminal-data"
    (data_path / "MQL5" / "Profiles" / "Charts" / "Default").mkdir(parents=True)
    terminal_path = tmp_path / "terminal64.exe"
    terminal_path.write_bytes(b"test-terminal-placeholder")
    rejected_output = tmp_path / "rejected.json"

    rejected = _invoke(
        data_path=data_path,
        terminal_path=terminal_path,
        output_path=rejected_output,
        acknowledge=False,
    )

    assert rejected.returncode != 0
    assert "Explicit -AcknowledgeProfileRepair is required" in rejected.stderr
    assert not rejected_output.exists()

    noop_output = tmp_path / "noop.json"
    accepted = _invoke(
        data_path=data_path,
        terminal_path=terminal_path,
        output_path=noop_output,
        acknowledge=True,
    )
    assert accepted.returncode == 0, accepted.stderr
    receipt = json.loads(noop_output.read_text(encoding="utf-8-sig"))
    assert receipt["result"] == "NOOP_CHART_MISSING"
    assert receipt["backup_path"] is None
