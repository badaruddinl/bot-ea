from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PROFILES = ("GOLDI", "GOLDM")


@dataclass(frozen=True, slots=True)
class EntrySession:
    profile_id: str
    profile_fingerprint: str
    account_login: int
    session_id: str
    authority_enabled: bool


@dataclass(frozen=True, slots=True)
class EntryGateStatus:
    profile_id: str
    available: bool
    enabled: bool
    authority_enabled: bool
    session_id: str | None
    reason: str


class EntryGateController:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def status(self, profile_id: str) -> EntryGateStatus:
        profile = self._profile(profile_id)
        try:
            session = self._read_session(profile)
        except (OSError, ValueError) as exc:
            return EntryGateStatus(profile, False, False, False, None, str(exc))
        if session is None:
            return EntryGateStatus(profile, False, False, False, None, "SESSION_MISSING")
        if not session.authority_enabled:
            return EntryGateStatus(
                profile,
                True,
                False,
                False,
                session.session_id,
                "ORDER_AUTHORITY_DISABLED",
            )
        enabled = self._matching_command_enabled(session)
        return EntryGateStatus(
            profile,
            True,
            enabled,
            True,
            session.session_id,
            "ENABLED" if enabled else "DISABLED",
        )

    def set_enabled(self, profile_id: str, enabled: bool, *, actor_id: str) -> EntryGateStatus:
        profile = self._profile(profile_id)
        session = self._read_session(profile)
        if session is None:
            raise RuntimeError(f"{profile} entry session is not available")
        if not session.authority_enabled:
            raise RuntimeError(f"{profile} order authority is disabled")
        actor = str(actor_id).strip()
        if not actor.isascii() or not actor.isdecimal() or int(actor) <= 0:
            raise ValueError("entry gate actor must be a positive private chat ID")
        state = "ENABLED" if enabled else "DISABLED"
        payload = "|".join(
            (
                "1",
                profile,
                session.profile_fingerprint,
                str(session.account_login),
                session.session_id,
                state,
                actor,
                datetime.now(UTC).isoformat(),
            )
        )
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._command_path(profile)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(payload + "\n", encoding="ascii")
        os.replace(temporary, path)
        return self.status(profile)

    def _read_session(self, profile: str) -> EntrySession | None:
        path = self._session_path(profile)
        if not path.exists():
            return None
        parts = path.read_text(encoding="ascii").strip().split("|")
        if len(parts) != 6 or parts[0] != "1" or parts[1] != profile:
            raise ValueError("ENTRY_SESSION_INVALID")
        fingerprint = parts[2]
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise ValueError("ENTRY_SESSION_FINGERPRINT_INVALID")
        login = int(parts[3])
        if login <= 0 or not parts[4]:
            raise ValueError("ENTRY_SESSION_IDENTITY_INVALID")
        if parts[5] not in {"ENABLED", "DISABLED"}:
            raise ValueError("ENTRY_SESSION_AUTHORITY_INVALID")
        return EntrySession(profile, fingerprint, login, parts[4], parts[5] == "ENABLED")

    def _matching_command_enabled(self, session: EntrySession) -> bool:
        path = self._command_path(session.profile_id)
        if not path.exists():
            return False
        try:
            parts = path.read_text(encoding="ascii").strip().split("|")
        except (OSError, UnicodeError):
            return False
        return bool(
            len(parts) == 8
            and parts[0] == "1"
            and parts[1] == session.profile_id
            and parts[2] == session.profile_fingerprint
            and parts[3] == str(session.account_login)
            and parts[4] == session.session_id
            and parts[5] == "ENABLED"
        )

    def _session_path(self, profile: str) -> Path:
        return self.root / f"{profile}.entry-session"

    def _command_path(self, profile: str) -> Path:
        return self.root / f"{profile}.entry-gate"

    @staticmethod
    def _profile(profile_id: str) -> str:
        profile = str(profile_id).strip().upper()
        if profile not in PROFILES:
            raise ValueError(f"unsupported entry gate profile: {profile_id}")
        return profile
