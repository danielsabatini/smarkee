"""Motor do Observer: decide quando observar, lê o Zitadel e publica `observed`.

O Observer não altera o sistema externo (`docs/loop/RESOURCE-CONTROL-LOOP.md`). Observa um recurso:

- quando o `desired` é novo ou muda de geração;
- depois de cada `completed` ou `failed`, com `causationId` igual ao `messageId` do resultado;
- periodicamente, para que `observed` não envelheça.

Para de observar um recurso com `lifecycle = absent` cuja remoção já convergiu (`absent` observado).
"""

import asyncio
import hashlib
import logging
import random
from collections.abc import Awaitable, Callable, Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ipm_permission.common.contracts import generated
from ipm_permission.common.contracts.envelope import EnvelopeError, read_envelope
from ipm_permission.common.ids import new_identifier, utc_now
from ipm_permission.common.logging_config import bind_context, restore_context, save_context
from ipm_permission.common.ports import Publisher, PublishError
from ipm_permission.common.resource import MODULE, RESOURCE_TYPE, SCHEMA_VERSION
from ipm_permission.observer.domain.observation import Drivers, Observation, observe
from ipm_permission.observer.settings import PartitionSettings, PermissionObserverSettings

logger = logging.getLogger(__name__)


@contextmanager
def observation_context(resource_id: str, **fields: str | None) -> Generator[None]:
    """Amarra os identificadores da observação aos logs e restaura o contexto ao sair."""
    saved = save_context()
    bind_context(resource_id=resource_id, actor_type="system", **fields)
    try:
        yield
    finally:
        restore_context(saved)


@dataclass(slots=True)
class Watch:
    """O que a instância acompanha de um recurso."""

    generation: int = 0
    lifecycle: str = "present"
    permission_name: str | None = None
    tombstone: bool = False
    """`True` quando `lifecycle = absent` e a ausência no provedor já foi observada."""


def owns_partition(resource_id: str, partition: PartitionSettings) -> bool:
    if partition.count <= 1:
        return True
    digest = int.from_bytes(hashlib.blake2b(resource_id.encode(), digest_size=8).digest(), "big")
    return digest % partition.count == partition.index


ObserveFn = Callable[[Drivers, str | None], Awaitable[Observation]]


class Observer:
    def __init__(
        self,
        drivers: Drivers,
        publisher: Publisher,
        settings: PermissionObserverSettings,
        *,
        observe_fn: ObserveFn = observe,
        clock: Callable[[], datetime] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
    ) -> None:
        self._drivers = drivers
        self._publisher = publisher
        self._settings = settings
        self._observe = observe_fn
        self._clock = clock
        self._identifiers = identifiers
        self._watches: dict[str, Watch] = {}
        self._reads = asyncio.Semaphore(settings.loop.maximum_concurrent_reads)

    @property
    def watched_ids(self) -> list[str]:
        return [rid for rid, watch in self._watches.items() if not watch.tombstone]

    def watch_of(self, resource_id: str) -> Watch | None:
        return self._watches.get(resource_id)

    # ------------------------------------------------------------------ entrada

    async def on_message(self, data: bytes) -> None:
        try:
            envelope = read_envelope(data)
        except EnvelopeError as error:
            logger.error("message rejected", extra={"smarkee.reason": error.reason})
            return
        if envelope.module != MODULE or envelope.resource_type != RESOURCE_TYPE:
            logger.error("message of another type ignored")
            return
        if not owns_partition(envelope.resource_id, self._settings.partition):
            return
        match envelope.message_type.value:
            case "desired":
                await self._on_desired(envelope)
            case "completed" | "failed":
                await self.observe_resource(envelope.resource_id, causation_id=envelope.message_id)
            case _:
                pass

    async def _on_desired(self, envelope: generated.MessageEnvelope) -> None:
        generation = envelope.desired_generation
        if generation is None:
            return
        watch = self._watches.setdefault(envelope.resource_id, Watch())
        if generation < watch.generation:
            return
        data: Mapping[str, Any] = envelope.data
        changed = generation != watch.generation
        watch.generation = generation
        watch.lifecycle = str(data.get("lifecycle", "present"))
        name = data.get("name")
        if isinstance(name, str) and name:
            watch.permission_name = name
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
        permission_name = watch.permission_name
        with observation_context(resource_id):
            async with self._reads:
                observation: Observation = await self._observe(self._drivers, permission_name)
            if watch.lifecycle == "absent" and observation.presence == "absent":
                watch.tombstone = True  # remoção convergiu: não observa mais nos ciclos periódicos
            await self._publish(
                resource_id,
                observation,
                causation_id=causation_id,
                observed_generation=generation or None,
            )

    async def observe_all(self) -> None:
        for resource_id in self.watched_ids:
            await self.observe_resource(resource_id, causation_id=None)

    async def _publish(
        self,
        resource_id: str,
        observation: Observation,
        *,
        causation_id: str | None,
        observed_generation: int | None,
    ) -> None:
        now = self._clock()
        message_id = self._identifiers()
        envelope = generated.MessageEnvelope.model_validate(
            {
                "messageId": message_id,
                "schemaVersion": SCHEMA_VERSION,
                "messageType": "observed",
                "emitter": "observer",
                "module": MODULE,
                "resourceType": RESOURCE_TYPE,
                "resourceId": resource_id,
                "operation": "changed",
                "presence": observation.presence,
                "observedAt": now.isoformat(),
                **(
                    {"observedGeneration": observed_generation}
                    if observed_generation is not None
                    else {}
                ),
                "correlationId": self._identifiers(),
                **({"causationId": causation_id} if causation_id else {}),
                "occurredAt": now.isoformat(),
                "publishedAt": now.isoformat(),
                "data": observation.observed,
            }
        )
        subject = f"observer.observed.{MODULE}.{RESOURCE_TYPE}.{resource_id}.changed"
        try:
            await self._publisher.publish(
                subject,
                envelope.model_dump_json(exclude_none=True).encode(),
                message_id=message_id,
            )
        except PublishError:
            logger.warning(
                "observed publication failed",
                extra={"smarkee.resource.id": resource_id},
            )
            return
        logger.debug(
            "observed published",
            extra={"smarkee.resource.id": resource_id, "smarkee.presence": observation.presence},
        )


async def periodic_observation(
    observer: Observer,
    settings: PermissionObserverSettings,
    stop: asyncio.Event,
    on_cycle: Callable[[], None] = lambda: None,
) -> None:
    """Observa os recursos acompanhados em `observationInterval`, com jitter ±20%."""
    while not stop.is_set():
        on_cycle()
        jitter = 1 + random.uniform(  # noqa: S311 (jitter, não criptografia)
            -settings.loop.observation_jitter, settings.loop.observation_jitter
        )
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=settings.loop.observation_interval_seconds * jitter
            )
        except TimeoutError:
            await observer.observe_all()
