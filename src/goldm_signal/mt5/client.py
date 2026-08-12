from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Any

from .bars import ClosedBar, Timeframe


class ReadOnlyMT5Client:
    """Small MT5 boundary that can read bars and symbol metadata only.

    Closed candles are requested with ``start_pos=1``. No order validation or
    order-send method is intentionally available on this class.
    """

    def __init__(self, *, mt5_module: Any | None = None, path: str | None = None) -> None:
        self._mt5 = mt5_module
        self._path = path
        self._initialized = False

    def initialize(self) -> None:
        mt5 = self._module()
        kwargs = {"path": self._path} if self._path else {}
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        self._initialized = True

    def close(self) -> None:
        if self._initialized:
            with contextlib.suppress(Exception):
                self._module().shutdown()
            self._initialized = False

    def symbol_info(self, symbol: str) -> Any:
        mt5 = self._ready_module()
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"MT5 symbol_info({symbol!r}) failed: {mt5.last_error()}")
        if not bool(getattr(info, "visible", True)) and not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"MT5 symbol_select({symbol!r}) failed: {mt5.last_error()}")
        return info

    def copy_closed_bars(self, symbol: str, timeframe: Timeframe, count: int) -> list[ClosedBar]:
        if count <= 0:
            raise ValueError("count must be positive")
        mt5 = self._ready_module()
        self.symbol_info(symbol)
        mt5_timeframe = getattr(mt5, f"TIMEFRAME_{timeframe.value}", None)
        if mt5_timeframe is None:
            raise RuntimeError(f"MT5 module does not support timeframe {timeframe.value}")
        rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 1, count)
        if rates is None:
            raise RuntimeError(
                f"MT5 copy_rates_from_pos({symbol!r}, {timeframe.value}) failed: {mt5.last_error()}"
            )
        return [self._to_bar(rate) for rate in rates]

    def _ready_module(self) -> Any:
        if not self._initialized:
            self.initialize()
        return self._module()

    def _module(self) -> Any:
        if self._mt5 is None:
            try:
                import MetaTrader5 as mt5  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError("install the 'live' extra to use MetaTrader 5") from exc
            self._mt5 = mt5
        return self._mt5

    @staticmethod
    def _to_bar(rate: Any) -> ClosedBar:
        def read(name: str, default: float = 0.0) -> float:
            try:
                return float(rate[name])
            except (KeyError, TypeError, ValueError):
                return float(getattr(rate, name, default) or default)

        timestamp = read("time")
        return ClosedBar(
            time=datetime.fromtimestamp(timestamp, tz=timezone.utc),
            open=read("open"),
            high=read("high"),
            low=read("low"),
            close=read("close"),
            tick_volume=read("tick_volume"),
            spread_points=read("spread"),
            real_volume=read("real_volume"),
        )
