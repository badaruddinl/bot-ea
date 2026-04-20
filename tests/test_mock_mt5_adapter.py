from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.models import CapitalAllocation, CapitalAllocationMode, RiskPolicy, TradingStyle  # noqa: E402
from bot_ea.mt5_adapter import LiveMT5Adapter, MockMT5Adapter  # noqa: E402
from bot_ea.polling_runtime import MT5SnapshotProvider  # noqa: E402


class MockMT5AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = MockMT5Adapter(
            account_info={
                "equity": 1000.0,
                "balance": 1000.0,
                "margin_free": 800.0,
                "margin_level": 400.0,
            },
            symbols={
                "EURUSD": {
                    "name": "EURUSD",
                    "point": 0.0001,
                    "trade_tick_size": 0.0001,
                    "trade_tick_value": 10.0,
                    "volume_min": 0.01,
                    "volume_max": 10.0,
                    "volume_step": 0.01,
                    "spread": 12,
                    "trade_stops_level": 15,
                    "trade_freeze_level": 0,
                    "volatility_points": 200.0,
                    "visible": True,
                    "bid": 1.1000,
                    "ask": 1.1012,
                }
            },
            capabilities={
                "EURUSD": {
                    "trade_mode": "full",
                    "order_mode": "market",
                    "execution_mode": "market",
                    "filling_mode": "fok",
                    "quote_session_active": True,
                    "trade_session_active": True,
                    "server_time": "2026-04-20T09:00:00",
                }
            },
        )

    def test_load_symbol_capabilities(self) -> None:
        capabilities = self.adapter.load_symbol_capabilities("EURUSD")
        self.assertEqual(capabilities.trade_mode, "full")
        self.assertTrue(capabilities.trade_session_active)

    def test_validate_order_rejects_stop_level_violation(self) -> None:
        result = self.adapter.validate_order(
            {
                "symbol": "EURUSD",
                "volume": 0.10,
                "price": 1.1000,
                "order_type": "buy",
                "stop_distance_points": 5,
            }
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.retcode, 10016)

    def test_validate_order_accepts_valid_request(self) -> None:
        result = self.adapter.validate_order(
            {
                "symbol": "EURUSD",
                "volume": 0.10,
                "price": 1.1000,
                "order_type": "buy",
                "stop_distance_points": 25,
            }
        )
        self.assertTrue(result.accepted)
        self.assertGreater(result.projected_margin_free, 0)

    def test_mock_adapter_load_price_tick(self) -> None:
        tick = self.adapter.load_price_tick("EURUSD")
        self.assertGreater(tick.ask, tick.bid)

    def test_mock_adapter_send_order_returns_fill(self) -> None:
        result = self.adapter.send_order(
            {
                "symbol": "EURUSD",
                "volume": 0.10,
                "price": 1.1000,
                "order_type": "buy",
                "stop_distance_points": 25,
            }
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.order, 900001)


class FakeMT5Module:
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    ORDER_TIME_GTC = 0
    TRADE_ACTION_DEAL = 1

    def __init__(self) -> None:
        self.initialize_calls = []
        self.symbol_select_calls = []
        self.last_checked_request = None
        self._selected = False

    def initialize(self, **kwargs):
        self.initialize_calls.append(kwargs)
        return True

    def shutdown(self):
        return None

    def last_error(self):
        return (0, "ok")

    def account_info(self):
        return SimpleNamespace(
            equity=1200.0,
            balance=1180.0,
            margin_free=950.0,
            margin_level=420.0,
            positions=1,
            trade_allowed=True,
            trade_expert=True,
        )

    def symbol_info(self, symbol):
        visible = self._selected
        return SimpleNamespace(
            name=symbol,
            visible=visible,
            trade_mode=4,
            order_mode=127,
            trade_exemode=1,
            filling_mode=3,
            point=0.0001,
            trade_tick_size=0.0001,
            trade_tick_value=10.0,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            spread=15,
            trade_stops_level=12,
            trade_freeze_level=0,
            bid=1.0998,
            ask=1.1000,
            last=1.0999,
            trade_contract_size=100000.0,
            margin_initial=0.0,
            time=1713628800,
        )

    def symbol_select(self, symbol, enable):
        self.symbol_select_calls.append((symbol, enable))
        self._selected = True
        return True

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(
            bid=1.0998,
            ask=1.1000,
            last=1.0999,
            time=1713628800,
        )

    def order_calc_margin(self, order_type, symbol, volume, price):
        return 55.5

    def order_check(self, request):
        self.last_checked_request = request
        return SimpleNamespace(
            retcode=0,
            comment="accepted",
            margin_free=900.0,
            margin_level=380.0,
        )

    def order_send(self, request):
        self.last_checked_request = request
        return SimpleNamespace(
            retcode=10009,
            comment="done",
            order=123456,
            deal=654321,
            volume=request["volume"],
            price=request.get("price", 1.1),
            bid=1.0998,
            ask=1.1000,
            request_id=777,
            retcode_external=0,
        )


class LiveMT5AdapterTests(unittest.TestCase):
    def test_live_adapter_uses_symbol_select_and_order_check(self) -> None:
        fake_mt5 = FakeMT5Module()
        adapter = LiveMT5Adapter(mt5_module=fake_mt5)

        account = adapter.load_account_snapshot()
        symbol = adapter.load_symbol_snapshot("EURUSD")
        margin = adapter.estimate_margin("EURUSD", 0.1, "buy", 1.1000)
        result = adapter.validate_order(
            {
                "symbol": "EURUSD",
                "volume": 0.10,
                "order_type": "buy",
                "price": 1.1000,
                "stop_distance_points": 25,
            }
        )

        self.assertEqual(account.equity, 1200.0)
        self.assertEqual(symbol.instrument_class, "forex_major")
        self.assertTrue(fake_mt5.symbol_select_calls)
        self.assertTrue(margin.success)
        self.assertEqual(margin.required_margin, 55.5)
        self.assertTrue(result.accepted)
        self.assertEqual(result.retcode, 0)
        self.assertIsNotNone(fake_mt5.last_checked_request)
        self.assertIn("sl", fake_mt5.last_checked_request)

    def test_mt5_snapshot_provider_builds_runtime_snapshot(self) -> None:
        adapter = MockMT5Adapter(
            account_info={
                "equity": 1000.0,
                "balance": 1000.0,
                "margin_free": 800.0,
                "margin_level": 400.0,
            },
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
                    "trade_stops_level": 15,
                    "trade_freeze_level": 0,
                    "visible": True,
                    "bid": 1.1000,
                    "ask": 1.1002,
                }
            },
        )
        provider = MT5SnapshotProvider(
            adapter=adapter,
            symbol="EURUSD",
            timeframe="M5",
            risk_policy=RiskPolicy(base_risk_pct=1.0, max_total_open_risk_pct=2.0, daily_loss_limit_pct=3.0),
            trading_style=TradingStyle.INTRADAY,
            stop_distance_points=50.0,
            capital_allocation=CapitalAllocation(mode=CapitalAllocationMode.FIXED_CASH, value=200.0),
            session_state="london",
            news_state="clear",
        )

        snapshot = provider.get_snapshot()

        self.assertEqual(snapshot.symbol, "EURUSD")
        self.assertEqual(snapshot.bid, 1.1000)
        self.assertEqual(snapshot.ask, 1.1002)
        self.assertAlmostEqual(snapshot.spread_points, 2.0)
        self.assertEqual(snapshot.symbol_snapshot.ask, 1.1002)
        self.assertIn("tick_time", snapshot.context)

    def test_live_adapter_send_order_returns_broker_result(self) -> None:
        fake_mt5 = FakeMT5Module()
        adapter = LiveMT5Adapter(mt5_module=fake_mt5)

        result = adapter.send_order(
            {
                "symbol": "EURUSD",
                "volume": 0.10,
                "order_type": "buy",
                "price": 1.1000,
                "stop_distance_points": 25,
            }
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.order, 123456)
        self.assertEqual(result.retcode, 10009)

    def test_live_adapter_reinitializes_after_no_ipc_on_account_info(self) -> None:
        class IPCFlakyAccountMT5(FakeMT5Module):
            def __init__(self) -> None:
                super().__init__()
                self.shutdown_calls = 0
                self._fail_next_account_info = True
                self._last_error = (0, "ok")

            def shutdown(self):
                self.shutdown_calls += 1
                return None

            def last_error(self):
                return self._last_error

            def account_info(self):
                if self._fail_next_account_info:
                    self._fail_next_account_info = False
                    self._last_error = (-10004, "No IPC connection")
                    return None
                self._last_error = (0, "ok")
                return super().account_info()

        fake_mt5 = IPCFlakyAccountMT5()
        adapter = LiveMT5Adapter(mt5_module=fake_mt5)

        account = adapter.load_account_snapshot()

        self.assertEqual(account.equity, 1200.0)
        self.assertEqual(len(fake_mt5.initialize_calls), 2)
        self.assertEqual(fake_mt5.shutdown_calls, 1)

    def test_live_adapter_reinitializes_after_no_ipc_on_tick(self) -> None:
        class IPCFlakyTickMT5(FakeMT5Module):
            def __init__(self) -> None:
                super().__init__()
                self.shutdown_calls = 0
                self._fail_next_tick = True
                self._last_error = (0, "ok")

            def shutdown(self):
                self.shutdown_calls += 1
                return None

            def last_error(self):
                return self._last_error

            def symbol_info_tick(self, symbol):
                if self._fail_next_tick:
                    self._fail_next_tick = False
                    self._last_error = (-10004, "No IPC connection")
                    return None
                self._last_error = (0, "ok")
                return super().symbol_info_tick(symbol)

        fake_mt5 = IPCFlakyTickMT5()
        adapter = LiveMT5Adapter(mt5_module=fake_mt5)

        tick = adapter.load_price_tick("EURUSD")

        self.assertEqual(tick.ask, 1.1000)
        self.assertEqual(len(fake_mt5.initialize_calls), 2)
        self.assertEqual(fake_mt5.shutdown_calls, 1)


if __name__ == "__main__":
    unittest.main()
