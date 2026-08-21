from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


class EvidenceError(RuntimeError):
    """Raised when a tester log cannot prove the native G14 guard matrix."""


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
    expert = "Experts\\bot-ea\\GoldEngineExecutionGuardHarness.ex5"
    core_marker = f"{symbol},{timeframe}: testing of {expert}"
    server_marker = f"{symbol},{timeframe} ({server}):"
    lines = text.splitlines()
    starts = [
        index for index, line in enumerate(lines) if core_marker in line and " started" in line
    ]
    if not starts:
        raise EvidenceError("native G14 guard core start marker is missing")
    core_start = starts[-1]
    server_starts = [
        index for index, line in enumerate(lines[: core_start + 1]) if server_marker in line
    ]
    if not server_starts:
        raise EvidenceError("native G14 guard server marker is missing")
    end = next(
        (index for index in range(core_start, len(lines)) if "connection closed" in lines[index]),
        None,
    )
    if end is None:
        raise EvidenceError("native G14 guard run has no connection-closed boundary")
    return "\n".join(lines[server_starts[-1] : end + 1]) + "\n"


def validate_block(block: str, *, symbol: str, timeframe: str, server: str) -> None:
    required = (
        f"{symbol},{timeframe} ({server}):",
        "G14_EXECUTION_GUARD passed=true goldi=true goldm=true ",
        "structural_geometry=true reasons=18 order_authority=DISABLED",
        "final balance 100.00 USD",
        "OnTester result 1",
    )
    missing = [item for item in required if item not in block]
    if missing:
        raise EvidenceError(f"native G14 guard proof is incomplete: {missing}")
    forbidden = (
        "passed=false",
        "OnTester result 0",
        "order placed",
        "deal performed",
        "buy market",
        "sell market",
    )
    folded = block.casefold()
    present = [item for item in forbidden if item.casefold() in folded]
    if present:
        raise EvidenceError(f"native G14 guard proof contains mutation/failure: {present}")


def write_evidence(
    *, source: Path, output_directory: Path, symbol: str, timeframe: str, server: str
) -> dict[str, object]:
    source_raw = source.read_bytes()
    block = capture_block(_decode(source), symbol=symbol, timeframe=timeframe, server=server)
    validate_block(block, symbol=symbol, timeframe=timeframe, server=server)
    output_directory.mkdir(parents=True, exist_ok=True)
    log_path = output_directory / "goldi-execution-guard-tester.log"
    log_raw = block.encode("utf-8")
    log_path.write_bytes(log_raw)
    digest = _sha256(log_raw)
    log_path.with_suffix(".sha256").write_text(f"{digest}  {log_path.name}\n", encoding="ascii")
    metadata: dict[str, object] = {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "captured_log": log_path.name,
        "captured_log_sha256": digest,
        "order_authority": "DISABLED",
        "profile_matrix": ["GOLDI", "GOLDM"],
        "server": server,
        "source_log": str(source.resolve()),
        "source_log_sha256": _sha256(source_raw),
        "symbol": symbol,
        "timeframe": timeframe,
    }
    (output_directory / "goldi-execution-guard-tester.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture native G14 guard proof")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--symbol", default="GOLD.i#")
    parser.add_argument("--timeframe", default="M15")
    parser.add_argument("--server", default="XMGlobal-MT5 5")
    args = parser.parse_args()
    metadata = write_evidence(
        source=args.source,
        output_directory=args.output_directory,
        symbol=args.symbol,
        timeframe=args.timeframe,
        server=args.server,
    )
    print(json.dumps(metadata, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
