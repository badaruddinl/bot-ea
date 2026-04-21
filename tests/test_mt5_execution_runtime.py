from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.models import (  # noqa: E402
    AccountSnapshot,
    CapitalAllocation,
    CapitalAllocationMode,
    OperatingMode,
    PositionSizeResult,
    RiskPolicy,
    SymbolSnapshot,
    TradingStyle,
)
from bot_ea.mt5_adapter import MockMT5Adapter  # noqa: E402
from bot_ea.mt5_adapter import PriceTickSnapshot  # noqa: E402
from bot_ea.mt5_execution_runtime import MT5ExecutionRuntime  # noqa: E402
from bot_ea.polling_runtime import AIIntent, DecisionAction, RuntimeSnapshot  # noqa: E402


class RefreshingMockMT5Adapter(MockMT5Adapter):
    def __init__(self, *args, tick_bid: float, tick_ask: float, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tick_bid = tick_bid
        self._tick_ask = tick_ask
        self.validated_requests: list[dict] = []
        self.sent_requests: list[dict] = []

    def load_price_tick(self, symbol: str) -> PriceTickSnapshot:
        return PriceTickSnapshot(symbol=symbol, bid=self._tick_bid, ask=self._tick_ask, time="2026-04-21T00:00:01+00:00")

    def validate_order(self, request: dict):
        self.validated_requests.append(dict(request))
        return super().validate_order(request)

    def send_order(self, request: dict):
        self.sent_requests.append(dict(request))
        return super().send_order(request)


class MT5ExecutionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = MockMT5Adapter(
            account_info={"equity": 1000.0, "balance": 1000.0, "margin_free": 900.0, "margin_level": 400.0},
            symbols={
                "EURUSD": {
                    "name": "EURUSD",
                    "point": 0.0001,
                    "trade_tick_size": 0.0001,
                    "trade_tick_value": 10.0,
                    "volume_min": 0.01,
                    "volume_max": 10.0,
                    "volume_step": 0.01,
                    "spread": 2,
                    "trade_stops_level": 10,
                    "trade_freeze_level": 0,
                    "visible": True,
                    "bid": 1.1000,
                    "ask": 1.1002,
                }
            },
        )
        self.snapshot = RuntimeSnapshot(
            symbol="EURUSD",
            timeframe="M5",
            bid=1.1000,
            ask=1.1002,
            spread_points=2.0,
            account=AccountSnapshot(equity=1000.0, balance=1000.0, free_margin=900.0, margin_level=400.0),
            symbol_snapshot=SymbolSnapshot(
                name="EURUSD",
                instrument_class="forex_major",
                risk_weight=1.0,
                point=0.0001,
                tick_size=0.0001,
                tick_value=10.0,
                volume_min=0.01,
                volume_max=10.0,
                volume_step=0.01,
                spread_points=2.0,
                stops_level_points=10.0,
                freeze_level_points=0.0,
                trade_mode="full",
                order_mode="market",
                quote_session_active=True,
                trade_session_active=True,
                trade_allowed=True,
                bid=1.1000,
                ask=1.1002,
                price=1.1002,
            ),
            risk_policy=RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0),
            trading_style=TradingStyle.INTRADAY,
            stop_distance_points=50.0,
            capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.FIXED_CASH, value=200.0),
        )
        self.intent = AIIntent(
            action=DecisionAction.OPEN,
            side="buy",
            reason="test",
            stop_distance_points=50.0,
            entry_price=1.1002,
        )
        self.size_result = PositionSizeResult(
            accepted=True,
            mode=OperatingMode.RECOMMEND,
            capital_base_cash=200.0,
            recommended_minimum_allocation_cash=100.0,
            effective_risk_pct=1.0,
            risk_cash_budget=2.0,
            normalized_volume=0.01,
            estimated_loss_cash=2.0,
            stop_distance_points=50.0,
        )

    def test_preflight_works(self) -> None:
        runtime = MT5ExecutionRuntime(adapter=self.adapter)
        result = runtime.preflight(self.snapshot, self.intent, self.size_result)
        self.assertEqual(result["status"], "PRECHECK_OK")
        self.assertIn("request", result)

    def test_execute_defaults_to_dry_run(self) -> None:
        runtime = MT5ExecutionRuntime(adapter=self.adapter)
        result = runtime.execute(self.snapshot, self.intent, self.size_result)
        self.assertEqual(result["status"], "DRY_RUN_OK")
        self.assertFalse(result["live_order_submitted"])

    def test_execute_live_submits(self) -> None:
        runtime = MT5ExecutionRuntime(adapter=self.adapter, allow_live_orders=True)
        result = runtime.execute(self.snapshot, self.intent, self.size_result)
        self.assertEqual(result["status"], "FILLED")
        self.assertTrue(result["live_order_submitted"])

    def test_execute_live_refreshes_price_before_revalidation_and_send(self) -> None:
        adapter = RefreshingMockMT5Adapter(
            account_info={"equity": 1000.0, "balance": 1000.0, "margin_free": 900.0, "margin_level": 400.0},
            symbols={
                "EURUSD": {
                    "name": "EURUSD",
                    "point": 0.0001,
                    "trade_tick_size": 0.0001,
                    "trade_tick_value": 10.0,
                    "volume_min": 0.01,
                    "volume_max": 10.0,
                    "volume_step": 0.01,
                    "spread": 2,
                    "trade_stops_level": 10,
                    "trade_freeze_level": 0,
                    "visible": True,
                    "bid": 1.1000,
                    "ask": 1.1002,
                }
            },
            tick_bid=1.1010,
            tick_ask=1.1013,
        )
        runtime = MT5ExecutionRuntime(adapter=adapter, allow_live_orders=True)
        result = runtime.execute(self.snapshot, self.intent, self.size_result)
        self.assertEqual(result["status"], "FILLED")
        self.assertEqual(result["request"]["price"], 1.1013)
        self.assertEqual(adapter.validated_requests[-1]["price"], 1.1013)
        self.assertEqual(adapter.sent_requests[-1]["price"], 1.1013)

    def test_close_position_dry_run_is_supported(self) -> None:
        runtime = MT5ExecutionRuntime(adapter=self.adapter)
        intent = AIIntent(
            action=DecisionAction.CLOSE,
            side="buy",
            reason="close test",
            payload={"position_ticket": 900001, "volume": 0.01},
        )

        result = runtime.execute(self.snapshot, intent, self.size_result)

        self.assertEqual(result["status"], "DRY_RUN_OK")
        self.assertEqual(result["request"]["action"], "close")
        self.assertEqual(result["request"]["order_type"], "sell")
        self.assertEqual(result["request"]["position_ticket"], 900001)

    def test_cancel_pending_dry_run_is_supported(self) -> None:
        runtime = MT5ExecutionRuntime(adapter=self.adapter)
        intent = AIIntent(
            action=DecisionAction.CANCEL_PENDING,
            side=None,
            reason="cancel test",
            payload={"order_ticket": 700001},
        )

        result = runtime.execute(self.snapshot, intent, self.size_result)

        self.assertEqual(result["status"], "DRY_RUN_OK")
        self.assertEqual(result["request"]["action"], "cancel_pending")
        self.assertEqual(result["request"]["order_ticket"], 700001)
