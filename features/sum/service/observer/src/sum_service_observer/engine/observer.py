"""Motor do Observer de `sum.service`: decide quando observar, lê o Zitadel e publica `observed`.

O Observer não altera o sistema externo (`docs/RESOURCE-CONTROL-LOOP.md`). Observa uma ligação:

- quando o `desired` é novo ou muda de geração (com o dono e o serviço vindos do `desired`);
- depois de cada `completed` ou `failed`, com `causationId` igual ao `messageId` do resultado;
- periodicamente, para que `observed` não envelheça.

Para de observar uma ligação desligada cuja remoção convergiu (sem roles do serviço).
"""

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from pydantic import ValidationError

from sum_service_observer.contracts import generated
from sum_service_observer.contracts.base import supports_major, validate_tolerant
from sum_service_observer.domain.observation import Observation, Reader, observe
from sum_service_observer.ids import new_identifier, utc_now
from sum_service_observer.message import MODULE, RESOURCE_TYPE, observed_envelope, subject_of

logger = logging.getLogger(__name__)


class PublishError(Exception):
    """O transporte não confirmou a publicação; a observação é refeita na próxima rodada."""


class Publisher(Protocol):
    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None: ...


def owns(resource_id: str, index: int, count: int) -> bool:
    """Partição determinística por `resourceId`: uma instância observa cada recurso."""
    digest = hashlib.sha256(resource_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % count == index


@dataclass(slots=True)
class Watch:
    owner_account_id: str
    service: str
    lifecycle: str = "present"
    generation: int = 0
    correlation_id: str | None = None
    tombstone: bool = False


def _removal_converged(watch: Watch, observation: Observation) -> bool:
    """Ligação desligada, lida como presente e sem roles do serviço: a remoção convergiu."""
    roles: object = observation.data.get("serviceRoles", [])
    return watch.lifecycle == "absent" and observation.presence == "present" and not roles


class Observer:
    def __init__(
        self,
        reader: Reader,
        publisher: Publisher,
        catalog: Mapping[str, tuple[str, ...]],
        *,
        partition_index: int = 0,
        partition_count: int = 1,
        clock: Callable[[], datetime] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
    ) -> None:
        self._partition = (partition_index, partition_count)
        self._reader = reader
        self._publisher = publisher
        self._catalog = catalog
        self._clock = clock
        self._identifiers = identifiers
        self._watches: dict[str, Watch] = {}

    async def on_message(self, data: bytes) -> str | None:
        """Trata um `desired` ou um resultado. Devolve o `resourceId` tratado, ou `None`."""
        envelope = self._parse(data)
        if envelope is None or not self._owned(envelope.resource_id):
            return None
        match envelope.message_type.value:
            case "desired":
                await self._on_desired(envelope)
            case "completed" | "failed":
                await self.observe_resource(envelope.resource_id, causation_id=envelope.message_id)
            case _:
                return None
        return envelope.resource_id

    def watch_of(self, resource_id: str) -> Watch | None:
        return self._watches.get(resource_id)

    def _owned(self, resource_id: str) -> bool:
        return owns(resource_id, *self._partition)

    @staticmethod
    def _parse(data: bytes) -> generated.MessageEnvelope | None:
        try:
            envelope = validate_tolerant(generated.MessageEnvelope, json.loads(data))
        except ValueError, ValidationError:
            logger.error("message is not a valid envelope")
            return None
        if not supports_major(envelope.schema_version):
            logger.error("schemaVersion MAJOR is not supported")
            return None
        if envelope.module != MODULE or envelope.resource_type != RESOURCE_TYPE:
            return None
        return envelope

    async def _on_desired(self, envelope: generated.MessageEnvelope) -> None:
        generation = envelope.desired_generation
        if generation is None:
            return
        data: Mapping[str, Any] = envelope.data
        owner = str(data.get("ownerAccountId", ""))
        service = str(data.get("service", ""))
        lifecycle = data.get("lifecycle")
        if not owner or not service or lifecycle not in ("present", "absent"):
            return  # sem dono, serviço e `lifecycle` válidos não há o que observar
        watch = self._watches.get(envelope.resource_id)
        if watch is not None and generation < watch.generation:
            return  # geração mais antiga
        changed = watch is None or generation != watch.generation
        if watch is None:
            watch = Watch(owner_account_id=owner, service=service)
            self._watches[envelope.resource_id] = watch
        watch.generation = generation
        watch.lifecycle = lifecycle
        watch.correlation_id = envelope.correlation_id
        if watch.lifecycle == "present":
            watch.tombstone = False
        if changed:
            await self.observe_resource(envelope.resource_id, causation_id=envelope.message_id)

    async def observe_resource(self, resource_id: str, *, causation_id: str | None) -> None:
        watch = self._watches.get(resource_id)
        if watch is None:
            return  # sem o `desired`, o Observer não sabe o que observar
        observation: Observation = await observe(
            self._reader, watch.owner_account_id, watch.service, self._catalog
        )
        if _removal_converged(watch, observation):
            watch.tombstone = True  # remoção convergida: deixa de observar
        await self._publish(resource_id, watch, observation, causation_id)

    async def observe_all(self) -> None:
        """Rodada periódica: todas as ligações que ainda são observadas."""
        for resource_id, watch in list(self._watches.items()):
            if not watch.tombstone and self._owned(resource_id):
                await self.observe_resource(resource_id, causation_id=None)

    async def _publish(
        self, resource_id: str, watch: Watch, observation: Observation, causation_id: str | None
    ) -> None:
        now = self._clock()
        message_id = self._identifiers()
        payload = observed_envelope(
            message_id=message_id,
            resource_id=resource_id,
            observation=observation,
            correlation_id=watch.correlation_id or self._identifiers(),
            causation_id=causation_id,
            now=now,
        )
        try:
            await self._publisher.publish(
                subject_of(resource_id),
                json.dumps(payload).encode(),
                message_id=message_id,
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
