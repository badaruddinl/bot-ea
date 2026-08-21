from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from gold_engine_core import verify_g11_compile_artifacts  # noqa: E402


class G12CompileError(RuntimeError):
    """Raised when native G12 compile artifacts are incomplete or unsafe."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_log(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise G12CompileError(f"unsupported compile-log encoding: {path}")


def verify_harness(evidence_root: Path) -> dict[str, object]:
    source = REPOSITORY_ROOT / "mt5" / "Experts" / "bot-ea" / "GoldEngineRevisedParityHarness.mq5"
    binary = source.with_suffix(".ex5")
    compile_log = evidence_root / "GoldEngineRevisedParityHarness.compile.log"
    for label, path in (("source", source), ("binary", binary), ("compile log", compile_log)):
        if not path.is_file():
            raise G12CompileError(f"harness {label} is missing: {path}")
    result_lines = [
        line.strip() for line in decode_log(compile_log).splitlines() if line.startswith("Result:")
    ]
    if len(result_lines) != 1 or not result_lines[0].startswith("Result: 0 errors, 0 warnings"):
        raise G12CompileError(f"harness compile is not clean: {result_lines}")
    source_text = source.read_text(encoding="utf-8")
    forbidden = ("OrderSend", "CTrade", "trade.mqh", "WebRequest")
    present = [token for token in forbidden if token.casefold() in source_text.casefold()]
    if present:
        raise G12CompileError(f"parity harness contains mutation/network authority: {present}")
    if binary.stat().st_size < 1024:
        raise G12CompileError("harness binary is unexpectedly small")
    return {
        "binary_sha256": sha256_file(binary),
        "binary_size": binary.stat().st_size,
        "compile_log_sha256": sha256_file(compile_log),
        "compile_result": "Result: 0 errors, 0 warnings",
        "source_sha256": sha256_file(source),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify warning-clean native G12 artifacts")
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metaeditor-build", type=int, required=True)
    args = parser.parse_args()
    profiles = verify_g11_compile_artifacts(REPOSITORY_ROOT, args.evidence_root)
    payload = {
        "gate": "G12",
        "harness": verify_harness(args.evidence_root),
        "metaeditor_build": args.metaeditor_build,
        "production_real_orders": "DISABLED",
        "profiles": [artifact.to_payload() for artifact in profiles],
        "status": "COMPILE_PASS",
    }
    raw = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    args.output.with_suffix(".sha256").write_text(
        f"{digest}  {args.output.name}\n",
        encoding="ascii",
    )
    print(f"status=COMPILE_PASS profiles={len(profiles)} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
