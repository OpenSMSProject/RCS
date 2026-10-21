import threading
import time
from collections import defaultdict, deque
from typing import Callable


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic):
        if int(limit) < 1:
            raise ValueError("limit must be >= 1")
        self.limit = int(limit)
        self.window_seconds = float(window_seconds)
        self.clock = clock
        self._events = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events[str(key)]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True
