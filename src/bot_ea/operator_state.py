from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from typing import Any


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value.strip())
    return normalized.strip("_").lower() or "default"


def _json_dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _json_load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class AccountFingerprint:
    login: str
    server: str
    broker: str = ""
    is_live: bool | None = None

    @property
    def key(self) -> str:
        parts = [self.broker or "broker", self.server or "server", self.login or "account"]
        return "_".join(_slugify(part) for part in parts if part)

    @property
    def label(self) -> str:
        broker = self.broker or "Broker tidak diketahui"
        server = self.server or "server tidak diketahui"
        login = self.login or "akun tidak diketahui"
        mode = "live" if self.is_live else "demo"
        return f"{broker} / {server} / {login} ({mode})"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AccountFingerprint":
        return cls(
            login=str(payload.get("login") or ""),
            server=str(payload.get("server") or ""),
            broker=str(payload.get("broker") or ""),
            is_live=payload.get("is_live"),
        )


@dataclass(slots=True)
class OperatorRuntimeSettings:
    mode: str = "operator"
    ai_runtime_command: str = "codex"
    ai_runtime_executable_path: str = ""
    ai_workspace_path: str = ""
    ai_documents_path: str = ""
    ai_context_root: str = ""
    default_model: str = "gpt-5.4-mini"
    timeout_seconds: int = 60
    strict_startup_gate: bool = True
    allow_dev_bypass: bool = True
    service_host: str = "127.0.0.1"
    service_port: int = 8765
    db_path: str = ""
    poll_interval_seconds: int = 30
    symbol: str = "EURUSD"
    timeframe: str = "M15"
    trading_style: str = "intraday"
    stop_distance_points: float = 200.0
    capital_mode: str = "fixed_cash"
    capital_value: float = 250.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ContextBinding:
    fingerprint: AccountFingerprint
    context_key: str
    context_path: str
    existed: bool
    created_now: bool
    mapping_source: str
    profile_path: str
    latest_summary_path: str
    open_issues_path: str
    last_session_path: str
    resume_prompt_path: str
    broker_notes_path: str
    operator_notes_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "fingerprint": self.fingerprint.to_dict(),
        }


class OperatorStateStore:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.runtime_data_dir = self.project_root / "runtime_data"
        self.runtime_settings_path = self.runtime_data_dir / "runtime_settings.json"
        self.app_settings_path = self.runtime_data_dir / "app_settings.json"
        self.account_context_map_path = self.runtime_data_dir / "account_context_map.json"
        self.runtime_state_path = self.runtime_data_dir / "runtime_state.json"

    def default_settings(self) -> OperatorRuntimeSettings:
        return OperatorRuntimeSettings(
            ai_workspace_path=str((self.project_root / "ai_workspace").resolve()),
            ai_documents_path=str((self.project_root / "ai_documents").resolve()),
            ai_context_root=str((self.project_root / "ai_context").resolve()),
            db_path=str((self.project_root / "bot_ea_runtime.db").resolve()),
        )

    def load_runtime_settings(self) -> OperatorRuntimeSettings:
        payload = self.default_settings().to_dict()
        payload.update(_json_load(self.runtime_settings_path))
        return OperatorRuntimeSettings(**payload)

    def load_runtime_state(self) -> dict[str, Any]:
        payload = self._default_runtime_state()
        payload.update(_json_load(self.runtime_state_path))
        return payload

    def save_runtime_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self._default_runtime_state()
        current.update(payload)
        current["updated_at"] = _utc_now_iso()
        _json_dump(self.runtime_state_path, current)
        return current

    def update_runtime_state(self, updates: dict[str, Any] | None = None, /, **changes: Any) -> dict[str, Any]:
        current = self.load_runtime_state()
        if updates:
            current.update(updates)
        if changes:
            current.update(changes)
        return self.save_runtime_state(current)

    def save_runtime_settings(self, settings: OperatorRuntimeSettings) -> dict[str, Any]:
        self.runtime_data_dir.mkdir(parents=True, exist_ok=True)
        payload = settings.to_dict()
        _json_dump(self.runtime_settings_path, payload)
        _json_dump(
            self.app_settings_path,
            {
                "mode": settings.mode,
                "strict_startup_gate": settings.strict_startup_gate,
                "allow_dev_bypass": settings.allow_dev_bypass,
                "service_host": settings.service_host,
                "service_port": settings.service_port,
                "updated_at": _utc_now_iso(),
            },
        )
        return payload

    def validate_runtime_command(
        self,
        *,
        command: str,
        executable_path: str = "",
    ) -> dict[str, Any]:
        explicit_path = Path(executable_path).expanduser() if executable_path else None
        if explicit_path and explicit_path.exists():
            resolved = explicit_path.resolve()
            return {
                "ok": True,
                "detail": f"AI runtime ditemukan di {resolved}",
                "command": command or str(resolved),
                "resolved_path": str(resolved),
            }
        if command:
            resolved_path = shutil.which(command)
            if resolved_path:
                return {
                    "ok": True,
                    "detail": f"AI runtime command tersedia: {resolved_path}",
                    "command": command,
                    "resolved_path": resolved_path,
                }
        raise RuntimeError("AI runtime tidak ditemukan. Periksa command atau executable path.")

    def validate_path(
        self,
        *,
        path: str,
        label: str,
        create: bool = False,
        writable: bool = False,
    ) -> dict[str, Any]:
        candidate = Path(path).expanduser()
        if create:
            candidate.mkdir(parents=True, exist_ok=True)
        if not candidate.exists():
            raise RuntimeError(f"{label} tidak ditemukan.")
        if not candidate.is_dir():
            raise RuntimeError(f"{label} harus berupa folder.")
        if writable:
            probe_path = candidate / ".write_test"
            try:
                probe_path.write_text("ok", encoding="utf-8")
                probe_path.unlink()
            except OSError as exc:
                raise RuntimeError(f"{label} tidak bisa ditulis: {exc}") from exc
        return {
            "ok": True,
            "detail": f"{label} siap: {candidate.resolve()}",
            "path": str(candidate.resolve()),
        }

    def validate_storage(self, *, db_path: str) -> dict[str, Any]:
        db_candidate = Path(db_path).expanduser()
        db_candidate.parent.mkdir(parents=True, exist_ok=True)
        try:
            with db_candidate.open("a", encoding="utf-8"):
                pass
        except OSError as exc:
            raise RuntimeError(f"Runtime DB tidak bisa dibuat: {exc}") from exc
        return {
            "ok": True,
            "detail": f"Storage siap: {db_candidate.resolve()}",
            "db_path": str(db_candidate.resolve()),
        }

    def build_resume_state(
        self,
        *,
        settings: OperatorRuntimeSettings,
        fingerprint_payload: dict[str, Any],
        create_new: bool = False,
        context_key: str | None = None,
    ) -> dict[str, Any]:
        fingerprint = AccountFingerprint.from_payload(fingerprint_payload)
        context_root = Path(settings.ai_context_root).expanduser()
        context_root.mkdir(parents=True, exist_ok=True)
        mapping = _json_load(self.account_context_map_path)
        listing = self.list_account_contexts(settings=settings, fingerprint_payload=fingerprint_payload)

        if create_new:
            resolved_context_key = str(listing["new_context"]["context_key"])
            mapping_source = "new_context"
        elif context_key:
            resolved_context_key = self._normalize_context_key(context_key)
            available = {entry["context_key"]: entry for entry in listing["available_contexts"]}
            if resolved_context_key in available:
                mapping_source = str(available[resolved_context_key]["mapping_source"])
            elif resolved_context_key == fingerprint.key:
                mapping_source = "existing" if (context_root / resolved_context_key).exists() else "new"
            else:
                raise RuntimeError("Context key tidak dikenal untuk akun ini.")
        else:
            resolved_context_key = str(listing["default_context_key"])
            available = {entry["context_key"]: entry for entry in listing["available_contexts"]}
            mapping_source = str(available.get(resolved_context_key, {}).get("mapping_source") or "new")

        context_path = context_root / resolved_context_key
        existed = context_path.exists()
        created_now = not existed

        self._ensure_context_structure(context_path, fingerprint)

        mapping[fingerprint.key] = resolved_context_key
        _json_dump(self.account_context_map_path, mapping)

        binding = ContextBinding(
            fingerprint=fingerprint,
            context_key=resolved_context_key,
            context_path=str(context_path.resolve()),
            existed=existed,
            created_now=created_now,
            mapping_source=mapping_source,
            profile_path=str((context_path / "profile.yaml").resolve()),
            latest_summary_path=str((context_path / "memory" / "latest_summary.md").resolve()),
            open_issues_path=str((context_path / "memory" / "open_issues.md").resolve()),
            last_session_path=str((context_path / "memory" / "last_session.json").resolve()),
            resume_prompt_path=str((context_path / "resume" / "resume_prompt.md").resolve()),
            broker_notes_path=str((context_path / "documents" / "broker_notes.md").resolve()),
            operator_notes_path=str((context_path / "documents" / "operator_notes.md").resolve()),
        )

        runtime_state = self.save_runtime_state(
            {
            "active_account_fingerprint": fingerprint.to_dict(),
            "context_key": resolved_context_key,
            "context_path": binding.context_path,
            "last_runtime_state": "ready",
            }
        )
        return {
            "ok": True,
            "detail": f"Context akun siap: {context_path.resolve()}",
            "binding": binding.to_dict(),
            "runtime_state": runtime_state,
        }

    def list_account_contexts(
        self,
        *,
        settings: OperatorRuntimeSettings,
        fingerprint_payload: dict[str, Any],
    ) -> dict[str, Any]:
        fingerprint = AccountFingerprint.from_payload(fingerprint_payload)
        context_root = Path(settings.ai_context_root).expanduser()
        context_root.mkdir(parents=True, exist_ok=True)
        mapping = _json_load(self.account_context_map_path)
        base_key = fingerprint.key
        mapped_key = self._normalize_context_key(str(mapping.get(base_key) or "")) if mapping.get(base_key) else None
        contexts: dict[str, dict[str, Any]] = {}

        if mapped_key:
            mapped_path = context_root / mapped_key
            contexts[mapped_key] = self._context_entry(
                context_root=context_root,
                context_key=mapped_key,
                fingerprint=fingerprint,
                mapping_source="mapped",
                force_exists=mapped_path.exists(),
            )

        for child in sorted(context_root.iterdir()) if context_root.exists() else []:
            if not child.is_dir():
                continue
            session = self.load_last_session(context_path=child)
            session_fingerprint = AccountFingerprint.from_payload(dict(session.get("account_fingerprint") or {}))
            if session_fingerprint.key != base_key:
                continue
            entry = self._context_entry(
                context_root=context_root,
                context_key=child.name,
                fingerprint=fingerprint,
                mapping_source="mapped" if child.name == mapped_key else "existing",
                force_exists=True,
            )
            existing = contexts.get(child.name)
            if existing:
                existing.update(entry)
            else:
                contexts[child.name] = entry

        if base_key not in contexts and (context_root / base_key).exists():
            contexts[base_key] = self._context_entry(
                context_root=context_root,
                context_key=base_key,
                fingerprint=fingerprint,
                mapping_source="existing",
                force_exists=True,
            )

        default_context_key = mapped_key or (base_key if base_key in contexts else None)
        if default_context_key is None and contexts:
            default_context_key = sorted(contexts.values(), key=self._context_sort_key)[0]["context_key"]
        if default_context_key is None:
            default_context_key = base_key

        available_contexts = sorted(contexts.values(), key=self._context_sort_key)
        for entry in available_contexts:
            entry["selected_by_default"] = entry["context_key"] == default_context_key

        return {
            "ok": True,
            "fingerprint": fingerprint.to_dict(),
            "mapped_context_key": mapped_key,
            "default_context_key": default_context_key,
            "available_contexts": available_contexts,
            "new_context": self._new_context_entry(context_root=context_root, base_key=base_key),
        }

    def load_last_session(self, *, context_path: str | Path) -> dict[str, Any]:
        path = self._last_session_path(context_path)
        payload = self._default_last_session()
        payload.update(_json_load(path))
        return payload

    def save_last_session(self, *, context_path: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
        current = self._default_last_session()
        current.update(payload)
        current["updated_at"] = _utc_now_iso()
        _json_dump(self._last_session_path(context_path), current)
        return current

    def update_last_session(
        self,
        *,
        context_path: str | Path,
        updates: dict[str, Any] | None = None,
        **changes: Any,
    ) -> dict[str, Any]:
        current = self.load_last_session(context_path=context_path)
        if updates:
            current.update(updates)
        if changes:
            current.update(changes)
        return self.save_last_session(context_path=context_path, payload=current)

    def _ensure_context_structure(self, context_path: Path, fingerprint: AccountFingerprint) -> None:
        (context_path / "memory").mkdir(parents=True, exist_ok=True)
        (context_path / "decisions").mkdir(parents=True, exist_ok=True)
        (context_path / "telemetry").mkdir(parents=True, exist_ok=True)
        (context_path / "resume").mkdir(parents=True, exist_ok=True)
        (context_path / "documents").mkdir(parents=True, exist_ok=True)

        profile = context_path / "profile.yaml"
        if not profile.exists():
            profile.write_text(
                "\n".join(
                    [
                        "language: id",
                        "risk_mode: conservative",
                        "require_manual_approval: true",
                        "allow_live_without_review: false",
                        "halt_on_mt5_disconnect: true",
                        "halt_on_account_change: true",
                        "operator_summary_style: short",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

        latest_summary = context_path / "memory" / "latest_summary.md"
        if not latest_summary.exists():
            latest_summary.write_text(
                "\n".join(
                    [
                        "# Ringkasan Sesi Terakhir",
                        "",
                        "- Context baru dibuat untuk akun ini.",
                        "- Belum ada aktivitas trading yang direkam.",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

        open_issues = context_path / "memory" / "open_issues.md"
        if not open_issues.exists():
            open_issues.write_text("# Open Issues\n\n- Belum ada isu terbuka.\n", encoding="utf-8")

        last_session = context_path / "memory" / "last_session.json"
        if not last_session.exists():
            self.save_last_session(
                context_path=context_path,
                payload={
                    "account_fingerprint": fingerprint.to_dict(),
                    "last_run_id": None,
                    "last_runtime_state": "stopped",
                    "last_symbol": None,
                    "last_mode": "dry-run",
                    "last_shutdown_reason": "not_started",
                },
            )

        resume_prompt = context_path / "resume" / "resume_prompt.md"
        if not resume_prompt.exists():
            resume_prompt.write_text(
                "\n".join(
                    [
                        "# Resume Prompt",
                        "",
                        f"- Akun aktif: {fingerprint.label}",
                        "- Gunakan bahasa Indonesia yang ringkas.",
                        "- Hormati approval manual dan halt policy.",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

        broker_notes = context_path / "documents" / "broker_notes.md"
        if not broker_notes.exists():
            broker_notes.write_text("# Broker Notes\n\n", encoding="utf-8")

        operator_notes = context_path / "documents" / "operator_notes.md"
        if not operator_notes.exists():
            operator_notes.write_text("# Operator Notes\n\n", encoding="utf-8")

    @staticmethod
    def _default_runtime_state() -> dict[str, Any]:
        return {
            "active_account_fingerprint": {},
            "context_key": "",
            "context_path": "",
            "last_runtime_state": "stopped",
            "last_run_id": None,
            "last_shutdown_reason": "not_started",
            "updated_at": None,
        }

    @staticmethod
    def _default_last_session() -> dict[str, Any]:
        return {
            "account_fingerprint": {},
            "last_run_id": None,
            "last_runtime_state": "stopped",
            "last_symbol": None,
            "last_mode": "dry-run",
            "last_shutdown_reason": "not_started",
            "updated_at": None,
        }

    @staticmethod
    def _normalize_context_key(value: str) -> str:
        normalized = value.strip()
        if not normalized or re.search(r"[\\/]", normalized) or ".." in normalized:
            raise RuntimeError("Context key tidak valid.")
        return normalized

    @staticmethod
    def _context_sort_key(entry: dict[str, Any]) -> tuple[int, str, str]:
        priority = 0 if entry.get("mapping_source") == "mapped" else 1
        updated = str(entry.get("updated_at") or "")
        return (priority, updated == "", updated or entry["context_key"])

    def _context_entry(
        self,
        *,
        context_root: Path,
        context_key: str,
        fingerprint: AccountFingerprint,
        mapping_source: str,
        force_exists: bool,
    ) -> dict[str, Any]:
        context_path = context_root / context_key
        last_session = self.load_last_session(context_path=context_path)
        session_fingerprint = dict(last_session.get("account_fingerprint") or {})
        account_match = not session_fingerprint or AccountFingerprint.from_payload(session_fingerprint).key == fingerprint.key
        return {
            "context_key": context_key,
            "context_path": str(context_path.resolve()),
            "exists": bool(force_exists),
            "mapping_source": mapping_source,
            "account_match": account_match,
            "last_run_id": last_session.get("last_run_id"),
            "last_runtime_state": last_session.get("last_runtime_state"),
            "last_shutdown_reason": last_session.get("last_shutdown_reason"),
            "updated_at": last_session.get("updated_at"),
        }

    def _new_context_entry(self, *, context_root: Path, base_key: str) -> dict[str, Any]:
        for suffix in count(start=1):
            candidate = base_key if suffix == 1 else f"{base_key}_{suffix}"
            path = context_root / candidate
            if not path.exists():
                return {
                    "context_key": candidate,
                    "context_path": str(path.resolve()),
                    "exists": False,
                    "mapping_source": "new_context",
                }
        raise RuntimeError("Tidak bisa menentukan context key baru.")

    @staticmethod
    def _last_session_path(context_path: str | Path) -> Path:
        return Path(context_path).expanduser() / "memory" / "last_session.json"
