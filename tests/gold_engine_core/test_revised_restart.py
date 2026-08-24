from __future__ import annotations

import json
import runpy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from gold_engine_core.rules.revised import RevisedEngine, RevisedSide
from gold_engine_core.rules.revised_setup import (
    RevisedDetectorState,
    RevisedSetupDetector,
)
from gold_portfolio.config import load_worker_config
from gold_portfolio.worker import CompositePortfolioWorker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=3))
START = datetime(2026, 8, 18, 8, 0, tzinfo=TZ)


def revised_bar(index: int, open_: float, high: float, low: float, close: float):
    from gold_engine_core.rules.revised import RevisedBar

    return RevisedBar(
        time=START + timedelta(minutes=5 * index),
        open=open_,
        high=max(high, open_, close),
        low=min(low, open_, close),
        close=close,
        volume=100 + index,
        spread=0.20,
    )


def initial_setup_bars():
    bars = [revised_bar(index, 99.0, 100.0, 98.0, 99.2) for index in range(16)]
    bars.extend(
        (
            revised_bar(16, 100.0, 100.5, 98.5, 99.0),
            revised_bar(17, 98.8, 102.0, 98.4, 101.6),
        )
    )
    return tuple(bars)


def reinforced_bars():
    return (
        *initial_setup_bars(),
        revised_bar(18, 101.0, 103.5, 100.8, 103.2),
    )


def roundtrip(detector: RevisedSetupDetector) -> RevisedSetupDetector:
    payload = json.loads(json.dumps(detector.snapshot().to_payload()))
    return RevisedSetupDetector.from_state(RevisedDetectorState.from_payload(payload))


def test_restart_before_setup_is_identity_preserving() -> None:
    detector = RevisedSetupDetector(maximum_m1_bars=12)
    restored = roundtrip(detector)

    assert restored.snapshot() == detector.snapshot()
    assert (
        restored.update(initial_setup_bars()[:1], current_m1_time=START, side=RevisedSide.BUY)
        is None
    )


def test_restart_after_setup_reinforcement_and_during_watch_preserves_trigger() -> None:
    detector = RevisedSetupDetector(maximum_m1_bars=12)
    bars = initial_setup_bars()
    first = detector.update(
        bars,
        current_m1_time=bars[-1].time + timedelta(minutes=6),
        side=RevisedSide.BUY,
    )
    assert first is not None

    after_setup = roundtrip(detector)
    persisted = after_setup.update(
        bars,
        current_m1_time=first.trigger_time + timedelta(minutes=2),
        side=RevisedSide.BUY,
    )
    assert persisted == first

    reinforced = detector.update(
        reinforced_bars(),
        current_m1_time=first.trigger_time + timedelta(minutes=6),
        side=RevisedSide.BUY,
    )
    assert reinforced is not None
    assert reinforced.trigger_time == first.trigger_time
    restored_reinforced = roundtrip(detector)
    after_restart = restored_reinforced.update(
        reinforced_bars(),
        current_m1_time=first.trigger_time + timedelta(minutes=7),
        side=RevisedSide.BUY,
    )
    assert after_restart == reinforced
    assert (
        restored_reinforced.snapshot().last_classified_m5 == detector.snapshot().last_classified_m5
    )


def test_restart_immediately_before_entry_ready_produces_identical_decision() -> None:
    module = runpy.run_path(str(REPOSITORY_ROOT / "tests" / "test_goldm_revised.py"))
    snapshot_factory = module["snapshot"]
    detector = RevisedSetupDetector(maximum_m1_bars=12)
    bars = initial_setup_bars()
    setup = detector.update(
        bars,
        current_m1_time=bars[-1].time + timedelta(minutes=6),
        side=RevisedSide.BUY,
    )
    assert setup is not None
    restored_setup = roundtrip(detector).update(
        bars,
        current_m1_time=setup.trigger_time + timedelta(minutes=1),
        side=RevisedSide.BUY,
    )
    assert restored_setup == setup

    base_snapshot = snapshot_factory()
    before = RevisedEngine().evaluate(
        replace(
            base_snapshot,
            m5_trigger_time=setup.trigger_time,
            m5_pattern=setup.pattern,
            m5_votes=setup.votes,
            confidence=setup.confidence,
            level=setup.level,
            invalidation=setup.invalidation,
        )
    )
    after = RevisedEngine().evaluate(
        replace(
            base_snapshot,
            m5_trigger_time=restored_setup.trigger_time,
            m5_pattern=restored_setup.pattern,
            m5_votes=restored_setup.votes,
            confidence=restored_setup.confidence,
            level=restored_setup.level,
            invalidation=restored_setup.invalidation,
        )
    )

    assert asdict(after) == asdict(before)


def test_consumed_or_cancelled_setup_never_resurrects_after_warmup() -> None:
    bars = initial_setup_bars()
    detector = RevisedSetupDetector(maximum_m1_bars=12)
    setup = detector.update(
        bars,
        current_m1_time=bars[-1].time + timedelta(minutes=6),
        side=RevisedSide.BUY,
    )
    assert setup is not None
    detector.consume(RevisedSide.BUY, setup.trigger_time)
    restored = roundtrip(detector)

    for end in range(2, len(bars) + 1):
        assert (
            restored.update(
                bars[:end],
                current_m1_time=setup.trigger_time + timedelta(minutes=1),
                side=RevisedSide.BUY,
            )
            is None
        )
    assert restored.snapshot().consumed == detector.snapshot().consumed

    expiring = RevisedSetupDetector(maximum_m1_bars=2)
    live = expiring.update(
        bars,
        current_m1_time=bars[-1].time + timedelta(minutes=6),
        side=RevisedSide.BUY,
    )
    assert live is not None
    assert (
        expiring.update(
            bars,
            current_m1_time=live.trigger_time + timedelta(minutes=3),
            side=RevisedSide.BUY,
        )
        is None
    )
    restored_expiry = roundtrip(expiring)
    assert restored_expiry.pop_termination(RevisedSide.BUY) == (
        live,
        "WATCH_WINDOW_EXPIRED",
    )
    assert restored_expiry.pop_termination(RevisedSide.BUY) is None

    opposite = RevisedSetupDetector(maximum_m1_bars=12)
    buy = opposite.update(
        bars,
        current_m1_time=bars[-1].time + timedelta(minutes=6),
        side=RevisedSide.BUY,
    )
    assert buy is not None
    reversal = (
        *bars,
        revised_bar(18, 102.0, 102.2, 96.0, 96.5),
    )
    assert (
        opposite.update(
            reversal,
            current_m1_time=reversal[-1].time + timedelta(minutes=6),
            side=RevisedSide.SELL,
        )
        is not None
    )
    restored_opposite = roundtrip(opposite)
    assert restored_opposite.pop_termination(RevisedSide.BUY) == (
        buy,
        "OPPOSITE_M5_SETUP_ACCEPTED",
    )


@pytest.mark.parametrize("group", ["goldi", "goldm"])
def test_worker_restart_with_open_position_keeps_seen_and_consumed_setup(
    monkeypatch,
    tmp_path: Path,
    group: str,
) -> None:
    monkeypatch.setenv("GOLDI_MT5_TERMINAL_PATH", "C:/Goldi/terminal64.exe")
    monkeypatch.setenv("GOLDI_MT5_LOGIN", "123456")
    monkeypatch.setenv("GOLDI_MT5_SERVER", "XMGlobal-MT5 5")
    monkeypatch.setenv("GOLDM_REAL_MT5_TERMINAL_PATH", "C:/Goldm/terminal64.exe")
    monkeypatch.setenv("GOLDM_REAL_MT5_LOGIN", "391425346")
    monkeypatch.setenv("GOLDM_REAL_MT5_SERVER", "XMGlobal-MT5 14")
    config = load_worker_config(REPOSITORY_ROOT / "config" / "final" / group / "worker.json")
    config = replace(
        config,
        state_path=tmp_path / group / "state.json",
        audit_path=tmp_path / group / "audit.jsonl",
    )

    class NoopTelegram:
        def send(self, text: str, *, include_subscribers: bool = False) -> None:
            del text, include_subscribers

    worker = CompositePortfolioWorker(config, mt5_module=object(), telegram=NoopTelegram())
    bars = initial_setup_bars()
    setup = worker.revised_detector.update(
        bars,
        current_m1_time=bars[-1].time + timedelta(minutes=6),
        side=RevisedSide.BUY,
    )
    assert setup is not None
    worker.revised_detector.consume(RevisedSide.BUY, setup.trigger_time)
    worker.state["seen"] = ["revised:open-signal"]
    worker.state["open_positions"] = {"777": {"signal_id": "revised:open-signal"}}
    worker._save_state()

    restarted = CompositePortfolioWorker(config, mt5_module=object(), telegram=NoopTelegram())
    assert restarted._seen("revised:open-signal")
    assert "777" in restarted.state["open_positions"]
    assert (
        restarted.revised_detector.update(
            bars,
            current_m1_time=setup.trigger_time + timedelta(minutes=1),
            side=RevisedSide.BUY,
        )
        is None
    )


def test_detector_payload_rejects_invalid_window_and_unknown_shape() -> None:
    state = RevisedSetupDetector(maximum_m1_bars=12).snapshot()
    payload = state.to_payload()
    payload["unknown"] = True
    with pytest.raises(ValueError, match="keys"):
        RevisedDetectorState.from_payload(payload)

    payload = state.to_payload()
    payload["maximum_m1_bars"] = True
    with pytest.raises(ValueError, match="integer"):
        RevisedDetectorState.from_payload(payload)

    detector = RevisedSetupDetector(maximum_m1_bars=12)
    bars = initial_setup_bars()
    assert (
        detector.update(
            bars,
            current_m1_time=bars[-1].time + timedelta(minutes=6),
            side=RevisedSide.BUY,
        )
        is not None
    )
    payload = detector.snapshot().to_payload()
    payload["active"][0]["confidence"] = float("inf")
    with pytest.raises(ValueError, match="finite"):
        RevisedDetectorState.from_payload(payload)
