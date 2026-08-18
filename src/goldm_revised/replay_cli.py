from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Sequence

from .engine import RevisedEngine, RevisedEngineConfig
from .evidence import august_five, validate_evidence
from .replay import RevisedMt5HistoryLoader, RevisedReplay
from .runtime import load_runtime_config


def _server_time(value: str, zone: timezone) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(type(value).__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay GOLDM_REVISED on closed broker bars.")
    parser.add_argument("--config", type=Path, default=Path("config/goldm-revised-shadow.json"))
    parser.add_argument("--from-server-time", required=True)
    parser.add_argument("--to-server-time", required=True)
    parser.add_argument("--server-utc-offset-minutes", type=int, default=180)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--inspect-server-time", action="append", default=[])
    parser.add_argument("--validate-august-five", action="store_true")
    parser.add_argument("--validation-summary", action="store_true")
    args = parser.parse_args(argv)
    zone = timezone(timedelta(minutes=args.server_utc_offset_minutes))
    start = _server_time(args.from_server_time, zone)
    end = _server_time(args.to_server_time, zone)
    evidence_expectations = august_five(zone) if args.validate_august_five else ()
    inspect_times = tuple(_server_time(value, zone) for value in args.inspect_server_time) + tuple(
        item.requested_time for item in evidence_expectations
    )
    if end <= start:
        raise SystemExit("replay end must be after start")
    config = load_runtime_config(args.config)
    engine_values = dict(config.get("engine", {}))
    if "psychological_steps" in engine_values:
        engine_values["psychological_steps"] = tuple(engine_values["psychological_steps"])
    if "strong_m5_patterns" in engine_values:
        engine_values["strong_m5_patterns"] = tuple(engine_values["strong_m5_patterns"])
    engine = RevisedEngine(RevisedEngineConfig(**engine_values))
    loader = RevisedMt5HistoryLoader()
    try:
        data = loader.load(
            symbol=engine.config.symbol,
            start=start,
            end=end,
            server_timezone=zone,
        )
    finally:
        loader.close()
    report = RevisedReplay(engine).run(
        m1_bars=data["m1"],
        m5_bars=data["m5"],
        h1_bars=data["h1"],
        d1_bars=data["d1"],
        from_time=start,
        to_time=end,
        inspect_times=inspect_times,
        inspect_tolerance_minutes=30 if evidence_expectations else 5,
    )
    report_payload = asdict(report)
    if evidence_expectations:
        report_payload["evidence_validation"] = validate_evidence(
            evidence_expectations,
            report.inspections,
            report.outcomes,
        )
        report_payload["evidence_pass_count"] = sum(
            bool(item["matched"])
            for item in report_payload["evidence_validation"]
        )
    payload = json.dumps(report_payload, default=_json_default, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    if args.validation_summary:
        _print_validation_summary(report_payload)
    else:
        print(payload)
    return 0


def _print_validation_summary(payload: dict[str, object]) -> None:
    print(
        "ALL "
        f"signals={payload['signals']} resolved={payload['resolved']} "
        f"buy={payload['buy_signals']} core_buy={payload['core_buy_signals']} "
        f"scalper={payload['scalper_signals']} sell={payload['sell_signals']} "
        f"tp={payload['target_count']} sl={payload['stop_count']} "
        f"total_r={payload['total_r']:.6f} expectancy_r={payload['expectancy_r']:.6f} "
        f"max_dd_r={payload['maximum_drawdown_r']:.6f}"
    )
    for evidence in payload.get("evidence_validation", []):
        observed = evidence.get("observed") or {}
        outcome = evidence.get("outcome") or {}
        print(
            f"{evidence['evidence_id']} {evidence['status']} "
            f"expected={evidence['expected_side'].value}/{evidence['expected_profile']} "
            f"observed={getattr(observed.get('side'), 'value', '-')}/"
            f"{observed.get('entry_profile', '-')} "
            f"state={getattr(observed.get('state'), 'value', '-')} "
            f"trigger={observed.get('setup_trigger_time', '-')} "
            f"retests={observed.get('retest_count', '-')} votes={observed.get('m1_votes', '-')} "
            f"room_r={observed.get('first_obstacle_r', '-')} "
            f"outcome={outcome.get('result', '-')} r={outcome.get('outcome_r', '-')} "
            f"reason={observed.get('reason', 'no candidate')}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
