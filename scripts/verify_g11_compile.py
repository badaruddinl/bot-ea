from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from gold_engine_core import verify_g11_compile_artifacts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify warning-clean G11 MQL5 binaries")
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metaeditor-build", type=int, required=True)
    args = parser.parse_args()
    artifacts = verify_g11_compile_artifacts(REPOSITORY_ROOT, args.evidence_root)
    payload = {
        "artifacts": [artifact.to_payload() for artifact in artifacts],
        "gate": "G11",
        "metaeditor_build": args.metaeditor_build,
        "production_real_orders": "DISABLED",
        "status": "PASS",
    }
    raw = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    args.output.with_suffix(".sha256").write_text(
        f"{digest}  {args.output.name}\n",
        encoding="ascii",
    )
    print(f"status=PASS profiles={len(artifacts)} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
