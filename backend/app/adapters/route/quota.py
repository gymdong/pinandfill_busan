"""Thread-safe in-process request budget; external shared quota comes later."""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from threading import Lock

MAX_PAUSE_SECONDS = 3_600.0


class CallBudget:
    def __init__(
        self,
        limit: int,
        window_seconds: float = 86_400,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("invalid call budget configuration")
        if limit < 0 or not math.isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("invalid call budget configuration")
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._calls: deque[float] = deque()
        self._paused_until = 0.0
        self._lock = Lock()

    def allow(self) -> bool:
        with self._lock:
            now = self._clock()
            if not math.isfinite(now):
                return False
            if now < self._paused_until:
                return False
            cutoff = now - self._window_seconds
            while self._calls and self._calls[0] <= cutoff:
                self._calls.popleft()
            if len(self._calls) >= self._limit:
                return False
            self._calls.append(now)
            return True

    def pause(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("invalid pause duration")
        with self._lock:
            now = self._clock()
            if not math.isfinite(now):
                return
            self._paused_until = max(self._paused_until, now + min(seconds, MAX_PAUSE_SECONDS))
