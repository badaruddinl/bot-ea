"""Notification runtime exports, loaded lazily at their first use.

The production CLI must validate its bound files and MT5 installation before
importing broker/runtime code. Eager package re-exports used to import the MT5
adapter as a side effect of importing ``goldm_signal.notify.cli`` and defeated
that startup boundary.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "ApprovedTelegramSender": (".telegram", "ApprovedTelegramSender"),
    "Mt5LogBridge": (".mt5_log", "Mt5LogBridge"),
    "OutboxWorker": (".outbox", "OutboxWorker"),
    "ParsedMt5Event": (".mt5_log", "ParsedMt5Event"),
    "TelegramApprovalWorker": (".approval", "TelegramApprovalWorker"),
    "TelegramBotClient": (".telegram", "TelegramBotClient"),
    "TelegramSender": (".telegram", "TelegramSender"),
    "TradeLifecycleConfig": (".trade_lifecycle", "TradeLifecycleConfig"),
    "TradeLifecycleWorker": (".trade_lifecycle", "TradeLifecycleWorker"),
    "parse_mt5_log_line": (".mt5_log", "parse_mt5_log_line"),
    "render_stored_event": (".mt5_log", "render_stored_event"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
