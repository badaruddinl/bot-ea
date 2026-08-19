from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goldm_revised.replay_cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(
        main(
            [
                "--from-server-time",
                "2020-01-01",
                "--to-server-time",
                "2026-08-19",
                "--server-utc-offset-minutes",
                "180",
                "--validation-summary",
                "--output",
                "data/research/goldm_revised/replay_2020_2026.json",
            ]
        )
    )
