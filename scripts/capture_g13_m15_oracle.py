from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from dataclasses import asdict, is_dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from gold_engine_core import load_named_profile  # noqa: E402
from gold_engine_core.rules import BearEngine, confluence_v1_config  # noqa: E402
from gold_engine_core.rules.bear import BearAction, BearBar  # noqa: E402


class CaptureError(RuntimeError):
    """Raised when read-only MT5 data cannot prove a scanner oracle."""


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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()


def capture(
    *,
    terminal_path: Path,
    source_symbol: str,
    signal_time: datetime,
) -> dict[str, object]:
    if signal_time.tzinfo is None or signal_time.utcoffset() is None:
        raise CaptureError("signal_time must include an explicit UTC offset")
    if signal_time.second or signal_time.microsecond or signal_time.minute % 15:
        raise CaptureError("signal_time must be aligned to an M15 open")
    try:
        mt5 = importlib.import_module("MetaTrader5")
    except ImportError as exc:  # pragma: no cover - Windows prerequisite
        raise CaptureError("MetaTrader5 package is unavailable") from exc
    if not mt5.initialize(path=str(terminal_path.resolve())):
        raise CaptureError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        account = mt5.account_info()
        symbol_info = mt5.symbol_info(source_symbol)
        if account is None or symbol_info is None:
            raise CaptureError("account or symbol contract is unavailable")
        signal_utc = signal_time.astimezone(UTC)
        rates = mt5.copy_rates_range(
            source_symbol,
            mt5.TIMEFRAME_M15,
            signal_utc - timedelta(days=5),
            signal_utc,
        )
        if rates is None:
            raise CaptureError(f"M15 rates unavailable: {mt5.last_error()}")
        signal_epoch = int(signal_utc.timestamp())
        eligible = [row for row in rates if int(row["time"]) <= signal_epoch]
        if not eligible or int(eligible[-1]["time"]) != signal_epoch:
            raise CaptureError("the requested signal bar is not the final closed oracle input")
        minimum_bars = BearEngine(confluence_v1_config(symbol=source_symbol)).minimum_bars
        if len(eligible) < minimum_bars:
            raise CaptureError("insufficient M15 history for the confluence scanner")
        selected = eligible[-minimum_bars:]
        point = float(symbol_info.point)
        raw_bars: list[dict[str, Any]] = [
            {
                "close": float(row["close"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "open": float(row["open"]),
                "raw_spread": float(row["spread"]) * point,
                "tick_volume": float(row["tick_volume"]),
                "time": datetime.fromtimestamp(int(row["time"]), UTC)
                .astimezone(signal_time.tzinfo)
                .isoformat(),
            }
            for row in selected
        ]
        vectors = []
        for profile_id, spread_floor in (("GOLDI", 0.20), ("GOLDM", 0.24)):
            manifest = load_named_profile(REPOSITORY_ROOT, profile_id)
            bars = tuple(
                BearBar(
                    time=datetime.fromisoformat(item["time"]),
                    open=item["open"],
                    high=item["high"],
                    low=item["low"],
                    close=item["close"],
                    tick_volume=item["tick_volume"],
                    spread=spread_floor,
                )
                for item in raw_bars
            )
            config = replace(
                confluence_v1_config(symbol=manifest.symbol),
                spread_floor=spread_floor,
            )
            decision = BearEngine(config).evaluate(bars)
            if decision.action is not BearAction.SELL:
                raise CaptureError(
                    f"oracle is not SELL for {profile_id}: {decision.action}/{decision.reason}"
                )
            vectors.append(
                {
                    "bars": [
                        {
                            **{key: value for key, value in item.items() if key != "raw_spread"},
                            "spread": spread_floor,
                        }
                        for item in raw_bars
                    ],
                    "case_id": "m15_confluence_sell_2026_08_18_1700",
                    "expected": canonicalize(decision),
                    "profile_fingerprint": manifest.fingerprint,
                    "profile_id": profile_id,
                    "schema_version": 1,
                    "spread_normalization": "PROFILE_RESEARCH_FLOOR",
                    "symbol": manifest.symbol,
                }
            )
        return {
            "account_server": str(account.server),
            "raw_source_symbol": source_symbol,
            "raw_terminal_path_sha256": _sha256_text(str(terminal_path.resolve())),
            "schema_version": 1,
            "signal_time": signal_time.isoformat(),
            "source_bar_count": len(raw_bars),
            "vectors": vectors,
        }
    finally:
        mt5.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture read-only G13 M15 scanner oracle")
    parser.add_argument("--terminal-path", type=Path, required=True)
    parser.add_argument("--source-symbol", required=True)
    parser.add_argument("--signal-time", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = capture(
        terminal_path=args.terminal_path,
        source_symbol=args.source_symbol,
        signal_time=args.signal_time,
    )
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
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    args.output.with_suffix(".sha256").write_text(
        f"{digest}  {args.output.name}\n",
        encoding="ascii",
    )
    print(f"vectors=2 sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
