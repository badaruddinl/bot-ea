from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


class EvidenceError(RuntimeError):
    """Raised when a tester log cannot prove complete G13 native parity."""


def _decode(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise EvidenceError(f"unsupported tester log encoding: {path}")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def capture_block(text: str, *, symbol: str, timeframe: str, server: str) -> str:
    expert = "Experts\\bot-ea\\GoldEngineBearParityHarness.ex5"
    core_marker = f"{symbol},{timeframe}: testing of {expert}"
    server_marker = f"{symbol},{timeframe} ({server}): testing of {expert}"
    lines = text.splitlines()
    core_starts = [
        index for index, line in enumerate(lines) if core_marker in line and " started" in line
    ]
    if not core_starts:
        raise EvidenceError("native G13 core start marker is missing")
    core_start = core_starts[-1]
    server_starts = [
        index for index, line in enumerate(lines[: core_start + 1]) if server_marker in line
    ]
    if not server_starts:
        raise EvidenceError("native G13 server marker is missing")
    end = next(
        (index for index in range(core_start, len(lines)) if "connection closed" in lines[index]),
        None,
    )
    if end is None:
        raise EvidenceError("native G13 run has no connection-closed boundary")
    return "\n".join(lines[server_starts[-1] : end + 1]) + "\n"


def validate_block(block: str, *, symbol: str, timeframe: str, server: str) -> None:
    marker = (
        f"G13_BEAR_PARITY profile={symbol} passed=true "
        "h1_m5_m1=true incremental=true m15=true h1_reject=true "
        "m5_acceptance=true restart_expiry=true persistence=true"
    )
    required = (
        f"{symbol},{timeframe} ({server}): testing of ",
        marker,
        "final balance 100.00 USD",
        "OnTester result 1",
        f"{symbol},{timeframe}: 1 ticks, 1 bars generated.",
    )
    missing = [item for item in required if item not in block]
    if missing:
        raise EvidenceError(f"native G13 proof is incomplete: {missing}")
    forbidden = (
        "passed=false",
        "OnTester result 0",
        "cannot get history",
        "order placed",
        "deal performed",
    )
    present = [item for item in forbidden if item in block]
    if present:
        raise EvidenceError(f"native G13 proof contains failure/mutation: {present}")


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
    block = capture_block(_decode(source), symbol=symbol, timeframe=timeframe, server=server)
    validate_block(block, symbol=symbol, timeframe=timeframe, server=server)
    output_directory.mkdir(parents=True, exist_ok=True)
    stem = profile_id.lower()
    log_path = output_directory / f"{stem}-bear-strategy-tester.log"
    block_raw = block.encode("utf-8")
    log_path.write_bytes(block_raw)
    digest = _sha256(block_raw)
    (output_directory / f"{stem}-bear-strategy-tester.sha256").write_text(
        f"{digest}  {log_path.name}\n",
        encoding="ascii",
    )
    metadata: dict[str, object] = {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "captured_log": log_path.name,
        "captured_log_sha256": digest,
        "profile_id": profile_id,
        "real_order_authority": "DISABLED",
        "server": server,
        "source_log": str(source.resolve()),
        "source_log_sha256": _sha256(source_raw),
        "symbol": symbol,
        "timeframe": timeframe,
    }
    (output_directory / f"{stem}-bear-strategy-tester.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture native G13 Strategy Tester proof")
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
        server=args.server,
        timeframe=args.timeframe,
    )
    print(json.dumps(metadata, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
