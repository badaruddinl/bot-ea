from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot_ea import entrypoints


def test_qt_main_delegates_to_qt_app(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_import(module_name: str) -> SimpleNamespace:
        assert module_name == "bot_ea.qt_app"
        return SimpleNamespace(main=lambda: calls.append("qt"))

    monkeypatch.setattr(entrypoints, "import_module", fake_import)

    entrypoints.qt_main()

    assert calls == ["qt"]


def test_qt_main_exits_with_install_hint_when_pyside6_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_import(module_name: str) -> SimpleNamespace:
        assert module_name == "bot_ea.qt_app"
        raise ModuleNotFoundError("No module named 'PySide6'", name="PySide6")

    monkeypatch.setattr(entrypoints, "import_module", fake_import)

    with pytest.raises(SystemExit, match=r"pip install \.\[desktop\]") as exc_info:
        entrypoints.qt_main()

    assert exc_info.value.code == entrypoints._QT_DEPENDENCY_HINT


def test_qt_main_reraises_non_gui_import_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = ModuleNotFoundError("No module named 'websockets'", name="websockets")

    def fake_import(module_name: str) -> SimpleNamespace:
        assert module_name == "bot_ea.qt_app"
        raise expected

    monkeypatch.setattr(entrypoints, "import_module", fake_import)

    with pytest.raises(ModuleNotFoundError) as exc_info:
        entrypoints.qt_main()

    assert exc_info.value is expected


def test_websocket_main_delegates_to_websocket_service(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_import(module_name: str) -> SimpleNamespace:
        assert module_name == "bot_ea.websocket_service"
        return SimpleNamespace(main=lambda: calls.append("websocket"))

    monkeypatch.setattr(entrypoints, "import_module", fake_import)

    entrypoints.websocket_main()

    assert calls == ["websocket"]
