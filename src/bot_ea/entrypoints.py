from __future__ import annotations

from importlib import import_module

_QT_DEPENDENCY_HINT = (
    "bot-ea-qt requires the optional desktop dependencies. "
    "Install them with `pip install .[desktop]`."
)


def qt_main() -> None:
    try:
        module = import_module("bot_ea.qt_app")
    except ModuleNotFoundError as exc:
        missing_name = (exc.name or "").split(".", 1)[0]
        if missing_name == "PySide6":
            raise SystemExit(_QT_DEPENDENCY_HINT) from exc
        raise
    module.main()


def websocket_main() -> None:
    module = import_module("bot_ea.websocket_service")
    module.main()
