from __future__ import annotations

import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_desktop_ui_and_websocket_surfaces_are_absent() -> None:
    removed = (
        "src/bot_ea/qt_app.py",
        "src/bot_ea/gui_app.py",
        "src/bot_ea/desktop_runtime.py",
        "src/bot_ea/websocket_service.py",
        "src/bot_ea/entrypoints.py",
        "scripts/run-desktop-gui.ps1",
        "scripts/run-qt-gui.ps1",
        "scripts/run-websocket-service.ps1",
        "docs/desktop-runtime-runbook.md",
        "docs/user-manual.md",
        "docs/windows-packaging-plan.md",
        "docs/project-handoff.md",
    )
    assert not [path for path in removed if (REPOSITORY_ROOT / path).exists()]


def test_package_has_no_ui_websocket_dependency_or_entrypoint() -> None:
    payload = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = payload["project"]
    dependencies = tuple(project.get("dependencies", ()))
    optional = project.get("optional-dependencies", {})
    scripts = project.get("scripts", {})

    flattened = [*dependencies]
    for values in optional.values():
        flattened.extend(values)
    normalized_dependencies = " ".join(flattened).casefold()
    normalized_scripts = " ".join(f"{name}={target}" for name, target in scripts.items()).casefold()

    assert "pyside" not in normalized_dependencies
    assert "websocket" not in normalized_dependencies
    assert "qt" not in normalized_scripts
    assert "websocket" not in normalized_scripts


def test_bot_ea_public_package_does_not_export_desktop_runtime() -> None:
    source = (REPOSITORY_ROOT / "src" / "bot_ea" / "__init__.py").read_text(encoding="utf-8")
    forbidden = ("DesktopRuntime", "qt_app", "gui_app", "websocket_service")
    assert not [name for name in forbidden if name in source]
