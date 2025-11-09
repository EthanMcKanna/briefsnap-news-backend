"""Simple thread-safe rate limiter for controlling task start cadence."""

import threading
import time


class RateLimiter:
    """Ensures at most one permit is granted per configured interval."""

    def __init__(self, min_interval: float = 0.0):
        self.min_interval = max(0.0, float(min_interval))
        self._lock = threading.Lock()
        self._next_time = time.monotonic()

    def acquire(self):
        """Block until the next permit is available."""
        if self.min_interval <= 0:
            return

        while True:
            with self._lock:
                now = time.monotonic()
                wait = self._next_time - now
                if wait <= 0:
                    self._next_time = max(now, self._next_time) + self.min_interval
                    return
            time.sleep(max(min(wait, self.min_interval), 0.0))
