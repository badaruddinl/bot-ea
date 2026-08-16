from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.models import CapitalAllocation, CapitalAllocationMode, RiskPolicy, TradingStyle  # noqa: E402
from bot_ea.mt5_adapter import (  # noqa: E402
    LiveMT5Adapter,
    MockMT5Adapter,
    MutationAccountBinding,
    OpenPositionSnapshot,
)
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

    def test_mock_adapter_modifies_protection_and_preserves_omitted_tp(self) -> None:
        adapter = MockMT5Adapter(
            account_info=self.adapter._account_info,
            symbols=self.adapter._symbols,
            open_positions=[
                OpenPositionSnapshot(
                    ticket=321,
                    symbol="EURUSD",
                    side="buy",
                    volume=0.1,
                    price_open=1.1000,
                    sl=1.0900,
                    tp=1.1200,
                    profit=5.0,
                    opened_at="2024-04-20T00:00:00+00:00",
                    magic=260814,
                    comment="GMS: abc123",
                    position_identifier=987,
                )
            ],
        )

        result = adapter.modify_position_protection(
            position_identifier=987,
            sl=1.09504,
        )

        self.assertTrue(result.accepted)
        self.assertTrue(result.changed)
        self.assertTrue(result.postcondition_met)
        self.assertEqual(result.position_ticket, 321)
        self.assertEqual(result.position_identifier, 987)
        self.assertAlmostEqual(result.sl or 0.0, 1.0950)
        self.assertAlmostEqual(result.tp or 0.0, 1.1200)
        observed = adapter.find_open_position(position_identifier=987)
        self.assertIsNotNone(observed)
        self.assertAlmostEqual(observed.tp, 1.1200)

        idempotent = adapter.modify_position_protection(
            position_identifier=987,
            sl=1.0950,
        )
        self.assertTrue(idempotent.accepted)
        self.assertFalse(idempotent.changed)
        self.assertTrue(idempotent.postcondition_met)
        self.assertIsNone(idempotent.retcode)

    def test_mock_adapter_falls_back_to_ticket_as_stable_identifier(self) -> None:
        legacy_position = OpenPositionSnapshot(
            ticket=321,
            symbol="EURUSD",
            side="buy",
            volume=0.1,
            price_open=1.1000,
            sl=1.0900,
            tp=1.1200,
            profit=5.0,
            opened_at=None,
            magic=260814,
            comment="legacy constructor",
        )
        self.assertEqual(legacy_position.position_identifier, 321)
        adapter = MockMT5Adapter(
            account_info=self.adapter._account_info,
            symbols=self.adapter._symbols,
            open_positions=[legacy_position],
        )

        position = adapter.find_open_position(position_identifier=321)

        self.assertIsNotNone(position)
        self.assertEqual(position.position_identifier, 321)


class FakeMT5Module:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_CONTEST = 1
    ACCOUNT_TRADE_MODE_REAL = 2
    ACCOUNT_MARGIN_MODE_RETAIL_NETTING = 0
    ACCOUNT_MARGIN_MODE_EXCHANGE = 1
    ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    ORDER_TIME_GTC = 0
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 6
    TRADE_RETCODE_PLACED = 10008
    TRADE_RETCODE_DONE = 10009
    POSITION_TYPE_BUY = 0
    DEAL_TYPE_BUY = 0
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_INOUT = 2
    DEAL_ENTRY_OUT_BY = 3
    DEAL_REASON_EXPERT = 3
    DEAL_REASON_SL = 4
    DEAL_REASON_TP = 5

    def __init__(self) -> None:
        self.initialize_calls = []
        self.symbol_select_calls = []
        self.last_checked_request = None
        self.order_send_calls = []
        self._selected = False
        self._position_ticket = 321
        self._position_sl = 1.09
        self._position_tp = 1.12

    def initialize(self, **kwargs):
        self.initialize_calls.append(kwargs)
        return True

    def shutdown(self):
        return None

    def last_error(self):
        return (0, "ok")

    def positions_get(self, **kwargs):
        return (
            SimpleNamespace(
                ticket=self._position_ticket, symbol="EURUSD", type=0, volume=0.1, price_open=1.1,
                sl=self._position_sl, tp=self._position_tp, profit=5.0,
                time=1713628800, magic=260814, comment="GMS: abc123",
                identifier=987,
            ),
        )

    def history_deals_get(self, start, end):
        return (
            SimpleNamespace(
                ticket=654, position_id=321, symbol="EURUSD", type=1, entry=1,
                volume=0.1, price=1.12, profit=20.0, commission=-0.5, swap=0.0,
                fee=-0.25,
                reason=5, time=1713629800, magic=260814, comment="GMS: abc123",
            ),
        )

    def account_info(self):
        return SimpleNamespace(
            login=108098316,
            server="XMGlobal-MT5",
            company="XM Global Limited",
            trade_mode=self.ACCOUNT_TRADE_MODE_DEMO,
            margin_mode=self.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING,
            equity=1200.0,
            balance=1180.0,
            margin_free=950.0,
            margin_level=420.0,
            positions=1,
            trade_allowed=True,
            trade_expert=True,
        )

    def terminal_info(self):
        return SimpleNamespace(
            connected=True,
            trade_allowed=True,
            tradeapi_disabled=False,
            path=r"C:\MT5",
            data_path=r"C:\MT5Data",
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
        self.order_send_calls.append(dict(request))
        if request["action"] == self.TRADE_ACTION_SLTP:
            self._position_sl = request["sl"]
            self._position_tp = request["tp"]
        return SimpleNamespace(
            retcode=10009,
            comment="done",
            order=123456,
            deal=654321,
            volume=request.get("volume", 0.0),
            price=request.get("price", 1.1),
            bid=1.0998,
            ask=1.1000,
            request_id=777,
            retcode_external=0,
        )


class LiveMT5AdapterTests(unittest.TestCase):
    def test_live_adapter_uses_account_trade_mode_for_demo_fingerprint(self) -> None:
        adapter = LiveMT5Adapter(mt5_module=FakeMT5Module())

        fingerprint = adapter.load_account_fingerprint()

        self.assertFalse(fingerprint.is_live)
        self.assertEqual(fingerprint.login, "108098316")
        self.assertEqual(fingerprint.server, "XMGlobal-MT5")
        self.assertEqual(fingerprint.margin_mode, "HEDGING")

    def test_live_adapter_exposes_netting_margin_mode_without_guessing(self) -> None:
        class NettingAccountMT5(FakeMT5Module):
            def account_info(self):
                account = super().account_info()
                return SimpleNamespace(
                    **{
                        **vars(account),
                        "margin_mode": self.ACCOUNT_MARGIN_MODE_RETAIL_NETTING,
                    }
                )

        fingerprint = LiveMT5Adapter(
            mt5_module=NettingAccountMT5()
        ).load_account_fingerprint()

        self.assertEqual(fingerprint.margin_mode, "NETTING")

    def test_live_adapter_uses_account_trade_mode_for_real_fingerprint(self) -> None:
        class RealAccountMT5(FakeMT5Module):
            def account_info(self):
                account = super().account_info()
                return SimpleNamespace(**{**vars(account), "trade_mode": self.ACCOUNT_TRADE_MODE_REAL})

        adapter = LiveMT5Adapter(mt5_module=RealAccountMT5())

        self.assertTrue(adapter.load_account_fingerprint().is_live)

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

    def test_live_adapter_maps_positions_and_deals_for_lifecycle_reconciliation(self) -> None:
        adapter = LiveMT5Adapter(mt5_module=FakeMT5Module())
        positions = adapter.load_open_positions(symbol="EURUSD")
        deals = adapter.load_deals(
            since=datetime(2024, 4, 20, tzinfo=timezone.utc), symbol="EURUSD"
        )
        self.assertEqual(positions[0].ticket, 321)
        self.assertEqual(positions[0].position_identifier, 987)
        self.assertEqual(positions[0].side, "buy")
        self.assertEqual(deals[0].position_ticket, 321)
        self.assertEqual(deals[0].reason, "take_profit")
        self.assertEqual(deals[0].entry, "out")
        self.assertEqual(deals[0].fee, -0.25)

    def test_live_adapter_modifies_sltp_without_volume_and_preserves_tp(self) -> None:
        fake_mt5 = FakeMT5Module()
        adapter = LiveMT5Adapter(mt5_module=fake_mt5)

        result = adapter.modify_position_protection(
            position_identifier=987,
            sl=1.09504,
        )

        self.assertTrue(result.accepted)
        self.assertTrue(result.changed)
        self.assertTrue(result.postcondition_met)
        self.assertEqual(result.retcode, fake_mt5.TRADE_RETCODE_DONE)
        self.assertEqual(result.position_ticket, 321)
        self.assertEqual(result.order, 123456)
        self.assertEqual(result.deal, 654321)
        self.assertEqual(result.request_id, 777)
        self.assertEqual(result.retcode_external, 0)
        request = fake_mt5.order_send_calls[-1]
        self.assertEqual(
            set(request),
            {"action", "symbol", "position", "sl", "tp"},
        )
        self.assertEqual(request["action"], fake_mt5.TRADE_ACTION_SLTP)
        self.assertEqual(request["position"], 321)
        self.assertAlmostEqual(request["sl"], 1.0950)
        self.assertAlmostEqual(request["tp"], 1.1200)
        self.assertNotIn("volume", request)

    def test_live_adapter_resolves_current_ticket_from_stable_identifier(self) -> None:
        fake_mt5 = FakeMT5Module()
        fake_mt5._position_ticket = 654
        adapter = LiveMT5Adapter(mt5_module=fake_mt5)

        position = adapter.find_open_position(position_identifier=987)
        result = adapter.modify_position_protection(
            position_ticket=321,
            position_identifier=987,
            sl=1.0950,
        )

        self.assertIsNotNone(position)
        self.assertEqual(position.ticket, 654)
        self.assertTrue(result.accepted)
        self.assertEqual(result.position_identifier, 987)
        self.assertEqual(result.position_ticket, 654)
        self.assertEqual(fake_mt5.order_send_calls[-1]["position"], 654)

        churned = adapter.find_open_position(
            position_ticket=321,
            position_identifier=987,
        )
        self.assertIsNotNone(churned)
        self.assertEqual(churned.ticket, 654)

    def test_live_adapter_idempotent_protection_does_not_send_order(self) -> None:
        fake_mt5 = FakeMT5Module()
        adapter = LiveMT5Adapter(mt5_module=fake_mt5)

        result = adapter.modify_position_protection(
            position_ticket=321,
            sl=1.0900,
        )

        self.assertTrue(result.accepted)
        self.assertFalse(result.changed)
        self.assertTrue(result.postcondition_met)
        self.assertIsNone(result.retcode)
        self.assertEqual(fake_mt5.order_send_calls, [])

    def test_live_adapter_rejects_non_done_retcode_even_if_postcondition_is_met(self) -> None:
        class RejectedButAppliedMT5(FakeMT5Module):
            def order_send(self, request):
                result = super().order_send(request)
                return SimpleNamespace(**{**vars(result), "retcode": self.TRADE_RETCODE_PLACED})

        fake_mt5 = RejectedButAppliedMT5()
        adapter = LiveMT5Adapter(mt5_module=fake_mt5)

        result = adapter.modify_position_protection(position_ticket=321, sl=1.0950)

        self.assertFalse(result.accepted)
        self.assertTrue(result.postcondition_met)
        self.assertTrue(result.changed)
        self.assertEqual(result.retcode, fake_mt5.TRADE_RETCODE_PLACED)

    def test_live_adapter_rejects_done_when_postcondition_is_not_met(self) -> None:
        class DoneWithoutApplyingMT5(FakeMT5Module):
            def order_send(self, request):
                self.last_checked_request = request
                self.order_send_calls.append(dict(request))
                return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, comment="done")

        fake_mt5 = DoneWithoutApplyingMT5()
        adapter = LiveMT5Adapter(mt5_module=fake_mt5)

        result = adapter.modify_position_protection(position_ticket=321, sl=1.0950)

        self.assertFalse(result.accepted)
        self.assertFalse(result.postcondition_met)
        self.assertFalse(result.changed)
        self.assertEqual(result.retcode, fake_mt5.TRADE_RETCODE_DONE)

    def test_live_order_send_does_not_retry_ambiguous_ipc_result(self) -> None:
        class AmbiguousOrderMT5(FakeMT5Module):
            def __init__(self) -> None:
                super().__init__()
                self.send_attempts = 0

            def last_error(self):
                return (-10004, "No IPC connection")

            def order_send(self, request):
                self.send_attempts += 1
                return None

        fake_mt5 = AmbiguousOrderMT5()
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

        self.assertFalse(result.accepted)
        self.assertTrue(result.outcome_unknown)
        self.assertEqual(result.execution_status, "UNKNOWN")
        self.assertEqual(fake_mt5.send_attempts, 1)
        self.assertEqual(len(fake_mt5.initialize_calls), 1)

    def test_live_order_rechecks_account_binding_immediately_before_send(self) -> None:
        class SwitchedAccountMT5(FakeMT5Module):
            def account_info(self):
                account = super().account_info()
                return SimpleNamespace(**{**vars(account), "login": 999999})

        fake_mt5 = SwitchedAccountMT5()
        adapter = LiveMT5Adapter(mt5_module=fake_mt5)
        result = adapter.send_order(
            {
                "symbol": "EURUSD",
                "volume": 0.10,
                "order_type": "buy",
                "price": 1.1000,
                "stop_distance_points": 25,
                "_mutation_binding": MutationAccountBinding(
                    login="108098316",
                    server="XMGlobal-MT5",
                    broker="XM Global Limited",
                    account_scope="demo",
                    margin_mode="HEDGING",
                ),
            }
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.execution_status, "REJECTED")
        self.assertIn("login changed", result.detail)
        self.assertEqual(fake_mt5.order_send_calls, [])

    def test_live_order_rejects_netting_account_before_send(self) -> None:
        class NettingAccountMT5(FakeMT5Module):
            def account_info(self):
                account = super().account_info()
                return SimpleNamespace(
                    **{
                        **vars(account),
                        "margin_mode": self.ACCOUNT_MARGIN_MODE_RETAIL_NETTING,
                    }
                )

        fake_mt5 = NettingAccountMT5()
        adapter = LiveMT5Adapter(mt5_module=fake_mt5)
        result = adapter.send_order(
            {
                "symbol": "EURUSD",
                "volume": 0.10,
                "order_type": "buy",
                "price": 1.1000,
                "stop_distance_points": 25,
                "_mutation_binding": MutationAccountBinding(
                    login="108098316",
                    server="XMGlobal-MT5",
                    broker="XM Global Limited",
                    account_scope="demo",
                    margin_mode="HEDGING",
                ),
            }
        )

        self.assertFalse(result.accepted)
        self.assertIn("margin mode changed", result.detail)
        self.assertEqual(fake_mt5.order_send_calls, [])

    def test_live_adapter_can_require_mutation_binding(self) -> None:
        fake_mt5 = FakeMT5Module()
        adapter = LiveMT5Adapter(
            mt5_module=fake_mt5,
            require_mutation_binding=True,
        )

        result = adapter.send_order(
            {
                "symbol": "EURUSD",
                "volume": 0.10,
                "order_type": "buy",
                "price": 1.1000,
                "stop_distance_points": 25,
            }
        )

        self.assertFalse(result.accepted)
        self.assertIn("missing its immutable account binding", result.detail)
        self.assertEqual(fake_mt5.order_send_calls, [])

    def test_live_adapter_accepts_exact_account_and_terminal_binding(self) -> None:
        fake_mt5 = FakeMT5Module()
        adapter = LiveMT5Adapter(
            mt5_module=fake_mt5,
            path=r"C:\MT5\terminal64.exe",
            login=108098316,
            server="XMGlobal-MT5",
            require_mutation_binding=True,
        )
        binding = MutationAccountBinding(
            login="108098316",
            server="XMGlobal-MT5",
            broker="XM Global Limited",
            account_scope="demo",
            margin_mode="HEDGING",
            terminal_path=r"C:\MT5",
            terminal_data_path=r"C:\MT5Data",
        )

        result = adapter.send_order(
            {
                "symbol": "EURUSD",
                "volume": 0.10,
                "order_type": "buy",
                "price": 1.1000,
                "stop_distance_points": 25,
                "_mutation_binding": binding,
            }
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.execution_status, "FILLED")
        self.assertEqual(len(fake_mt5.order_send_calls), 1)

    def test_live_protection_rechecks_terminal_binding_before_send(self) -> None:
        class SwitchedTerminalMT5(FakeMT5Module):
            def terminal_info(self):
                terminal = super().terminal_info()
                return SimpleNamespace(
                    **{**vars(terminal), "data_path": r"C:\UnexpectedData"}
                )

        fake_mt5 = SwitchedTerminalMT5()
        adapter = LiveMT5Adapter(mt5_module=fake_mt5)
        result = adapter.modify_position_protection(
            position_identifier=987,
            sl=1.0950,
            mutation_binding=MutationAccountBinding(
                login="108098316",
                server="XMGlobal-MT5",
                broker="XM Global Limited",
                account_scope="demo",
                margin_mode="HEDGING",
                terminal_path=r"C:\MT5",
                terminal_data_path=r"C:\MT5Data",
            ),
        )

        self.assertFalse(result.accepted)
        self.assertIn("data path changed", result.detail)
        self.assertEqual(fake_mt5.order_send_calls, [])

    def test_live_sltp_does_not_retry_ambiguous_ipc_result(self) -> None:
        class AmbiguousProtectionMT5(FakeMT5Module):
            def __init__(self) -> None:
                super().__init__()
                self.send_attempts = 0

            def last_error(self):
                return (-10004, "No IPC connection")

            def order_send(self, request):
                self.send_attempts += 1
                return None

        fake_mt5 = AmbiguousProtectionMT5()
        adapter = LiveMT5Adapter(mt5_module=fake_mt5)

        result = adapter.modify_position_protection(
            position_ticket=321,
            position_identifier=987,
            sl=1.0950,
        )

        self.assertFalse(result.accepted)
        self.assertTrue(result.outcome_unknown)
        self.assertFalse(result.postcondition_met)
        self.assertEqual(fake_mt5.send_attempts, 1)
        self.assertEqual(len(fake_mt5.initialize_calls), 1)

    def test_live_sltp_exposes_reconciled_state_after_lost_response(self) -> None:
        class AppliedWithoutResponseMT5(FakeMT5Module):
            def __init__(self) -> None:
                super().__init__()
                self.send_attempts = 0

            def last_error(self):
                return (-10004, "No IPC connection")

            def order_send(self, request):
                self.send_attempts += 1
                self._position_sl = request["sl"]
                self._position_tp = request["tp"]
                return None

        fake_mt5 = AppliedWithoutResponseMT5()
        adapter = LiveMT5Adapter(mt5_module=fake_mt5)

        result = adapter.modify_position_protection(position_identifier=987, sl=1.0950)

        self.assertFalse(result.accepted)
        self.assertTrue(result.outcome_unknown)
        self.assertTrue(result.postcondition_met)
        self.assertTrue(result.changed)
        self.assertEqual(result.sl, 1.0950)
        self.assertEqual(fake_mt5.send_attempts, 1)

    def test_mt5_snapshot_provider_builds_runtime_snapshot(self) -> None:
        adapter = MockMT5Adapter(
            account_info={
                "equity": 1000.0,
                "balance": 1000.0,
                "margin_free": 800.0,
                "margin_level": 400.0,
                "login": 108098316,
                "server": "XMGlobal-MT5",
                "company": "XM Global Limited",
                "margin_mode": "HEDGING",
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
        self.assertEqual(
            snapshot.context["account_fingerprint"]["margin_mode"], "HEDGING"
        )

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
