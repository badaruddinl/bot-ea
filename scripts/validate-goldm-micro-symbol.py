from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goldm_revised.instrument_profile import GoldInstrumentProfile  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "goldm-micro-baseline-v1.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.config.read_text(encoding="utf-8"))
    profile = GoldInstrumentProfile.from_mapping(payload)
    import MetaTrader5 as mt5

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        if not mt5.symbol_select(profile.symbol, True):
            result = {
                "status": "FAIL",
                "profile_id": profile.profile_id,
                "symbol": profile.symbol,
                "errors": [f"symbol selection failed: {mt5.last_error()}"],
            }
            print(json.dumps(result, indent=2, sort_keys=True))
            return 1
        info = mt5.symbol_info(profile.symbol)
        errors = profile.validate_mt5_symbol_info(info)
        result = {
            "status": "PASS" if not errors else "FAIL",
            "profile_id": profile.profile_id,
            "symbol": profile.symbol,
            "errors": list(errors),
            "low_exposure_oz": profile.exposure_ounces(profile.low_lot),
            "high_exposure_oz": profile.exposure_ounces(profile.high_lot),
            "partial_exposure_oz": profile.exposure_ounces(profile.partial_lot),
            "actual": (
                None
                if info is None
                else {
                    field: getattr(info, field, None)
                    for field in (
                        "trade_contract_size",
                        "volume_min",
                        "volume_step",
                        "volume_max",
                        "point",
                        "trade_tick_size",
                        "trade_tick_value",
                        "spread",
                    )
                }
            ),
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if not errors else 1
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
