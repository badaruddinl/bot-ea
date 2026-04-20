from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .polling_runtime import AIIntent, DecisionAction, RuntimeSnapshot


class CodexTimeoutError(RuntimeError):
    """Raised when `codex exec` exceeds the allowed decision timeout."""


class CodexContractError(RuntimeError):
    """Raised when `codex exec` returns text outside the required KEY=VALUE contract."""

    def __init__(self, message: str, *, raw_response: str | None = None) -> None:
        super().__init__(message)
        self.raw_response = raw_response


class CodexCLIEngine:
    """Subprocess adapter for `codex exec` using a plain-text response contract."""

    def __init__(
        self,
        *,
        executable: str = "codex",
        model: str | None = None,
        cwd: str | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        self.executable = executable
        self.model = model
        self.cwd = cwd
        self.timeout_seconds = timeout_seconds

    def decide(self, snapshot: RuntimeSnapshot) -> AIIntent:
        prompt = self._build_prompt(snapshot)
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "codex_last_message.txt"
            command = self._build_exec_command(prompt=prompt, output_file=output_file)
            try:
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    cwd=self.cwd,
                )
            except subprocess.TimeoutExpired as exc:
                raise CodexTimeoutError(f"codex exec timed out after {self.timeout_seconds} seconds") from exc
            except FileNotFoundError as exc:
                raise RuntimeError(f"codex executable not found: {self.executable}") from exc
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or "").strip()
                stdout = (exc.stdout or "").strip()
                detail = stderr or stdout or f"exit code {exc.returncode}"
                raise RuntimeError(f"codex exec failed: {self._shorten(detail)}") from exc
            response = output_file.read_text(encoding="utf-8").strip()
        return self.parse_response(response)

    def probe(self) -> str:
        try:
            result = subprocess.run(
                [self._resolve_executable(), "--version"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                cwd=self.cwd,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"codex --version timed out after {self.timeout_seconds} seconds") from exc
        except FileNotFoundError as exc:
            raise RuntimeError(f"codex executable not found: {self.executable}") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            detail = stderr or stdout or f"exit code {exc.returncode}"
            raise RuntimeError(f"codex probe failed: {self._shorten(detail)}") from exc
        return result.stdout.strip() or result.stderr.strip() or "codex-cli available"

    @staticmethod
    def parse_response(response: str) -> AIIntent:
        pairs = CodexCLIEngine._extract_pairs(response)

        action_raw = pairs.get("ACTION")
        if action_raw in {None, ""}:
            raise CodexContractError(
                f"codex response missing required keys ACTION: {CodexCLIEngine._shorten(response)}",
                raw_response=response,
            )
        try:
            action = DecisionAction(action_raw.strip().upper())
        except ValueError as exc:
            raise CodexContractError(
                f"codex response has invalid ACTION={pairs.get('ACTION')!r}: {CodexCLIEngine._shorten(response)}",
                raw_response=response,
            ) from exc

        required_keys = {"REASON"} if action in {DecisionAction.NO_TRADE, DecisionAction.HALT} else {"CONFIDENCE", "REASON"}
        missing_keys = sorted(required_keys.difference({key for key, value in pairs.items() if value not in {None, ""}}))
        if missing_keys:
            raise CodexContractError(
                f"codex response missing required keys {', '.join(missing_keys)}: {CodexCLIEngine._shorten(response)}",
                raw_response=response,
            )

        side_token = pairs.get("SIDE") or pairs.get("DIRECTION") or ("none" if action in {DecisionAction.NO_TRADE, DecisionAction.HALT} else "")
        side_raw = side_token.lower()
        side_value = side_raw or None
        if side_value == "none":
            side_value = None
        elif side_value not in {"buy", "sell"}:
            raise CodexContractError(
                f"codex response has invalid SIDE={pairs.get('SIDE')!r}: {CodexCLIEngine._shorten(response)}",
                raw_response=response,
            )
        confidence_raw = pairs.get("CONFIDENCE")
        stop_raw = pairs.get("STOP_DISTANCE_POINTS")

        try:
            if action in {DecisionAction.NO_TRADE, DecisionAction.HALT} and confidence_raw in {None, "", "none"}:
                confidence = 0.0
            else:
                confidence = float(confidence_raw) if confidence_raw not in {None, "", "none"} else None
        except ValueError as exc:
            raise CodexContractError(
                f"codex response has invalid CONFIDENCE={confidence_raw!r}: {CodexCLIEngine._shorten(response)}",
                raw_response=response,
            ) from exc
        if confidence is not None and not (0.0 <= confidence <= 1.0):
            raise CodexContractError(
                f"codex response has out-of-range CONFIDENCE={confidence_raw!r}: {CodexCLIEngine._shorten(response)}",
                raw_response=response,
            )

        try:
            stop_distance_points = float(stop_raw) if stop_raw not in {None, "", "none", "NONE"} else None
        except ValueError as exc:
            raise CodexContractError(
                f"codex response has invalid STOP_DISTANCE_POINTS={stop_raw!r}: {CodexCLIEngine._shorten(response)}",
                raw_response=response,
            ) from exc
        if action not in {DecisionAction.NO_TRADE, DecisionAction.HALT} and stop_distance_points is None:
            raise CodexContractError(
                f"codex response missing required STOP_DISTANCE_POINTS for ACTION={action.value}: {CodexCLIEngine._shorten(response)}",
                raw_response=response,
            )

        return AIIntent(
            action=action,
            side=side_value,
            confidence=confidence,
            reason=pairs.get("REASON"),
            stop_distance_points=stop_distance_points,
            payload={"raw_response": response},
        )

    @staticmethod
    def _extract_pairs(response: str) -> dict[str, str]:
        normalized = str(response or "").strip()
        if not normalized:
            return {}

        # Support both the documented multi-line contract and the single-line
        # fallback shape sometimes returned by the CLI.
        matches = list(re.finditer(r"(?<!\S)([A-Z_]+)=", normalized))
        if not matches:
            return {}

        pairs: dict[str, str] = {}
        for index, match in enumerate(matches):
            key = match.group(1).strip().upper()
            value_start = match.end()
            value_end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
            value = normalized[value_start:value_end].strip()
            pairs[key] = value
        return pairs

    def _build_exec_command(self, *, prompt: str, output_file: Path) -> list[str]:
        command = [
            self._resolve_executable(),
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--output-last-message",
            str(output_file),
        ]
        if self.cwd:
            command.extend(["-C", self.cwd])
        if self.model:
            command.extend(["-m", self.model])
        command.append(prompt)
        return command

    def _resolve_executable(self) -> str:
        candidate = self.executable.strip()
        if not candidate:
            raise RuntimeError("codex executable is empty")
        if os.name != "nt":
            return candidate

        expanded = os.path.expandvars(candidate)
        if os.path.isabs(expanded) or os.path.sep in expanded or "/" in expanded:
            return candidate

        for name in (f"{candidate}.cmd", f"{candidate}.exe", candidate):
            resolved = shutil.which(name)
            if resolved:
                return resolved
        return candidate

    @staticmethod
    def _shorten(message: str, *, limit: int = 220) -> str:
        normalized = " ".join(str(message).split())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[: limit - 3]}..."

    @staticmethod
    def _build_prompt(snapshot: RuntimeSnapshot) -> str:
        return (
            "You are the decision brain for an MT5 trading bot. "
            "Return only KEY=VALUE pairs for ACTION, SIDE, CONFIDENCE, STOP_DISTANCE_POINTS, and REASON. "
            "No markdown. No explanation. No questions. "
            "ACTION must be one of NO_TRADE, OPEN, ADD, REDUCE, CLOSE, CANCEL_PENDING, HALT. "
            "SIDE must be buy, sell, or none. "
            "STOP_DISTANCE_POINTS may be none for NO_TRADE or HALT. "
            "For NO_TRADE or HALT, you may omit STOP_DISTANCE_POINTS or set it to none. "
            "If uncertain, return ACTION=NO_TRADE SIDE=none CONFIDENCE=0.0 STOP_DISTANCE_POINTS=none REASON=insufficient_data.\n\n"
            f"SYMBOL={snapshot.symbol}\n"
            f"TIMEFRAME={snapshot.timeframe}\n"
            f"BID={snapshot.bid}\n"
            f"ASK={snapshot.ask}\n"
            f"SPREAD_POINTS={snapshot.spread_points}\n"
            f"SESSION_STATE={snapshot.session_state}\n"
            f"NEWS_STATE={snapshot.news_state}\n"
            f"TRADING_STYLE={snapshot.trading_style.value}\n"
            f"EQUITY={snapshot.account.equity}\n"
            f"FREE_MARGIN={snapshot.account.free_margin}\n"
            f"STOP_DISTANCE_POINTS_DEFAULT={snapshot.stop_distance_points}\n"
            f"ALLOCATION_MODE={snapshot.capital_allocation.mode.value if snapshot.capital_allocation else 'full_equity'}\n"
            f"ALLOCATION_VALUE={snapshot.capital_allocation.value if snapshot.capital_allocation else snapshot.account.equity}\n"
            f"CONTEXT={snapshot.context}\n"
        )
