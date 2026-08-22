from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from importlib import import_module
from math import floor
from pathlib import Path
from types import ModuleType
from typing import Any

from gold_engine_core import ProfileConfig, load_execution_policy, load_named_profile
from goldm_bear.engine import BearBar
from goldm_revised.engine import RevisedBar
from goldm_revised.timebase import mt5_epoch_to_server_wall

from .config import PortfolioWorkerConfig
from .models import SignalPlan


class BoundMt5Session:
    def __init__(
        self, config: PortfolioWorkerConfig, *, mt5_module: ModuleType | None = None
    ) -> None:
        self.config = config
        self.mt5 = mt5_module or import_module("MetaTrader5")
        self.connected = False
        profile_id = {"goldi": "GOLDI", "goldm": "GOLDM"}.get(config.group)
        if profile_id is None:
            raise ValueError(f"unsupported final worker group: {config.group!r}")
        root = Path(__file__).resolve().parents[2]
        self.profile = ProfileConfig.from_manifest(
            load_named_profile(root, profile_id), tick_size=Decimal("0.01")
        )
        self.execution_policy = load_execution_policy(
            root / "config" / "execution_profiles" / f"{profile_id}.json"
        )

    @property
    def server_timezone(self) -> timezone:
        return timezone(timedelta(minutes=self.config.server_utc_offset_minutes))

    def connect(self) -> None:
        if self.connected:
            return
        kwargs: dict[str, Any] = {}
        if self.config.terminal.expected_login:
            kwargs["login"] = self.config.terminal.expected_login
        if self.config.terminal.expected_server:
            kwargs["server"] = self.config.terminal.expected_server
        path = self.config.terminal.path
        initialized = self.mt5.initialize(path, **kwargs) if path else self.mt5.initialize(**kwargs)
        if not initialized:
            raise RuntimeError(f"MT5 initialize failed: {self.mt5.last_error()}")
        if not self.mt5.symbol_select(self.config.symbol, True):
            self.mt5.shutdown()
            raise RuntimeError(f"MT5 symbol selection failed: {self.mt5.last_error()}")
        self.connected = True
        self.validate_binding()

    def close(self) -> None:
        if self.connected:
            self.mt5.shutdown()
            self.connected = False

    def account_info(self) -> Any:
        self.connect()
        account = self.mt5.account_info()
        if account is None:
            raise RuntimeError(f"MT5 account_info failed: {self.mt5.last_error()}")
        return account

    def validate_binding(self) -> None:
        account = self.mt5.account_info()
        terminal = self.mt5.terminal_info()
        info = self.mt5.symbol_info(self.config.symbol)
        if account is None or terminal is None or info is None:
            raise RuntimeError("MT5 terminal/account/symbol metadata is unavailable")
        binding = self.config.terminal
        if binding.require_account_binding:
            if int(account.login) != binding.expected_login:
                raise RuntimeError(
                    f"MT5 login mismatch: expected {binding.expected_login}, got {account.login}"
                )
            if str(account.server) != binding.expected_server:
                raise RuntimeError(
                    f"MT5 server mismatch: expected {binding.expected_server}, got {account.server}"
                )
        if self.config.order_execution:
            expected_modes = {
                "demo": int(getattr(self.mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)),
                "real": int(getattr(self.mt5, "ACCOUNT_TRADE_MODE_REAL", 2)),
            }
            if binding.expected_trade_mode not in expected_modes:
                raise RuntimeError("executable worker requires explicit demo/real trade mode")
            expected_mode = expected_modes[binding.expected_trade_mode]
            if int(account.trade_mode) != expected_mode:
                raise RuntimeError(
                    f"{self.config.group} worker refuses account trade mode "
                    f"{account.trade_mode}; expected {binding.expected_trade_mode}"
                )
            if not bool(getattr(account, "trade_allowed", False)):
                raise RuntimeError("account trading is disabled")
            if not bool(getattr(account, "trade_expert", False)):
                raise RuntimeError("expert trading is disabled for the account")
            if not bool(getattr(terminal, "trade_allowed", False)):
                raise RuntimeError("Algo Trading is disabled in the terminal")
        if str(info.name) != self.config.symbol:
            raise RuntimeError(f"symbol mismatch: {info.name}")

    def closed_revised_bars(self, timeframe_name: str, count: int) -> tuple[RevisedBar, ...]:
        self.connect()
        timeframe = getattr(self.mt5, timeframe_name)
        raw = self.mt5.copy_rates_from_pos(self.config.symbol, timeframe, 1, count)
        if raw is None:
            raise RuntimeError(f"MT5 rates failed for {timeframe_name}: {self.mt5.last_error()}")
        point = float(self.mt5.symbol_info(self.config.symbol).point)
        return tuple(
            RevisedBar(
                time=mt5_epoch_to_server_wall(int(row["time"]), self.server_timezone),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["tick_volume"]),
                spread=max(float(row["spread"]) * point, 0.0),
            )
            for row in raw
        )

    def bear_bars_range(
        self,
        timeframe_name: str,
        start: datetime,
        end: datetime,
    ) -> tuple[BearBar, ...]:
        self.connect()
        timeframe = getattr(self.mt5, timeframe_name)
        raw = self.mt5.copy_rates_range(
            self.config.symbol,
            timeframe,
            start.astimezone(UTC),
            end.astimezone(UTC),
        )
        if raw is None:
            raise RuntimeError(
                f"MT5 range rates failed for {timeframe_name}: {self.mt5.last_error()}"
            )
        point = float(self.mt5.symbol_info(self.config.symbol).point)
        return tuple(
            BearBar(
                time=mt5_epoch_to_server_wall(int(row["time"]), self.server_timezone),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                tick_volume=float(row["tick_volume"]),
                spread=max(float(row["spread"]) * point, 0.0),
            )
            for row in raw
        )

    def select_lot(self) -> float:
        balance = float(self.account_info().balance)
        return self.normalize_volume(self.config.lot_for_balance(balance))

    def normalize_volume(self, volume: float) -> float:
        info = self.mt5.symbol_info(self.config.symbol)
        minimum = float(info.volume_min)
        maximum = float(info.volume_max)
        step = float(info.volume_step)
        capped = min(volume, maximum, self.config.maximum_total_lot or maximum)
        normalized = floor((capped + 1e-12) / step) * step
        if normalized + 1e-12 < minimum:
            return 0.0
        decimals = max(0, len(f"{step:.10f}".rstrip("0").split(".")[-1]))
        return round(normalized, decimals)

    def managed_positions(self) -> Sequence[Any]:
        positions = self.mt5.positions_get(symbol=self.config.symbol)
        if positions is None:
            raise RuntimeError(f"MT5 positions_get failed: {self.mt5.last_error()}")
        return tuple(
            position
            for position in positions
            if int(getattr(position, "magic", 0)) == self.config.magic
        )

    def closed_position_result(self, position_ticket: int) -> dict[str, Any] | None:
        current = self.mt5.positions_get(ticket=position_ticket)
        if current:
            return None
        deals = self.mt5.history_deals_get(position=position_ticket)
        if deals is None:
            raise RuntimeError(f"history_deals_get failed: {self.mt5.last_error()}")
        if not deals:
            return None
        exit_types = {
            int(getattr(self.mt5, "DEAL_ENTRY_OUT", 1)),
            int(getattr(self.mt5, "DEAL_ENTRY_OUT_BY", 3)),
        }
        exits = [deal for deal in deals if int(getattr(deal, "entry", -1)) in exit_types]
        if not exits:
            return None
        close_deal = max(exits, key=lambda deal: int(getattr(deal, "time_msc", 0)))
        total_pl = sum(
            float(getattr(deal, "profit", 0.0))
            + float(getattr(deal, "swap", 0.0))
            + float(getattr(deal, "commission", 0.0))
            + float(getattr(deal, "fee", 0.0))
            for deal in deals
        )
        account = self.account_info()
        return {
            "position_ticket": position_ticket,
            "close_time": datetime.fromtimestamp(int(close_deal.time), tz=self.server_timezone),
            "close_price": float(close_deal.price),
            "profit_loss": total_pl,
            "balance": float(account.balance),
            "equity": float(account.equity),
            "deal_count": len(deals),
        }

    def execute(self, signal: SignalPlan) -> dict[str, Any]:
        return {
            "status": "SIGNAL_ONLY",
            "order_authority": self.config.order_authority.upper(),
            "signal_id": signal.event_id,
        }

    def _tick_server_time(self, tick: Any) -> datetime | None:
        time_msc = int(getattr(tick, "time_msc", 0) or 0)
        if time_msc > 0:
            return datetime.fromtimestamp(time_msc / 1000.0, tz=self.server_timezone)
        timestamp = int(getattr(tick, "time", 0) or 0)
        if timestamp > 0:
            return datetime.fromtimestamp(timestamp, tz=self.server_timezone)
        return None

    def _filling_type(self, info: Any) -> int:
        filling = int(getattr(info, "filling_mode", 0))
        if filling & 1 and hasattr(self.mt5, "ORDER_FILLING_FOK"):
            return int(self.mt5.ORDER_FILLING_FOK)
        if filling & 2 and hasattr(self.mt5, "ORDER_FILLING_IOC"):
            return int(self.mt5.ORDER_FILLING_IOC)
        return int(getattr(self.mt5, "ORDER_FILLING_RETURN", self.mt5.ORDER_FILLING_FOK))
