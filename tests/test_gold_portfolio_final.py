from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from gold_portfolio.config import load_worker_config
from gold_portfolio.models import SignalPlan
from gold_portfolio.mt5_session import BoundMt5Session
from gold_portfolio.worker import CompositePortfolioWorker


ROOT = Path(__file__).resolve().parents[1]


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


def test_final_goldi_is_tag_pinned_signal_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_env(monkeypatch)
    config = load_worker_config(ROOT / "config/final/goldi/worker.json")

    assert config.execution_mode == "signal_only"
    assert not config.orders_enabled
    assert config.revised["source_tag"] == "goldi-profit-v1-research-20260819"
    assert config.bear["source_tag"] == "goldi-profit-v1-research-20260819"
    assert config.terminal.path == "C:/Goldi/terminal64.exe"


def test_final_goldm_is_composite_real_and_uses_aggressive_tiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_env(monkeypatch)
    config = load_worker_config(ROOT / "config/final/goldm/worker.json")

    assert config.real_execution
    assert config.symbol == "GOLDm#"
    assert config.terminal.expected_login == 391425346
    assert config.balance_tiers == (
        (0.0, 0.1),
        (10.0, 0.2),
        (30.0, 0.5),
        (50.0, 1.0),
        (100.0, 2.0),
    )
    assert config.revised["component"] == "revised"
    assert config.bear["component"] == "bear"


class FakeMt5:
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

    def __init__(self) -> None:
        self.sent = []
        self.balance = 60.0
        self.open_positions = ()
        self.deals = ()

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
        )

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(ask=4400.2, bid=4399.9)

    def positions_get(self, **kwargs):
        return self.open_positions

    def order_check(self, request):
        return SimpleNamespace(retcode=0, comment="ok")

    def order_send(self, request):
        self.sent.append(request)
        return SimpleNamespace(
            retcode=10009,
            comment="done",
            order=777,
            deal=778,
            price=request["price"],
        )

    def history_deals_get(self, **kwargs):
        return self.deals

    def last_error(self):
        return (1, "Success")


def test_real_executor_reads_shared_balance_and_sends_one_checked_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_env(monkeypatch)
    config = load_worker_config(ROOT / "config/final/goldm/worker.json")
    module = FakeMt5()
    session = BoundMt5Session(config, mt5_module=module)
    signal = SignalPlan(
        event_id="revised:1",
        component="revised",
        symbol="GOLDm#",
        side="BUY",
        time=datetime.now(timezone.utc),
        entry=4400.0,
        stop=4390.0,
        target=4420.0,
        reason="test",
    )

    result = session.execute(signal)

    assert result["status"] == "EXECUTED"
    assert result["volume"] == 1.0
    assert len(module.sent) == 1
    assert module.sent[0]["magic"] == config.magic
    assert module.sent[0]["sl"] == 4390.2
    assert module.sent[0]["tp"] == 4420.2


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

        def send(self, text: str) -> None:
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
    assert "P/L=+10.00 USD" in telegram.messages[0]
    assert "balance=73.50" in telegram.messages[0]
