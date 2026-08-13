from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ..storage.database import SignalStore
from ..strategy.state_machine import SetupRecord, SetupState


_EVENT_RE = re.compile(
    r"\b(?P<event>SNIPER_(?:EARLY_CANDIDATE|EARLY_PROMOTED|SIGNAL|EARLY_CANCELLED))\b(?P<body>.*)"
)
_SETUP_ID_RE = re.compile(r"\bid=(?P<setup_id>.+?)\s+status=")
_FIELD_RE = re.compile(r"(?P<key>[A-Za-z][A-Za-z0-9_]*)=(?P<value>\S+)")
_ID_PARTS_RE = re.compile(
    r"^(?P<symbol>.+)-(?P<side>BUY|SELL)-(?P<level>-?\d+(?:\.\d+)?)-"
    r"(?P<date>\d{4}\.\d{2}\.\d{2}) (?P<time>\d{2}:\d{2})$"
)


@dataclass(frozen=True)
class ParsedMt5Event:
    event_type: str
    setup_id: str
    symbol: str
    side: str
    level: float
    occurred_at: datetime
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
        appdata: str | Path | None = None,
    ) -> None:
        self._store = store
        self._log_paths = (
            tuple(Path(path) for path in log_paths) if log_paths is not None else None
        )
        self._appdata = Path(appdata) if appdata else None

    def run_once(self) -> tuple[int, int, int]:
        files = 0
        lines = 0
        enqueued = 0
        for path in self.discover_log_paths():
            files += 1
            parsed_lines, added = self._consume(path)
            lines += parsed_lines
            enqueued += added
        return files, lines, enqueued

    def discover_log_paths(self) -> list[Path]:
        if self._log_paths is not None:
            return sorted(path for path in self._log_paths if path.is_file())

        appdata = self._appdata or Path(os.environ.get("APPDATA", ""))
        if not str(appdata):
            return []
        pattern = str(appdata / "MetaQuotes" / "Terminal" / "*" / "MQL5" / "Logs" / "*.log")
        candidates = [Path(value) for value in glob.glob(pattern)]

        # Each installed terminal may have years of logs. The newest live log per
        # terminal is enough; outbox deduplication safely handles a worker restart.
        newest_by_directory: dict[Path, Path] = {}
        for candidate in candidates:
            previous = newest_by_directory.get(candidate.parent)
            if previous is None or candidate.stat().st_mtime > previous.stat().st_mtime:
                newest_by_directory[candidate.parent] = candidate
        return sorted(newest_by_directory.values())

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
            },
        )

    def _consume(self, path: Path) -> tuple[int, int]:
        cursor = self._store.mt5_log_cursor(path)
        size = path.stat().st_size
        offset = int(cursor["byte_offset"]) if cursor else 0
        encoding = str(cursor["encoding"]) if cursor else ""
        fragment = str(cursor["fragment"]) if cursor else ""
        if size < offset:
            offset = 0
            encoding = ""
            fragment = ""

        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
            new_offset = handle.tell()

        if not data:
            return 0, 0
        if not encoding:
            encoding, bom_length = _detect_encoding(data)
            data = data[bom_length:]
        text = fragment + data.decode(encoding, errors="replace")
        complete_lines, fragment = _split_complete_lines(text)

        enqueued = 0
        for line in complete_lines:
            event = parse_mt5_log_line(line)
            if event is not None and self._persist(event):
                enqueued += 1

        self._store.set_mt5_log_cursor(
            log_path=path,
            byte_offset=new_offset,
            encoding=encoding,
            fragment=fragment,
        )
        return len(complete_lines), enqueued

    def _persist(self, event: ParsedMt5Event) -> bool:
        state = {
            "SNIPER_EARLY_CANDIDATE": SetupState.EARLY_CANDIDATE,
            "SNIPER_EARLY_PROMOTED": SetupState.CONFIRMED_A_PLUS,
            "SNIPER_SIGNAL": SetupState.CONFIRMED_A_PLUS,
            "SNIPER_EARLY_CANCELLED": SetupState.CANCELLED,
        }[event.event_type]
        self._store.save_setup(
            SetupRecord(
                setup_id=event.setup_id,
                symbol=event.symbol,
                side=event.side,
                level=event.level,
                breakout_at=event.occurred_at,
                state=state,
                reason=event.fields.get("reason", event.event_type),
            )
        )
        return self._store.enqueue(
            setup_id=event.setup_id,
            event_type=event.event_type,
            event_key=event.event_type,
            payload={
                "text": event.telegram_text,
                "setup_id": event.setup_id,
                "event_type": event.event_type,
                "fields": event.fields,
                "source": "mt5_expert_log",
            },
        )


def parse_mt5_log_line(line: str) -> ParsedMt5Event | None:
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
    fields = {match.group("key"): match.group("value") for match in _FIELD_RE.finditer(body)}
    occurred_at = datetime.strptime(
        f"{id_match.group('date')} {id_match.group('time')}", "%Y.%m.%d %H:%M"
    ).replace(tzinfo=timezone.utc)
    return ParsedMt5Event(
        event_type=event_match.group("event"),
        setup_id=setup_id,
        symbol=id_match.group("symbol"),
        side=id_match.group("side"),
        level=float(id_match.group("level")),
        occurred_at=occurred_at,
        fields=fields,
        raw_text=event_match.group(0).strip(),
    )


def _detect_encoding(data: bytes) -> tuple[str, int]:
    if data.startswith(b"\xff\xfe"):
        return "utf-16-le", 2
    if data.startswith(b"\xfe\xff"):
        return "utf-16-be", 2
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8", 3
    if len(data) >= 4 and data[1] == 0 and data[3] == 0:
        return "utf-16-le", 0
    return "utf-8", 0


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
    event_time = f"🕒 Waktu sinyal: {_format_wib_time(event.occurred_at)}"
    identity = f"🆔 {_format_display_id(event)}"
    if event.event_type == "SNIPER_EARLY_CANDIDATE":
        return "\n".join(
            [
                "🟡 WATCH ONLY",
                instrument,
                event_time,
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
                event_time,
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
                event_time,
                "",
                "💰 RENCANA TRADE",
                f"• Entry: {fields.get('entry', '?')}",
                f"• Stop Loss: {fields.get('stop', '?')}",
                f"• Take Profit: {fields.get('target', '?')}",
                "",
                "📊 VALIDASI FINAL",
                f"• Score: {fields.get('score', '?')}/100",
                f"• Projected R: {fields.get('projectedR', '?')}R",
                f"• M5 votes: {fields.get('m5Votes', '?')}",
                f"• Konfirmasi M1: {_yes_no(fields.get('m1Confirmed'))}",
                "",
                "⚠️ STATUS ORDER",
                "Sinyal akun demo — bukan konfirmasi bahwa order broker sudah terbuka.",
                "Periksa tab Trade di MT5 untuk status eksekusi.",
                "",
                identity,
            ]
        )
    return "\n".join(
        [
            "⚪ WATCH CANCELLED",
            instrument,
            event_time,
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
