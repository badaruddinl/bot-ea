from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .runtime import RevisedShadowRuntime, load_runtime_config


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run signal-only GOLDM_REVISED shadow runtime.")
    parser.add_argument("--config", type=Path, default=Path("config/goldm-revised-shadow.json"))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    runtime = RevisedShadowRuntime(load_runtime_config(args.config))
    if args.once:
        result = runtime.run_once()
        print(json.dumps(result, default=str, sort_keys=True))
        runtime.source.close()
        return 0
    runtime.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
