from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from gold_engine_core.current_behavior import build_current_behavior_corpus  # noqa: E402


def main() -> int:
    results = build_current_behavior_corpus(REPOSITORY_ROOT)
    for profile_id, digest in results.items():
        print(f"{profile_id}={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
