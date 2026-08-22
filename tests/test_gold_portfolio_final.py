from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from gold_engine_core import Side
from gold_portfolio.config import load_worker_config
from gold_portfolio.models import SignalPlan, WatchEvent
from gold_portfolio.mt5_session import BoundMt5Session
from gold_portfolio.worker import CompositePortfolioWorker, TelegramBroadcast

ROOT = Path(__file__).resolve().parents[1]
FAKE_SERVER_TIME = datetime(2026, 8, 19, 19, 0, tzinfo=timezone(timedelta(hours=3)))


def test_pinned_hash_accepts_crlf_only_as_transport_normalization(
    tmp_path: Path,
) -> None:
    canonical = b'{\n  "locked": true\n}\n'
    pinned = tmp_path / "pinned.json"
    pinned.write_bytes(canonical.replace(b"\n", b"\r\n"))
    revised = tmp_path / "revised.json"
    bear = tmp_path / "bear.json"
    revised.write_text("{}", encoding="utf-8")
    bear.write_text("{}", encoding="utf-8")
    portfolio = tmp_path / "portfolio.json"
    portfolio.write_text(
        json.dumps(
            {
                "portfolio_id": "TEST",
                "symbol": "TEST",
                "execution_mode": "signal_only",
                "revised_config": str(revised),
                "bear_config": str(bear),
                "terminal": {"require_account_binding": False},
                "orders_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    worker = tmp_path / "worker.json"
    worker.write_text(
        json.dumps(
            {
                "group": "test",
                "portfolio_config": str(portfolio),
                "state_path": str(tmp_path / "state.json"),
                "audit_path": str(tmp_path / "audit.jsonl"),
                "pinned_files": {str(pinned): sha256(canonical).hexdigest()},
            }
        ),
        encoding="utf-8",
    )

    assert load_worker_config(worker).portfolio_id == "TEST"
    pinned.write_text('{"locked": false}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="pinned config hash mismatch"):
        load_worker_config(worker)


def _bind_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOLDI_MT5_TERMINAL_PATH", "C:/Goldi/terminal64.exe")
    monkeypatch.setenv("GOLDI_MT5_LOGIN", "123456")
    monkeypatch.setenv("GOLDI_MT5_SERVER", "XMGlobal-MT5 5")
    monkeypatch.setenv(
        "GOLDM_REAL_MT5_TERMINAL_PATH",
        "C:/Goldm/terminal64.exe",
    )
    monkeypatch.setenv("GOLDM_REAL_MT5_LOGIN", "391425346")
    monkeypatch.setenv("GOLDM_REAL_MT5_SERVER", "XMGlobal-MT5 14")


def executable_signal(
    session: BoundMt5Session,
    *,
    event_id: str,
    component: str,
    symbol: str,
    side: str,
    time: datetime,
    entry: float,
    stop: float,
    target: float,
    reason: str,
) -> SignalPlan:
    profile = session.profile
    account = session.account_info()
    side_value = Side(side)
    return SignalPlan(
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        profile_fingerprint=profile.manifest_fingerprint,
        strategy_id="GOLDM_REVISED" if component == "revised" else "GOLDM_BEAR",
        strategy_version="1.0.0",
        component=component,
        reason=reason,
        setup_id=f"{profile.profile_id}:setup:{event_id}",
        signal_id=event_id,
        side=side_value,
        symbol=symbol,
        setup_created_at=time - timedelta(minutes=1),
        entry_ready_at=time,
        valid_until=time + timedelta(seconds=60),
        planned_entry=Decimal(str(entry)),
        stop=Decimal(str(stop)),
        target=Decimal(str(target)),
        planned_risk=abs(Decimal(str(entry)) - Decimal(str(stop))),
        invalidation=Decimal(str(stop)),
        maximum_spread=session.execution_policy.maximum_spread,
        maximum_drift_r=session.execution_policy.maximum_drift_r,
        tick_size=profile.tick_size,
        volume=Decimal(str(session.select_lot())),
        account_login=int(account.login),
        account_server=str(account.server),
        trade_mode="real" if session.config.execution_mode == "real" else "demo",
        terminal_identity=profile.terminal_identity,
        magic=profile.magic,
    )


def test_final_goldi_is_tag_pinned_mql5_demo_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_env(monkeypatch)
    config = load_worker_config(ROOT / "config/final/goldi/worker.json")

    assert not config.demo_execution
    assert not config.order_execution
    assert config.orders_enabled
    assert config.order_authority == "mql5"
    assert config.terminal.expected_trade_mode == "demo"
    assert config.balance_tiers == (
        (0.0, 0.01),
        (100.0, 0.02),
        (200.0, 0.05),
        (1000.0, 0.1),
        (2000.0, 0.2),
        (10000.0, 1.0),
        (20000.0, 2.0),
    )
    assert config.maximum_positions == 2
    assert config.maximum_total_lot == 4.0
    assert config.telegram.audience == "goldi_approved"
    assert config.revised["source_tag"] == "goldi-profit-v1-research-20260819"
    assert config.bear["source_tag"] == "goldi-profit-v1-research-20260819"
    assert config.terminal.path == "C:/Goldi/terminal64.exe"


def test_final_goldm_is_composite_real_and_uses_aggressive_tiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_env(monkeypatch)
    config = load_worker_config(ROOT / "config/final/goldm/worker.json")

    assert not config.real_execution
    assert not config.order_execution
    assert config.order_authority == "mql5"
    assert config.symbol == "GOLDm#"
    assert config.terminal.expected_login == 391425346
    assert config.balance_tiers == (
        (0.0, 0.1),
        (10.0, 0.2),
        (30.0, 0.5),
        (50.0, 1.0),
        (100.0, 2.0),
        (200.0, 5.0),
        (1000.0, 10.0),
        (2000.0, 20.0),
        (10000.0, 100.0),
    )
    assert config.maximum_total_lot == 200.0
    assert config.revised["component"] == "revised"
    assert config.bear["component"] == "bear"


@pytest.mark.parametrize(
    ("group", "balance", "expected"),
    [
        ("goldi", 0.0, 0.01),
        ("goldi", 99.99, 0.01),
        ("goldi", 100.0, 0.02),
        ("goldi", 199.99, 0.02),
        ("goldi", 200.0, 0.05),
        ("goldi", 999.99, 0.05),
        ("goldi", 1000.0, 0.1),
        ("goldi", 2000.0, 0.2),
        ("goldi", 10000.0, 1.0),
        ("goldi", 20000.0, 2.0),
        ("goldm", 0.0, 0.1),
        ("goldm", 9.99, 0.1),
        ("goldm", 10.0, 0.2),
        ("goldm", 30.0, 0.5),
        ("goldm", 50.0, 1.0),
        ("goldm", 100.0, 2.0),
        ("goldm", 200.0, 5.0),
        ("goldm", 1000.0, 10.0),
        ("goldm", 2000.0, 20.0),
        ("goldm", 9999.99, 20.0),
        ("goldm", 10000.0, 100.0),
    ],
)
def test_balance_tier_boundaries_are_continuous(
    monkeypatch: pytest.MonkeyPatch,
    group: str,
    balance: float,
    expected: float,
) -> None:
    _bind_env(monkeypatch)
    config = load_worker_config(ROOT / f"config/final/{group}/worker.json")

    assert config.lot_for_balance(balance) == expected


class FakeMt5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_PLACED = 10008
    TRADE_RETCODE_DONE_PARTIAL = 10010
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_OUT_BY = 3
    SYMBOL_TRADE_MODE_DISABLED = 0

    def __init__(self) -> None:
        self.sent = []
        self.checks = []
        self.balance = 60.0
        self.open_positions = ()
        self.deals = ()
        self.bid = 4399.9
        self.ask = 4400.2
        self.check_retcode = 0

    def initialize(self, path, **kwargs):
        return True

    def shutdown(self):
        return None

    def symbol_select(self, symbol, enabled):
        return True

    def account_info(self):
        return SimpleNamespace(
            login=391425346,
            server="XMGlobal-MT5 14",
            trade_mode=2,
            trade_allowed=True,
            trade_expert=True,
            balance=self.balance,
            equity=self.balance,
            margin_free=self.balance,
        )

    def terminal_info(self):
        return SimpleNamespace(trade_allowed=True)

    def symbol_info(self, symbol):
        return SimpleNamespace(
            name="GOLDm#",
            volume_min=0.1,
            volume_max=100.0,
            volume_step=0.01,
            trade_contract_size=1.0,
            digits=2,
            filling_mode=1,
            point=0.01,
            trade_tick_size=0.01,
            trade_stops_level=0,
            trade_freeze_level=0,
            trade_mode=1,
        )

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(
            ask=self.ask,
            bid=self.bid,
            time=1787155200,
            time_msc=1787155200123,
            volume=1.0,
        )

    def positions_get(self, **kwargs):
        return self.open_positions

    def order_check(self, request):
        self.checks.append(request)
        return SimpleNamespace(retcode=self.check_retcode, comment="ok")

    def order_calc_margin(self, order_type, symbol, volume, price):
        return 1.0

    def order_send(self, request):
        self.sent.append(request)
        return SimpleNamespace(
            retcode=10009,
            comment="done",
            order=777,
            deal=778,
            request_id=779,
            price=request["price"],
        )

    def history_deals_get(self, **kwargs):
        return self.deals

    def last_error(self):
        return (1, "Success")


class DemoFakeMt5(FakeMt5):
    def __init__(self) -> None:
        super().__init__()
        self.balance = 1630.77

    def account_info(self):
        return SimpleNamespace(
            login=123456,
            server="XMGlobal-MT5 5",
            trade_mode=0,
            trade_allowed=True,
            trade_expert=True,
            balance=self.balance,
            equity=self.balance,
            margin_free=self.balance,
        )

    def symbol_info(self, symbol):
        return SimpleNamespace(
            name="GOLD.i#",
            volume_min=0.01,
            volume_max=50.0,
            volume_step=0.01,
            trade_contract_size=100.0,
            digits=2,
            filling_mode=1,
            point=0.01,
            trade_tick_size=0.01,
            trade_stops_level=0,
            trade_freeze_level=0,
            trade_mode=1,
        )


@pytest.mark.parametrize(
    ("group", "module", "event_id", "symbol", "side"),
    [
        ("goldi", DemoFakeMt5, "goldi:1", "GOLD.i#", "SELL"),
        ("goldm", FakeMt5, "goldm:1", "GOLDm#", "BUY"),
    ],
)
def test_python_worker_is_signal_only_when_mql5_owns_order_authority(
    monkeypatch: pytest.MonkeyPatch,
    group: str,
    module,
    event_id: str,
    symbol: str,
    side: str,
) -> None:
    _bind_env(monkeypatch)
    config = load_worker_config(ROOT / "config" / "final" / group / "worker.json")
    mt5 = module()
    session = BoundMt5Session(config, mt5_module=mt5)
    signal = executable_signal(
        session,
        event_id=event_id,
        component="revised",
        symbol=symbol,
        side=side,
        time=FAKE_SERVER_TIME,
        entry=4400.0,
        stop=4390.0 if side == "BUY" else 4410.0,
        target=4420.0 if side == "BUY" else 4380.0,
        reason="test",
    )

    result = session.execute(signal)

    assert result == {
        "status": "SIGNAL_ONLY",
        "order_authority": "MQL5",
        "signal_id": event_id,
    }
    assert mt5.sent == []


@pytest.mark.parametrize(
    ("group", "module", "side", "volume"),
    [
        ("goldi", DemoFakeMt5, Side.BUY, Decimal("0.1")),
        ("goldm", FakeMt5, Side.SELL, Decimal("1.0")),
    ],
)
def test_worker_builds_profile_owned_versioned_execution_plan(
    monkeypatch: pytest.MonkeyPatch,
    group: str,
    module,
    side: Side,
    volume: Decimal,
) -> None:
    _bind_env(monkeypatch)
    config = load_worker_config(ROOT / "config" / "final" / group / "worker.json")
    worker = CompositePortfolioWorker(config, mt5_module=module())
    stop = 4390.0 if side is Side.BUY else 4410.0
    target = 4420.0 if side is Side.BUY else 4380.0
    value = worker._create_signal_plan(
        component="revised" if side is Side.BUY else "bear",
        strategy_id="GOLDM_REVISED" if side is Side.BUY else "GOLDM_BEAR",
        strategy_version="1.0.0",
        setup_id=f"{worker.profile.profile_id}:setup:owned",
        setup_created_at=FAKE_SERVER_TIME - timedelta(minutes=1),
        signal_id=f"{worker.profile.profile_id}:signal:owned",
        side=side,
        entry_ready_at=FAKE_SERVER_TIME,
        entry=4400.0,
        stop=stop,
        target=target,
        reason="owned plan",
    )

    assert value.profile_id == worker.profile.profile_id
    assert value.profile_fingerprint == worker.profile.manifest_fingerprint
    assert value.maximum_drift_r == worker.execution_policy.maximum_drift_r
    assert value.maximum_spread == worker.execution_policy.maximum_spread
    assert value.volume == volume
    assert value.magic == worker.profile.magic
    assert value.valid_until - value.entry_ready_at == timedelta(seconds=60)


def test_goldi_subscribers_receive_entries_but_goldm_remains_admin_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _bind_env(monkeypatch)

    class CaptureClient:
        def __init__(self) -> None:
            self.chat_ids: list[str] = []

        def send_message(self, *, chat_id, text):
            del text
            self.chat_ids.append(str(chat_id))

    subscriber_state = tmp_path / "orchestrator-state.json"
    subscriber_state.write_text(
        json.dumps({"goldi_subscribers": ["-999"]}),
        encoding="utf-8",
    )
    goldi = load_worker_config(ROOT / "config/final/goldi/worker.json")
    goldi_telegram = replace(
        goldi.telegram,
        bot_token="test",
        chat_ids=("123",),
        subscriber_state_path=subscriber_state,
    )
    goldi_broadcast = TelegramBroadcast(goldi_telegram)
    goldi_client = CaptureClient()
    goldi_broadcast.client = goldi_client
    goldi_broadcast.send("entry", include_subscribers=True)
    assert goldi_client.chat_ids == ["-999", "123"]

    goldi_client.chat_ids.clear()
    goldi_broadcast.send("health", include_subscribers=False)
    assert goldi_client.chat_ids == ["123"]

    goldm = load_worker_config(ROOT / "config/final/goldm/worker.json")
    goldm_telegram = replace(
        goldm.telegram,
        bot_token="test",
        chat_ids=("123",),
        subscriber_state_path=subscriber_state,
    )
    goldm_broadcast = TelegramBroadcast(goldm_telegram)
    goldm_client = CaptureClient()
    goldm_broadcast.client = goldm_client
    goldm_broadcast.send("real entry", include_subscribers=True)
    assert goldm_client.chat_ids == ["123"]


def test_watch_is_internal_bounded_and_never_notifies_or_sends_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _bind_env(monkeypatch)
    config = load_worker_config(ROOT / "config/final/goldm/worker.json")
    config = replace(
        config,
        execution_mode="signal_only",
        orders_enabled=False,
        state_path=tmp_path / "state.json",
        audit_path=tmp_path / "audit.jsonl",
    )
    module = FakeMt5()

    class CaptureTelegram:
        def __init__(self) -> None:
            self.messages: list[tuple[str, bool]] = []

        def send(self, text: str, *, include_subscribers: bool = False) -> None:
            self.messages.append((text, include_subscribers))

    telegram = CaptureTelegram()
    worker = CompositePortfolioWorker(config, mt5_module=module, telegram=telegram)
    server_time = datetime(2026, 8, 20, 10, 0, tzinfo=timezone(timedelta(hours=3)))
    started = WatchEvent(
        watch_id="bear:SELL:2026-08-20T09:45:00+03:00",
        component="bear",
        symbol="GOLDm#",
        side="SELL",
        state="WATCH",
        stage="M5_VALIDATION",
        time=server_time,
        trigger_time=server_time - timedelta(minutes=15),
        reason="M5_RETEST_CONFIRMATION_PENDING",
        level=4500.0,
        invalidation=4510.0,
        touch_count=1,
        rejection_count=1,
    )

    assert worker._process_watch(started) is None
    assert telegram.messages == []
    assert worker.state["active_watches"]["bear:SELL"]["watch_id"] == started.watch_id
    assert not config.audit_path.exists()
    assert module.sent == []

    unchanged = replace(started, time=server_time + timedelta(minutes=1))
    assert worker._process_watch(unchanged) is None
    assert telegram.messages == []

    changed = replace(
        unchanged,
        touch_count=2,
        rejection_count=2,
        reason="M5_SECOND_REJECTION_CONFIRMED",
    )
    assert worker._process_watch(changed) is None
    assert telegram.messages == []
    assert worker.state["active_watches"]["bear:SELL"]["touches"] == 2

    worker._save_state()
    restarted = CompositePortfolioWorker(config, mt5_module=module, telegram=telegram)
    restarted_watch = replace(changed, time=server_time + timedelta(minutes=2))
    assert restarted._process_watch(restarted_watch) is None

    cancelled = replace(
        restarted_watch,
        state="CANCELLED",
        reason="M5_ACCEPTANCE",
    )
    assert restarted._process_watch(cancelled) is None
    assert telegram.messages == []
    assert restarted.state["active_watches"] == {}
    assert not config.audit_path.exists()
    assert module.sent == []


def test_bear_watch_reports_m5_preparation_without_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _bind_env(monkeypatch)
    config = load_worker_config(ROOT / "config/final/goldm/worker.json")
    config = replace(
        config,
        execution_mode="signal_only",
        orders_enabled=False,
        state_path=tmp_path / "state.json",
        audit_path=tmp_path / "audit.jsonl",
    )
    worker = CompositePortfolioWorker(config, mt5_module=FakeMt5())
    server_tz = timezone(timedelta(hours=3))
    setup_time = datetime(2026, 8, 20, 9, 30, tzinfo=server_tz)
    setup = SimpleNamespace(
        time=setup_time,
        resistance=4500.0,
        stop=4510.0,
        entry=4495.0,
        take_profit=4470.0,
    )

    class FakeSetupEngine:
        def scan(self, _bars):
            return [setup]

    class FakeBearReplay:
        def __init__(self) -> None:
            self.setup_engine = FakeSetupEngine()
            self.config = SimpleNamespace(
                h1_sma_period=20,
                m5_watch_bars=12,
                m1_entry_bars=20,
            )

        @staticmethod
        def _h1_bearish(_bars):
            return True

        @staticmethod
        def _arm_on_m5(_setup, _history, _candidates, _available):
            return {"state": "EXPIRED", "touches": 1, "rejections": 1}

    worker.bear_replay = FakeBearReplay()
    latest = datetime(2026, 8, 20, 9, 50, tzinfo=server_tz)
    m5_bars = tuple(
        SimpleNamespace(time=setup_time + timedelta(minutes=5 * index)) for index in range(4)
    )
    h1_bars = tuple(
        SimpleNamespace(time=setup_time - timedelta(hours=index + 1))
        for index in reversed(range(25))
    )

    watch = worker._bear_watch_event(
        latest_m1=latest,
        end=latest + timedelta(minutes=1),
        start=latest - timedelta(days=30),
        m1_bars=(),
        m5_bars=m5_bars,
        m15_bars=(),
        h1_bars=h1_bars,
        report=SimpleNamespace(outcomes=()),
        signal=None,
    )

    assert watch is not None
    assert watch.state == "WATCH"
    assert watch.stage == "M5_VALIDATION"
    assert watch.reason == "M5_RETEST_CONFIRMATION_PENDING"
    assert watch.touch_count == 1
    assert watch.rejection_count == 1


def test_final_entry_sends_one_human_readable_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _bind_env(monkeypatch)
    config = load_worker_config(ROOT / "config/final/goldm/worker.json")
    config = replace(
        config,
        state_path=tmp_path / "state.json",
        audit_path=tmp_path / "audit.jsonl",
    )
    module = FakeMt5()

    class CaptureTelegram:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def send(self, text: str, *, include_subscribers: bool = False) -> None:
            assert include_subscribers
            self.messages.append(text)

    telegram = CaptureTelegram()
    worker = CompositePortfolioWorker(config, mt5_module=module, telegram=telegram)
    signal_time = datetime(2026, 8, 20, 2, 30, tzinfo=timezone(timedelta(hours=3)))
    signal = executable_signal(
        worker.session,
        event_id="revised:BUY:ready-1",
        component="revised",
        symbol="GOLDm#",
        side="BUY",
        time=signal_time,
        entry=4520.0,
        stop=4510.0,
        target=4540.0,
        reason="M1_RANGE_CONFIRMED",
    )
    monkeypatch.setattr(worker.session, "connect", lambda: None)
    monkeypatch.setattr(worker, "_deliver_closed_positions", lambda: [])
    monkeypatch.setattr(
        worker,
        "_revised_snapshot",
        lambda: SimpleNamespace(m1_bars=(SimpleNamespace(time=signal_time),)),
    )
    monkeypatch.setattr(worker, "_evaluate_revised", lambda _latest: (signal, None))
    monkeypatch.setattr(worker, "_evaluate_bear", lambda _latest: (None, None))
    monkeypatch.setattr(
        worker.session,
        "execute",
        lambda _signal: {
            "status": "EXECUTED",
            "order": 1001,
            "deal": 1002,
            "request_id": 1003,
            "volume": 0.1,
            "price": 4520.2,
            "sl": 4510.2,
            "tp": 4540.2,
            "balance": 1.15,
            "server_time": signal_time.isoformat(),
            "vm_time": "2026-08-20T06:30:01+07:00",
            "retcode": 10009,
            "comment": "Request executed",
        },
    )

    result = worker.run_once()

    assert len(result["events"]) == 1
    assert len(telegram.messages) == 1
    message = telegram.messages[0]
    assert "✅ ENTRY DIBUKA — REAL" in message
    assert "GOLDm# • BUY • Revised" in message
    assert "ID order: 1001" in message
    assert "Server broker: 20 Agu 2026 02:30:00 GMT+3" in message
    assert "VM: 20 Agu 2026 06:30:01 GMT+7" in message
    assert "evidence=" not in message


def test_worker_audit_rotation_is_storage_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _bind_env(monkeypatch)
    config = load_worker_config(ROOT / "config/final/goldm/worker.json")
    config = replace(
        config,
        state_path=tmp_path / "state.json",
        audit_path=tmp_path / "audit.jsonl",
    )
    worker = CompositePortfolioWorker(config, mt5_module=FakeMt5())
    monkeypatch.setattr("gold_portfolio.worker.AUDIT_MAX_BYTES", 120)
    monkeypatch.setattr("gold_portfolio.worker.AUDIT_BACKUPS", 2)

    for index in range(12):
        worker._audit({"event": index, "payload": "x" * 80})

    files = sorted(tmp_path.glob("audit.jsonl*"))
    assert [item.name for item in files] == [
        "audit.jsonl",
        "audit.jsonl.1",
        "audit.jsonl.2",
    ]
    assert sum(item.stat().st_size for item in files) < 1_000


def test_closed_position_result_includes_total_pl_and_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_env(monkeypatch)
    config = load_worker_config(ROOT / "config/final/goldm/worker.json")
    module = FakeMt5()
    module.balance = 73.5
    module.deals = (
        SimpleNamespace(
            entry=0,
            time=100,
            time_msc=100000,
            price=4400.0,
            profit=0.0,
            swap=0.0,
            commission=-0.1,
            fee=0.0,
        ),
        SimpleNamespace(
            entry=1,
            time=160,
            time_msc=160000,
            price=4420.0,
            profit=10.0,
            swap=-0.2,
            commission=-0.1,
            fee=0.0,
        ),
    )
    session = BoundMt5Session(config, mt5_module=module)
    session.connect()

    result = session.closed_position_result(777)

    assert result is not None
    assert result["profit_loss"] == pytest.approx(9.6)
    assert result["balance"] == 73.5
    assert result["close_price"] == 4420.0


def test_worker_sends_close_lifecycle_with_rr_duration_and_balance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _bind_env(monkeypatch)
    config = load_worker_config(ROOT / "config/final/goldm/worker.json")
    config = replace(
        config,
        execution_mode="signal_only",
        orders_enabled=False,
        state_path=tmp_path / "state.json",
        audit_path=tmp_path / "audit.jsonl",
    )
    module = FakeMt5()
    module.balance = 73.5
    module.deals = (
        SimpleNamespace(
            entry=0,
            time=100,
            time_msc=100000,
            price=4400.0,
            profit=0.0,
            swap=0.0,
            commission=0.0,
            fee=0.0,
        ),
        SimpleNamespace(
            entry=1,
            time=160,
            time_msc=160000,
            price=4420.0,
            profit=10.0,
            swap=0.0,
            commission=0.0,
            fee=0.0,
        ),
    )

    class CaptureTelegram:
        def __init__(self) -> None:
            self.messages = []

        def send(self, text: str, *, include_subscribers: bool = False) -> None:
            assert include_subscribers
            self.messages.append(text)

    telegram = CaptureTelegram()
    worker = CompositePortfolioWorker(
        config,
        mt5_module=module,
        telegram=telegram,
    )
    opened_at = datetime.fromtimestamp(100, tz=worker.session.server_timezone)
    worker.state["open_positions"] = {
        "777": {
            "signal": {
                "component": "revised",
                "side": "BUY",
                "reason": "range confirmed",
                "event_id": "revised:test:4400.00",
            },
            "opened_at": opened_at.isoformat(),
            "fill_price": 4400.0,
            "volume": 1.0,
            "sl": 4390.0,
            "tp": 4420.0,
            "balance_after_entry": 60.0,
        }
    }

    closed = worker._deliver_closed_positions()

    assert len(closed) == 1
    assert closed[0]["planned_rr"] == 2.0
    assert closed[0]["realized_r"] == 1.0
    assert closed[0]["duration_seconds"] == 60
    assert worker.state["open_positions"] == {}
    assert "P/L: +10.00 USD" in telegram.messages[0]
    assert "Saldo: 73.50 USD" in telegram.messages[0]
    assert "GOLDm#" in telegram.messages[0]
    assert "ID sinyal: revised:test:4400.00" in telegram.messages[0]
    assert "Server broker:" in telegram.messages[0]
    assert "VM:" in telegram.messages[0]
