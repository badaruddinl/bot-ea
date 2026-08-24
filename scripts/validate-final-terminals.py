from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gold_portfolio.config import load_worker_config  # noqa: E402
from gold_portfolio.cli import _load_local_env  # noqa: E402
from gold_portfolio.mt5_session import BoundMt5Session  # noqa: E402


def main() -> int:
    _load_local_env()
    parser = argparse.ArgumentParser(description="Read-only validation of final MT5 bindings")
    parser.add_argument(
        "--group",
        choices=("goldi", "goldm", "all"),
        default="all",
    )
    args = parser.parse_args()
    groups = ("goldi", "goldm") if args.group == "all" else (args.group,)
    failures = 0
    for group in groups:
        config = load_worker_config(ROOT / "config" / "final" / group / "worker.json")
        session = BoundMt5Session(config)
        try:
            session.connect()
            account = session.account_info()
            print(
                f"{group}=OK path={config.terminal.path} login={account.login} "
                f"server={account.server} symbol={config.symbol} "
                f"balance={account.balance:.2f} equity={account.equity:.2f}"
            )
        except Exception as exc:
            failures += 1
            print(f"{group}=FAILED {type(exc).__name__}: {exc}")
        finally:
            session.close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
