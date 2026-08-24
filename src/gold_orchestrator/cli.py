from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .config import load_orchestrator_config
from .locking import SingleInstanceLock
from .runtime import GlobalOrchestrator


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the global GOLD worker orchestrator")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/final/orchestrator.json"),
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--notify-shutdown", action="store_true")
    args = parser.parse_args(argv)
    config = load_orchestrator_config(args.config)
    orchestrator = GlobalOrchestrator(config)
    if args.notify_shutdown:
        orchestrator.send_shutdown_notice()
        return 0
    if args.check:
        print(
            f"{config.orchestrator_id} config OK: "
            + ", ".join(sorted(config.workers))
        )
        return 0
    lock_path = config.state_path.with_name("orchestrator.lock")
    with SingleInstanceLock(lock_path):
        orchestrator.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
