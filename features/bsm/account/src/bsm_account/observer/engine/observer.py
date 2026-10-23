"""Motor do Observer: decide o que observar, lê o Zitadel e publica `observed`.

O Observer transforma a realidade externa em `observed` e **não altera** o sistema externo. Observa
um recurso (`docs/RESOURCE-CONTROL-LOOP.md` §6.3, §10, §25 e §26.1):

- quando o `desired` é novo ou muda de geração;
- depois de cada `completed` ou `failed`, com `causationId` igual ao `messageId` do resultado;
- periodicamente, para que `observed` não envelheça, com jitter;
- apenas para os recursos da sua partição (`hash(resourceId) mod count == index`).
"""

import asyncio
import hashlib
import logging
import random
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bsm_account.common.contracts import generated
from bsm_account.common.contracts.envelope import EnvelopeError, read_envelope
from bsm_account.common.ids import new_identifier, utc_now
from bsm_account.common.logging_config import bind_context, restore_context, save_context
from bsm_account.common.ports import Publisher, PublishError
from bsm_account.common.resource import MODULE, RESOURCE_TYPE, SCHEMA_VERSION
from bsm_account.observer.domain.observation import (
    Drivers,
    Observation,
    log_identifiers,
    observe,
)
from bsm_account.observer.settings import AccountObserverSettings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Watch:
    """O que o Observer sabe de um recurso: o necessário para decidir quando observar."""

    lifecycle: str = "present"
    generation: int = 0
    correlation_id: str | None = None
    tombstone: bool = False
    """`lifecycle = absent` já convergido: não há mais o que observar."""


@contextmanager
def observation_context(resource_id: str, **identifiers: str) -> Generator[None]:
    """Liga o recurso observado ao contexto de log durante a observação.

    Sem isso, os logs das leituras ao sistema externo (por exemplo, a chamada HTTP ao Zitadel) saem
    sem `smarkee.resource.id`, porque a rodada periódica não nasce de uma mensagem. O contexto
    anterior é restaurado ao sair, para não vazar para o consumidor que chamou.
    """
    saved = save_context()
    bind_context(resource_id=resource_id, **identifiers)
    try:
        yield
    finally:
        restore_context(saved)


def owns(resource_id: str, index: int, count: int) -> bool:
    """Partição determinística por `resourceId`: uma instância observa cada recurso."""
    digest = hashlib.sha256(resource_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % count == index


class Observer:
    def __init__(
        self,
        drivers: Drivers,
        publisher: Publisher,
        settings: AccountObserverSettings,
        *,
        clock: Callable[[], datetime] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
        observe_resource: Callable[..., Any] = observe,
    ) -> None:
        self._drivers = drivers
        self._publisher = publisher
        self._settings = settings
        self._clock = clock
        self._identifiers = identifiers
        self._observe = observe_resource
        self._watches: dict[str, Watch] = {}
        self._reads = asyncio.Semaphore(settings.loop.maximum_concurrent_reads)

    @property
    def resource_ids(self) -> list[str]:
        return list(self._watches)

    def watch_of(self, resource_id: str) -> Watch | None:
        return self._watches.get(resource_id)

    def _owned(self, resource_id: str) -> bool:
        partition = self._settings.partition
        return owns(resource_id, partition.index, partition.count)

    # ------------------------------------------------------------------ entrada

    async def on_message(self, data: bytes) -> None:
        envelope = self._parse(data)
        if envelope is None or not self._owned(envelope.resource_id):
            return
        match envelope.message_type.value:
            case "desired":
                await self._on_desired(envelope)
            case "completed" | "failed":
                # Observação causada pelo resultado: o Reconciler só decide depois dela.
                await self.observe_resource(envelope.resource_id, causation_id=envelope.message_id)
            case _:
                return

    @staticmethod
    def _parse(data: bytes) -> generated.MessageEnvelope | None:
        try:
            envelope = read_envelope(data)
        except EnvelopeError as error:
            logger.error("message rejected", extra={"smarkee.reason": error.reason})
            return None
        if envelope.module != MODULE or envelope.resource_type != RESOURCE_TYPE:
            return None
        return envelope

    async def _on_desired(self, envelope: generated.MessageEnvelope) -> None:
        generation = envelope.desired_generation
        if generation is None:
            return
        watch = self._watches.setdefault(envelope.resource_id, Watch())
        if generation < watch.generation:
            return  # geração mais antiga: ignorada
        changed = generation != watch.generation
        watch.generation = generation
        watch.lifecycle = str(envelope.data.get("lifecycle", "present"))
        watch.correlation_id = envelope.correlation_id
        if watch.lifecycle == "present":
            watch.tombstone = False
        if changed:
            await self.observe_resource(envelope.resource_id, causation_id=envelope.message_id)

    # ------------------------------------------------------------------ observação

    async def observe_resource(self, resource_id: str, *, causation_id: str | None) -> None:
        watch = self._watches.setdefault(resource_id, Watch())
        # A geração conhecida **antes** da leitura: a observação só pode confirmar o que já era
        # desejado quando o provedor foi lido (decisão 0072). Um `desired` que chegue durante a
        # leitura não é atribuído a ela.
        generation = watch.generation
        with observation_context(resource_id, **log_identifiers(resource_id)):
            async with self._reads:
                observation: Observation = await self._observe(self._drivers, resource_id)
            if watch.lifecycle == "absent" and observation.presence == "absent":
                watch.tombstone = True  # remoção convergida: deixa de observar
            await self._publish(resource_id, watch, observation, causation_id, generation)

    async def observe_all(self) -> None:
        """Rodada periódica: todos os recursos da partição que ainda existem."""
        pending = [
            self.observe_resource(resource_id, causation_id=None)
            for resource_id, watch in self._watches.items()
            if not watch.tombstone and self._owned(resource_id)
        ]
        await asyncio.gather(*pending)

    async def _publish(
        self,
        resource_id: str,
        watch: Watch,
        observation: Observation,
        causation_id: str | None,
        generation: int,
    ) -> None:
        now = self._clock()
        envelope = generated.MessageEnvelope.model_validate(
            {
                "messageId": self._identifiers(),
                "schemaVersion": SCHEMA_VERSION,
                "messageType": "observed",
                "emitter": "observer",
                "module": MODULE,
                "resourceType": RESOURCE_TYPE,
                "resourceId": resource_id,
                "operation": "changed",
                "presence": observation.presence,
                "observedAt": now.isoformat(),
                **({"observedGeneration": generation} if generation > 0 else {}),
                **({"causationId": causation_id} if causation_id else {}),
                "correlationId": watch.correlation_id or self._identifiers(),
                "occurredAt": now.isoformat(),
                "publishedAt": now.isoformat(),
                "data": observation.data,
            }
        )
        subject = f"observer.observed.{MODULE}.{RESOURCE_TYPE}.{resource_id}.changed"
        try:
            await self._publisher.publish(
                subject,
                envelope.model_dump_json(exclude_none=True).encode(),
                message_id=envelope.message_id,
            )
        except PublishError:
            logger.warning(
                "observed publication failed", extra={"smarkee.resource.id": resource_id}
            )
            return
        logger.info(
            "observed published",
            extra={
                "smarkee.resource.id": resource_id,
                "smarkee.observation.presence": observation.presence,
            },
        )


HEARTBEAT_SLICE_SECONDS = 15.0
"""A espera entre observações é fatiada para o laço dar sinal de vida (liveness) no intervalo."""


async def periodic_observation(
    observer: Observer,
    settings: AccountObserverSettings,
    stop: asyncio.Event,
    on_cycle: Callable[[], None] = lambda: None,
) -> None:
    """Observação periódica, independente de eventos, com jitter (`LOOP.md` §25)."""
    loop = settings.loop
    while not stop.is_set():
        jitter = 1 + random.uniform(-loop.observation_jitter, loop.observation_jitter)  # noqa: S311
        remaining = loop.observation_interval_seconds * jitter
        while remaining > 0 and not stop.is_set():
            on_cycle()
            wait = min(HEARTBEAT_SLICE_SECONDS, remaining)
            try:
                await asyncio.wait_for(stop.wait(), timeout=wait)
            except TimeoutError:
                remaining -= wait
        if not stop.is_set():
            await observer.observe_all()
            on_cycle()
