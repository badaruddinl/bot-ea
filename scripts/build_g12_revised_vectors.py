from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from gold_engine_core import load_named_profile  # noqa: E402
from gold_engine_core.rules.revised import (  # noqa: E402
    RevisedBar,
    RevisedDecision,
    RevisedEngine,
    RevisedEngineConfig,
    RevisedSide,
    RevisedSnapshot,
)
from gold_engine_core.rules.revised_setup import (  # noqa: E402
    RevisedDetectorState,
    RevisedM5Setup,
    RevisedSetupDetector,
)

TZ = timezone(timedelta(hours=3))
BASE = datetime(2026, 8, 18, 12, 0, tzinfo=TZ)
SETUP_BASE = datetime(2026, 8, 18, 8, 0, tzinfo=TZ)


def bar(
    index: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    *,
    minutes: int,
) -> RevisedBar:
    return RevisedBar(
        time=BASE + timedelta(minutes=index * minutes),
        open=open_,
        high=max(high, open_, close),
        low=min(low, open_, close),
        close=close,
        volume=100 + index,
        spread=0.20,
    )


def flat_m5() -> tuple[RevisedBar, ...]:
    result = []
    for index in range(20):
        close = 4392.0 + (0.2 if index % 2 else 0.0)
        result.append(
            bar(
                index,
                close - 0.1,
                close + 1.0,
                close - 1.0,
                close,
                minutes=5,
            )
        )
    return tuple(result)


def momentum_m5() -> tuple[RevisedBar, ...]:
    return tuple(
        bar(
            index,
            4390.0 + index * 2.0,
            4392.0 + index * 2.0,
            4389.0 + index * 2.0,
            4392.0 + index * 2.0,
            minutes=5,
        )
        for index in range(20)
    )


def range_m1(side: RevisedSide = RevisedSide.BUY) -> tuple[RevisedBar, ...]:
    if side is RevisedSide.BUY:
        values = [
            *((4392.0, 4393.0, 4391.0, 4392.5),) * 4,
            (4391.0, 4394.0, 4390.0, 4393.5),
            (4393.5, 4394.0, 4392.0, 4393.0),
            (4393.0, 4394.0, 4391.5, 4392.5),
            (4392.5, 4394.0, 4390.0, 4394.0),
            (4393.4, 4394.0, 4392.0, 4393.2),
            (4393.2, 4394.0, 4391.5, 4392.8),
            (4392.8, 4394.0, 4390.0, 4394.0),
            (4393.4, 4394.0, 4392.0, 4393.0),
            (4393.0, 4394.0, 4391.5, 4392.7),
            (4392.7, 4394.0, 4390.0, 4394.0),
            (4393.5, 4394.0, 4392.0, 4393.0),
            (4393.0, 4395.0, 4392.5, 4394.6),
        ]
    else:
        values = [
            *((4402.0, 4404.0, 4401.0, 4402.5),) * 4,
            (4404.0, 4405.0, 4401.0, 4401.5),
            (4401.5, 4403.0, 4400.5, 4401.8),
            (4401.8, 4403.5, 4400.8, 4402.0),
            (4402.0, 4405.0, 4401.0, 4401.6),
            (4401.6, 4403.0, 4400.5, 4401.9),
            (4401.9, 4403.5, 4400.8, 4402.1),
            (4402.1, 4405.0, 4401.0, 4401.7),
            (4401.7, 4403.0, 4400.5, 4401.9),
            (4401.9, 4403.5, 4400.8, 4402.0),
            (4402.0, 4405.0, 4401.0, 4401.8),
            (4401.8, 4403.0, 4400.5, 4401.7),
            (4401.7, 4402.0, 4398.5, 4399.0),
        ]
    return tuple(bar(index, *values[index], minutes=1) for index in range(len(values)))


def base_snapshot(symbol: str) -> RevisedSnapshot:
    m1 = range_m1()
    return RevisedSnapshot(
        symbol=symbol,
        side=RevisedSide.BUY,
        current_time=m1[-1].time,
        m1_bars=m1,
        m5_bars=flat_m5(),
        m5_trigger_time=m1[0].time - timedelta(minutes=1),
        m5_pattern="BULL_ENGULFING",
        m5_votes=3,
        confidence=92.0,
    )


def setup_bar(index: int, open_: float, high: float, low: float, close: float) -> RevisedBar:
    return RevisedBar(
        time=SETUP_BASE + timedelta(minutes=5 * index),
        open=open_,
        high=max(high, open_, close),
        low=min(low, open_, close),
        close=close,
        volume=100 + index,
        spread=0.20,
    )


def initial_setup_bars() -> tuple[RevisedBar, ...]:
    bars = [setup_bar(index, 99.0, 100.0, 98.0, 99.2) for index in range(16)]
    bars.extend(
        (
            setup_bar(16, 100.0, 100.5, 98.5, 99.0),
            setup_bar(17, 98.8, 102.0, 98.4, 101.6),
        )
    )
    return tuple(bars)


def reinforced_setup_bars() -> tuple[RevisedBar, ...]:
    return (*initial_setup_bars(), setup_bar(18, 101.0, 103.5, 100.8, 103.2))


def reversal_setup_bars() -> tuple[RevisedBar, ...]:
    return (*initial_setup_bars(), setup_bar(18, 102.0, 102.2, 96.0, 96.5))


def serialize_bar(value: RevisedBar) -> dict[str, object]:
    return {
        "close": value.close,
        "high": value.high,
        "low": value.low,
        "open": value.open,
        "spread": value.spread,
        "time": value.time.isoformat(),
        "volume": value.volume,
    }


def serialize_snapshot(value: RevisedSnapshot) -> dict[str, object]:
    return {
        "confidence": value.confidence,
        "current_time": value.current_time.isoformat(),
        "d1_bars": [serialize_bar(item) for item in value.d1_bars],
        "entry": value.entry,
        "h1_bars": [serialize_bar(item) for item in value.h1_bars],
        "invalidation": value.invalidation,
        "m1_bars": [serialize_bar(item) for item in value.m1_bars],
        "m5_bars": [serialize_bar(item) for item in value.m5_bars],
        "m5_pattern": value.m5_pattern,
        "m5_trigger_time": (value.m5_trigger_time.isoformat() if value.m5_trigger_time else None),
        "m5_votes": value.m5_votes,
        "side": value.side.value,
        "stop": value.stop,
        "symbol": value.symbol,
    }


def serialize_decision(value: RevisedDecision) -> dict[str, object]:
    return {
        "action": value.action.value,
        "confidence": value.confidence,
        "entry": value.entry,
        "entry_profile": value.entry_profile,
        "first_obstacle": value.first_obstacle,
        "first_obstacle_kind": value.first_obstacle_kind,
        "first_obstacle_r": value.first_obstacle_r,
        "m1_votes": value.m1_votes,
        "mode": value.mode.value if value.mode else None,
        "observation_only": value.observation_only,
        "reason": value.reason,
        "rejection_count": value.rejection_count,
        "state": value.state.value,
        "stop": value.stop,
        "target": value.target,
        "touch_count": value.touch_count,
    }


def serialize_setup(value: RevisedM5Setup | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "confidence": value.confidence,
        "invalidation": value.invalidation,
        "level": value.level,
        "pattern": value.pattern,
        "side": value.side.value,
        "trigger_time": value.trigger_time.isoformat(),
        "votes": value.votes,
    }


def roundtrip_detector(detector: RevisedSetupDetector) -> RevisedSetupDetector:
    payload = json.loads(json.dumps(detector.snapshot().to_payload()))
    return RevisedSetupDetector.from_state(RevisedDetectorState.from_payload(payload))


def build_vectors() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for profile_id, symbol in (("GOLDI", "GOLD.i#"), ("GOLDM", "GOLDm#")):
        profile_fingerprint = load_named_profile(REPOSITORY_ROOT, profile_id).fingerprint
        base = base_snapshot(symbol)
        cases = (
            ("range_entry", base),
            (
                "sell_range_entry",
                replace(
                    base,
                    side=RevisedSide.SELL,
                    m1_bars=range_m1(RevisedSide.SELL),
                    current_time=range_m1(RevisedSide.SELL)[-1].time,
                    m5_pattern="BEAR_ENGULFING",
                ),
            ),
            (
                "no_setup",
                replace(base, m5_trigger_time=None, m5_pattern="NONE"),
            ),
            (
                "sub_one_r_obstacle",
                replace(base, entry=4399.7, stop=4398.7),
            ),
            (
                "momentum_entry",
                replace(base, m5_bars=momentum_m5(), entry=4394.0, stop=4390.0),
            ),
        )
        engine = RevisedEngine(RevisedEngineConfig(symbol=symbol))
        for case_id, snapshot in cases:
            decision = engine.evaluate(snapshot)
            result.append(
                {
                    "case_id": case_id,
                    "expected": serialize_decision(decision),
                    "profile_id": profile_id,
                    "profile_fingerprint": profile_fingerprint,
                    "schema_version": 1,
                    "snapshot": serialize_snapshot(snapshot),
                }
            )
    return result


def build_setup_vectors() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    initial = initial_setup_bars()
    reinforced_bars = reinforced_setup_bars()
    reversal_bars = reversal_setup_bars()
    for profile_id, symbol in (("GOLDI", "GOLD.i#"), ("GOLDM", "GOLDm#")):
        fingerprint = load_named_profile(REPOSITORY_ROOT, profile_id).fingerprint

        detector = RevisedSetupDetector(maximum_m1_bars=12)
        accepted = detector.update(
            initial,
            current_m1_time=initial[-1].time + timedelta(minutes=6),
            side=RevisedSide.BUY,
        )
        assert accepted is not None
        accepted_state = detector.snapshot().to_payload()

        reinforced = detector.update(
            reinforced_bars,
            current_m1_time=accepted.trigger_time + timedelta(minutes=6),
            side=RevisedSide.BUY,
        )
        assert reinforced is not None
        reinforced_state = detector.snapshot().to_payload()

        restored = roundtrip_detector(detector)
        after_restart = restored.update(
            reinforced_bars,
            current_m1_time=accepted.trigger_time + timedelta(minutes=7),
            side=RevisedSide.BUY,
        )
        assert after_restart == reinforced

        consumed = roundtrip_detector(detector)
        consumed.consume(RevisedSide.BUY, accepted.trigger_time)
        consumed = roundtrip_detector(consumed)
        after_consume = consumed.update(
            reinforced_bars,
            current_m1_time=accepted.trigger_time + timedelta(minutes=7),
            side=RevisedSide.BUY,
        )
        assert after_consume is None

        expiring = RevisedSetupDetector(maximum_m1_bars=2)
        expiring_setup = expiring.update(
            initial,
            current_m1_time=initial[-1].time + timedelta(minutes=6),
            side=RevisedSide.BUY,
        )
        assert expiring_setup is not None
        assert (
            expiring.update(
                initial,
                current_m1_time=expiring_setup.trigger_time + timedelta(minutes=3),
                side=RevisedSide.BUY,
            )
            is None
        )
        expiry_state = expiring.snapshot().to_payload()
        expiry_restored = roundtrip_detector(expiring)
        expiry_termination = expiry_restored.pop_termination(RevisedSide.BUY)
        assert expiry_termination == (expiring_setup, "WATCH_WINDOW_EXPIRED")

        opposite = RevisedSetupDetector(maximum_m1_bars=12)
        opposite_buy = opposite.update(
            initial,
            current_m1_time=initial[-1].time + timedelta(minutes=6),
            side=RevisedSide.BUY,
        )
        assert opposite_buy is not None
        opposite_sell = opposite.update(
            reversal_bars,
            current_m1_time=reversal_bars[-1].time + timedelta(minutes=6),
            side=RevisedSide.SELL,
        )
        assert opposite_sell is not None
        opposite_state = opposite.snapshot().to_payload()
        opposite_restored = roundtrip_detector(opposite)
        opposite_termination = opposite_restored.pop_termination(RevisedSide.BUY)
        assert opposite_termination == (opposite_buy, "OPPOSITE_M5_SETUP_ACCEPTED")

        cases = (
            ("setup_accept", serialize_setup(accepted), accepted_state),
            ("reinforcement", serialize_setup(reinforced), reinforced_state),
            (
                "restart_restore",
                serialize_setup(after_restart),
                restored.snapshot().to_payload(),
            ),
            (
                "consume_restart_no_resurrection",
                serialize_setup(after_consume),
                consumed.snapshot().to_payload(),
            ),
            (
                "expiry_restart",
                {
                    "reason": expiry_termination[1],
                    "setup": serialize_setup(expiry_termination[0]),
                },
                expiry_state,
            ),
            (
                "opposite_cancel_restart",
                {
                    "reason": opposite_termination[1],
                    "setup": serialize_setup(opposite_termination[0]),
                    "sell_setup": serialize_setup(opposite_sell),
                },
                opposite_state,
            ),
        )
        for case_id, expected, state in cases:
            result.append(
                {
                    "case_id": case_id,
                    "expected": expected,
                    "profile_fingerprint": fingerprint,
                    "profile_id": profile_id,
                    "schema_version": 1,
                    "state": state,
                    "symbol": symbol,
                }
            )
    return result


def write_canonical(path: Path, payload: object) -> str:
    raw = (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    path.with_suffix(".sha256").write_text(
        f"{digest}  {path.name}\n",
        encoding="ascii",
    )
    return digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "corpus" / "revised_parity" / "vectors.json",
    )
    parser.add_argument("--setup-output", type=Path)
    args = parser.parse_args()
    setup_output = args.setup_output or args.output.with_name("setup_vectors.json")
    digest = write_canonical(args.output, build_vectors())
    setup_digest = write_canonical(setup_output, build_setup_vectors())
    print(f"vectors=10 sha256={digest} setup_vectors=12 setup_sha256={setup_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
