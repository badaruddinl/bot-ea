from __future__ import annotations

import hashlib
import json
import runpy
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from gold_engine_core import ReferenceRuntimeReplay  # noqa: E402


def build_reports(repository_root: Path, output_root: Path) -> dict[str, str]:
    fixture = runpy.run_path(
        str(repository_root / "tests" / "gold_engine_core" / "test_causal_replay.py")
    )
    runtime_factory = fixture["runtime"]
    dataset_factory = fixture["dataset"]
    output_root.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for profile_id in ("GOLDI", "GOLDM"):
        runtime, engine_state = runtime_factory(profile_id)
        report = ReferenceRuntimeReplay(runtime).run(
            dataset_factory(profile_id), runtime.initial_state(engine_state)
        )
        payload = {
            "closed_bar_count": report.closed_bar_count,
            "decision_count": report.decision_count,
            "event_hash": report.event_hash,
            "from_time": report.from_time.isoformat(),
            "profile_fingerprint": report.profile_fingerprint,
            "profile_id": report.profile_id,
            "symbol": report.symbol,
            "tick_count": report.tick_count,
            "to_time": report.to_time.isoformat(),
            "warmup_suppressed_decisions": report.warmup_suppressed_decisions,
        }
        raw = (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8")
        path = output_root / f"{profile_id}-report.json"
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        path.with_suffix(".sha256").write_bytes(f"{digest}  {path.name}\n".encode("ascii"))
        hashes[profile_id] = digest
    return hashes


def main() -> int:
    output = REPOSITORY_ROOT / "evidence" / "G09-causal-tick-replay"
    for profile_id, digest in build_reports(REPOSITORY_ROOT, output).items():
        print(f"{profile_id}={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
