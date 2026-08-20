from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


class Mql5BuildError(ValueError):
    """Raised when a compiled G11 artifact is missing or not warning-clean."""


@dataclass(frozen=True, slots=True)
class Mql5CompileArtifact:
    profile_id: str
    source_sha256: str
    binary_sha256: str
    compile_log_sha256: str
    binary_size: int
    compile_result: str

    def to_payload(self) -> dict[str, object]:
        return {
            "binary_sha256": self.binary_sha256,
            "binary_size": self.binary_size,
            "compile_log_sha256": self.compile_log_sha256,
            "compile_result": self.compile_result,
            "profile_id": self.profile_id,
            "source_sha256": self.source_sha256,
        }


def verify_g11_compile_artifacts(
    repository_root: Path,
    evidence_root: Path,
) -> tuple[Mql5CompileArtifact, ...]:
    artifacts: list[Mql5CompileArtifact] = []
    for profile_id, stem in (
        ("GOLDI", "GoldEngine-GOLDi"),
        ("GOLDM", "GoldEngine-GOLDm"),
    ):
        source_path = repository_root / "mt5" / "Experts" / "bot-ea" / f"{stem}.mq5"
        binary_path = source_path.with_suffix(".ex5")
        log_path = evidence_root / f"{stem}.compile.log"
        for label, path in (
            ("source", source_path),
            ("binary", binary_path),
            ("compile log", log_path),
        ):
            if not path.is_file():
                raise Mql5BuildError(f"{profile_id} {label} is missing: {path}")
        log_text = _decode_log(log_path)
        result_lines = [
            line.strip() for line in log_text.splitlines() if line.startswith("Result:")
        ]
        if len(result_lines) != 1 or not result_lines[0].startswith("Result: 0 errors, 0 warnings"):
            raise Mql5BuildError(
                f"{profile_id} compile is not clean: {result_lines or ['missing Result']}"
            )
        binary_size = binary_path.stat().st_size
        if binary_size < 1024:
            raise Mql5BuildError(f"{profile_id} binary is unexpectedly small")
        artifacts.append(
            Mql5CompileArtifact(
                profile_id=profile_id,
                source_sha256=_sha256(source_path),
                binary_sha256=_sha256(binary_path),
                compile_log_sha256=_sha256(log_path),
                binary_size=binary_size,
                compile_result="Result: 0 errors, 0 warnings",
            )
        )
    if artifacts[0].binary_sha256 == artifacts[1].binary_sha256:
        raise Mql5BuildError("profile-locked binaries unexpectedly share one hash")
    return tuple(artifacts)


def _decode_log(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeError:
            continue
    raise Mql5BuildError(f"compile log encoding is unsupported: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
