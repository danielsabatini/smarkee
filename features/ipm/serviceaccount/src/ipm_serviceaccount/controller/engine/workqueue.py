"""Fila assíncrona de reconciliação (Workqueue) com deduplicação e backoff exponencial.

Inspirada na Workqueue do client-go / Kubernetes (referência de mercado, AGENTS.md §2.7):
- Deduplicação: se uma chave já está na fila ou sendo processada por um worker, novas chegadas
  marcam a chave como 'dirty' para um único reprocessamento posterior, sem duplicar na fila.
- Backoff exponencial com jitter em caso de falha transitória (ex: indisponibilidade do provedor).
- Rastreamento de falhas por chave com reset explícito (forget) em caso de sucesso.
"""

import asyncio
import logging
import random
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ipm_serviceaccount.common.ids import utc_now

logger = logging.getLogger(__name__)


class Workqueue:
    def __init__(
        self,
        *,
        base_backoff_seconds: float = 0.5,
        max_backoff_seconds: float = 60.0,
        jitter_factor: float = 0.2,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._dirty: set[str] = set()
        self._processing: set[str] = set()
        self._failures: dict[str, int] = {}
        self._base_backoff_seconds = base_backoff_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._jitter_factor = jitter_factor
        self._clock = clock
        self._scheduled_tasks: set[asyncio.Task[Any]] = set()

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def dirty_keys(self) -> frozenset[str]:
        return frozenset(self._dirty)

    @property
    def processing_keys(self) -> frozenset[str]:
        return frozenset(self._processing)

    def add(self, key: str) -> None:
        """Enfileira a chave para reconciliação com deduplicação."""
        if key in self._processing:
            self._dirty.add(key)
            return
        if key in self._dirty:
            return
        self._dirty.add(key)
        self._queue.put_nowait(key)

    async def get(self) -> str:
        """Aguarda e obtém a próxima chave pronta para reconciliação."""
        key = await self._queue.get()
        self._dirty.discard(key)
        self._processing.add(key)
        return key

    def done(self, key: str) -> None:
        """Sinaliza que o worker concluiu o ciclo de processamento da chave."""
        self._processing.discard(key)
        if key in self._dirty:
            self._dirty.discard(key)
            self._queue.put_nowait(key)

    def forget(self, key: str) -> None:
        """Reseta o histórico de falhas da chave (sucesso na reconciliação)."""
        self._failures.pop(key, None)

    def add_rate_limited(self, key: str) -> float:
        """Agenda reprocessamento com backoff exponencial + jitter após falha transitória."""
        count = self._failures.get(key, 0) + 1
        self._failures[key] = count
        backoff = min(
            self._max_backoff_seconds,
            self._base_backoff_seconds * (2 ** (count - 1)),
        )
        jitter = 1 + random.uniform(-self._jitter_factor, self._jitter_factor)  # noqa: S311
        delay = max(0.05, backoff * jitter)

        task = asyncio.create_task(self._delay_add(key, delay))
        self._scheduled_tasks.add(task)
        task.add_done_callback(self._scheduled_tasks.discard)
        return delay

    async def _delay_add(self, key: str, delay: float) -> None:
        await asyncio.sleep(delay)
        self.add(key)

    def close(self) -> None:
        for task in self._scheduled_tasks:
            task.cancel()
        self._scheduled_tasks.clear()
