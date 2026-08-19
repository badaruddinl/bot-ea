from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from goldm_signal.notify.telegram import TelegramBotClient

from .config import OrchestratorConfig, ROOT, WorkerSpec


PUBLIC_GOLDI_COMMANDS: tuple[dict[str, str], ...] = (
    {"command": "start", "description": "Minta akses notifikasi GOLD.i"},
    {"command": "subscription", "description": "Cek status akses GOLD.i"},
    {"command": "stop", "description": "Berhenti menerima GOLD.i"},
)


ORCHESTRATOR_BOT_COMMANDS: tuple[dict[str, str], ...] = (
    *PUBLIC_GOLDI_COMMANDS,
    {"command": "status", "description": "Status kedua worker GOLD"},
    {"command": "workers", "description": "Detail proses dan heartbeat"},
    {"command": "heartbeat", "description": "Kirim status sekarang"},
    {"command": "goldi_on", "description": "Hidupkan sinyal GOLD.i"},
    {"command": "goldi_off", "description": "Matikan sinyal GOLD.i"},
    {"command": "goldm_on", "description": "Hidupkan trading real GOLDm"},
    {"command": "goldm_off", "description": "Matikan trading real GOLDm"},
    {"command": "all_on", "description": "Hidupkan kedua worker"},
    {"command": "all_off", "description": "Matikan kedua worker"},
    {"command": "pending", "description": "Permintaan akses GOLD.i"},
    {"command": "subscribers", "description": "Subscriber GOLD.i aktif"},
    {"command": "approve", "description": "Approve ID untuk GOLD.i"},
    {"command": "deny", "description": "Tolak permintaan GOLD.i"},
    {"command": "remove", "description": "Hapus subscriber GOLD.i"},
    {"command": "help", "description": "Daftar perintah orchestrator"},
)


class GlobalOrchestrator:
    """One Telegram poller and watchdog for both final portfolio workers."""

    def __init__(
        self,
        config: OrchestratorConfig,
        *,
        telegram_client: TelegramBotClient | None = None,
        popen_factory=subprocess.Popen,
        monotonic=time.monotonic,
    ) -> None:
        self.config = config
        self.telegram = telegram_client or TelegramBotClient(
            bot_token=config.bot_token,
            timeout_seconds=max(10.0, float(config.poll_timeout_seconds + 5)),
        )
        self._popen_factory = popen_factory
        self._monotonic = monotonic
        self._state = self._load_state()
        self._children: dict[str, subprocess.Popen[Any]] = {}
        self._logs: dict[str, Any] = {}
        self._stop_event = threading.Event()
        self._last_supervision = 0.0
        self._last_heartbeat = 0.0
        self._next_restart: dict[str, float] = {}
        self._failure_counts: dict[str, int] = {}
        self._reported_problem: dict[str, str] = {}

    def run_forever(self) -> None:
        self._install_signal_handlers()
        self._save_state()
        self.publish_command_menu()
        self._send_all(
            f"{self.config.orchestrator_id} ONLINE\n"
            f"pid={os.getpid()} workers={self._desired_summary()}"
        )
        self._last_heartbeat = self._monotonic()
        self._audit("ORCHESTRATOR_ONLINE", {"pid": os.getpid()})
        try:
            while not self._stop_event.is_set():
                now = self._monotonic()
                if now - self._last_supervision >= self.config.supervision_interval_seconds:
                    self.supervise_once(now=now)
                    self._last_supervision = now
                if now - self._last_heartbeat >= self.config.heartbeat_seconds:
                    self._send_all(self.status_text(title="SCHEDULED HEARTBEAT"))
                    self._last_heartbeat = now
                self.poll_once(timeout=self.config.poll_timeout_seconds)
        finally:
            for name in list(self._children):
                self.stop_worker(name, notify=False)
            self._audit("ORCHESTRATOR_STOPPED", {})

    def publish_command_menu(self) -> None:
        self.telegram.replace_commands(
            commands=PUBLIC_GOLDI_COMMANDS,
            chat_ids=set(),
        )
        self.telegram.replace_commands(
            commands=ORCHESTRATOR_BOT_COMMANDS,
            chat_ids=set(self.config.admin_chat_ids),
            include_default=False,
        )
        self._audit(
            "TELEGRAM_COMMAND_MENU_UPDATED",
            {"commands": [item["command"] for item in ORCHESTRATOR_BOT_COMMANDS]},
        )

    def request_stop(self) -> None:
        self._stop_event.set()

    def poll_once(self, *, timeout: int = 0) -> int:
        offset = int(self._state.get("telegram_offset") or 0) or None
        updates = self.telegram.get_updates(offset=offset, timeout=timeout)
        handled = 0
        for update in updates:
            update_id = int(update.get("update_id") or 0)
            if update_id:
                self._state["telegram_offset"] = update_id + 1
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            actor_id = str(chat.get("id") or "")
            text = str(message.get("text") or "").strip()
            if not text:
                continue
            handled += 1
            self.handle_command(actor_id=actor_id, text=text)
        if updates:
            self._save_state()
        return handled

    def handle_command(self, *, actor_id: str, text: str) -> None:
        command_parts = text.split()
        command = command_parts[0].split("@", 1)[0].lower()
        arguments = command_parts[1:]
        if actor_id not in set(self.config.admin_chat_ids):
            self._handle_public_command(actor_id=actor_id, command=command)
            return
        if command in {"/start", "/help"}:
            response = self.help_text()
        elif command in {"/status", "/workers", "/heartbeat"}:
            self.supervise_once(now=self._monotonic())
            response = self.status_text()
        elif command in {"/goldi_on", "/goldm_on"}:
            name = command[1:].removesuffix("_on")
            response = self.set_desired(name, True)
        elif command in {"/goldi_off", "/goldm_off"}:
            name = command[1:].removesuffix("_off")
            response = self.set_desired(name, False)
        elif command == "/all_on":
            responses = [self.set_desired(name, True) for name in ("goldi", "goldm")]
            response = "\n".join(responses)
        elif command == "/all_off":
            responses = [self.set_desired(name, False) for name in ("goldi", "goldm")]
            response = "\n".join(responses)
        elif command == "/pending":
            response = self.pending_text()
        elif command == "/subscribers":
            response = self.subscribers_text()
        elif command in {"/approve", "/deny", "/remove"}:
            if not arguments:
                response = f"Gunakan {command} <chat_id>."
            else:
                response = self._admin_subscription_action(
                    command=command,
                    target_id=arguments[0],
                )
        else:
            response = "Perintah tidak dikenal. Gunakan /help."
        self.telegram.send_message(chat_id=actor_id, text=response)

    def _handle_public_command(self, *, actor_id: str, command: str) -> None:
        if command == "/start":
            subscribers = set(self._state.get("goldi_subscribers") or [])
            if actor_id in subscribers:
                response = "Akses notifikasi GOLD.i sudah aktif."
            else:
                pending = dict(self._state.get("goldi_pending") or {})
                pending[actor_id] = {
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                }
                self._state["goldi_pending"] = pending
                self._save_state()
                response = "Permintaan akses GOLD.i dikirim ke admin."
                self._send_all(
                    "GOLD.i SUBSCRIPTION REQUEST\n"
                    f"chat_id={actor_id}\n"
                    f"approve: /approve {actor_id}\n"
                    f"deny: /deny {actor_id}"
                )
                self._audit("GOLDI_SUBSCRIPTION_REQUESTED", {"chat_id": actor_id})
        elif command == "/subscription":
            subscribers = set(self._state.get("goldi_subscribers") or [])
            pending = dict(self._state.get("goldi_pending") or {})
            if actor_id in subscribers:
                response = "Status GOLD.i: APPROVED."
            elif actor_id in pending:
                response = "Status GOLD.i: PENDING."
            else:
                response = "Status GOLD.i: belum terdaftar. Gunakan /start."
        elif command == "/stop":
            subscribers = set(self._state.get("goldi_subscribers") or [])
            subscribers.discard(actor_id)
            pending = dict(self._state.get("goldi_pending") or {})
            pending.pop(actor_id, None)
            self._state["goldi_subscribers"] = sorted(subscribers, key=int)
            self._state["goldi_pending"] = pending
            self._save_state()
            response = "Notifikasi GOLD.i dihentikan."
            self._audit("GOLDI_SUBSCRIPTION_STOPPED", {"chat_id": actor_id})
        else:
            response = "Perintah publik: /start, /subscription, /stop."
            self._audit("UNAUTHORIZED_COMMAND", {"actor_id": actor_id})
        self.telegram.send_message(chat_id=actor_id, text=response)

    def _admin_subscription_action(self, *, command: str, target_id: str) -> str:
        if not target_id.isascii() or not target_id.isdecimal() or int(target_id) <= 0:
            return "chat_id harus berupa angka positif."
        target_id = str(int(target_id))
        pending = dict(self._state.get("goldi_pending") or {})
        subscribers = set(self._state.get("goldi_subscribers") or [])
        if command == "/approve":
            pending.pop(target_id, None)
            subscribers.add(target_id)
            result = f"GOLD.i subscriber APPROVED: {target_id}"
            target_message = "Akses notifikasi entry GOLD.i telah disetujui."
            event = "GOLDI_SUBSCRIPTION_APPROVED"
        elif command == "/deny":
            pending.pop(target_id, None)
            subscribers.discard(target_id)
            result = f"Permintaan GOLD.i ditolak: {target_id}"
            target_message = "Permintaan akses notifikasi GOLD.i ditolak."
            event = "GOLDI_SUBSCRIPTION_DENIED"
        else:
            pending.pop(target_id, None)
            subscribers.discard(target_id)
            result = f"GOLD.i subscriber dihapus: {target_id}"
            target_message = "Akses notifikasi GOLD.i dihentikan oleh admin."
            event = "GOLDI_SUBSCRIPTION_REMOVED"
        self._state["goldi_pending"] = pending
        self._state["goldi_subscribers"] = sorted(subscribers, key=int)
        self._save_state()
        self.telegram.send_message(chat_id=target_id, text=target_message)
        self._audit(event, {"chat_id": target_id})
        return result

    def pending_text(self) -> str:
        pending = dict(self._state.get("goldi_pending") or {})
        if not pending:
            return "Tidak ada permintaan GOLD.i pending."
        return "GOLD.i PENDING\n" + "\n".join(
            f"{chat_id} requested_at={values.get('requested_at', '-')}"
            for chat_id, values in sorted(pending.items(), key=lambda item: int(item[0]))
        )

    def subscribers_text(self) -> str:
        subscribers = list(self._state.get("goldi_subscribers") or [])
        if not subscribers:
            return "Belum ada subscriber GOLD.i."
        return "GOLD.i SUBSCRIBERS\n" + "\n".join(
            sorted((str(item) for item in subscribers), key=int)
        )

    def set_desired(self, name: str, enabled: bool) -> str:
        self._require_worker(name)
        desired = dict(self._state.get("desired") or {})
        desired[name] = enabled
        self._state["desired"] = desired
        self._save_state()
        if enabled:
            result = self.start_worker(name)
        else:
            result = self.stop_worker(name, notify=False)
        self._audit("DESIRED_CHANGED", {"worker": name, "enabled": enabled})
        return result

    def start_worker(self, name: str, *, notify: bool = True) -> str:
        spec = self._require_worker(name)
        current = self._children.get(name)
        if current is not None and current.poll() is None:
            return f"{name}=ALREADY_RUNNING pid={current.pid}"
        spec.log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = spec.log_path.open("a", encoding="utf-8", buffering=1)
        command = [
            str(self.config.python_executable),
            str(ROOT / "scripts" / "run-final-portfolio-worker.py"),
            "--config",
            str(spec.config_path),
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = self._popen_factory(
                command,
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        except Exception:
            log_handle.close()
            raise
        self._children[name] = process
        self._logs[name] = log_handle
        self._next_restart.pop(name, None)
        self._audit("WORKER_STARTED", {"worker": name, "pid": process.pid})
        if notify:
            self._send_all(f"WORKER STARTED\n{name}=RUNNING pid={process.pid}")
        return f"{name}=STARTED pid={process.pid}"

    def stop_worker(self, name: str, *, notify: bool = True) -> str:
        self._require_worker(name)
        process = self._children.pop(name, None)
        if process is None or process.poll() is not None:
            self._close_log(name)
            return f"{name}=STOPPED"
        process.terminate()
        try:
            process.wait(timeout=self.config.shutdown_grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        self._close_log(name)
        self._audit("WORKER_STOPPED", {"worker": name, "pid": process.pid})
        if notify:
            self._send_all(f"WORKER STOPPED\n{name}=STOPPED")
        return f"{name}=STOPPED"

    def supervise_once(self, *, now: float | None = None) -> None:
        current_time = self._monotonic() if now is None else now
        desired = dict(self._state.get("desired") or {})
        for name, spec in self.config.workers.items():
            process = self._children.get(name)
            enabled = bool(desired.get(name, spec.enabled_on_first_boot))
            if not enabled:
                if process is not None and process.poll() is None:
                    self.stop_worker(name)
                continue
            if process is None or process.poll() is not None:
                if process is not None:
                    exit_code = process.poll()
                    self._close_log(name)
                    self._children.pop(name, None)
                    problem = f"process exited code={exit_code}"
                    self._report_problem(name, problem)
                    failures = self._failure_counts.get(name, 0) + 1
                    self._failure_counts[name] = failures
                    restart_delay = min(
                        self.config.restart_delay_seconds * (2 ** (failures - 1)),
                        300.0,
                    )
                    self._next_restart.setdefault(
                        name, current_time + restart_delay
                    )
                if current_time >= self._next_restart.get(name, 0.0):
                    self.start_worker(
                        name,
                        notify=self._failure_counts.get(name, 0) == 0,
                    )
                continue
            health = self._read_health(spec.health_path)
            problem = self._health_problem(health)
            if problem:
                self._report_problem(name, problem)
            else:
                self._reported_problem.pop(name, None)
                self._failure_counts.pop(name, None)

    def status_text(self, *, title: str = "WORKER STATUS") -> str:
        lines = [self.config.orchestrator_id, title]
        desired = dict(self._state.get("desired") or {})
        for name, spec in self.config.workers.items():
            process = self._children.get(name)
            running = process is not None and process.poll() is None
            health = self._read_health(spec.health_path)
            health_status = str(health.get("status") or "NO_HEALTH")
            updated = str(health.get("updated_at") or "-")
            account = ""
            if health.get("login"):
                account = (
                    f" login={health['login']} balance={float(health.get('balance') or 0):.2f}"
                    f" equity={float(health.get('equity') or 0):.2f}"
                )
            lines.append(
                f"{name}: desired={'ON' if desired.get(name, spec.enabled_on_first_boot) else 'OFF'} "
                f"process={'RUNNING' if running else 'STOPPED'} health={health_status} "
                f"updated={updated}{account}"
            )
        return "\n".join(lines)

    @staticmethod
    def help_text() -> str:
        return (
            "GOLD worker control (admin only)\n"
            "/workers atau /status - status lengkap\n"
            "/goldi_on /goldi_off - sinyal GOLD.i\n"
            "/goldm_on /goldm_off - trading GOLDm real\n"
            "/all_on /all_off - kedua worker\n"
            "/pending /subscribers - audience GOLD.i\n"
            "/approve ID /deny ID /remove ID - kelola GOLD.i\n"
            "/heartbeat - status segera"
        )

    def send_shutdown_notice(self, detail: str = "Windows shutdown event received") -> None:
        self._send_all(f"{self.config.orchestrator_id} SHUTDOWN\n{detail}")
        self._audit("SHUTDOWN_NOTICE", {"detail": detail})

    def _desired_summary(self) -> str:
        desired = dict(self._state.get("desired") or {})
        return ",".join(
            f"{name}={'ON' if desired.get(name, spec.enabled_on_first_boot) else 'OFF'}"
            for name, spec in self.config.workers.items()
        )

    def _load_state(self) -> dict[str, Any]:
        if self.config.state_path.exists():
            payload = json.loads(self.config.state_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("goldi_pending", {})
                payload.setdefault("goldi_subscribers", [])
                return payload
        return {
            "telegram_offset": 0,
            "goldi_pending": {},
            "goldi_subscribers": [],
            "desired": {
                name: spec.enabled_on_first_boot
                for name, spec in self.config.workers.items()
            },
        }

    def _save_state(self) -> None:
        self.config.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.config.state_path)

    def _audit(self, event: str, fields: dict[str, Any]) -> None:
        self.config.audit_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "time": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        with self.config.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")

    def _send_all(self, text: str) -> None:
        for chat_id in self.config.admin_chat_ids:
            self.telegram.send_message(chat_id=chat_id, text=text)

    def _require_worker(self, name: str) -> WorkerSpec:
        normalized = name.strip().lower()
        if normalized not in self.config.workers:
            raise ValueError(f"unknown worker: {name}")
        return self.config.workers[normalized]

    def _close_log(self, name: str) -> None:
        handle = self._logs.pop(name, None)
        if handle is not None:
            handle.close()

    @staticmethod
    def _read_health(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _health_problem(self, health: dict[str, Any]) -> str:
        if not health:
            return "health file missing"
        status = str(health.get("status") or "").upper()
        if status == "ERROR":
            return f"worker health ERROR: {health.get('detail', '-') }"
        raw_updated = str(health.get("updated_at") or "")
        try:
            updated = datetime.fromisoformat(raw_updated)
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds()
        except ValueError:
            return "invalid health timestamp"
        if age > self.config.health_stale_seconds:
            return f"health heartbeat stale age={int(age)}s"
        return ""

    def _report_problem(self, name: str, problem: str) -> None:
        if self._reported_problem.get(name) == problem:
            return
        self._reported_problem[name] = problem
        self._audit("WORKER_PROBLEM", {"worker": name, "problem": problem})
        self._send_all(f"WORKER ALERT\n{name}: {problem}")

    def _install_signal_handlers(self) -> None:
        def stop_handler(_signum, _frame) -> None:
            self.request_stop()

        for signal_name in ("SIGINT", "SIGTERM"):
            signal_value = getattr(signal, signal_name, None)
            if signal_value is not None:
                signal.signal(signal_value, stop_handler)
