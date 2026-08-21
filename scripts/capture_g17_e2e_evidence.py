from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path


class EvidenceError(RuntimeError):
    pass


def decode(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def _last_line(lines: list[str], contains: str) -> str:
    matches = [line for line in lines if contains in line]
    if not matches:
        raise EvidenceError(f"required log marker missing: {contains}")
    return matches[-1]


def capture_live_goldi(mql_text: str, terminal_text: str) -> tuple[str, dict[str, object]]:
    mql_lines = mql_text.splitlines()
    marker = _last_line(mql_lines, "G17_E2E passed=true profile=GOLDI")
    lifecycle = _last_line(mql_lines, "G14_EXECUTION_LIFECYCLE passed=true")
    match = re.search(
        r"chain_id=(?P<chain>G17\|GOLDI\|\d+).*order_id=(?P<order>\d+) "
        r"position_id=(?P<position>\d+) events=6",
        marker,
    )
    if not match:
        raise EvidenceError("GOLDI live correlation fields are incomplete")
    if "positions_before=0 positions_after=0" not in lifecycle:
        raise EvidenceError("GOLDI live position boundary is not zero-to-zero")
    if "open_retcode=10009" not in lifecycle or "close_retcode=10009" not in lifecycle:
        raise EvidenceError("GOLDI live retcodes are incomplete")
    order_id = match.group("order")
    terminal_lines = terminal_text.splitlines()
    selected = [
        line
        for line in terminal_lines
        if any(
            token in line
            for token in (
                "authorized on XMGlobal-MT5 5",
                "trading has been enabled, demo account",
                f"order #{order_id} buy",
                "modify #" + order_id,
                "market sell 0.1 GOLD.i#, close #" + order_id,
                "accepted market sell 0.1 GOLD.i#, close #" + order_id,
            )
        )
    ]
    required = (
        "authorized on XMGlobal-MT5 5",
        "trading has been enabled, demo account",
        f"order #{order_id} buy",
        "modify #" + order_id,
        "market sell 0.1 GOLD.i#, close #" + order_id,
    )
    joined = "\n".join(selected)
    if missing := [token for token in required if token not in joined]:
        raise EvidenceError(f"GOLDI live broker chain incomplete: {missing}")
    block = joined + "\n" + lifecycle + "\n" + marker + "\n"
    return block, {
        "profile_id": "GOLDI",
        "account_login": 108098316,
        "account_mode": "DEMO",
        "server": "XMGlobal-MT5 5",
        "symbol": "GOLD.i#",
        "chain_id": match.group("chain"),
        "order_id": order_id,
        "position_id": match.group("position"),
        "event_count": 6,
        "positions_before": 0,
        "positions_after": 0,
        "order_authority": "DEMO_E2E_ONLY",
    }


def capture_tester_goldm(text: str) -> tuple[str, dict[str, object]]:
    lines = text.splitlines()
    marker_indexes = [
        index for index, line in enumerate(lines) if "G17_E2E passed=true profile=GOLDM" in line
    ]
    if not marker_indexes:
        raise EvidenceError("GOLDM tester G17 marker missing")
    marker_index = marker_indexes[-1]
    start = next(
        (
            index
            for index in range(marker_index, -1, -1)
            if "testing of Experts\\bot-ea\\GoldEngineExecutionLifecycleGoldmHarness.ex5"
            in lines[index]
            and "started" in lines[index]
        ),
        None,
    )
    end = next(
        (index for index in range(marker_index, len(lines)) if "connection closed" in lines[index]),
        None,
    )
    if start is None or end is None:
        raise EvidenceError("GOLDM tester run boundary incomplete")
    block = "\n".join(lines[start : end + 1]) + "\n"
    required = (
        "G17_E2E passed=true profile=GOLDM",
        "positions_before=0 positions_after=0",
        "open_retcode=10009",
        "modify_retcode=10009",
        "close_retcode=10009",
        "magic=26081912",
        "events=6",
        "OnTester result 1",
    )
    if missing := [token for token in required if token not in block]:
        raise EvidenceError(f"GOLDM tester chain incomplete: {missing}")
    chain = re.search(r"chain_id=(G17\|GOLDM\|\d+)", block)
    if not chain:
        raise EvidenceError("GOLDM chain ID missing")
    return block, {
        "profile_id": "GOLDM",
        "account_mode": "STRATEGY_TESTER",
        "server": "XMGlobal-MT5 14",
        "symbol": "GOLDm#",
        "chain_id": chain.group(1),
        "event_count": 6,
        "positions_before": 0,
        "positions_after": 0,
        "order_authority": "TESTER_ONLY",
    }


def write_evidence(block: str, metadata: dict[str, object], output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    stem = str(metadata["profile_id"]).lower() + "-e2e"
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
    parser = argparse.ArgumentParser(description="Capture G17 E2E evidence")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    live = subparsers.add_parser("goldi-live")
    live.add_argument("--mql-log", type=Path, required=True)
    live.add_argument("--terminal-log", type=Path, required=True)
    live.add_argument("--output", type=Path, required=True)
    tester = subparsers.add_parser("goldm-tester")
    tester.add_argument("--tester-log", type=Path, required=True)
    tester.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "goldi-live":
        block, metadata = capture_live_goldi(decode(args.mql_log), decode(args.terminal_log))
    else:
        block, metadata = capture_tester_goldm(decode(args.tester_log))
    print(json.dumps(write_evidence(block, metadata, args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
