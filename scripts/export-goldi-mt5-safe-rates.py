from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from goldm_signal.directional_research import load_registered_bar_dataset


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a registered GoldI bar dataset for offline MT5 custom rates."
    )
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    dataset = load_registered_bar_dataset(args.dataset_manifest.resolve())
    output = args.output.resolve()
    receipt = args.receipt.resolve()
    if output == receipt or output.exists() or receipt.exists():
        raise SystemExit("output and receipt must be distinct new files")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="ascii", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("time", "open", "high", "low", "close", "tick_volume", "spread"))
        for bar in dataset.bars:
            writer.writerow(
                (
                    int(bar.time.timestamp()),
                    format(bar.open, ".10g"),
                    format(bar.high, ".10g"),
                    format(bar.low, ".10g"),
                    format(bar.close, ".10g"),
                    1,
                    0,
                )
            )
    output_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
    payload = {
        "schema_version": 1,
        "status": "REGISTERED_BAR_MODEL_EXPORT",
        "model": "EPSOFT_BID_M5_AS_SPARSE_M1_CUSTOM_RATES",
        "dataset_id": dataset.dataset_id,
        "dataset_manifest_path": str(dataset.manifest_path),
        "dataset_manifest_sha256": dataset.manifest_sha256,
        "source_symbol": dataset.source_symbol,
        "target_custom_symbol": "GOLD_i_DEV_SAFE",
        "warmup_from_inclusive": dataset.warmup_start.isoformat(),
        "run_from_inclusive": dataset.run_start.isoformat(),
        "to_exclusive": dataset.end.isoformat(),
        "row_count": len(dataset.bars),
        "first_time": dataset.bars[0].time.isoformat(),
        "last_time": dataset.bars[-1].time.isoformat(),
        "output_path": str(output),
        "output_sha256": output_sha256,
        "limitations": [
            "BID OHLC only; no broker ask or tick path",
            "Five-minute bars are stored as sparse M1 custom rates",
            "Not a real-tick backtest and not blind OOS evidence",
        ],
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
