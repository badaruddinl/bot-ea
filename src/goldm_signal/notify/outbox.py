from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..storage.database import SignalStore


class OutboxWorker:
    def __init__(self, store: SignalStore, sender: Callable[[dict[str, Any]], None]) -> None:
        self.store = store
        self.sender = sender

    def run_once(self, *, limit: int = 20) -> tuple[int, int]:
        sent = 0
        failed = 0
        for event in self.store.pending(limit=limit):
            try:
                self.sender(event)
            except Exception as exc:  # worker boundary: retain event for retry
                self.store.mark_failed(int(event["id"]), str(exc))
                failed += 1
            else:
                self.store.mark_sent(int(event["id"]))
                sent += 1
        return sent, failed
