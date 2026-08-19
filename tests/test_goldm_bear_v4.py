from __future__ import annotations

from datetime import datetime, timedelta, timezone

from goldm_bear.engine import BearAction, BearBar, BearDecision
import pytest

from goldm_bear.multitimeframe import BearMultiTimeframeReplay, BearV4Config


TZ = timezone(timedelta(hours=3))


def _bar(
    minute: int,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> BearBar:
    return BearBar(
        time=datetime(2026, 1, 1, tzinfo=TZ) + timedelta(minutes=minute),
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_volume=100.0,
        spread=0.2,
    )


def _setup() -> BearDecision:
    return BearDecision(
        action=BearAction.SELL,
        time=datetime(2026, 1, 1, tzinfo=TZ),
        symbol="GOLD.i#",
        reason="v4_test_setup",
        score=90,
        resistance=100.0,
        entry=99.0,
        stop=101.0,
        take_profit=94.0,
        reward_risk=2.5,
    )


def test_v4_h1_gate_uses_falling_closed_sma() -> None:
    replay = BearMultiTimeframeReplay()
    bars = [
        _bar(index * 60, 120 - index, 120.2 - index, 118.8 - index, 119 - index)
        for index in range(22)
    ]

    assert replay._h1_bearish(bars) is True


def test_v4_m5_strong_failed_breakout_arms_setup() -> None:
    replay = BearMultiTimeframeReplay()
    history = [
        _bar(index * 5, 99.2, 99.7, 98.7, 99.1)
        for index in range(20)
    ]
    candidates = [
        _bar(100, 99.5, 100.1, 99.0, 99.8),
        _bar(105, 100.0, 100.2, 97.8, 98.1),
    ]

    result = replay._arm_on_m5(
        _setup(),
        history,
        candidates,
        candidates[0].time,
    )

    assert result["state"] == "ARMED"
    assert result["armed_at"] == candidates[-1].time + timedelta(minutes=5)


def test_v4_m5_acceptance_cancels_setup() -> None:
    replay = BearMultiTimeframeReplay()
    history = [
        _bar(index * 5, 99.2, 99.7, 98.7, 99.1)
        for index in range(20)
    ]
    candidates = [
        _bar(100, 100.2, 100.8, 100.1, 100.6),
        _bar(105, 100.6, 101.0, 100.4, 100.8),
    ]

    result = replay._arm_on_m5(
        _setup(),
        history,
        candidates,
        candidates[0].time,
    )

    assert result["state"] == "CANCELLED"
    assert result["reason"] == "M5_ACCEPTANCE"


def test_v4_m1_retest_requires_micro_break() -> None:
    replay = BearMultiTimeframeReplay()
    armed_at = datetime(2026, 1, 1, 2, tzinfo=TZ)
    history = [
        _bar(100 + index, 98.7, 99.0, 98.2, 98.6)
        for index in range(20)
    ]
    candidates = [
        BearBar(armed_at, 99.0, 99.5, 97.8, 98.0, 100.0, 0.2),
        BearBar(
            armed_at + timedelta(minutes=1),
            98.0,
            98.5,
            97.7,
            97.9,
            100.0,
            0.2,
        ),
        BearBar(
            armed_at + timedelta(minutes=2),
            99.2,
            99.4,
            96.9,
            97.1,
            100.0,
            0.2,
        ),
    ]
    m5_result = {
        "state": "ARMED",
        "armed_at": armed_at,
        "atr": 1.5,
        "touches": 1,
        "rejections": 1,
        "recent_high": 100.2,
    }

    plan = replay._entry_on_m1(
        _setup(),
        m5_result,
        history,
        candidates,
    )

    assert plan is not None
    assert plan["entry"] == history[-1].low - 0.01
    assert plan["target"] < plan["entry"] < plan["stop"]


def test_v4_fixed_target_r_must_be_positive() -> None:
    with pytest.raises(ValueError, match="fixed target R"):
        BearV4Config(fixed_target_r=0.0)
