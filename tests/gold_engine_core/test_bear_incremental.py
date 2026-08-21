from __future__ import annotations

import bisect
import inspect
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from gold_engine_core import ProfileConfig, Timeframe, load_named_profile
from gold_engine_core.rules.bear import BearAction, BearBar, BearDecision
from gold_engine_core.rules.bear_incremental import (
    BearIncrementalError,
    BearIncrementalMachine,
    BearIncrementalPhase,
)
from gold_engine_core.rules.bear_multitimeframe import BearMultiTimeframeReplay, BearV4Config
from gold_portfolio.config import load_worker_config
from gold_portfolio.worker import CompositePortfolioWorker

TZ = timezone(timedelta(hours=3))
SETUP_TIME = datetime(2026, 1, 2, 0, 0, tzinfo=TZ)


def make_bar(
    time: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> BearBar:
    return BearBar(time, open_, high, low, close, 100.0, 0.20)


def setup_decision(symbol: str = "GOLD.i#") -> BearDecision:
    return BearDecision(
        action=BearAction.SELL,
        time=SETUP_TIME,
        symbol=symbol,
        reason="v4_incremental_fixture",
        score=90,
        resistance=100.0,
        entry=99.0,
        stop=101.0,
        take_profit=94.0,
        reward_risk=2.5,
    )


class FakeSetupEngine:
    minimum_bars = 1

    def __init__(self, setup: BearDecision) -> None:
        self.setup = setup

    def scan(self, bars):
        return [self.setup] if bars else []


def fixture_bars():
    setup_available = SETUP_TIME + timedelta(minutes=15)
    h1 = tuple(
        make_bar(
            setup_available - timedelta(hours=22 - index),
            120.0 - index,
            120.2 - index,
            118.8 - index,
            119.0 - index,
        )
        for index in range(22)
    )
    m15 = (make_bar(SETUP_TIME, 100.0, 100.2, 98.8, 99.0),)
    m5_history = tuple(
        make_bar(
            setup_available - timedelta(minutes=5 * (20 - index)),
            99.2,
            99.7,
            98.7,
            99.1,
        )
        for index in range(20)
    )
    m5 = (
        *m5_history,
        make_bar(setup_available, 99.5, 100.1, 99.0, 99.8),
        make_bar(setup_available + timedelta(minutes=5), 100.0, 100.2, 97.8, 98.1),
    )
    armed_at = setup_available + timedelta(minutes=10)
    m1_history = tuple(
        make_bar(
            armed_at - timedelta(minutes=20 - index),
            98.7,
            99.0,
            98.2,
            98.6,
        )
        for index in range(20)
    )
    m1 = (
        *m1_history,
        make_bar(armed_at, 99.0, 99.5, 97.8, 98.0),
        make_bar(armed_at + timedelta(minutes=1), 98.0, 98.5, 97.7, 97.9),
        make_bar(armed_at + timedelta(minutes=2), 99.2, 99.4, 96.9, 97.1),
    )
    return m1, m5, m15, h1


def machine(profile_id: str) -> BearIncrementalMachine:
    manifest = load_named_profile(Path(__file__).resolve().parents[2], profile_id)
    profile = ProfileConfig.from_manifest(manifest, tick_size=Decimal("0.01"))
    spread = 0.20 if profile_id == "GOLDI" else 0.24
    replay = BearMultiTimeframeReplay(
        BearV4Config(price_tick=0.01, spread_floor=spread, fixed_target_r=2.0),
        symbol=profile.symbol,
    )
    replay.setup_engine = FakeSetupEngine(setup_decision(profile.symbol))
    return BearIncrementalMachine(profile, replay)


@pytest.mark.parametrize("profile_id", ["GOLDI", "GOLDM"])
def test_bar_by_bar_incremental_matches_replay_geometry_and_events(profile_id: str) -> None:
    evaluator = machine(profile_id)
    m1, m5, m15, h1 = fixture_bars()
    initial = evaluator.initial_state(h1[0].time)
    available_at = m1[-1].time + timedelta(minutes=1)

    output = evaluator.feed_closed_batches(
        initial,
        m1_bars=m1,
        m5_bars=m5,
        m15_bars=m15,
        h1_bars=h1,
        available_at=available_at,
        emit_after=SETUP_TIME,
    )
    report = evaluator.replay.run(
        m1_bars=m1,
        m5_bars=m5,
        m15_bars=m15,
        h1_bars=h1,
        from_time=SETUP_TIME,
        to_time=available_at,
    )

    setup = setup_decision(evaluator.profile.symbol)
    setup_available = setup.time + timedelta(minutes=15)
    m5_times = [bar.time for bar in m5]
    start = max(0, bisect.bisect_left(m5_times, setup_available) - 3)
    m5_result = evaluator.replay._arm_on_m5(
        setup,
        m5[max(0, start - 20) : start],
        m5[start : start + evaluator.replay.config.m5_watch_bars],
        setup_available,
    )
    armed_at = m5_result["armed_at"]
    m1_times = [bar.time for bar in m1]
    m1_index = bisect.bisect_left(m1_times, armed_at)
    replay_plan = evaluator.replay._entry_on_m1(
        setup,
        m5_result,
        m1[max(0, m1_index - 20) : m1_index],
        m1[m1_index : m1_index + evaluator.replay.config.m1_entry_bars],
    )

    assert replay_plan is not None
    assert report.h1_rejected == 0
    assert report.m5_armed == 1
    assert report.executed_signals == 1
    reference = report.outcomes[0]
    assert output.signal is not None
    # Later closed bars in the same recovery batch consume the terminal state,
    # while the newly emitted signal remains available exactly once.
    assert output.next_state.phase is BearIncrementalPhase.IDLE
    assert output.signal.profile_id == profile_id
    assert output.signal.entry == replay_plan["entry"]
    assert output.signal.stop == replay_plan["stop"]
    assert output.signal.target == replay_plan["target"]
    assert output.signal.entry == reference.entry
    assert output.signal.stop == reference.stop
    assert output.signal.target == reference.target
    assert [event.to_phase for event in output.events] == [
        BearIncrementalPhase.WATCH_H1,
        BearIncrementalPhase.WATCH_M5,
        BearIncrementalPhase.WATCH_M1,
        BearIncrementalPhase.ENTRY_READY,
    ]
    assert output.signal.m5_touches == replay_plan["m5_touches"]
    assert output.signal.m5_rejections == replay_plan["m5_rejections"]
    assert all(
        abs(
            value / float(evaluator.profile.tick_size)
            - round(value / float(evaluator.profile.tick_size))
        )
        < 1e-7
        for value in (output.signal.entry, output.signal.stop, output.signal.target)
    )


def test_incremental_processing_is_idempotent_bounded_and_rejects_old_bars() -> None:
    evaluator = machine("GOLDI")
    first = make_bar(SETUP_TIME, 100.0, 101.0, 99.0, 100.0)
    state = evaluator.initial_state(SETUP_TIME - timedelta(minutes=1))
    once = evaluator.on_bar_close(state, Timeframe.M1, first).next_state
    duplicate = evaluator.on_bar_close(once, Timeframe.M1, first).next_state
    assert duplicate == once

    with pytest.raises(BearIncrementalError, match="before the processed cursor"):
        evaluator.on_bar_close(
            once,
            Timeframe.M1,
            replace(first, time=first.time - timedelta(minutes=1)),
        )

    current = once
    for index in range(100):
        current = evaluator.on_bar_close(
            current,
            Timeframe.M1,
            replace(first, time=SETUP_TIME + timedelta(minutes=index + 1)),
        ).next_state
    assert len(current.m1_bars) == evaluator._limits[Timeframe.M1]
    assert evaluator.maximum_warmup_span < timedelta(days=2)


def test_profile_state_cannot_cross_machine_boundary() -> None:
    goldi = machine("GOLDI")
    goldm = machine("GOLDM")
    state = goldi.initial_state(SETUP_TIME)
    with pytest.raises(BearIncrementalError, match="another profile"):
        goldm.on_bar_close(
            state,
            Timeframe.M1,
            make_bar(SETUP_TIME, 100.0, 101.0, 99.0, 100.0),
        )


def test_h1_rejection_and_m5_acceptance_are_terminal_and_causal() -> None:
    evaluator = machine("GOLDI")
    _m1, m5, m15, h1 = fixture_bars()
    flat_h1 = tuple(replace(bar, open=100.0, high=100.2, low=99.8, close=100.0) for bar in h1)
    initial = evaluator.initial_state(flat_h1[0].time)
    rejected = evaluator.feed_closed_batches(
        initial,
        m1_bars=(),
        m5_bars=(),
        m15_bars=m15,
        h1_bars=flat_h1,
        available_at=SETUP_TIME + timedelta(minutes=15),
        emit_after=SETUP_TIME,
    )
    assert rejected.next_state.phase is BearIncrementalPhase.CANCELLED
    assert rejected.events[-1].reason == "H1_BEARISH_CONTEXT_REJECTED"

    setup_available = SETUP_TIME + timedelta(minutes=15)
    accepted_m5 = (
        *m5[:-2],
        make_bar(setup_available, 100.2, 100.8, 100.1, 100.6),
        make_bar(setup_available + timedelta(minutes=5), 100.6, 101.0, 100.4, 100.8),
    )
    accepted = evaluator.feed_closed_batches(
        evaluator.initial_state(h1[0].time),
        m1_bars=(),
        m5_bars=accepted_m5,
        m15_bars=m15,
        h1_bars=h1,
        available_at=setup_available + timedelta(minutes=10),
        emit_after=SETUP_TIME,
    )
    assert accepted.next_state.phase is BearIncrementalPhase.CANCELLED
    assert accepted.next_state.acceptance is True
    assert accepted.events[-1].reason == "M5_ACCEPTANCE"


def test_m1_expiry_and_bounded_watch_recovery() -> None:
    evaluator = machine("GOLDI")
    m1, m5, m15, h1 = fixture_bars()
    armed_at = SETUP_TIME + timedelta(minutes=25)
    watching = evaluator.feed_closed_batches(
        evaluator.initial_state(h1[0].time),
        m1_bars=m1[:20],
        m5_bars=m5,
        m15_bars=m15,
        h1_bars=h1,
        available_at=armed_at,
        emit_after=SETUP_TIME,
    )
    assert watching.next_state.phase is BearIncrementalPhase.WATCH_M1
    assert watching.next_state.arm is not None

    resumed = evaluator.feed_closed_batches(
        watching.next_state,
        m1_bars=m1,
        m5_bars=m5,
        m15_bars=m15,
        h1_bars=h1,
        available_at=m1[-1].time + timedelta(minutes=1),
        emit_after=armed_at,
    )
    assert resumed.signal is not None
    assert resumed.signal.opened_at >= armed_at

    flat_candidates = tuple(
        make_bar(
            armed_at + timedelta(minutes=index),
            98.5,
            98.8,
            98.0,
            98.4,
        )
        for index in range(evaluator.replay.config.m1_entry_bars)
    )
    expired = evaluator.feed_closed_batches(
        watching.next_state,
        m1_bars=(*m1[:20], *flat_candidates),
        m5_bars=m5,
        m15_bars=m15,
        h1_bars=h1,
        available_at=flat_candidates[-1].time + timedelta(minutes=1),
        emit_after=armed_at,
    )
    assert expired.next_state.phase is BearIncrementalPhase.CANCELLED
    assert expired.events[-1].reason == "M1_WATCH_WINDOW_EXPIRED_OR_INVALIDATED"


def test_profile_tick_contract_mismatch_fails_closed() -> None:
    manifest = load_named_profile(Path(__file__).resolve().parents[2], "GOLDI")
    wrong_tick = ProfileConfig.from_manifest(manifest, tick_size=Decimal("0.10"))
    replay = BearMultiTimeframeReplay(BearV4Config(price_tick=0.01))
    with pytest.raises(BearIncrementalError, match="tick_size"):
        BearIncrementalMachine(wrong_tick, replay)


def test_live_worker_uses_only_bounded_incremental_bear_path(monkeypatch) -> None:
    source = inspect.getsource(CompositePortfolioWorker._evaluate_bear)
    assert "bear_replay.run" not in source
    assert "lookback_days" not in source

    monkeypatch.setenv("GOLDI_MT5_TERMINAL_PATH", "C:/Goldi/terminal64.exe")
    monkeypatch.setenv("GOLDI_MT5_LOGIN", "123456")
    monkeypatch.setenv("GOLDI_MT5_SERVER", "XMGlobal-MT5 5")
    config = load_worker_config(
        Path(__file__).resolve().parents[2] / "config" / "final" / "goldi" / "worker.json"
    )

    class NoopTelegram:
        def send(self, text: str, *, include_subscribers: bool = False) -> None:
            del text, include_subscribers

    worker = CompositePortfolioWorker(
        config,
        mt5_module=object(),
        telegram=NoopTelegram(),
    )

    class EmptySession:
        server_timezone = TZ

        def __init__(self) -> None:
            self.calls: list[tuple[str, datetime, datetime]] = []

        def bear_bars_range(self, timeframe: str, start: datetime, end: datetime):
            self.calls.append((timeframe, start, end))
            return ()

    session = EmptySession()
    worker.session = session

    def forbidden_replay(**kwargs):
        raise AssertionError(f"full Bear replay reached live path: {kwargs}")

    worker.bear_replay.run = forbidden_replay
    signal, watch = worker._evaluate_bear(SETUP_TIME)

    assert signal is None
    assert watch is None
    assert len(session.calls) == 4
    assert {item[0] for item in session.calls} == {
        "TIMEFRAME_M1",
        "TIMEFRAME_M5",
        "TIMEFRAME_M15",
        "TIMEFRAME_H1",
    }
    assert all(
        end - start == worker.bear_incremental.maximum_warmup_span
        for _, start, end in session.calls
    )
    assert worker.bear_incremental.maximum_warmup_span < timedelta(days=2)


@pytest.mark.parametrize(
    ("group", "symbol"),
    (("goldi", "GOLD.i#"), ("goldm", "GOLDm#")),
)
def test_worker_binds_bear_setup_scanner_to_exact_profile_symbol(
    monkeypatch,
    group: str,
    symbol: str,
) -> None:
    monkeypatch.setenv("GOLDI_MT5_TERMINAL_PATH", "C:/Goldi/terminal64.exe")
    monkeypatch.setenv("GOLDI_MT5_LOGIN", "108098316")
    monkeypatch.setenv("GOLDI_MT5_SERVER", "XMGlobal-MT5 5")
    monkeypatch.setenv("GOLDM_REAL_MT5_TERMINAL_PATH", "C:/Goldm/terminal64.exe")
    monkeypatch.setenv("GOLDM_REAL_MT5_LOGIN", "391425346")
    monkeypatch.setenv("GOLDM_REAL_MT5_SERVER", "XMGlobal-MT5 14")
    config = load_worker_config(
        Path(__file__).resolve().parents[2] / "config" / "final" / group / "worker.json"
    )

    class NoopTelegram:
        def send(self, text: str, *, include_subscribers: bool = False) -> None:
            del text, include_subscribers

    worker = CompositePortfolioWorker(
        config,
        mt5_module=object(),
        telegram=NoopTelegram(),
    )

    assert worker.config.symbol == symbol
    assert worker.bear_replay.setup_engine.config.symbol == symbol
