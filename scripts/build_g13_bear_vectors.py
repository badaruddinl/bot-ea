from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from gold_engine_core import ProfileConfig, load_named_profile  # noqa: E402
from gold_engine_core.rules.bear import BearAction, BearBar, BearDecision  # noqa: E402
from gold_engine_core.rules.bear_incremental import (  # noqa: E402
    BearIncrementalMachine,
    BearIncrementalOutput,
)
from gold_engine_core.rules.bear_multitimeframe import (  # noqa: E402
    BearMultiTimeframeReplay,
    BearV4Config,
)

TZ = timezone(timedelta(hours=3))
SETUP_TIME = datetime(2026, 1, 2, 0, 0, tzinfo=TZ)


def bar(time: datetime, open_: float, high: float, low: float, close: float) -> BearBar:
    return BearBar(time, open_, high, low, close, 100.0, 0.20)


def setup_decision(symbol: str) -> BearDecision:
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


class FixtureSetupEngine:
    minimum_bars = 1

    def __init__(self, setup: BearDecision) -> None:
        self.setup = setup

    def scan(self, bars: tuple[BearBar, ...]) -> list[BearDecision]:
        return [self.setup] if bars else []


def fixture_bars() -> tuple[
    tuple[BearBar, ...],
    tuple[BearBar, ...],
    tuple[BearBar, ...],
    tuple[BearBar, ...],
]:
    setup_available = SETUP_TIME + timedelta(minutes=15)
    h1 = tuple(
        bar(
            setup_available - timedelta(hours=22 - index),
            120.0 - index,
            120.2 - index,
            118.8 - index,
            119.0 - index,
        )
        for index in range(22)
    )
    m15 = (bar(SETUP_TIME, 100.0, 100.2, 98.8, 99.0),)
    m5_history = tuple(
        bar(
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
        bar(setup_available, 99.5, 100.1, 99.0, 99.8),
        bar(setup_available + timedelta(minutes=5), 100.0, 100.2, 97.8, 98.1),
    )
    armed_at = setup_available + timedelta(minutes=10)
    m1_history = tuple(
        bar(
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
        bar(armed_at, 99.0, 99.5, 97.8, 98.0),
        bar(armed_at + timedelta(minutes=1), 98.0, 98.5, 97.7, 97.9),
        bar(armed_at + timedelta(minutes=2), 99.2, 99.4, 96.9, 97.1),
    )
    return m1, m5, m15, h1


def machine(profile_id: str) -> BearIncrementalMachine:
    manifest = load_named_profile(REPOSITORY_ROOT, profile_id)
    profile = ProfileConfig.from_manifest(manifest, tick_size=Decimal("0.01"))
    spread = 0.20 if profile_id == "GOLDI" else 0.24
    replay = BearMultiTimeframeReplay(
        BearV4Config(price_tick=0.01, spread_floor=spread, fixed_target_r=2.0)
    )
    replay.setup_engine = FixtureSetupEngine(setup_decision(profile.symbol))
    return BearIncrementalMachine(profile, replay)


def canonicalize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return canonicalize(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): canonicalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    return value


def output_payload(output: BearIncrementalOutput) -> dict[str, object]:
    state = output.next_state
    return {
        "events": canonicalize(output.events),
        "phase": state.phase.value,
        "sequence": state.sequence,
        "setup_id": state.setup_id,
        "signal": canonicalize(output.signal),
        "state": canonicalize(state),
    }


def build_profile_cases(profile_id: str) -> list[dict[str, object]]:
    evaluator = machine(profile_id)
    m1, m5, m15, h1 = fixture_bars()
    initial = evaluator.initial_state(h1[0].time)
    available_at = m1[-1].time + timedelta(minutes=1)
    happy = evaluator.feed_closed_batches(
        initial,
        m1_bars=m1,
        m5_bars=m5,
        m15_bars=m15,
        h1_bars=h1,
        available_at=available_at,
        emit_after=SETUP_TIME,
    )

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

    flat_h1 = tuple(replace(item, open=100.0, high=100.2, low=99.8, close=100.0) for item in h1)
    h1_rejected = evaluator.feed_closed_batches(
        evaluator.initial_state(flat_h1[0].time),
        m1_bars=(),
        m5_bars=(),
        m15_bars=m15,
        h1_bars=flat_h1,
        available_at=SETUP_TIME + timedelta(minutes=15),
        emit_after=SETUP_TIME,
    )

    setup_available = SETUP_TIME + timedelta(minutes=15)
    accepted_m5 = (
        *m5[:-2],
        bar(setup_available, 100.2, 100.8, 100.1, 100.6),
        bar(setup_available + timedelta(minutes=5), 100.6, 101.0, 100.4, 100.8),
    )
    m5_accepted = evaluator.feed_closed_batches(
        evaluator.initial_state(h1[0].time),
        m1_bars=(),
        m5_bars=accepted_m5,
        m15_bars=m15,
        h1_bars=h1,
        available_at=setup_available + timedelta(minutes=10),
        emit_after=SETUP_TIME,
    )

    flat_candidates = tuple(
        bar(
            armed_at + timedelta(minutes=index),
            98.5,
            98.8,
            98.0,
            98.4,
        )
        for index in range(evaluator.replay.config.m1_entry_bars)
    )
    m1_expired = evaluator.feed_closed_batches(
        watching.next_state,
        m1_bars=(*m1[:20], *flat_candidates),
        m5_bars=m5,
        m15_bars=m15,
        h1_bars=h1,
        available_at=flat_candidates[-1].time + timedelta(minutes=1),
        emit_after=armed_at,
    )

    manifest = load_named_profile(REPOSITORY_ROOT, profile_id)
    inputs = {
        "h1": canonicalize(h1),
        "m1": canonicalize(m1),
        "m15": canonicalize(m15),
        "m5": canonicalize(m5),
        "setup": canonicalize(setup_decision(evaluator.profile.symbol)),
    }
    return [
        {
            "case_id": case_id,
            "expected": output_payload(output),
            "inputs": inputs,
            "profile_fingerprint": manifest.fingerprint,
            "profile_id": profile_id,
            "schema_version": 1,
            "symbol": evaluator.profile.symbol,
        }
        for case_id, output in (
            ("happy_path_entry", happy),
            ("watch_m1_restart_state", watching),
            ("h1_rejected", h1_rejected),
            ("m5_acceptance_cancelled", m5_accepted),
            ("m1_expired", m1_expired),
        )
    ]


def build_vectors() -> list[dict[str, object]]:
    return [item for profile_id in ("GOLDI", "GOLDM") for item in build_profile_cases(profile_id)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build canonical G13 Bear parity vectors")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "corpus" / "bear_parity" / "vectors.json",
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
    print(f"vectors=10 sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
