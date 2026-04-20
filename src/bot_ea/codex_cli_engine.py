from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .polling_runtime import AIIntent, DecisionAction, RuntimeSnapshot


class CodexCLIEngine:
    """Subprocess adapter for `codex exec` using a plain-text response contract."""

    def __init__(
        self,
        *,
        executable: str = "codex",
        model: str | None = None,
        cwd: str | None = None,
        timeout_seconds: int = 20,
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
            response = output_file.read_text(encoding="utf-8").strip()
        return self.parse_response(response)

    def probe(self) -> str:
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
        return result.stdout.strip() or result.stderr.strip() or "codex-cli available"

    @staticmethod
    def parse_response(response: str) -> AIIntent:
        lines = [line.strip() for line in response.splitlines() if line.strip()]
        pairs: dict[str, str] = {}
        for line in lines:
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            pairs[key.strip().upper()] = value.strip()

        action = DecisionAction(pairs.get("ACTION", "NO_TRADE"))
        side_value = pairs.get("SIDE", "").lower() or None
        if side_value == "none":
            side_value = None
        confidence_raw = pairs.get("CONFIDENCE")
        stop_raw = pairs.get("STOP_DISTANCE_POINTS")

        return AIIntent(
            action=action,
            side=side_value,
            confidence=float(confidence_raw) if confidence_raw not in {None, "", "none"} else None,
            reason=pairs.get("REASON"),
            stop_distance_points=float(stop_raw) if stop_raw not in {None, "", "none"} else None,
            payload={"raw_response": response},
        )

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
    def _build_prompt(snapshot: RuntimeSnapshot) -> str:
        return (
            "You are the decision brain for an MT5 trading bot. "
            "Respond with exactly these lines and no extra text:\n"
            "ACTION=<NO_TRADE|OPEN|ADD|REDUCE|CLOSE|CANCEL_PENDING|HALT>\n"
            "SIDE=<buy|sell|none>\n"
            "CONFIDENCE=<0.0-1.0 or none>\n"
            "STOP_DISTANCE_POINTS=<number or none>\n"
            "REASON=<one short sentence>\n\n"
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
