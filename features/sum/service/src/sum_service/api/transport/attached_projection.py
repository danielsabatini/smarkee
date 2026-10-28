"""Projeções locais dos recursos de outros módulos ligados a cada dono (decisões 0040, 0082 e 0100).

Substituem a consulta HTTP aos outros módulos. Para cada tipo, o `StateConsumer` entrega o último
`desired` de cada recurso (`manager.desired.<módulo>.<tipo>.>`), e a projeção guarda a quem ele
pertence (`ownerAccountId`) enquanto estiver ativo (`lifecycle = present`). Desligar `ipm` confere
as Organizations do dono, e ligar um serviço exige uma Billing Account do dono, ambos de forma
síncrona e em memória.
"""

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sum_service.api.domain.attachments import Attachment
from sum_service.common.contracts.envelope import EnvelopeError, read_envelope

logger = logging.getLogger(__name__)

_PRESENT = "present"


@dataclass(frozen=True, slots=True)
class AttachedKind:
    """Um tipo de recurso de outro módulo que pode pertencer ao dono da ligação."""

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
        """Quantos recursos ativos do tipo pertencem à conta."""
        return sum(1 for owner in self._owners.values() if owner == account_id)


DEPENDENTS_OF_SERVICE: dict[str, AttachedKind] = {"ipm": ORGANIZATIONS}
"""Recursos do dono que impedem desligar o serviço (decisão 0040). Serviço fora daqui não tem."""


class AttachedResources:
    """O que o dono tem em outros módulos, a partir das projeções locais (decisão 0100)."""

    def __init__(
        self,
        organizations: AttachedProjection,
        billing_accounts: AttachedProjection,
        consumers: Callable[[], bool],
    ) -> None:
        self._projections = {ORGANIZATIONS: organizations}
        self._billing_accounts = billing_accounts
        self._consumers_synced = consumers

    @property
    def is_synced(self) -> bool:
        return self._consumers_synced()

    def of(self, service: str, owner_account_id: str) -> list[Attachment]:
        kind = DEPENDENTS_OF_SERVICE.get(service)
        if kind is None:
            return []
        count = self._projections[kind].count(owner_account_id)
        return [Attachment(kind.singular, kind.plural, count)] if count else []

    def has_billing_account(self, owner_account_id: str) -> bool:
        return self._billing_accounts.count(owner_account_id) > 0
