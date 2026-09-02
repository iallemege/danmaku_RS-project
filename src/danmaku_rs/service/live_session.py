from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class LiveSession:
    success: int = 0
    failed: int = 0
    skipped: int = 0
    consecutive_fail: int = 0
    rate_limit_hits: int = 0
    intercept_412: int = 0
    last_code: Optional[int] = None
    sending: bool = False
    simulate: bool = False
    accounts_active: int = 1
    events: List[dict] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def reset_run(self, simulate: bool, accounts_active: int = 1) -> None:
        with self._lock:
            self.success = self.failed = self.skipped = 0
            self.consecutive_fail = 0
            self.rate_limit_hits = 0
            self.intercept_412 = 0
            self.last_code = None
            self.sending = True
            self.simulate = simulate
            self.accounts_active = accounts_active
            self.events.clear()

    def note(self, event: dict) -> None:
        kind = event.get("kind")
        code = event.get("code")
        with self._lock:
            if code is not None:
                try:
                    self.last_code = int(code)
                except (TypeError, ValueError):
                    pass
            self.events.append({"ts": time.time(), **event})
            self.events = self.events[-200:]
            if kind == "success":
                self.success += 1
                self.consecutive_fail = 0
            elif kind == "skip":
                self.skipped += 1
            elif kind == "rate_limit":
                self.rate_limit_hits += 1
                self.failed += 1
                self.consecutive_fail += 1
            elif kind == "intercept":
                self.intercept_412 += 1
                self.failed += 1
                self.consecutive_fail += 1
            elif kind in {"fail", "fatal", "network"}:
                self.failed += 1
                self.consecutive_fail += 1

    def snapshot_counters(self) -> dict:
        with self._lock:
            return {
                "success": self.success,
                "failed": self.failed,
                "skipped": self.skipped,
                "consecutive_fail": self.consecutive_fail,
                "rate_limit_hits": self.rate_limit_hits,
                "intercept_412": self.intercept_412,
                "last_code": self.last_code,
                "sending": self.sending,
                "simulate": self.simulate,
                "accounts_active": self.accounts_active,
            }

    def finish(self) -> None:
        with self._lock:
            self.sending = False
