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

from gold_engine_core.rules.revised import (  # noqa: E402
    RevisedBar,
    RevisedEngine,
    RevisedEngineConfig,
    RevisedSide,
    RevisedSnapshot,
)

TZ = timezone(timedelta(hours=3))
BASE = datetime(2026, 8, 18, 12, 0, tzinfo=TZ)


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


def range_m1() -> tuple[RevisedBar, ...]:
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


def serialize_decision(value) -> dict[str, object]:
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


def build_vectors() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for profile_id, symbol in (("GOLDI", "GOLD.i#"), ("GOLDM", "GOLDm#")):
        base = base_snapshot(symbol)
        cases = (
            ("range_entry", base),
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
                    "schema_version": 1,
                    "snapshot": serialize_snapshot(snapshot),
                }
            )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "corpus" / "revised_parity" / "vectors.json",
    )
    args = parser.parse_args()
    raw = (
        json.dumps(
            build_vectors(),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    args.output.with_suffix(".sha256").write_text(
        f"{digest}  {args.output.name}\n",
        encoding="ascii",
    )
    print(f"vectors=8 sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
