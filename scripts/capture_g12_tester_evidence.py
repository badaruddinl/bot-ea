from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


class EvidenceError(RuntimeError):
    """Raised when a tester log cannot prove the expected native parity run."""


def _decode_log(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    if raw.count(b"\x00") >= max(1, len(raw) // 8):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    raise EvidenceError(f"unsupported tester log encoding: {path}")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def capture_block(text: str, *, symbol: str, timeframe: str, server: str) -> str:
    start_marker = (
        f"{symbol},{timeframe}: testing of Experts\\bot-ea\\GoldEngineRevisedParityHarness.ex5"
    )
    lines = text.splitlines()
    starts = [
        index for index, line in enumerate(lines) if start_marker in line and " started" in line
    ]
    if not starts:
        raise EvidenceError(f"native tester start marker not found for {symbol},{timeframe}")
    core_start = starts[-1]
    server_marker = f"{symbol},{timeframe} ({server}): testing of "
    server_starts = [
        index
        for index, line in enumerate(lines[: core_start + 1])
        if server_marker in line and "Experts\\bot-ea\\GoldEngineRevisedParityHarness.ex5" in line
    ]
    if not server_starts:
        raise EvidenceError(f"native tester server marker not found for {server}")
    start = server_starts[-1]
    end = next(
        (index for index in range(start, len(lines)) if "connection closed" in lines[index]),
        None,
    )
    if end is None:
        raise EvidenceError("native tester run has no terminal connection-closed boundary")
    return "\n".join(lines[start : end + 1]) + "\n"


def validate_block(block: str, *, symbol: str, timeframe: str, server: str) -> None:
    parity = (
        f"G12_REVISED_PARITY profile={symbol} passed=true "
        "range=true sell_range=true no_setup=true obstacle=true momentum=true "
        "setup=true reinforcement_restart=true consume_restart=true "
        "expiry_restart=true opposite_restart=true"
    )
    required = (
        f"{symbol},{timeframe} ({server}): testing of ",
        parity,
        "final balance 100.00 USD",
        "OnTester result 1",
        f"{symbol},{timeframe}: 1 ticks, 1 bars generated.",
    )
    missing = [item for item in required if item not in block]
    if missing:
        raise EvidenceError(f"native tester proof is incomplete: {missing}")
    forbidden = (
        "passed=false",
        "OnTester result 0",
        "cannot get history",
        "order placed",
        "deal performed",
    )
    present = [item for item in forbidden if item in block]
    if present:
        raise EvidenceError(f"native tester proof contains a failure or mutation: {present}")


def write_evidence(
    *,
    source: Path,
    output_directory: Path,
    profile_id: str,
    symbol: str,
    timeframe: str,
    server: str,
) -> dict[str, object]:
    source_raw = source.read_bytes()
    block = capture_block(
        _decode_log(source),
        symbol=symbol,
        timeframe=timeframe,
        server=server,
    )
    validate_block(block, symbol=symbol, timeframe=timeframe, server=server)
    output_directory.mkdir(parents=True, exist_ok=True)
    stem = profile_id.lower()
    log_path = output_directory / f"{stem}-strategy-tester.log"
    block_raw = block.encode("utf-8")
    log_path.write_bytes(block_raw)
    log_digest = _sha256(block_raw)
    (output_directory / f"{stem}-strategy-tester.sha256").write_text(
        f"{log_digest}  {log_path.name}\n",
        encoding="ascii",
    )
    metadata: dict[str, object] = {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "captured_log": log_path.name,
        "captured_log_sha256": log_digest,
        "profile_id": profile_id,
        "real_order_authority": "DISABLED",
        "server": server,
        "source_log": str(source.resolve()),
        "source_log_sha256": _sha256(source_raw),
        "symbol": symbol,
        "timeframe": timeframe,
    }
    metadata_path = output_directory / f"{stem}-strategy-tester.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--profile-id", choices=("GOLDI", "GOLDM"), required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--timeframe", default="M15")
    args = parser.parse_args()
    metadata = write_evidence(
        source=args.source,
        output_directory=args.output_directory,
        profile_id=args.profile_id,
        symbol=args.symbol,
        timeframe=args.timeframe,
        server=args.server,
    )
    print(json.dumps(metadata, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
