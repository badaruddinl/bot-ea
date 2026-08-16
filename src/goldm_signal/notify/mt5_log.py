from __future__ import annotations

import base64
import binascii
import codecs
import glob
import hashlib
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterable

from ..config import gold_i_profile
from ..storage.database import Mt5SetupIdentityError, SignalStore
from ..strategy.state_machine import SetupRecord, SetupState


_EVENT_RE = re.compile(
    r"\b(?P<event>SNIPER_(?:EARLY_CANDIDATE|EARLY_PROMOTED|SIGNAL|EARLY_CANCELLED|OUTCOME))\b(?P<body>.*)"
)
_SETUP_ID_RE = re.compile(r"\bid=(?P<setup_id>.+?)\s+status=")
_FIELD_RE = re.compile(r"(?P<key>[A-Za-z][A-Za-z0-9_]*)=(?P<value>\S+)")
_ID_PARTS_RE = re.compile(
    r"^(?P<symbol>.+)-(?P<side>BUY|SELL)-(?P<level>-?\d+(?:\.\d+)?)-"
    r"(?P<date>\d{4}\.\d{2}\.\d{2}) (?P<time>\d{2}:\d{2})$"
)
_ACCOUNT_LOGIN_RE = re.compile(r"[1-9][0-9]{0,19}\Z")
_SERVER_B64_RE = re.compile(r"[A-Za-z0-9_-]{1,684}\Z")
_SECURITY_METADATA_FIELDS = frozenset(
    {
        "id",
        "runId",
        "strategy",
        "strategyVersion",
        "directionProfile",
        "setupUtcEpoch",
        "generatedUtcEpoch",
        "validUntilUtcEpoch",
        "accountScope",
        "accountLogin",
        "originServerB64",
    }
)
_CURSOR_ANCHOR_BYTES = 4096


@dataclass(frozen=True)
class ParsedMt5Event:
    event_type: str
    setup_id: str
    symbol: str
    side: str
    level: float
    occurred_at: datetime
    generated_at: datetime
    fields: dict[str, str]
    raw_text: str

    @property
    def telegram_text(self) -> str:
        return _format_telegram_text(self)


class Mt5LogBridge:
    """Tail MT5 Expert logs and persist sniper events in the notification outbox."""

    def __init__(
        self,
        store: SignalStore,
        *,
        log_paths: Iterable[str | Path] | None = None,
        log_directories: Iterable[str | Path] | None = None,
        required_run_id: str | None = None,
        expected_symbol: str | None = None,
        account_context_provider: Callable[[], Mapping[str, Any]] | None = None,
        appdata: str | Path | None = None,
        server_utc_offset_minutes: int | None = None,
    ) -> None:
        self._store = store
        if log_paths is not None and log_directories is not None:
            raise ValueError("log_paths and log_directories are mutually exclusive")
        self._log_paths = (
            tuple(Path(path) for path in log_paths) if log_paths is not None else None
        )
        self._log_directories = (
            tuple(Path(path).resolve(strict=True) for path in log_directories)
            if log_directories is not None
            else None
        )
        normalized_run_id = str(required_run_id or "").strip()
        if normalized_run_id and (
            normalized_run_id.upper() == "UNSET"
            or re.fullmatch(r"[A-Za-z0-9._-]{8,96}", normalized_run_id) is None
        ):
            raise ValueError("required_run_id must be an explicit safe 8-96 character token")
        self._required_run_id = normalized_run_id or None
        normalized_symbol = str(expected_symbol or "").strip()
        if normalized_symbol and normalized_symbol != gold_i_profile().symbol:
            raise ValueError("expected_symbol must be the canonical GOLD.i# symbol")
        self._expected_symbol = normalized_symbol or None
        self._account_context_provider = account_context_provider
        self._appdata = Path(appdata) if appdata else None
        configured_offset = os.environ.get("MT5_SERVER_UTC_OFFSET_MINUTES", "0")
        self._server_utc_offset_minutes = (
            int(configured_offset)
            if server_utc_offset_minutes is None
            else int(server_utc_offset_minutes)
        )

    def run_once(self) -> tuple[int, int, int]:
        files = 0
        lines = 0
        enqueued = 0
        matched_events = 0
        mismatched_events = 0
        should_probe_account = (
            self._required_run_id is not None
            or self._account_context_provider is not None
        )
        current_account, current_account_errors = self._load_current_account_context(
            required=should_probe_account
        )
        current_probe_failed = bool(current_account_errors)
        provider_failures = int(current_probe_failed)
        last_session_observation: str | None = None
        last_account_context_result: str | None = (
            "failure" if current_probe_failed else "ok" if should_probe_account else None
        )
        paths = self.discover_log_paths()
        for path in paths:
            files += 1
            (
                parsed_lines,
                added,
                matched,
                mismatched,
                probe_failures,
                path_session_observation,
                path_account_result,
            ) = self._consume(
                path,
                current_account=current_account,
                current_account_errors=current_account_errors,
            )
            lines += parsed_lines
            enqueued += added
            matched_events += matched
            mismatched_events += mismatched
            if not current_probe_failed:
                provider_failures += probe_failures
            if path_session_observation is not None:
                last_session_observation = path_session_observation
            if path_account_result == "failure":
                last_account_context_result = "failure"
            elif (
                path_account_result == "ok"
                and last_account_context_result is None
            ):
                last_account_context_result = "ok"
        self._store.record_mt5_bridge_health(
            session_fingerprint=(
                hashlib.sha256(self._required_run_id.encode("utf-8")).hexdigest()
                if self._required_run_id is not None
                else None
            ),
            files_discovered=files,
            tracked_cursors=sum(
                self._store.mt5_log_cursor(path) is not None for path in paths
            ),
            matched_events=matched_events,
            mismatched_events=mismatched_events,
            provider_failures=provider_failures,
            last_session_observation=last_session_observation,
            last_account_context_result=last_account_context_result,
        )
        return files, lines, enqueued

    def discover_log_paths(self) -> list[Path]:
        if self._log_paths is not None:
            return sorted(
                (path.resolve(strict=True) for path in self._log_paths if path.is_file()),
                key=_log_path_sort_key,
            )

        if self._log_directories is not None:
            candidates: list[Path] = []
            for directory in self._log_directories:
                if not directory.is_dir():
                    continue
                candidates.extend(
                    path.resolve(strict=True)
                    for path in directory.glob("*.log")
                    if path.is_file()
                )
            return sorted(candidates, key=_log_path_sort_key)

        appdata = self._appdata or Path(os.environ.get("APPDATA", ""))
        if not str(appdata):
            return []
        pattern = str(appdata / "MetaQuotes" / "Terminal" / "*" / "MQL5" / "Logs" / "*.log")
        candidates = [Path(value) for value in glob.glob(pattern)]

        # Every exact-directory log has its own durable byte cursor. Reading all
        # files in chronological order is required across midnight: an OUTCOME
        # appended to yesterday's file must not be skipped merely because a new
        # daily file already exists.
        return sorted(candidates, key=_log_path_sort_key)

    def enqueue_debug_notification(self, *, now: datetime | None = None) -> bool:
        timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        setup_id = f"DEBUG-BUY-0-{timestamp:%Y.%m.%d %H:%M:%S.%f}"
        self._store.save_setup(
            SetupRecord(
                setup_id=setup_id,
                symbol="DEBUG",
                side="BUY",
                level=0.0,
                breakout_at=timestamp,
                state=SetupState.EARLY_CANDIDATE,
                reason="Telegram bridge diagnostic",
            )
        )
        return self._store.enqueue(
            setup_id=setup_id,
            event_type="DEBUG_TELEGRAM_BRIDGE",
            event_key=f"DEBUG_TELEGRAM_BRIDGE:{timestamp.isoformat()}",
            payload={
                "text": (
                    "🧪 DEBUG TELEGRAM BRIDGE\n"
                    "Jalur MT5 log → SQLite outbox → subscriber APPROVED aktif.\n"
                    "Ini bukan entry dan tidak membuka order."
                ),
                "debug": True,
                "account_scope": "unknown",
                "account_login": "",
                "account_server": "",
                "event_origin_account_scope": "unknown",
                "event_origin_account_login": "",
                "event_origin_account_server": "",
                "current_account_scope": "unknown",
                "current_account_login": "",
                "current_account_server": "",
                "event_account_binding_verified": False,
                "audience": "admin_only",
            },
        )

    def _consume(
        self,
        path: Path,
        *,
        current_account: Mapping[str, str],
        current_account_errors: tuple[str, ...],
    ) -> tuple[int, int, int, int, int, str | None, str | None]:
        cursor = self._store.mt5_log_cursor(path)
        offset = int(cursor["byte_offset"]) if cursor else 0
        encoding = str(cursor["encoding"]) if cursor else ""
        fragment = str(cursor["fragment"]) if cursor else ""
        continuity_reset = False
        with path.open("rb") as handle:
            stat = os.fstat(handle.fileno())
            file_identity = _file_identity(stat)
            if cursor is not None and not _cursor_continuity_matches(
                handle=handle,
                cursor=cursor,
                size=int(stat.st_size),
                file_identity=file_identity,
            ):
                # A same-path replacement or truncate-and-regrow must be read
                # from byte zero. Outbox uniqueness makes replay safe; seeking
                # into unverified content could silently skip a REAL event.
                offset = 0
                encoding = ""
                fragment = ""
                continuity_reset = True
            handle.seek(offset)
            data = handle.read()
            read_end = handle.tell()

            decoded = ""
            raw_tail = b""
            if data:
                bom_length = 0
                if not encoding:
                    detected = _detect_encoding(data)
                    if detected is None:
                        raw_tail = data
                    else:
                        encoding, bom_length = detected
                if encoding:
                    decoder = codecs.getincrementaldecoder(encoding)(
                        errors="replace"
                    )
                    decoded = decoder.decode(data[bom_length:], final=False)
                    raw_tail = bytes(decoder.getstate()[0])
            new_offset = read_end - len(raw_tail)
            raw_tail_b64 = base64.b64encode(raw_tail).decode("ascii")
            anchor_sha256 = _cursor_content_anchor(handle, new_offset)

        if not data:
            if continuity_reset:
                self._store.set_mt5_log_cursor(
                    log_path=path,
                    byte_offset=new_offset,
                    encoding=encoding,
                    fragment=fragment,
                    file_identity=file_identity,
                    anchor_offset=new_offset,
                    anchor_sha256=anchor_sha256,
                    raw_tail_b64="",
                )
            return 0, 0, 0, 0, 0, None, None
        text = fragment + decoded
        complete_lines, fragment = _split_complete_lines(text)

        cursor_unchanged = bool(
            cursor is not None
            and not continuity_reset
            and int(cursor.get("byte_offset", -1)) == new_offset
            and str(cursor.get("encoding") or "") == encoding
            and str(cursor.get("fragment") or "") == fragment
            and str(cursor.get("raw_tail_b64") or "") == raw_tail_b64
        )
        if cursor_unchanged and not complete_lines:
            return 0, 0, 0, 0, 0, None, None

        enqueued = 0
        matched = 0
        mismatched = 0
        provider_failures = 0
        last_session_observation: str | None = None
        last_account_context_result: str | None = None
        for line in complete_lines:
            event = parse_mt5_log_line(
                line, server_utc_offset_minutes=self._server_utc_offset_minutes
            )
            if event is not None:
                try:
                    persisted, session_matched, provider_failed = self._persist(
                        event,
                        source_path=path,
                        current_account=current_account,
                        current_account_errors=current_account_errors,
                    )
                except Mt5SetupIdentityError as exc:
                    # A permanent immutable-identity conflict must not poison
                    # the whole file cursor and starve valid later lines. Only
                    # this typed validation failure is quarantined; transient
                    # SQLite/storage failures still propagate and retain the
                    # cursor for a safe retry.
                    persisted = self._quarantine_setup_identity_conflict(
                        event,
                        source_path=path,
                        error=exc,
                    )
                    session_matched = self._required_run_id is not None
                    provider_failed = True
                matched += int(session_matched)
                mismatched += int(not session_matched and self._required_run_id is not None)
                provider_failures += int(provider_failed)
                enqueued += int(persisted)
                if self._required_run_id is not None:
                    last_session_observation = (
                        "match" if session_matched else "mismatch"
                    )
                if session_matched:
                    if provider_failed:
                        last_account_context_result = "failure"
                    elif last_account_context_result is None:
                        last_account_context_result = "ok"

        self._store.set_mt5_log_cursor(
            log_path=path,
            byte_offset=new_offset,
            encoding=encoding,
            fragment=fragment,
            file_identity=file_identity,
            anchor_offset=new_offset,
            anchor_sha256=anchor_sha256,
            raw_tail_b64=raw_tail_b64,
        )
        return (
            len(complete_lines),
            enqueued,
            matched,
            mismatched,
            provider_failures,
            last_session_observation,
            last_account_context_result,
        )

    def _quarantine_setup_identity_conflict(
        self,
        event: ParsedMt5Event,
        *,
        source_path: Path,
        error: Mt5SetupIdentityError,
    ) -> bool:
        resolved_source = str(source_path.resolve(strict=False))
        line_digest = hashlib.sha256(
            f"{resolved_source}\0{event.raw_text}".encode("utf-8")
        ).hexdigest()
        detail = str(error).strip() or "immutable setup identity conflict"
        return self._store.enqueue(
            setup_id=event.setup_id,
            event_type="MT5_SETUP_IDENTITY_REJECTED",
            event_key=f"MT5_SETUP_IDENTITY_REJECTED:{line_digest}",
            payload={
                "text": (
                    "🚨 MT5 SETUP IDENTITY DITOLAK\n"
                    f"• Setup: {event.setup_id}\n"
                    f"• Event: {event.event_type}\n"
                    f"• Alasan: {detail}\n"
                    "Cursor tetap maju; event ini tidak disimpan sebagai sinyal "
                    "dan tidak boleh dieksekusi."
                ),
                "setup_id": event.setup_id,
                "event_type": event.event_type,
                "source": "mt5_expert_log",
                "source_log_path": resolved_source,
                "source_run_id": event.fields.get("runId", ""),
                "account_scope": "unknown",
                "account_login": "",
                "account_server": "",
                "event_origin_account_scope": "unknown",
                "event_origin_account_login": "",
                "event_origin_account_server": "",
                "current_account_scope": "unknown",
                "current_account_login": "",
                "current_account_server": "",
                "event_account_binding_verified": False,
                "audience": "admin_only",
                "account_context_error": detail,
            },
        )

    def _persist(
        self,
        event: ParsedMt5Event,
        *,
        source_path: Path,
        current_account: Mapping[str, str],
        current_account_errors: tuple[str, ...],
    ) -> tuple[bool, bool, bool]:
        duplicate_fields = {
            value
            for value in str(event.fields.get("_duplicateFields") or "").split(",")
            if value
        }
        if duplicate_fields & {"id", "runId"}:
            # Setup/session identity cannot be selected with last-value-wins.
            # Reject before any setup mutation or outbox persistence.
            return False, False, False
        if self._required_run_id is not None:
            observed_run_id = str(event.fields.get("runId") or "")
            if observed_run_id != self._required_run_id:
                return False, False, False
        account_context = self._resolve_account_binding(
            event.fields,
            current_account=current_account,
            current_account_errors=current_account_errors,
        )
        if self._expected_symbol is not None and event.symbol != self._expected_symbol:
            detail = (
                "event symbol does not match the canonical runtime symbol "
                f"{self._expected_symbol}"
            )
            account_context["event_account_binding_verified"] = False
            account_context["audience"] = "admin_only"
            existing_error = str(
                account_context.get("account_context_error") or ""
            ).strip()
            account_context["account_context_error"] = "; ".join(
                value for value in (existing_error, detail) if value
            )[:1000]
        state = {
            "SNIPER_EARLY_CANDIDATE": SetupState.EARLY_CANDIDATE,
            "SNIPER_EARLY_PROMOTED": SetupState.CONFIRMED_A_PLUS,
            "SNIPER_SIGNAL": SetupState.ACTIVE_SIGNAL,
            "SNIPER_EARLY_CANCELLED": SetupState.CANCELLED,
            "SNIPER_OUTCOME": SetupState.CLOSED,
        }[event.event_type]
        record = SetupRecord(
            setup_id=event.setup_id,
            symbol=event.symbol,
            side=event.side,
            level=event.level,
            breakout_at=event.occurred_at,
            state=state,
            reason=event.fields.get("reason", event.event_type),
        )
        payload = {
            "text": (
                event.telegram_text
                if account_context["event_account_binding_verified"]
                else (
                    "⛔ EVENT ACCOUNT BINDING DIBLOKIR\n"
                    "Event hanya untuk audit admin; viewer dan eksekusi wajib "
                    "ditolak.\n"
                    f"Alasan: {account_context['account_context_error']}\n\n"
                    f"{event.telegram_text}"
                )
            ),
            "setup_id": event.setup_id,
            "event_type": event.event_type,
            "fields": event.fields,
            "setup_at_utc": _iso_utc(event.occurred_at),
            "generated_at_utc": _iso_utc(event.generated_at),
            "source": "mt5_expert_log",
            "source_log_path": str(source_path.resolve(strict=False)),
            "source_run_id": event.fields.get("runId", ""),
            "event_symbol": event.symbol,
            "expected_symbol": self._expected_symbol or "",
            **account_context,
        }
        persisted = self._store.ingest_mt5_event(
            record=record,
            event_type=event.event_type,
            event_key=event.event_type,
            payload=payload,
        )
        return (
            persisted,
            self._required_run_id is not None,
            not bool(account_context["event_account_binding_verified"]),
        )

    def _load_current_account_context(
        self, *, required: bool
    ) -> tuple[dict[str, str], tuple[str, ...]]:
        unknown = {"scope": "unknown", "login": "", "server": ""}
        if self._account_context_provider is None:
            return (
                unknown,
                ("account context provider is not configured",) if required else (),
            )
        try:
            candidate = self._account_context_provider()
            if not isinstance(candidate, Mapping):
                raise TypeError("account context provider must return a mapping")
        except Exception:
            return unknown, ("account context provider failed",)

        errors: list[str] = []
        login = str(candidate.get("login") or "").strip()
        server = str(candidate.get("server") or "").strip()
        is_live = candidate.get("is_live")
        if is_live is True:
            scope = "live"
            errors.append("current account is live; demo bridge health requires demo")
        elif is_live is False:
            scope = "demo"
        else:
            scope = "unknown"
            errors.append("current account type is unknown")
        if _ACCOUNT_LOGIN_RE.fullmatch(login) is None:
            login = ""
            errors.append("current account login is missing or invalid")
        if not _valid_account_server(server):
            server = ""
            errors.append("current account server is missing or invalid")
        return (
            {"scope": scope, "login": login, "server": server},
            tuple(dict.fromkeys(errors)),
        )

    def _resolve_account_binding(
        self,
        fields: Mapping[str, Any],
        *,
        current_account: Mapping[str, str],
        current_account_errors: tuple[str, ...],
    ) -> dict[str, Any]:
        """Bind immutable event origin to the account attached during ingestion.

        The EA snapshots origin identity when a setup id is created.  Reading a
        delayed line after an account switch must never relabel a REAL event as
        DEMO, so viewer approval requires two independently valid, equal DEMO
        identities.  Every incomplete or ambiguous case remains durable but is
        restricted to administrators.
        """

        errors: list[str] = list(current_account_errors)
        duplicates = {
            value
            for value in str(fields.get("_duplicateFields") or "").split(",")
            if value
        }
        duplicated_security = sorted(duplicates & _SECURITY_METADATA_FIELDS)
        if duplicated_security:
            errors.append(
                "event security metadata has duplicate fields: "
                + ",".join(duplicated_security)
            )

        raw_origin_scope = str(fields.get("accountScope") or "").strip()
        if raw_origin_scope not in {"demo", "live"}:
            origin_scope = "unknown"
            errors.append("event origin account scope is missing or invalid")
        else:
            origin_scope = raw_origin_scope

        raw_origin_login = str(fields.get("accountLogin") or "").strip()
        if _ACCOUNT_LOGIN_RE.fullmatch(raw_origin_login) is None:
            origin_login = ""
            errors.append("event origin account login is missing or invalid")
        else:
            origin_login = raw_origin_login

        origin_server = _decode_canonical_server_b64(
            str(fields.get("originServerB64") or "").strip()
        )
        if origin_server is None:
            origin_server = ""
            errors.append("event origin account server is missing or invalid")

        current_scope = str(current_account.get("scope") or "unknown")
        current_login = str(current_account.get("login") or "")
        current_server = str(current_account.get("server") or "")
        if (
            current_scope not in {"demo", "live"}
            or not current_login
            or not current_server
        ):
            errors.append("current account context is unavailable or invalid")

        if origin_scope == "live":
            errors.append("event origin account is live; viewer delivery requires demo")
        if origin_scope in {"demo", "live"} and current_scope in {"demo", "live"}:
            if origin_scope != current_scope:
                errors.append("event origin/current account scope mismatch")
            if origin_login and current_login and origin_login != current_login:
                errors.append("event origin/current account login mismatch")
            if (
                origin_server
                and current_server
                and origin_server != current_server
            ):
                errors.append("event origin/current account server mismatch")

        errors = list(dict.fromkeys(errors))
        verified = bool(
            not errors
            and origin_scope == "demo"
            and current_scope == "demo"
            and origin_login == current_login
            and origin_server == current_server
        )
        payload: dict[str, Any] = {
            # Standard account fields intentionally represent the immutable
            # event origin, never the account observed later by the reader.
            "account_scope": origin_scope,
            "account_login": origin_login,
            "account_server": origin_server,
            "event_origin_account_scope": origin_scope,
            "event_origin_account_login": origin_login,
            "event_origin_account_server": origin_server,
            "current_account_scope": current_scope,
            "current_account_login": current_login,
            "current_account_server": current_server,
            "event_account_binding_verified": verified,
            "audience": "approved" if verified else "admin_only",
        }
        if errors:
            payload["account_context_error"] = "; ".join(errors)[:1000]
        return payload


def parse_mt5_log_line(
    line: str, *, server_utc_offset_minutes: int = 0
) -> ParsedMt5Event | None:
    event_match = _EVENT_RE.search(line)
    if event_match is None:
        return None
    body = event_match.group("body")
    setup_match = _SETUP_ID_RE.search(body)
    if setup_match is None:
        return None
    setup_id = setup_match.group("setup_id").strip()
    id_match = _ID_PARTS_RE.match(setup_id)
    if id_match is None:
        return None
    field_matches = list(_FIELD_RE.finditer(body))
    fields = {
        match.group("key"): match.group("value") for match in field_matches
    }
    seen_fields: set[str] = set()
    duplicate_fields: set[str] = set()
    for match in field_matches:
        key = match.group("key")
        if key in seen_fields:
            duplicate_fields.add(key)
        seen_fields.add(key)
    if duplicate_fields:
        # Keep the event visible/auditable, but make silent last-value-wins
        # ambiguity available to the execution layer's fail-closed gate.
        fields["_duplicateFields"] = ",".join(sorted(duplicate_fields))
    fallback_offset = int(fields.get("serverUtcOffsetMinutes", server_utc_offset_minutes))
    fallback_zone = timezone(timedelta(minutes=fallback_offset))
    setup_server_time = datetime.strptime(
        f"{id_match.group('date')} {id_match.group('time')}", "%Y.%m.%d %H:%M"
    ).replace(tzinfo=fallback_zone)
    occurred_at = _datetime_from_epoch(fields.get("setupUtcEpoch")) or setup_server_time.astimezone(
        timezone.utc
    )
    generated_at = _datetime_from_epoch(fields.get("generatedUtcEpoch")) or occurred_at
    return ParsedMt5Event(
        event_type=event_match.group("event"),
        setup_id=setup_id,
        symbol=id_match.group("symbol"),
        side=id_match.group("side"),
        level=float(id_match.group("level")),
        occurred_at=occurred_at,
        generated_at=generated_at,
        fields=fields,
        raw_text=event_match.group(0).strip(),
    )


def _decode_canonical_server_b64(token: str) -> str | None:
    """Strictly decode the EA's unpadded UTF-8 base64url server field."""

    if _SERVER_B64_RE.fullmatch(token) is None or len(token) % 4 == 1:
        return None
    padded = token + "=" * ((4 - len(token) % 4) % 4)
    try:
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        server = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    if not _valid_account_server(server):
        return None
    canonical = base64.urlsafe_b64encode(server.encode("utf-8")).decode("ascii").rstrip("=")
    return server if canonical == token else None


def _valid_account_server(server: str) -> bool:
    return bool(
        server
        and server == server.strip()
        and len(server.encode("utf-8")) <= 512
        and all(ord(character) >= 32 and ord(character) != 127 for character in server)
    )


def render_stored_event(
    *, event_type: str, setup_id: str, symbol: str, side: str, level: float,
    setup_at: datetime, generated_at: datetime, fields: dict[str, str]
) -> str:
    """Render a stored event again after account-specific sizing/execution enrichment."""
    return _format_telegram_text(
        ParsedMt5Event(
            event_type=event_type,
            setup_id=setup_id,
            symbol=symbol,
            side=side,
            level=level,
            occurred_at=setup_at,
            generated_at=generated_at,
            fields=fields,
            raw_text="",
        )
    )


def _detect_encoding(data: bytes) -> tuple[str, int] | None:
    byte_order_marks = (
        (b"\xef\xbb\xbf", "utf-8"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
    )
    for marker, encoding in byte_order_marks:
        if data.startswith(marker):
            return encoding, len(marker)
    if any(marker.startswith(data) for marker, _ in byte_order_marks):
        # Do not guess while a BOM itself is split across polls.
        return None
    if len(data) >= 4 and data[1] == 0 and data[3] == 0:
        return "utf-16-le", 0
    return "utf-8", 0


def _log_path_sort_key(path: Path) -> tuple[str, str, int]:
    """Return a deterministic oldest-first key for one terminal log directory."""

    resolved = path.resolve(strict=False)
    return (
        str(resolved.parent).casefold(),
        resolved.name.casefold(),
        resolved.stat().st_mtime_ns,
    )


def _file_identity(stat: os.stat_result) -> str:
    """Return a stable identity for an open file, without relying on its path."""

    device = int(getattr(stat, "st_dev", 0) or 0)
    inode = int(getattr(stat, "st_ino", 0) or 0)
    if inode:
        return f"{device:x}:{inode:x}"
    # Modern Windows exposes a file index as st_ino. This fallback is only for
    # filesystems that do not; creation/change time is safer than path alone.
    created = int(getattr(stat, "st_ctime_ns", 0) or 0)
    return f"{device:x}:ctime:{created:x}"


def _cursor_content_anchor(handle: BinaryIO, offset: int) -> str:
    """Hash the consumed prefix and tail windows at an exact byte boundary."""

    boundary = max(0, int(offset))
    prefix_length = min(boundary, _CURSOR_ANCHOR_BYTES)
    tail_start = max(0, boundary - _CURSOR_ANCHOR_BYTES)
    handle.seek(0)
    prefix = handle.read(prefix_length)
    handle.seek(tail_start)
    tail = handle.read(boundary - tail_start)
    digest = hashlib.sha256()
    digest.update(b"GOLDM-MT5-CURSOR-V1\0")
    digest.update(boundary.to_bytes(8, byteorder="big", signed=False))
    digest.update(len(prefix).to_bytes(4, byteorder="big", signed=False))
    digest.update(prefix)
    digest.update(len(tail).to_bytes(4, byteorder="big", signed=False))
    digest.update(tail)
    return digest.hexdigest()


def _cursor_continuity_matches(
    *,
    handle: BinaryIO,
    cursor: Mapping[str, Any],
    size: int,
    file_identity: str,
) -> bool:
    try:
        offset = int(cursor.get("byte_offset", 0))
        anchor_offset = int(cursor.get("anchor_offset", -1))
    except (TypeError, ValueError):
        return False
    stored_identity = str(cursor.get("file_identity") or "")
    stored_anchor = str(cursor.get("anchor_sha256") or "")
    if (
        offset < 0
        or size < offset
        or not stored_identity
        or stored_identity != file_identity
        or anchor_offset != offset
        or re.fullmatch(r"[0-9a-f]{64}", stored_anchor) is None
    ):
        return False
    return _cursor_content_anchor(handle, offset) == stored_anchor


def _split_complete_lines(text: str) -> tuple[list[str], str]:
    pieces = text.splitlines(keepends=True)
    if not pieces:
        return [], text
    if pieces[-1].endswith(("\n", "\r")):
        return [piece.rstrip("\r\n") for piece in pieces], ""
    return [piece.rstrip("\r\n") for piece in pieces[:-1]], pieces[-1]


def _format_telegram_text(event: ParsedMt5Event) -> str:
    fields = event.fields
    instrument = f"{event.symbol}  •  {event.side}"
    generated_time = f"🕒 Dibuat: {_format_wib_time(event.generated_at)}"
    setup_time = f"• Setup M15: {_format_wib_time(event.occurred_at)}"
    identity = f"🆔 {_format_display_id(event)}"
    if event.event_type == "SNIPER_EARLY_CANDIDATE":
        return "\n".join(
            [
                "🟡 WATCH ONLY",
                instrument,
                generated_time,
                setup_time,
                "",
                "📍 LEVEL PANTAU",
                f"• Trigger: {fields.get('level', event.level)}",
                f"• Harga saat sinyal: {fields.get('watchPrice', '?')}",
                f"• Invalidasi: {fields.get('invalidation', '?')}",
                "",
                "📊 VALIDASI",
                f"• Confidence: {fields.get('confidence', '?')}/100 (indikator, bukan probabilitas)",
                f"• M5 votes: {fields.get('m5Votes', '?')}",
                f"• Pattern: {_display_token(fields.get('pattern', '?'))}",
                f"• Reaksi Fibonacci: {fields.get('fibonacciReaction', '?')}",
                "",
                "⏳ STATUS",
                "Belum entry — menunggu konfirmasi M1 dan pemeriksaan risiko final.",
                "",
                identity,
            ]
        )
    if event.event_type == "SNIPER_EARLY_PROMOTED":
        return "\n".join(
            [
                "🟢 WATCH PROMOTED",
                instrument,
                generated_time,
                setup_time,
                "",
                "📊 PENILAIAN",
                f"• Confidence awal: {fields.get('confidenceEarly', '?')}/100",
                f"• Score final: {fields.get('scoreFinal', '?')}/100",
                "",
                "⏳ STATUS",
                "Kandidat lolos promosi analisis dan menunggu sinyal final.",
                "Belum ada order broker.",
                "",
                identity,
            ]
        )
    if event.event_type == "SNIPER_SIGNAL":
        return "\n".join(
            [
                "🔔 ENTRY READY",
                instrument,
                generated_time,
                setup_time,
                "",
                "💰 RENCANA TRADE",
                f"• Entry: {fields.get('entry', '?')}",
                f"• Stop Loss: {fields.get('stop', '?')}",
                f"• Take Profit: {fields.get('target', '?')}",
                f"• Lot: {fields.get('volume', 'menunggu sizing MT5')}",
                f"• Risiko estimasi: {_money(fields.get('expectedLossCash'))}",
                f"• Profit estimasi: {_money(fields.get('expectedProfitCash'))}",
                f"• Berlaku sampai: {_format_epoch_wib(fields.get('validUntilUtcEpoch'))}",
                f"• Estimasi durasi: belum dikalibrasi; batas max {_duration(fields.get('maxHoldingMinutes'))}",
                "",
                "📊 VALIDASI FINAL",
                f"• Score: {fields.get('score', '?')}/100",
                f"• Projected R: {fields.get('projectedR', '?')}R",
                f"• M5 votes: {fields.get('m5Votes', '?')}",
                f"• Konfirmasi M1: {_yes_no(fields.get('m1Confirmed'))}",
                "",
                "⚠️ STATUS ORDER",
                *_execution_status_lines(fields),
                "",
                identity,
            ]
        )
    if event.event_type == "SNIPER_OUTCOME":
        return "\n".join(
            [
                "📌 HASIL MODEL STRATEGI",
                instrument,
                generated_time,
                setup_time,
                "",
                "📊 HASIL SIMULASI",
                f"• Alasan keluar: {_display_token(fields.get('result', '?'))}",
                f"• Entry: {fields.get('entry', '?')}",
                f"• Exit: {fields.get('exitPrice', '?')}",
                f"• Hasil: {fields.get('outcomeR', '?')}R",
                f"• Durasi aktual: {_duration(fields.get('durationMinutes'))}",
                "",
                "⚠️ BUKAN KONFIRMASI BROKER",
                "Ini outcome model strategi. Status order aktual dilaporkan terpisah.",
                "",
                identity,
            ]
        )
    return "\n".join(
        [
            "⚪ WATCH CANCELLED",
            instrument,
            generated_time,
            setup_time,
            "",
            "📊 PENILAIAN",
            f"• Confidence awal: {fields.get('confidenceEarly', '?')}/100",
            "",
            "❌ ALASAN",
            _display_token(fields.get("reason", "setup dibatalkan")),
            "",
            "⛔ STATUS",
            "Kandidat dibatalkan — tidak ada entry.",
            "",
            identity,
        ]
    )


def _display_token(value: str) -> str:
    return value.replace("_", " ").strip()


def _format_wib_time(value: datetime) -> str:
    months = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "Mei",
        "Jun",
        "Jul",
        "Agu",
        "Sep",
        "Okt",
        "Nov",
        "Des",
    )
    local = value.astimezone(timezone(timedelta(hours=7)))
    return f"{local.day:02d} {months[local.month - 1]} {local.year} • {local:%H:%M} WIB (UTC+7)"


def _format_display_id(event: ParsedMt5Event) -> str:
    local = event.occurred_at.astimezone(timezone(timedelta(hours=7)))
    return (
        f"{event.symbol}-{event.side}-{event.level:.2f}-"
        f"{local:%Y.%m.%d %H:%M} WIB"
    )


def _yes_no(value: str | None) -> str:
    if str(value).strip().lower() == "true":
        return "✅ Ya"
    if str(value).strip().lower() == "false":
        return "❌ Tidak"
    return "?"


def _datetime_from_epoch(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _iso_utc(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _format_epoch_wib(value: str | None) -> str:
    parsed = _datetime_from_epoch(value)
    return _format_wib_time(parsed) if parsed is not None else "tidak tersedia"


def _money(value: str | None) -> str:
    if value in {None, ""}:
        return "menunggu sizing MT5"
    try:
        return f"{float(value):.2f} (mata uang akun)"
    except ValueError:
        return str(value)


def _duration(value: str | None) -> str:
    if value in {None, ""}:
        return "tidak tersedia"
    try:
        minutes = max(0, int(float(value)))
    except ValueError:
        return str(value)
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours}j {remainder}m"
    if hours:
        return f"{hours} jam"
    return f"{remainder} menit"


def _execution_status_lines(fields: dict[str, str]) -> list[str]:
    status = fields.get("executionStatus", "SIGNAL_ONLY")
    if status == "FILLED":
        return [
            f"✅ Order broker terisi • ticket {fields.get('positionTicket') or fields.get('orderTicket', '?')}",
            f"Harga aktual: {fields.get('actualEntry', fields.get('entry', '?'))}",
        ]
    if status in {
        "PRECHECK_REJECTED",
        "GUARD_REJECTED",
        "RISK_REJECTED",
        "DIRECTION_REJECTED",
        "EXPIRED",
    }:
        return [
            f"⛔ Tidak entry: {_display_token(status)}",
            _display_token(fields.get("executionDetail", "ditolak oleh pemeriksaan risiko")),
        ]
    if status == "READY_MANUAL":
        return [
            "Mode eksekusi OFF — sizing selesai, order tidak dikirim.",
            "Approval Telegram hanya memberi akses notifikasi, bukan izin trading.",
        ]
    if status == "DRY_RUN_OK":
        return ["Dry-run lolos — tidak ada order broker yang dikirim."]
    return [
        "Sinyal strategi — belum ada konfirmasi order broker.",
        "Approval Telegram hanya memberi akses notifikasi, bukan izin trading.",
    ]
