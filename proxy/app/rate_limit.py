from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    """Sliding window per key, in memory. Fine for a single container; resets on restart."""

    def __init__(self, limit: int, window_s: int):
        self.limit, self.window_s = limit, window_s
        self._hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            retry = max(1, int(self.window_s - (now - hits[0])))
            raise HTTPException(429, "Too many attempts", headers={"Retry-After": str(retry)})
        hits.append(now)


def limit_auth(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    request.app.state.limiter.check(ip)
