"""Projeções locais dos recursos de outros módulos atrelados a cada conta (decisões 0040 e 0100).

Substituem a consulta HTTP aos outros módulos na exclusão da conta. Para cada tipo, o
`StateConsumer` entrega o último `desired` de cada recurso (`manager.desired.<módulo>.<tipo>.>`), e
a projeção guarda a quem ele pertence (`ownerAccountId`) enquanto estiver ativo
(`lifecycle = present`). O `DELETE` confere a projeção de forma síncrona e em memória.
"""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core_account.api.domain.attachments import Attachment
from core_account.common.contracts.envelope import EnvelopeError, read_envelope

logger = logging.getLogger(__name__)

_PRESENT = "present"


@dataclass(frozen=True, slots=True)
class AttachedKind:
    """Um tipo de recurso que pode estar atrelado a uma conta."""

    module: str
    resource_type: str
    singular: str
    plural: str

    @property
    def subject(self) -> str:
        """Subject do `DESIRED` de que a projeção se alimenta."""
        return f"desired.{self.module}.{self.resource_type}.>"


ORGANIZATIONS = AttachedKind("ipm", "organization", "Organization", "Organizations")
BILLING_ACCOUNTS = AttachedKind("bsm", "account", "Billing Account", "Billing Accounts")
SERVICES = AttachedKind("sum", "service", "serviço habilitado", "serviços habilitados")
"""Uma ligação desligada fica como histórico: só a ligada (`present`) pertence à conta."""


class AttachedProjection:
    """Dono de cada recurso ativo de um tipo, mantido a partir dos eventos `desired`."""

    def __init__(self, kind: AttachedKind) -> None:
        self.kind = kind
        self._owners: dict[str, str] = {}

    async def on_message(self, data: bytes) -> bool:
        """Aplica um evento `desired`; devolve `True` se a projeção mudou."""
        try:
            raw: Mapping[str, Any] = json.loads(data)
            envelope = read_envelope(raw)
        except (ValueError, EnvelopeError) as error:
            logger.warning("ignoring invalid desired message", exc_info=error)
            return False
        if (
            envelope.message_type.value != "desired"
            or envelope.module != self.kind.module
            or envelope.resource_type != self.kind.resource_type
        ):
            return False
        return self.apply(envelope.resource_id, envelope.data)

    def apply(self, resource_id: str, desired: Mapping[str, Any]) -> bool:
        owner = desired.get("ownerAccountId")
        active = desired.get("lifecycle") == _PRESENT and isinstance(owner, str) and bool(owner)
        before = self._owners.get(resource_id)
        if not active:
            return self._owners.pop(resource_id, None) is not None
        assert isinstance(owner, str)  # noqa: S101 (estreitamento de tipo, já verificado acima)
        self._owners[resource_id] = owner
        return before != owner

    def count(self, account_id: str) -> int:
        return sum(1 for owner in self._owners.values() if owner == account_id)


class AttachedResources:
    """O que ainda pertence a uma conta, somando as projeções dos tipos de outros módulos."""

    def __init__(self, projections: list[AttachedProjection]) -> None:
        self._projections = projections

    def of(self, account_id: str) -> list[Attachment]:
        found = [
            Attachment(item.kind.singular, item.kind.plural, item.count(account_id))
            for item in self._projections
        ]
        return [item for item in found if item.count]
