from __future__ import annotations

from datetime import datetime, timezone
from importlib import import_module
from types import ModuleType

from .engine import BearBar


def load_mt5_m15_bars(
    *,
    symbol: str,
    start: datetime,
    end: datetime,
    server_timezone: timezone,
    mt5_module: ModuleType | None = None,
) -> list[BearBar]:
    """Read M15 bars from MT5 without placing or modifying any order."""

    return load_mt5_bars(
        symbol=symbol,
        timeframe_name="TIMEFRAME_M15",
        start=start,
        end=end,
        server_timezone=server_timezone,
        mt5_module=mt5_module,
    )


def load_mt5_bars(
    *,
    symbol: str,
    timeframe_name: str,
    start: datetime,
    end: datetime,
    server_timezone: timezone,
    mt5_module: ModuleType | None = None,
) -> list[BearBar]:
    """Read one closed-bar timeframe from MT5 without any trade API."""

    if not symbol.strip():
        raise ValueError("symbol is required")
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("MT5 range timestamps must be timezone-aware")
    if end <= start:
        raise ValueError("MT5 range end must be after start")

    mt5 = mt5_module or import_module("MetaTrader5")
    if not hasattr(mt5, timeframe_name):
        raise ValueError(f"unsupported MT5 timeframe: {timeframe_name}")
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"MT5 symbol selection failed for {symbol}: {mt5.last_error()}")
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"MT5 symbol info is unavailable for {symbol}: {mt5.last_error()}")
        rates = mt5.copy_rates_range(
            symbol,
            getattr(mt5, timeframe_name),
            start.astimezone(timezone.utc),
            end.astimezone(timezone.utc),
        )
        if rates is None:
            raise RuntimeError(f"MT5 CopyRates failed for {symbol}: {mt5.last_error()}")
        point = float(info.point)
        bars = [
            BearBar(
                time=datetime.fromtimestamp(int(rate["time"]), tz=timezone.utc).astimezone(
                    server_timezone
                ),
                open=float(rate["open"]),
                high=float(rate["high"]),
                low=float(rate["low"]),
                close=float(rate["close"]),
                tick_volume=float(rate["tick_volume"]),
                spread=float(rate["spread"]) * point,
            )
            for rate in rates
        ]
        if not bars:
            raise RuntimeError(f"MT5 returned no {timeframe_name} bars for {symbol}")
        return bars
    finally:
        mt5.shutdown()
