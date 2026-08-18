from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from time import sleep
from types import ModuleType

from .engine import RevisedBar, RevisedSide, RevisedSnapshot
from .timebase import mt5_epoch_to_server_wall


@dataclass(frozen=True, slots=True)
class RevisedMt5Config:
    symbol: str = "GOLD.i#"
    server_timezone: timezone = timezone.utc
    m1_count: int = 80
    m5_count: int = 80
    h1_count: int = 80
    d1_count: int = 80
    max_attempts: int = 3
    initial_backoff_seconds: float = 1.0


class RevisedMt5ReadOnlySource:
    """MT5 bars/ticks/account metadata adapter with no trade API calls."""

    def __init__(self, config: RevisedMt5Config | None = None, *, mt5_module: ModuleType | None = None) -> None:
        self.config = config or RevisedMt5Config()
        self._mt5 = mt5_module
        self._connected = False

    def connect(self) -> None:
        mt5 = self._module()
        if self._connected:
            return
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        if not mt5.symbol_select(self.config.symbol, True):
            mt5.shutdown()
            raise RuntimeError(f"MT5 symbol selection failed: {mt5.last_error()}")
        self._connected = True

    def close(self) -> None:
        if self._connected:
            self._module().shutdown()
            self._connected = False

    def health(self) -> dict[str, object]:
        self.connect()
        mt5 = self._module()
        info = mt5.symbol_info(self.config.symbol)
        account = mt5.account_info()
        if info is None:
            raise RuntimeError(f"MT5 symbol info failed: {mt5.last_error()}")
        return {
            "symbol": self.config.symbol,
            "point": float(info.point),
            "digits": int(info.digits),
            "spread_points": int(info.spread),
            "account_login": int(getattr(account, "login", 0)) if account is not None else None,
            "account_server": str(getattr(account, "server", "")) if account is not None else None,
        }

    def snapshot(
        self,
        *,
        side: RevisedSide,
        current_time: datetime | None = None,
        m5_trigger_time: datetime | None = None,
        m5_pattern: str = "NONE",
        m5_votes: int = 0,
        confidence: float = 0.0,
        level: float | None = None,
        invalidation: float | None = None,
        entry: float | None = None,
        stop: float | None = None,
    ) -> RevisedSnapshot:
        self.connect()
        m1 = self._copy_rates("TIMEFRAME_M1", self.config.m1_count)
        m5 = self._copy_rates("TIMEFRAME_M5", self.config.m5_count)
        h1 = self._copy_rates("TIMEFRAME_H1", self.config.h1_count)
        d1 = self._copy_rates("TIMEFRAME_D1", self.config.d1_count)
        if not m1 or not m5:
            raise RuntimeError("MT5 returned no closed M1/M5 bars")
        return RevisedSnapshot(
            symbol=self.config.symbol,
            side=side,
            current_time=current_time or m1[-1].time,
            m1_bars=tuple(m1),
            m5_bars=tuple(m5),
            h1_bars=tuple(h1),
            d1_bars=tuple(d1),
            m5_trigger_time=m5_trigger_time,
            m5_pattern=m5_pattern,
            m5_votes=m5_votes,
            confidence=confidence,
            level=level,
            invalidation=invalidation,
            entry=entry,
            stop=stop,
        )

    def snapshot_with_retry(self, **kwargs) -> RevisedSnapshot:
        last_error: Exception | None = None
        for attempt in range(self.config.max_attempts):
            try:
                return self.snapshot(**kwargs)
            except Exception as exc:  # fail closed; never restart terminal
                last_error = exc
                if attempt + 1 < self.config.max_attempts:
                    sleep(self.config.initial_backoff_seconds * (2**attempt))
        raise RuntimeError(f"REVISED MT5 read-only snapshot failed after retries: {last_error}") from last_error

    def _module(self) -> ModuleType:
        if self._mt5 is None:
            self._mt5 = import_module("MetaTrader5")
        return self._mt5

    def _copy_rates(self, timeframe_name: str, count: int) -> list[RevisedBar]:
        mt5 = self._module()
        timeframe = getattr(mt5, timeframe_name)
        raw = mt5.copy_rates_from_pos(self.config.symbol, timeframe, 1, count)
        if raw is None:
            raise RuntimeError(f"MT5 CopyRates failed for {timeframe_name}: {mt5.last_error()}")
        info = mt5.symbol_info(self.config.symbol)
        point = float(info.point) if info is not None else 0.01
        return [
            RevisedBar(
                time=mt5_epoch_to_server_wall(
                    int(rate["time"]), self.config.server_timezone
                ),
                open=float(rate["open"]),
                high=float(rate["high"]),
                low=float(rate["low"]),
                close=float(rate["close"]),
                volume=float(rate["tick_volume"]),
                spread=max(float(rate["spread"]) * point, 0.0),
            )
            for rate in raw
        ]
