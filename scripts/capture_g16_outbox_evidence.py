from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


class EvidenceError(RuntimeError):
    pass


def decode(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def capture(text: str, *, symbol: str, server: str) -> str:
    expert = "Experts\\bot-ea\\GoldEngineOutboxHarness.ex5"
    start_marker = f"{symbol},M15: testing of {expert}"
    server_marker = f"{symbol},M15 ({server}):"
    lines = text.splitlines()
    starts = [
        index for index, line in enumerate(lines) if start_marker in line and "started" in line
    ]
    if not starts:
        raise EvidenceError("G16 outbox start marker missing")
    start = starts[-1]
    server_starts = [
        index for index, line in enumerate(lines[: start + 1]) if server_marker in line
    ]
    if not server_starts:
        raise EvidenceError("G16 server marker missing")
    end = next(
        (index for index in range(start, len(lines)) if "connection closed" in lines[index]),
        None,
    )
    if end is None:
        raise EvidenceError("G16 run boundary missing")
    return "\n".join(lines[server_starts[-1] : end + 1]) + "\n"


def validate(block: str) -> None:
    required = (
        "G16_OUTBOX passed=true goldi_append=true goldm_append=true",
        "goldi_audience=goldi_approved goldm_audience=admin_only",
        "order_authority=DISABLED",
        "final balance 100.00 USD",
        "OnTester result 1",
    )
    missing = [item for item in required if item not in block]
    if missing:
        raise EvidenceError(f"G16 proof incomplete: {missing}")
    folded = block.casefold()
    forbidden = ["passed=false", "order placed", "deal performed", "ctrade::ordersend"]
    if present := [item for item in forbidden if item in folded]:
        raise EvidenceError(f"G16 proof contains mutation/failure: {present}")


def write_evidence(source: Path, output: Path, *, symbol: str, server: str) -> dict[str, str]:
    block = capture(decode(source), symbol=symbol, server=server)
    validate(block)
    output.mkdir(parents=True, exist_ok=True)
    log_path = output / "goldi-outbox-tester.log"
    raw = block.encode()
    log_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    log_path.with_suffix(".sha256").write_text(f"{digest}  {log_path.name}\n", encoding="ascii")
    metadata = {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "captured_log": log_path.name,
        "captured_log_sha256": digest,
        "order_authority": "DISABLED",
        "profile_matrix": "GOLDI,GOLDM",
        "server": server,
        "symbol": symbol,
    }
    (output / "goldi-outbox-tester.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture G16 native outbox proof")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--server", default="XMGlobal-MT5 5")
    args = parser.parse_args()
    print(
        json.dumps(write_evidence(args.source, args.output, symbol=args.symbol, server=args.server))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
