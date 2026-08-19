from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from .config import load_worker_config
from .worker import CompositePortfolioWorker


def _load_local_env() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main(argv: Sequence[str] | None = None) -> int:
    _load_local_env()
    parser = argparse.ArgumentParser(description="Run a composite Revised + Bear portfolio worker")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-telegram", action="store_true")
    args = parser.parse_args(argv)
    config = load_worker_config(args.config)
    if args.dry_run:
        config = replace(config, execution_mode="signal_only", orders_enabled=False)
    if args.no_telegram:
        config = replace(
            config,
            telegram=replace(config.telegram, bot_token="", chat_ids=()),
        )
    worker = CompositePortfolioWorker(config)
    if args.once:
        try:
            print(json.dumps(worker.run_once(), sort_keys=True, default=str))
        finally:
            worker.session.close()
        return 0
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
