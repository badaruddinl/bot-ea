from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from goldm_bear.engine import BearAction, BearBar, BearDecision, BearEngineConfig
from goldm_bear.replay import BearReplay


TZ = timezone(timedelta(hours=3))


def _signal(minute: int = 0) -> BearDecision:
    return BearDecision(
        action=BearAction.SELL,
        time=datetime(2026, 1, 1, 1, minute, tzinfo=TZ),
        symbol="GOLD.i#",
        reason="test_sell",
        score=4,
        entry=100.0,
        stop=102.0,
        take_profit=97.0,
        reward_risk=1.5,
    )


def _bar(minute: int, *, high: float, low: float, close: float = 100.0) -> BearBar:
    return BearBar(
        time=datetime(2026, 1, 1, 1, minute, tzinfo=TZ),
        open=100.0,
        high=high,
        low=low,
        close=close,
        tick_volume=100.0,
        spread=0.2,
    )


def test_resolve_sell_target_uses_short_direction() -> None:
    signal = _signal()
    outcome = BearReplay()._resolve(
        signal,
        [_bar(15, high=100.5, low=96.9, close=97.0)],
        datetime(2026, 1, 1, 1, 15, tzinfo=TZ),
        datetime(2026, 1, 1, 2, tzinfo=TZ),
    )

    assert outcome.result == "TARGET"
    assert outcome.outcome_r == pytest.approx(1.5)
    assert outcome.mfe_r == pytest.approx(1.55)
    assert outcome.mae_r == pytest.approx(-0.25)


def test_resolve_sell_stop_is_negative_one_r() -> None:
    outcome = BearReplay()._resolve(
        _signal(),
        [_bar(15, high=102.1, low=99.0, close=102.0)],
        datetime(2026, 1, 1, 1, 15, tzinfo=TZ),
        datetime(2026, 1, 1, 2, tzinfo=TZ),
    )

    assert outcome.result == "STOP"
    assert outcome.outcome_r == -1.0


def test_resolve_same_bar_is_conservative_ambiguous_loss() -> None:
    outcome = BearReplay()._resolve(
        _signal(),
        [_bar(15, high=102.1, low=96.9)],
        datetime(2026, 1, 1, 1, 15, tzinfo=TZ),
        datetime(2026, 1, 1, 2, tzinfo=TZ),
    )

    assert outcome.result == "AMBIGUOUS_SAME_BAR"
    assert outcome.outcome_r == -1.0


def test_resolve_does_not_read_signal_candle() -> None:
    signal = _signal()
    outcome = BearReplay()._resolve(
        signal,
        [
            _bar(0, high=102.5, low=96.5),
            _bar(15, high=100.5, low=96.9, close=97.0),
        ],
        datetime(2026, 1, 1, 1, 15, tzinfo=TZ),
        datetime(2026, 1, 1, 2, tzinfo=TZ),
    )

    assert outcome.result == "TARGET"
    assert outcome.closed_at == datetime(2026, 1, 1, 1, 30, tzinfo=TZ)


def test_maximum_regime_drop_must_exceed_minimum() -> None:
    with pytest.raises(ValueError, match="maximum regime drop"):
        BearEngineConfig(maximum_regime_drop_atr=1.0)
