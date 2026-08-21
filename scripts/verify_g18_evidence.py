from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class G18VerificationError(RuntimeError):
    pass


def _json(path: Path) -> Any:
    if not path.is_file():
        raise G18VerificationError(f"required G18 evidence missing: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise G18VerificationError(message)


def build_report(root: Path) -> dict[str, Any]:
    native = root / "evidence/G18-failure-restart-e2e/native"
    paths = {
        "dependency": native / "dependency-lab.json",
        "instance": native / "instance.json",
        "broker": native / "broker.json",
        "ownership": native / "ownership.json",
        "market_closed": native / "market-closed.json",
        "algo_off": native / "algo-off.json",
        "position_restart": native / "open-position-restart.json",
        "windows_restart": native / "windows-restart.json",
        "dual_terminal_restart": native / "dual-terminal-restart.json",
        "guard": root / "evidence/G14-execution-lifecycle/native/goldi-execution-guard-tester.json",
        "manual": root
        / "evidence/G14-execution-lifecycle/native/goldi-position-persistence-tester.json",
        "revised_corpus": root / "corpus/revised_parity/setup_vectors.json",
        "bear_corpus": root / "corpus/bear_parity/vectors.json",
    }
    values = {key: _json(path) for key, path in paths.items()}
    dependency = values["dependency"]
    _require(
        dependency.get("status") == "PASS"
        and dependency.get("db_down_failed_closed") is True
        and dependency.get("telegram_down_failed_calls") == 9
        and dependency.get("telegram_recovery_delivered_calls") == 9
        and dependency.get("backlog_replay_duplicates") == 12
        and dependency.get("database_event_count") == 12
        and dependency.get("spool_unchanged") is True,
        "dependency failure/recovery matrix incomplete",
    )
    for name in ("instance", "broker", "ownership"):
        _require(values[name].get("result") == "PASS", f"{name} native proof not PASS")
    _require(
        values["market_closed"].get("retcode") == 10018
        and values["algo_off"].get("retcode") == 10027,
        "expected broker rejection retcodes incomplete",
    )
    restart = values["position_restart"]
    _require(
        restart.get("result") == "PASS"
        and restart.get("positions_seen_after_restart") == 1
        and restart.get("positions_after_recovery") == 0
        and restart.get("disconnect_seen") is True
        and restart.get("reconnect_authorized") is True,
        "open-position process restart evidence incomplete",
    )
    _require(
        values["windows_restart"].get("result") == "PASS"
        and values["windows_restart"].get("boot_id_changed") is True,
        "Windows/VM restart evidence incomplete",
    )
    _require(
        values["dual_terminal_restart"].get("result") == "PASS"
        and values["dual_terminal_restart"].get("both_profiles_recovered") is True
        and values["dual_terminal_restart"].get("one_profile_restart_isolated") is True,
        "dual-terminal restart evidence incomplete",
    )
    revised_cases = {
        (str(item.get("profile_id")), str(item.get("case_id"))) for item in values["revised_corpus"]
    }
    bear_cases = {
        (str(item.get("profile_id")), str(item.get("case_id"))) for item in values["bear_corpus"]
    }
    _require(
        all((profile, "restart_restore") in revised_cases for profile in ("GOLDI", "GOLDM")),
        "Revised restart corpus incomplete",
    )
    _require(
        all((profile, "watch_m1_restart_state") in bear_cases for profile in ("GOLDI", "GOLDM")),
        "Bear restart corpus incomplete",
    )
    _require(
        values["guard"].get("order_authority") == "DISABLED"
        and values["manual"].get("order_authority") == "DISABLED",
        "guard/manual upstream authority is unsafe",
    )
    for key, value in values.items():
        if isinstance(value, dict) and "production_real_orders" in value:
            _require(
                value.get("production_real_orders") == "DISABLED",
                f"REAL authority unsafe in {key}",
            )
    return {
        "schema_version": 1,
        "gate": "G18",
        "status": "PASS",
        "no_duplicate": True,
        "no_lost_ownership": True,
        "no_cross_profile_management": True,
        "input_sha256": {key: _sha256(path) for key, path in paths.items()},
        "production_real_orders": "DISABLED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify strict G18 evidence")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(args.root.resolve())
    encoded = (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(encoded)
        args.output.with_suffix(".sha256").write_text(
            f"{hashlib.sha256(encoded).hexdigest()}  {args.output.name}\n", encoding="ascii"
        )
    print(encoded.decode().strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
