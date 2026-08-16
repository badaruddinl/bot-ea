from __future__ import annotations

import tempfile
import unittest
import sys
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.mt5_adapter import (
    DealSnapshot,
    MockMT5Adapter,
    MutationAccountBinding,
    OpenPositionSnapshot,
    OrderSendResult,
    PositionProtectionResult,
)
from goldm_signal.notify.mt5_log import Mt5LogBridge
from goldm_signal.notify.position_manager import (
    BrokerPositionManager,
    PositionManagementCycle,
)
from goldm_signal.notify.trade_lifecycle import (
    TradeLifecycleConfig,
    TradeLifecycleWorker,
)
from goldm_signal.storage import SignalStore


NOW = datetime(2026, 8, 13, 12, 1, tzinfo=timezone.utc)
SETUP_ID = "GOLD.i#-BUY-4379.22-2026.08.13 15:00"
SIGNAL = (
    "SNIPER_SIGNAL id=GOLD.i#-BUY-4379.22-2026.08.13 15:00 status=ENTRY_READY "
    "strategy=GOLDM_SNIPER_PARITY strategyVersion=1.72 directionProfile=ALL "
    "accountScope=demo accountLogin=123456 originServerB64=QnJva2VyLURlbW8 "
    "strategyMode=0 autoEntryEligible=true side=BUY level=4379.22 entry=4380.10 stop=4374.20 "
    "target=4397.80 projectedR=3.000 score=78 m5Votes=3 m1Confirmed=true "
    f"setupUtcEpoch={int(NOW.timestamp()) - 60} generatedUtcEpoch={int(NOW.timestamp())} "
    f"serverUtcOffsetMinutes=180 validUntilUtcEpoch={int(NOW.timestamp()) + 300} "
    "maxHoldingMinutes=1440"
)
SELL_SIGNAL = (
    SIGNAL.replace("-BUY-", "-SELL-")
    .replace("side=BUY", "side=SELL")
    .replace("stop=4374.20", "stop=4386.00")
    .replace("target=4397.80", "target=4362.40")
)


class StatefulBrokerAdapter(MockMT5Adapter):
    def __init__(
        self,
        *,
        materialize_open: bool = True,
        partial_open: bool = False,
        open_sl: float | None = None,
        open_tp: float | None = None,
        close_removes_position: bool = True,
    ) -> None:
        super().__init__(
            account_info={
                "equity": 10_000.0,
                "balance": 10_000.0,
                "margin_free": 9_000.0,
                "margin_level": 500.0,
                "trade_allowed": True,
                "trade_expert": True,
                "login": 123456,
                "server": "Broker-Demo",
                "margin_mode": "HEDGING",
                "company": "Broker",
            },
            symbols={
                "GOLD.i#": {
                    "name": "GOLD.i#",
                    "point": 0.01,
                    "trade_tick_size": 0.05,
                    "trade_tick_value": 1.0,
                    "volume_min": 0.01,
                    "volume_max": 50.0,
                    "volume_step": 0.01,
                    "spread": 20,
                    "trade_stops_level": 10,
                    "trade_freeze_level": 0,
                    "volatility_points": 1_000.0,
                    "visible": True,
                    "bid": 4379.90,
                    "ask": 4380.10,
                    "price": 4380.10,
                }
            },
            capabilities={
                "GOLD.i#": {
                    "trade_mode": "full",
                    "order_mode": "market|sl|tp",
                    "execution_mode": "market",
                    "filling_mode": "fok",
                    "quote_session_active": True,
                    "trade_session_active": True,
                }
            },
        )
        self.materialize_open = materialize_open
        self.partial_open = partial_open
        self.open_sl = open_sl
        self.open_tp = open_tp
        self.close_removes_position = close_removes_position
        self.open_send_count = 0
        self.close_send_count = 0
        self.modify_count = 0
        self.order_bindings: list[MutationAccountBinding | None] = []
        self.modify_bindings: list[MutationAccountBinding | None] = []
        self.raise_modify = False
        self.raise_close = False
        self.deals = []
        self.deal_load_count = 0

    def send_order(self, request):
        self.order_bindings.append(request.get("_mutation_binding"))
        action = str(request.get("action") or "")
        if action == "open":
            self.open_send_count += 1
            requested_volume = float(request["volume"])
            actual_volume = requested_volume / 2 if self.partial_open else requested_volume
            status = "PARTIAL" if self.partial_open else "FILLED"
            if self.materialize_open:
                self._open_positions.append(
                    OpenPositionSnapshot(
                        ticket=321,
                        position_identifier=7001,
                        symbol=str(request["symbol"]),
                        side=str(request["order_type"]),
                        volume=actual_volume,
                        price_open=float(request["price"]),
                        sl=(
                            float(request["sl"])
                            if self.open_sl is None
                            else float(self.open_sl)
                        ),
                        tp=(
                            float(request["tp"])
                            if self.open_tp is None
                            else float(self.open_tp)
                        ),
                        profit=0.0,
                        opened_at=NOW.isoformat(),
                        magic=int(request["magic"]),
                        comment=str(request["comment"]),
                    )
                )
            return OrderSendResult(
                accepted=True,
                detail=f"test {status.lower()}",
                retcode=10010 if self.partial_open else 10009,
                order=900001,
                deal=800001,
                volume=actual_volume,
                price=float(request["price"]),
                execution_status=status,
            )
        if action == "close":
            self.close_send_count += 1
            if self.raise_close:
                raise RuntimeError("simulated close transport loss")
            if self.close_removes_position:
                ticket = int(request["position_ticket"])
                self._open_positions = [
                    position
                    for position in self._open_positions
                    if position.ticket != ticket
                ]
        return super().send_order(request)

    def modify_position_protection(self, *args, **kwargs):
        self.modify_bindings.append(kwargs.get("mutation_binding"))
        self.modify_count += 1
        if self.raise_modify:
            raise RuntimeError("simulated transport loss")
        return super().modify_position_protection(*args, **kwargs)

    def load_deals(self, *, since, symbol=None):
        del since, symbol
        self.deal_load_count += 1
        return list(self.deals)

    def set_price(self, *, bid: float, ask: float) -> None:
        self._symbols["GOLD.i#"].update(bid=bid, ask=ask, price=ask)


class MutationBindingRaceAdapter(StatefulBrokerAdapter):
    """Simulate identity changing inside the adapter immediately before mutation."""

    def __init__(self, *, race_action: str) -> None:
        super().__init__()
        self.race_action = race_action
        self.actual_broker_mutations = 0

    def _identity_changed(self, binding: MutationAccountBinding | None) -> bool:
        self._account_info["login"] = 999999
        return binding is None or str(binding.login) != str(
            self._account_info["login"]
        )

    def send_order(self, request):
        action = str(request.get("action") or "")
        binding = request.get("_mutation_binding")
        if action == self.race_action and self._identity_changed(binding):
            self.order_bindings.append(binding)
            return OrderSendResult(
                accepted=False,
                detail="MT5 login changed immediately before broker mutation",
                retcode=None,
                execution_status="REJECTED",
            )
        self.actual_broker_mutations += 1
        return super().send_order(request)

    def modify_position_protection(self, *args, **kwargs):
        binding = kwargs.get("mutation_binding")
        if self.race_action == "modify" and self._identity_changed(binding):
            self.modify_bindings.append(binding)
            return PositionProtectionResult(
                accepted=False,
                detail="MT5 login changed immediately before broker mutation",
                retcode=None,
            )
        self.actual_broker_mutations += 1
        return super().modify_position_protection(*args, **kwargs)


class BrokerPositionManagerTests(unittest.TestCase):
    def _fixture(
        self,
        root: Path,
        *,
        signal: str = SIGNAL,
        adapter: StatefulBrokerAdapter | None = None,
        config: TradeLifecycleConfig | None = None,
    ) -> tuple[SignalStore, StatefulBrokerAdapter, TradeLifecycleWorker, str]:
        log_path = root / "signal.log"
        log_path.write_text(signal + "\n", encoding="utf-8")
        store = SignalStore(root / "signal.db")
        store.initialize()
        self.assertEqual(
            Mt5LogBridge(
                store,
                log_paths=[log_path],
                account_context_provider=lambda: {
                    "login": 123456,
                    "server": "Broker-Demo",
                    "is_live": False,
                },
            ).run_once(),
            (1, 1, 1),
        )
        broker = adapter or StatefulBrokerAdapter()
        worker = TradeLifecycleWorker(
            store=store,
            adapter=broker,
            config=config
            or TradeLifecycleConfig(
                enabled=True,
                execution_mode="demo",
                max_entry_drift_r=0.2,
            ),
            now_fn=lambda: NOW,
        )
        worker.run_once()
        setup_id = str(store.recent_events(limit=1)[0]["setup_id"])
        return store, broker, worker, setup_id

    def test_open_modify_and_close_receive_immutable_account_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _, adapter, worker, _ = self._fixture(Path(tmpdir))
            open_binding = adapter.order_bindings[0]
            assert isinstance(open_binding, MutationAccountBinding)
            self.assertEqual(open_binding.login, "123456")
            self.assertEqual(open_binding.server, "Broker-Demo")
            self.assertEqual(open_binding.account_scope, "demo")
            self.assertEqual(open_binding.margin_mode, "HEDGING")

            adapter.set_price(bid=4386.05, ask=4386.20)
            worker.manage_positions_once()
            modify_binding = adapter.modify_bindings[0]
            assert isinstance(modify_binding, MutationAccountBinding)
            self.assertEqual(modify_binding, open_binding)

        with tempfile.TemporaryDirectory() as tmpdir:
            _, adapter, worker, _ = self._fixture(Path(tmpdir))
            adapter.set_price(bid=4400.0, ask=4400.20)
            worker.manage_positions_once()
            close_binding = adapter.order_bindings[-1]
            assert isinstance(close_binding, MutationAccountBinding)
            self.assertEqual(close_binding.login, "123456")
            self.assertEqual(close_binding.server, "Broker-Demo")
            self.assertEqual(close_binding.account_scope, "demo")
            self.assertEqual(close_binding.margin_mode, "HEDGING")

    def test_account_race_immediately_before_open_never_reaches_broker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = MutationBindingRaceAdapter(race_action="open")
            store, adapter, _, setup_id = self._fixture(
                Path(tmpdir), adapter=adapter
            )

            execution = store.trade_execution(setup_id)
            assert execution is not None
            action = store.position_actions(setup_id=setup_id)[0]
            self.assertEqual(adapter.actual_broker_mutations, 0)
            self.assertEqual(execution["status"], "REJECTED")
            self.assertEqual(action["status"], "FAILED")
            self.assertIn("immediately before", execution["last_error"])
            binding = adapter.order_bindings[0]
            assert isinstance(binding, MutationAccountBinding)
            self.assertEqual(binding.login, "123456")

    def test_account_race_immediately_before_modify_never_mutates_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = MutationBindingRaceAdapter(race_action="none")
            store, adapter, worker, setup_id = self._fixture(
                Path(tmpdir), adapter=adapter
            )
            baseline_mutations = adapter.actual_broker_mutations
            adapter.race_action = "modify"
            adapter.set_price(bid=4386.05, ask=4386.20)

            worker.manage_positions_once()

            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(adapter.actual_broker_mutations, baseline_mutations)
            self.assertEqual(execution["r1_protection_status"], "FAILED")
            binding = adapter.modify_bindings[-1]
            assert isinstance(binding, MutationAccountBinding)
            self.assertEqual(binding.login, "123456")

    def test_buy_r1_uses_bid_and_confirms_tick_normalized_stop_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, worker, setup_id = self._fixture(Path(tmpdir))
            adapter.set_price(bid=4386.05, ask=4386.2)

            worker.manage_positions_once()
            worker.manage_positions_once()

            position = adapter.find_open_position(position_identifier=7001)
            assert position is not None
            self.assertAlmostEqual(position.sl, 4381.60)
            self.assertEqual(adapter.modify_count, 1)
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["r1_protection_status"], "CONFIRMED")
            event_types = {row["event_type"] for row in store.recent_events(limit=100)}
            self.assertIn("POSITION_R1_TOUCHED", event_types)
            self.assertIn("POSITION_R1_PROTECTION_CONFIRMED", event_types)

    def test_sell_r1_uses_ask_and_rounds_stop_in_protective_direction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, worker, setup_id = self._fixture(
                Path(tmpdir), signal=SELL_SIGNAL
            )
            adapter.set_price(bid=4373.55, ask=4373.75)

            worker.manage_positions_once()

            position = adapter.find_open_position(position_identifier=7001)
            assert position is not None
            self.assertAlmostEqual(position.sl, 4378.35)
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["r1_protection_status"], "CONFIRMED")

    def test_gap_to_r3_closes_full_and_waits_for_deal_history_for_final_pnl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, worker, setup_id = self._fixture(Path(tmpdir))
            adapter.set_price(bid=4400.0, ask=4400.2)

            worker.manage_positions_once()

            self.assertEqual(adapter.close_send_count, 1)
            self.assertIsNone(adapter.find_open_position(position_identifier=7001))
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["status"], "CLOSE_SUBMITTED")
            self.assertEqual(execution["remaining_volume"], 0.0)
            self.assertEqual(execution["r3_close_status"], "CONFIRMED")
            self.assertFalse(
                any(
                    row["event_type"] == "POSITION_CLOSED"
                    for row in store.recent_events(limit=100)
                )
            )

    def test_r3_unreachable_before_frozen_broker_tp_alerts_admin_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target_below_r3 = SIGNAL.replace("target=4397.80", "target=4391.90")
            store, adapter, worker, setup_id = self._fixture(
                Path(tmpdir), signal=target_below_r3
            )

            worker.manage_positions_once()
            worker.manage_positions_once()

            warnings = [
                row
                for row in store.recent_events(limit=100)
                if row["event_type"] == "R3_UNREACHABLE_BEFORE_BROKER_TP"
            ]
            self.assertEqual(len(warnings), 1)
            self.assertEqual(warnings[0]["payload"]["audience"], "admin_only")
            self.assertIn("TP broker tetap dipertahankan", warnings[0]["payload"]["text"])
            position = adapter.find_open_position(position_identifier=7001)
            assert position is not None
            self.assertEqual(position.tp, 4391.9)
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["target_price"], 4391.9)

    def test_entry_off_does_not_disable_management_of_filled_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, worker, _ = self._fixture(Path(tmpdir))
            store.set_runtime_settings(
                {"trade.execution_mode": "off"}, updated_by="admin"
            )
            adapter.set_price(bid=4386.05, ask=4386.2)

            worker.manage_positions_once()

            self.assertEqual(adapter.modify_count, 1)

    def test_account_switch_blocks_adoption_even_for_matching_position_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_adapter = StatefulBrokerAdapter(materialize_open=False)
            store, adapter, worker, setup_id = self._fixture(
                Path(tmpdir), adapter=pending_adapter
            )
            record = store.trade_execution(setup_id)
            assert record is not None
            adapter._open_positions.append(
                OpenPositionSnapshot(
                    ticket=321,
                    position_identifier=7001,
                    symbol="GOLD.i#",
                    side="buy",
                    volume=float(record["volume"]),
                    price_open=4380.1,
                    sl=4374.2,
                    tp=4397.8,
                    profit=0.0,
                    opened_at=NOW.isoformat(),
                    magic=int(record["magic"]),
                    comment=f"GMS: {record['client_tag']}",
                )
            )
            adapter._account_info["login"] = 999999

            worker.manage_positions_once()

            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertNotEqual(execution["status"], "FILLED")
            self.assertTrue(
                any(
                    row["event_type"] == "POSITION_MANAGEMENT_ERROR"
                    for row in store.recent_events(limit=100)
                )
            )

    def test_ticket_churn_syncs_by_stable_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, worker, setup_id = self._fixture(Path(tmpdir))
            adapter._open_positions[0] = replace(adapter._open_positions[0], ticket=999)

            worker.manage_positions_once()

            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["position_ticket"], 999)
            self.assertEqual(execution["position_identifier"], 7001)

    def test_unknown_modify_is_not_blindly_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, worker, setup_id = self._fixture(Path(tmpdir))
            adapter.raise_modify = True
            adapter.set_price(bid=4386.05, ask=4386.2)

            worker.manage_positions_once()
            worker.manage_positions_once()

            self.assertEqual(adapter.modify_count, 1)
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["r1_protection_status"], "UNKNOWN")

    def test_milestone_latch_and_touch_outbox_are_crash_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store, adapter, worker, setup_id = self._fixture(root)
            adapter.set_price(bid=4386.05, ask=4386.2)
            connection = sqlite3.connect(store.path)
            try:
                connection.execute(
                    """
                    CREATE TRIGGER fail_r1_touch_before_insert
                    BEFORE INSERT ON signal_outbox
                    WHEN NEW.event_type = 'POSITION_R1_TOUCHED'
                    BEGIN
                        SELECT RAISE(ABORT, 'simulated outbox crash');
                    END
                    """
                )
            finally:
                connection.close()

            first_cycle = worker.manage_positions_once()
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertIsNone(execution["r1_reached_at"])
            self.assertGreaterEqual(first_cycle.isolated_failures, 1)
            self.assertFalse(
                any(
                    row["event_type"] == "POSITION_R1_TOUCHED"
                    for row in store.recent_events(limit=100)
                )
            )

            connection = sqlite3.connect(store.path)
            try:
                connection.execute("DROP TRIGGER fail_r1_touch_before_insert")
            finally:
                connection.close()
            restarted = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=worker.config,
                now_fn=lambda: NOW,
            )
            restarted.manage_positions_once()
            restarted.manage_positions_once()

            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertIsNotNone(execution["r1_reached_at"])
            touch_events = [
                row
                for row in store.recent_events(limit=100)
                if row["event_type"] == "POSITION_R1_TOUCHED"
            ]
            self.assertEqual(len(touch_events), 1)

    def test_close_fill_response_without_absence_is_not_confirmed_or_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = StatefulBrokerAdapter(close_removes_position=False)
            store, adapter, worker, setup_id = self._fixture(
                Path(tmpdir), adapter=adapter
            )
            adapter.set_price(bid=4400.0, ask=4400.2)

            worker.manage_positions_once()
            worker.manage_positions_once()

            self.assertEqual(adapter.close_send_count, 1)
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["status"], "CLOSE_UNKNOWN")
            self.assertEqual(execution["r3_close_status"], "UNKNOWN")
            self.assertIsNotNone(adapter.find_open_position(position_identifier=7001))

    def test_frozen_max_holding_closes_at_deadline_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            one_minute_signal = SIGNAL.replace(
                "maxHoldingMinutes=1440", "maxHoldingMinutes=1"
            )
            store, adapter, worker, setup_id = self._fixture(
                Path(tmpdir), signal=one_minute_signal
            )

            before_deadline = NOW + timedelta(seconds=59)
            worker.now_fn = lambda: before_deadline
            worker.position_manager.now_fn = lambda: before_deadline
            worker.manage_positions_once()
            self.assertEqual(adapter.close_send_count, 0)

            at_deadline = NOW + timedelta(minutes=1)
            worker.now_fn = lambda: at_deadline
            worker.position_manager.now_fn = lambda: at_deadline
            worker.manage_positions_once()
            worker.manage_positions_once()

            self.assertEqual(adapter.close_send_count, 1)
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["close_reason"], "MAX_HOLDING_EXPIRED")
            close_actions = [
                action
                for action in store.position_actions(setup_id=setup_id, limit=20)
                if action["action_type"] == "CLOSE_FULL"
            ]
            self.assertEqual(len(close_actions), 1)
            self.assertEqual(
                close_actions[0]["payload"]["reason"], "MAX_HOLDING_EXPIRED"
            )
            self.assertIsInstance(adapter.order_bindings[-1], MutationAccountBinding)

    def test_unknown_max_holding_close_is_never_blindly_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = StatefulBrokerAdapter(close_removes_position=False)
            adapter.raise_close = True
            one_minute_signal = SIGNAL.replace(
                "maxHoldingMinutes=1440", "maxHoldingMinutes=1"
            )
            store, adapter, worker, setup_id = self._fixture(
                Path(tmpdir), signal=one_minute_signal, adapter=adapter
            )
            expired = NOW + timedelta(minutes=2)
            worker.now_fn = lambda: expired
            worker.position_manager.now_fn = lambda: expired

            worker.manage_positions_once()
            worker.manage_positions_once()

            self.assertEqual(adapter.close_send_count, 1)
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["status"], "CLOSE_UNKNOWN")
            close_action = next(
                action
                for action in store.position_actions(setup_id=setup_id, limit=20)
                if action["action_type"] == "CLOSE_FULL"
            )
            self.assertEqual(close_action["status"], "UNKNOWN")

    def test_unprotected_position_obeys_frozen_max_holding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = StatefulBrokerAdapter(open_sl=0.0)
            adapter.raise_modify = True
            one_minute_signal = SIGNAL.replace(
                "maxHoldingMinutes=1440", "maxHoldingMinutes=1"
            )
            store, adapter, worker, setup_id = self._fixture(
                Path(tmpdir), signal=one_minute_signal, adapter=adapter
            )
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["status"], "UNPROTECTED")
            self.assertEqual(execution["position_identifier"], 7001)

            expired = NOW + timedelta(minutes=1)
            worker.now_fn = lambda: expired
            worker.position_manager.now_fn = lambda: expired
            worker.manage_positions_once()
            worker.manage_positions_once()

            self.assertEqual(adapter.close_send_count, 1)
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["close_reason"], "MAX_HOLDING_EXPIRED")

    def test_unprotected_position_is_not_rebound_on_a_different_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = StatefulBrokerAdapter(open_sl=0.0)
            adapter.raise_modify = True
            store, adapter, worker, setup_id = self._fixture(
                Path(tmpdir), adapter=adapter
            )
            before = store.trade_execution(setup_id)
            assert before is not None
            self.assertEqual(before["status"], "UNPROTECTED")
            action_count = len(store.position_actions(setup_id=setup_id, limit=100))

            adapter._account_info["login"] = 999999
            worker.now_fn = lambda: NOW + timedelta(days=2)
            worker.position_manager.now_fn = worker.now_fn
            worker.manage_positions_once()

            after = store.trade_execution(setup_id)
            assert after is not None
            self.assertEqual(after, before)
            self.assertEqual(
                len(store.position_actions(setup_id=setup_id, limit=100)),
                action_count,
            )
            self.assertEqual(adapter.close_send_count, 0)
            self.assertTrue(
                any(
                    row["event_type"] == "POSITION_MANAGEMENT_ERROR"
                    for row in store.recent_events(limit=100)
                )
            )

    def test_missing_tp_stages_emergency_protection_and_preserves_better_sl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = StatefulBrokerAdapter(open_sl=4375.0, open_tp=0.0)
            store, adapter, _, setup_id = self._fixture(Path(tmpdir), adapter=adapter)

            position = adapter.find_open_position(position_identifier=7001)
            assert position is not None
            self.assertEqual(position.sl, 4375.0)
            self.assertEqual(position.tp, 4397.8)
            self.assertEqual(adapter.modify_count, 1)
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["status"], "FILLED")
            self.assertEqual(execution["initial_stop_price"], 4375.0)
            self.assertEqual(execution["initial_take_profit_price"], 4397.8)

    def test_filled_position_repairs_loosened_sl_and_removed_tp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, worker, setup_id = self._fixture(Path(tmpdir))
            position = adapter._open_positions[0]
            position.sl = 4370.0
            position.tp = 0.0

            worker.manage_positions_once()
            worker.manage_positions_once()

            observed = adapter.find_open_position(position_identifier=7001)
            assert observed is not None
            self.assertEqual(observed.sl, 4374.2)
            self.assertEqual(observed.tp, 4397.8)
            self.assertEqual(adapter.modify_count, 1)
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["status"], "FILLED")
            event_types = {
                row["event_type"] for row in store.recent_events(limit=100)
            }
            self.assertIn("POSITION_PROTECTION_DEGRADED", event_types)
            self.assertIn("POSITION_PROTECTION_RESTORED", event_types)

    def test_filled_tp_repair_preserves_better_manual_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _, adapter, worker, _ = self._fixture(Path(tmpdir))
            position = adapter._open_positions[0]
            position.sl = 4384.0
            position.tp = 0.0

            worker.manage_positions_once()

            observed = adapter.find_open_position(position_identifier=7001)
            assert observed is not None
            self.assertEqual(observed.sl, 4384.0)
            self.assertEqual(observed.tp, 4397.8)
            self.assertEqual(adapter.modify_count, 1)

    def test_ambiguous_filled_protection_repair_is_not_blindly_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, worker, setup_id = self._fixture(Path(tmpdir))
            adapter._open_positions[0].tp = 0.0
            adapter.raise_modify = True

            worker.manage_positions_once()
            worker.manage_positions_once()

            self.assertEqual(adapter.modify_count, 1)
            repair = next(
                action
                for action in store.position_actions(setup_id=setup_id, limit=50)
                if action.get("payload", {}).get("repair_filled")
            )
            self.assertEqual(repair["status"], "UNKNOWN")

    def test_confirmed_filled_protection_can_repair_a_later_degradation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, worker, setup_id = self._fixture(Path(tmpdir))
            adapter._open_positions[0].tp = 0.0
            worker.manage_positions_once()
            self.assertEqual(adapter.modify_count, 1)

            adapter._open_positions[0].sl = 4370.0
            adapter._open_positions[0].tp = 0.0
            worker.manage_positions_once()

            self.assertEqual(adapter.modify_count, 2)
            repairs = [
                action
                for action in store.position_actions(setup_id=setup_id, limit=50)
                if action.get("payload", {}).get("repair_filled")
            ]
            self.assertEqual(len(repairs), 2)
            self.assertEqual([row["status"] for row in repairs], ["CONFIRMED"] * 2)

    def test_post_emergency_sl_tp_degradation_uses_new_ordinal_repair(self) -> None:
        for degraded_sl, degraded_tp in ((0.0, 4397.8), (0.0, 0.0)):
            with self.subTest(
                degraded_sl=degraded_sl, degraded_tp=degraded_tp
            ), tempfile.TemporaryDirectory() as tmpdir:
                adapter = StatefulBrokerAdapter(open_sl=0.0)
                store, adapter, worker, setup_id = self._fixture(
                    Path(tmpdir), adapter=adapter
                )
                self.assertEqual(adapter.modify_count, 1)
                emergency = next(
                    action
                    for action in store.position_actions(setup_id=setup_id, limit=50)
                    if action["idempotency_key"].startswith(
                        "SET_INITIAL_PROTECTION:"
                    )
                    and not action.get("payload", {}).get("repair_filled")
                )
                self.assertEqual(emergency["status"], "CONFIRMED")

                adapter._open_positions[0].sl = degraded_sl
                adapter._open_positions[0].tp = degraded_tp
                worker.manage_positions_once()

                observed = adapter.find_open_position(position_identifier=7001)
                assert observed is not None
                self.assertEqual(observed.sl, 4374.2)
                self.assertEqual(observed.tp, 4397.8)
                self.assertEqual(adapter.modify_count, 2)
                execution = store.trade_execution(setup_id)
                assert execution is not None
                self.assertEqual(execution["status"], "FILLED")
                repairs = [
                    action
                    for action in store.position_actions(setup_id=setup_id, limit=50)
                    if action.get("payload", {}).get("repair_filled")
                ]
                self.assertEqual(len(repairs), 1)
                self.assertTrue(
                    repairs[0]["idempotency_key"].startswith(
                        f"RESTORE_PROTECTION:{setup_id}:7001:1"
                    )
                )
                self.assertEqual(repairs[0]["status"], "CONFIRMED")
                self.assertEqual(
                    store.position_action(emergency["idempotency_key"])["status"],
                    "CONFIRMED",
                )

    def test_emergency_confirmation_closes_ambiguous_open_fence_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, worker, setup_id = self._fixture(
                Path(tmpdir), adapter=StatefulBrokerAdapter(materialize_open=False)
            )
            record = store.trade_execution(setup_id)
            assert record is not None
            open_action = next(
                action
                for action in store.position_actions(setup_id=setup_id, limit=20)
                if action["action_type"] == "OPEN"
            )
            self.assertEqual(open_action["status"], "UNKNOWN")
            adapter._open_positions.append(
                OpenPositionSnapshot(
                    ticket=321,
                    position_identifier=7001,
                    symbol="GOLD.i#",
                    side="buy",
                    volume=float(record["volume"]),
                    price_open=4380.1,
                    sl=4374.2,
                    tp=0.0,
                    profit=0.0,
                    opened_at=NOW.isoformat(),
                    magic=int(record["magic"]),
                    comment=f"GMS: {record['client_tag']}",
                )
            )

            worker.manage_positions_once()

            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["status"], "FILLED")
            actions = store.position_actions(setup_id=setup_id, limit=20)
            self.assertEqual(
                {row["action_type"]: row["status"] for row in actions},
                {"OPEN": "CONFIRMED", "SET_INITIAL_PROTECTION": "CONFIRMED"},
            )

    def test_initial_sl_tp_are_side_aware_tick_normalized_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_buy = SIGNAL.replace("stop=4374.20", "stop=4374.22").replace(
                "target=4397.80", "target=4397.83"
            )
            store, adapter, _, setup_id = self._fixture(
                Path(tmpdir), signal=raw_buy
            )

            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["status"], "FILLED")
            self.assertEqual(execution["stop_price"], 4374.25)
            self.assertEqual(execution["target_price"], 4397.8)
            observed = adapter.find_open_position(position_identifier=7001)
            assert observed is not None
            self.assertEqual(observed.sl, 4374.25)
            self.assertEqual(observed.tp, 4397.8)

    def test_sell_initial_sl_tp_use_mirrored_tick_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_sell = SELL_SIGNAL.replace("stop=4386.00", "stop=4386.03").replace(
                "target=4362.40", "target=4362.42"
            )
            store, adapter, _, setup_id = self._fixture(
                Path(tmpdir), signal=raw_sell
            )

            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["status"], "FILLED")
            self.assertEqual(execution["stop_price"], 4386.0)
            self.assertEqual(execution["target_price"], 4362.45)
            observed = adapter.find_open_position(position_identifier=7001)
            assert observed is not None
            self.assertEqual(observed.sl, 4386.0)
            self.assertEqual(observed.tp, 4362.45)

    def test_initial_confirmation_uses_half_trade_tick_tolerance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, _, _, setup_id = self._fixture(
                Path(tmpdir),
                adapter=StatefulBrokerAdapter(open_tp=4397.82),
            )

            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["status"], "FILLED")
            self.assertEqual(execution["initial_take_profit_price"], 4397.82)

    def test_partial_fill_freezes_broker_actual_volume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = StatefulBrokerAdapter(partial_open=True)
            store, _, _, setup_id = self._fixture(Path(tmpdir), adapter=adapter)

            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["status"], "FILLED")
            open_action = next(
                action
                for action in store.position_actions(setup_id=setup_id)
                if action["action_type"] == "OPEN"
            )
            self.assertAlmostEqual(
                float(execution["initial_volume"]),
                float(open_action["payload"]["requested_volume"]) / 2,
            )
            self.assertEqual(
                execution["remaining_volume"], execution["initial_volume"]
            )

    def test_freeze_level_rejection_occurs_before_modify_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, worker, setup_id = self._fixture(Path(tmpdir))
            adapter._symbols["GOLD.i#"]["trade_freeze_level"] = 1000
            adapter.set_price(bid=4386.05, ask=4386.2)

            worker.manage_positions_once()

            self.assertEqual(adapter.modify_count, 0)
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["r1_protection_status"], "FAILED")

    def test_frozen_disabled_r1_policy_keeps_touch_alert_without_modify(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TradeLifecycleConfig(
                enabled=True,
                execution_mode="demo",
                max_entry_drift_r=0.2,
                r1_protection_enabled=False,
            )
            store, adapter, worker, _ = self._fixture(
                Path(tmpdir), config=config
            )
            store.set_runtime_settings(
                {"trade.r1_protection_enabled": True}, updated_by="admin"
            )
            adapter.set_price(bid=4386.05, ask=4386.2)

            worker.manage_positions_once()

            self.assertEqual(adapter.modify_count, 0)
            self.assertTrue(
                any(
                    row["event_type"] == "POSITION_R1_TOUCHED"
                    for row in store.recent_events(limit=100)
                )
            )

    def test_projection_cursor_reaches_action_after_more_than_old_page_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, _, setup_id = self._fixture(Path(tmpdir))
            record = store.trade_execution(setup_id)
            assert record is not None
            for index in range(81):
                key = f"projection-regression:{index:03d}"
                store.create_position_action(
                    idempotency_key=key,
                    action_type="MODIFY_SL",
                    setup_id=setup_id,
                    position_ticket=int(record["position_ticket"]),
                    position_identifier=int(record["position_identifier"]),
                    payload={
                        "milestone": "MODEL",
                        "source_milestone": "R1",
                        "target_stop": 4381.6,
                        "take_profit_before": 4397.8,
                    },
                    management_policy=str(record["management_policy"]),
                    account_login=str(record["account_login"]),
                    account_server=str(record["account_server"]),
                    account_scope=str(record["account_scope"]),
                )
                store.mark_position_action_confirmed(key)
            manager = BrokerPositionManager(
                store=store,
                adapter=adapter,
                now_fn=lambda: NOW,
            )

            manager.run_once(current_entry_mode="off")

            newest = store.position_action("projection-regression:080")
            assert newest is not None
            self.assertIsNotNone(newest["projected_at"])

    def test_poison_projection_backs_off_without_starving_later_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SignalStore(Path(tmpdir) / "signal.db")
            store.initialize()
            for key in ("projection:poison", "projection:healthy"):
                store.create_position_action(
                    idempotency_key=key,
                    action_type="OPEN",
                )
                store.mark_position_action_failed(key, "terminal test outcome")
            manager = BrokerPositionManager(
                store=store,
                adapter=StatefulBrokerAdapter(materialize_open=False),
                now_fn=lambda: NOW,
                max_actions_per_cycle=2,
            )
            projected: list[str] = []

            def project(action, result):
                del result
                key = str(action["idempotency_key"])
                if key == "projection:poison":
                    raise RuntimeError("simulated poison projection")
                projected.append(key)

            manager._project_terminal_action = project  # type: ignore[method-assign]

            manager._reconcile_action_ledger(PositionManagementCycle())

            poison = store.position_action("projection:poison")
            healthy = store.position_action("projection:healthy")
            assert poison is not None and healthy is not None
            self.assertIsNone(poison["projected_at"])
            self.assertIsNotNone(poison["projection_lease_expires_at"])
            self.assertEqual(poison["projection_attempt_count"], 1)
            self.assertIsNotNone(healthy["projected_at"])
            self.assertEqual(projected, ["projection:healthy"])
            self.assertIsNone(
                store.claim_position_action_projection(
                    lease_owner="too-early", now=NOW + timedelta(seconds=4)
                )
            )
            retry = store.claim_position_action_projection(
                lease_owner="after-backoff", now=NOW + timedelta(seconds=5)
            )
            assert retry is not None
            self.assertEqual(retry["idempotency_key"], "projection:poison")

    def test_stale_live_open_is_blocked_by_current_deployment_kill_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_path = root / "signal.log"
            log_path.write_text(SIGNAL + "\n", encoding="utf-8")
            store = SignalStore(root / "signal.db")
            store.initialize()
            self.assertEqual(
                Mt5LogBridge(store, log_paths=[log_path]).run_once(), (1, 1, 1)
            )
            adapter = StatefulBrokerAdapter(materialize_open=False)
            adapter._account_info["server"] = "Broker-Live"
            worker = TradeLifecycleWorker(
                store=store,
                adapter=adapter,
                config=TradeLifecycleConfig(
                    enabled=True,
                    execution_mode="live",
                    max_entry_drift_r=0.2,
                    expected_login="123456",
                    expected_server="Broker-Live",
                    live_consent="I_UNDERSTAND_LIVE_ORDERS",
                    allow_live_activation=True,
                ),
                now_fn=lambda: NOW,
            )
            candidate = store.execution_candidates()[0]
            self.assertEqual(worker._process_signal(candidate), 1)
            self.assertEqual(adapter.open_send_count, 0)

            worker.position_manager.run_once(
                current_entry_mode="live", allow_live_open=False
            )

            self.assertEqual(adapter.open_send_count, 0)
            execution = store.trade_execution(SETUP_ID)
            assert execution is not None
            self.assertEqual(execution["status"], "PRECHECK_REJECTED")
            action = store.position_action(f"OPEN:{SETUP_ID}")
            self.assertIsNone(action)

    def test_account_switch_cannot_turn_filled_absence_into_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, worker, setup_id = self._fixture(Path(tmpdir))
            adapter._open_positions.clear()
            adapter._account_info["login"] = 999999

            cycle = worker.manage_positions_once()

            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["status"], "FILLED")
            self.assertEqual(adapter.deal_load_count, 0)
            self.assertGreaterEqual(cycle.isolated_failures, 1)
            self.assertFalse(
                any(
                    row["event_type"] == "POSITION_CLOSED"
                    for row in store.recent_events(limit=100)
                )
            )

    def test_account_switch_cannot_confirm_unknown_close_from_absence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, worker, setup_id = self._fixture(
                Path(tmpdir),
                adapter=StatefulBrokerAdapter(close_removes_position=False),
            )
            adapter.set_price(bid=4400.0, ask=4400.2)
            worker.manage_positions_once()
            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["status"], "CLOSE_UNKNOWN")
            action = next(
                row
                for row in store.position_actions(setup_id=setup_id, limit=20)
                if row["action_type"] == "CLOSE_FULL"
            )
            self.assertEqual(action["status"], "UNKNOWN")

            adapter._open_positions.clear()
            adapter._account_info["server"] = "Other-Demo"
            cycle = worker.manage_positions_once()

            execution = store.trade_execution(setup_id)
            assert execution is not None
            action = store.position_action(str(action["idempotency_key"]))
            assert action is not None
            self.assertEqual(execution["status"], "CLOSE_UNKNOWN")
            self.assertEqual(action["status"], "UNKNOWN")
            self.assertEqual(adapter.deal_load_count, 0)
            self.assertGreaterEqual(cycle.isolated_failures, 1)

    def test_open_then_close_history_without_protection_snapshot_stays_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store, adapter, worker, setup_id = self._fixture(
                Path(tmpdir), adapter=StatefulBrokerAdapter(materialize_open=False)
            )
            record = store.trade_execution(setup_id)
            assert record is not None
            common = {
                "position_ticket": 7001,
                "symbol": "GOLD.i#",
                "volume": float(record["volume"]),
                "magic": int(record["magic"]),
                "comment": f"GMS: {record['client_tag']}",
            }
            adapter.deals = [
                DealSnapshot(
                    ticket=800001,
                    side="buy",
                    entry="in",
                    price=4380.1,
                    profit=0.0,
                    commission=-0.2,
                    swap=0.0,
                    fee=0.0,
                    reason="expert",
                    occurred_at=NOW.isoformat(),
                    **common,
                ),
                DealSnapshot(
                    ticket=800002,
                    side="sell",
                    entry="out",
                    price=4374.2,
                    profit=-47.2,
                    commission=-0.8,
                    swap=-0.1,
                    fee=-0.3,
                    reason="sl",
                    occurred_at="2026-08-13T12:01:01+00:00",
                    **common,
                ),
            ]

            worker.manage_positions_once()

            execution = store.trade_execution(setup_id)
            assert execution is not None
            self.assertEqual(execution["status"], "OPEN_UNKNOWN")
            event_types = {
                row["event_type"] for row in store.recent_events(limit=100)
            }
            self.assertIn("POSITION_OPEN_UNKNOWN", event_types)
            self.assertIn("POSITION_ROUND_TRIP_UNRESOLVED", event_types)
            self.assertNotIn("POSITION_OPENED", event_types)
            self.assertNotIn("POSITION_CLOSED", event_types)
            unresolved = next(
                row
                for row in store.recent_events(limit=100)
                if row["event_type"] == "POSITION_ROUND_TRIP_UNRESOLVED"
            )
            self.assertIn("-48.60", unresolved["payload"]["text"])
            self.assertIn("komisi/swap/fee", unresolved["payload"]["text"])


if __name__ == "__main__":
    unittest.main()
