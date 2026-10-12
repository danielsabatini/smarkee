"""Limite de taxa em memória, por origem, para as escritas anônimas.

Janela deslizante. É um segundo nível de proteção: o primeiro é o gateway
(`docs/RESOURCE-CONTROL-SECURITY.md` §12). O estado é por instância do serviço.
"""

import time
from collections import deque
from collections.abc import Callable

MAXIMUM_TRACKED_ORIGINS = 10_000


class SlidingWindowLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._monotonic = monotonic
        self._hits: dict[str, deque[float]] = {}

    def allow(self, origin: str) -> bool:
        """Registra uma tentativa e informa se ela cabe no limite."""
        now = self._monotonic()
        if len(self._hits) >= MAXIMUM_TRACKED_ORIGINS:
            self._prune(now)
        hits = self._hits.setdefault(origin, deque())
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    def retry_after_seconds(self, origin: str) -> int:
        hits = self._hits.get(origin)
        if not hits:
            return 1
        return max(1, int(self._window - (self._monotonic() - hits[0])) + 1)

    def _prune(self, now: float) -> None:
        for origin in [
            o for o, hits in self._hits.items() if not hits or now - hits[-1] >= self._window
        ]:
            del self._hits[origin]
