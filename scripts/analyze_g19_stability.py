from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from gold_engine_core.g19_stability import analyze_stability


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze strict G19 stability evidence")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    report = analyze_stability(payload).to_payload()
    encoded = (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    args.output.with_suffix(".sha256").write_text(
        f"{hashlib.sha256(encoded).hexdigest()}  {args.output.name}\n", encoding="ascii"
    )
    print(encoded.decode().strip())
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
