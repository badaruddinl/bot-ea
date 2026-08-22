from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "capture_g10_vm_profiles.py"
    spec = importlib.util.spec_from_file_location("capture_g10_vm_profiles", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_capture_uses_distinct_config_bindings_and_restores_environment(
    tmp_path: Path,
) -> None:
    module = _load_script()
    goldi_terminal = tmp_path / "goldi" / "terminal64.exe"
    goldm_terminal = tmp_path / "goldm" / "terminal64.exe"
    goldi_terminal.parent.mkdir()
    goldm_terminal.parent.mkdir()
    goldi_terminal.write_bytes(b"goldi")
    goldm_terminal.write_bytes(b"goldm")
    config = tmp_path / "g20.json"
    config.write_text(
        json.dumps(
            {
                "production_real_orders": "DISABLED",
                "terminals": [
                    {
                        "profile_id": "GOLDI",
                        "terminal_path": str(goldi_terminal),
                        "expected_account_login": 101,
                        "expected_account_server": "DEMO",
                    },
                    {
                        "profile_id": "GOLDM",
                        "terminal_path": str(goldm_terminal),
                        "expected_account_login": 202,
                        "expected_account_server": "REAL",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    observed: dict[str, str] = {}

    def report_builder(_: Path) -> dict[str, object]:
        observed["goldi"] = os.environ["GOLDI_MT5_TERMINAL_PATH"]
        observed["goldm"] = os.environ["GOLDM_REAL_MT5_TERMINAL_PATH"]
        return {"ready": True, "production_real_orders": "DISABLED"}

    def profile_probe(profile_id: str, output: Path) -> dict[str, object]:
        value = {"profile_id": profile_id, "orders_sent": 0}
        output.write_text(json.dumps(value), encoding="utf-8")
        return value

    previous = os.environ.pop("GOLDI_MT5_LOGIN", None)
    try:
        result = module.capture(
            config,
            tmp_path / "evidence",
            repository_root=tmp_path,
            report_builder=report_builder,
            profile_probe=profile_probe,
        )
        assert result["ready"] is True
        assert result["orders_sent"] == {"GOLDI": 0, "GOLDM": 0}
        assert observed == {"goldi": str(goldi_terminal), "goldm": str(goldm_terminal)}
        assert "GOLDI_MT5_LOGIN" not in os.environ
        assert (tmp_path / "evidence" / "prerequisites.sha256").is_file()
        assert (tmp_path / "evidence" / "capture-summary.sha256").is_file()
    finally:
        if previous is not None:
            os.environ["GOLDI_MT5_LOGIN"] = previous


def test_capture_rejects_shared_terminal_and_enabled_real_authority(tmp_path: Path) -> None:
    module = _load_script()
    terminal = tmp_path / "terminal64.exe"
    terminal.write_bytes(b"terminal")
    bindings = [
        {
            "profile_id": profile_id,
            "terminal_path": str(terminal),
            "expected_account_login": index,
            "expected_account_server": profile_id,
        }
        for index, profile_id in enumerate(("GOLDI", "GOLDM"), start=1)
    ]
    config = tmp_path / "g20.json"
    config.write_text(
        json.dumps({"production_real_orders": "DISABLED", "terminals": bindings}),
        encoding="utf-8",
    )
    try:
        module.capture(config, tmp_path / "evidence", repository_root=tmp_path)
    except ValueError as exc:
        assert "terminal paths must be distinct" in str(exc)
    else:
        raise AssertionError("shared terminal path was accepted")

    config.write_text(
        json.dumps({"production_real_orders": "ENABLED", "terminals": bindings}),
        encoding="utf-8",
    )
    try:
        module.capture(config, tmp_path / "evidence", repository_root=tmp_path)
    except ValueError as exc:
        assert "REAL orders disabled" in str(exc)
    else:
        raise AssertionError("enabled REAL authority was accepted")
