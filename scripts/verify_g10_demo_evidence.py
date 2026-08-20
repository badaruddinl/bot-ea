from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from gold_engine_core import verify_g10_evidence  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify complete G10 DEMO/read-only/tester evidence"
    )
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify_g10_evidence(REPOSITORY_ROOT, args.evidence_root)
    raw = (
        json.dumps(
            result.to_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    args.output.with_suffix(".sha256").write_bytes(
        f"{digest}  {args.output.name}\n".encode("ascii")
    )
    print(f"accepted={str(result.accepted).lower()} sha256={digest}")
    return 0 if result.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
