from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class EvidenceError(RuntimeError):
    pass


def decode(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def tester_block(text: str, expert: str, marker: str) -> str:
    lines = text.splitlines()
    markers = [index for index, line in enumerate(lines) if marker in line]
    if not markers:
        raise EvidenceError(f"tester marker missing: {marker}")
    marker_index = markers[-1]
    start = next(
        (
            index
            for index in range(marker_index, -1, -1)
            if f"testing of Experts\\bot-ea\\{expert}.ex5" in lines[index]
            and "started" in lines[index]
        ),
        None,
    )
    end = next(
        (index for index in range(marker_index, len(lines)) if "connection closed" in lines[index]),
        None,
    )
    if start is None or end is None:
        raise EvidenceError("tester boundary incomplete")
    return "\n".join(lines[start : end + 1]) + "\n"


def capture_native_contract(text: str, mode: str) -> tuple[str, dict[str, Any]]:
    specifications = {
        "instance": (
            "GoldEngineInstanceLeaseHarness",
            "G18_INSTANCE_LEASE passed=true",
            (
                "first=true",
                "duplicate_refused=true",
                "recovery=true",
                "dual_profile=true",
                "one_profile_restart=true",
                "other_remained_alive=true",
                "cross_terminal=FILE_COMMON_EXCLUSIVE",
                "final balance 100.00 USD",
                "OnTester result 1",
            ),
        ),
        "broker": (
            "GoldEngineBrokerFailureContractHarness",
            "G18_BROKER_FAILURE_CONTRACT passed=true",
            (
                "partial=true",
                "timeout_ambiguous=true",
                "connection_ambiguous=true",
                "funds_rejected=true",
                "invalid_rejected=true",
                "blind_retry=false",
                "final balance 100.00 USD",
                "OnTester result 1",
            ),
        ),
        "ownership": (
            "GoldEngineOwnershipFailureHarness",
            "G18_OWNERSHIP_FAILURE passed=true",
            (
                "owned=true",
                "other_symbol=true",
                "foreign_magic=true",
                "magic_collision=true",
                "cross_profile_management=false",
                "final balance 100.00 USD",
                "OnTester result 1",
            ),
        ),
    }
    expert, marker, required = specifications[mode]
    block = tester_block(text, expert, marker)
    if missing := [token for token in required if token not in block]:
        raise EvidenceError(f"{mode} native proof incomplete: {missing}")
    if any(token in block.casefold() for token in ("deal performed", "order performed")):
        raise EvidenceError(f"{mode} native proof contains mutation")
    return block, {
        "proof": mode,
        "result": "PASS",
        "order_authority": "DISABLED",
    }


def capture_market_closed(text: str) -> tuple[str, dict[str, Any]]:
    block = tester_block(
        text,
        "GoldEngineExecutionLifecycleHarness",
        "open_retcode=10018",
    )
    required = ("[Market closed]", "positions_before=0 positions_after=0", "open_retcode=10018")
    if missing := [token for token in required if token not in block]:
        raise EvidenceError(f"market-closed proof incomplete: {missing}")
    if "deal performed" in block.casefold():
        raise EvidenceError("market-closed proof contains a deal")
    return block, {
        "proof": "market_closed",
        "result": "EXPECTED_REJECTION_PASS",
        "retcode": 10018,
        "positions_before": 0,
        "positions_after": 0,
        "order_authority": "TESTER_ONLY",
    }


def capture_algo_off(mql_text: str) -> tuple[str, dict[str, Any]]:
    lines = [
        line
        for line in mql_text.splitlines()
        if "G18_RESTART_RECOVERY passed=false phase=OPEN" in line and "retcode=10027" in line
    ]
    if not lines:
        raise EvidenceError("Algo-off retcode 10027 marker missing")
    block = lines[-1] + "\n"
    return block, {
        "proof": "algo_off",
        "result": "EXPECTED_REJECTION_PASS",
        "retcode": 10027,
        "order_authority": "DISABLED_BY_CLIENT",
    }


def capture_restart(mql_text: str, terminal_text: str) -> tuple[str, dict[str, Any]]:
    recovery_lines = [
        line
        for line in mql_text.splitlines()
        if "G18_RESTART_RECOVERY passed=true phase=RECOVER" in line
    ]
    if not recovery_lines:
        raise EvidenceError("restart recovery marker missing")
    recovery = recovery_lines[-1]
    match = re.search(r"ticket=(\d+).*positions_after=0 close_retcode=10009", recovery)
    if not match:
        raise EvidenceError("restart recovery ticket/retcode incomplete")
    ticket = match.group(1)
    selected = [
        line
        for line in terminal_text.splitlines()
        if any(
            token in line
            for token in (
                f"order #{ticket} buy 0.01 / 0.01 GOLD.i#",
                "terminal synchronized with XM Global Limited: 1 positions",
                f"market sell 0.01 GOLD.i#, close #{ticket}",
                f"order #{ticket}",
                "disconnected from XMGlobal-MT5 5",
                "authorized on XMGlobal-MT5 5",
                "shutdown with 0",
            )
        )
    ]
    joined = "\n".join(selected)
    required = (
        f"order #{ticket} buy 0.01 / 0.01 GOLD.i#",
        "terminal synchronized with XM Global Limited: 1 positions",
        f"market sell 0.01 GOLD.i#, close #{ticket}",
        "disconnected from XMGlobal-MT5 5",
        "authorized on XMGlobal-MT5 5",
        "shutdown with 0",
    )
    if missing := [token for token in required if token not in joined]:
        raise EvidenceError(f"restart process proof incomplete: {missing}")
    block = joined + "\n" + recovery + "\n"
    return block, {
        "proof": "open_position_restart",
        "result": "PASS",
        "profile_id": "GOLDI",
        "account_mode": "DEMO",
        "ticket": ticket,
        "positions_seen_after_restart": 1,
        "positions_after_recovery": 0,
        "disconnect_seen": True,
        "reconnect_authorized": True,
        "close_retcode": 10009,
        "order_authority": "DEMO_E2E_ONLY",
    }


def write_evidence(block: str, metadata: dict[str, Any], output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    stem = str(metadata["proof"]).replace("_", "-")
    log_path = output / f"{stem}.log"
    raw = block.encode()
    log_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    log_path.with_suffix(".sha256").write_text(f"{digest}  {log_path.name}\n", encoding="ascii")
    result = {
        **metadata,
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "captured_log": log_path.name,
        "captured_log_sha256": digest,
        "production_real_orders": "DISABLED",
    }
    (output / f"{stem}.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture G18 failure/restart evidence")
    parser.add_argument(
        "mode",
        choices=("instance", "broker", "ownership", "market-closed", "algo-off", "restart"),
    )
    parser.add_argument("--tester-log", type=Path)
    parser.add_argument("--mql-log", type=Path)
    parser.add_argument("--terminal-log", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode in {"instance", "broker", "ownership"}:
        block, metadata = capture_native_contract(decode(args.tester_log), args.mode)
    elif args.mode == "market-closed":
        block, metadata = capture_market_closed(decode(args.tester_log))
    elif args.mode == "algo-off":
        block, metadata = capture_algo_off(decode(args.mql_log))
    else:
        block, metadata = capture_restart(decode(args.mql_log), decode(args.terminal_log))
    print(json.dumps(write_evidence(block, metadata, args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
