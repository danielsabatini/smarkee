"""Projeção local das Organizations: dono e ciclo de vida, a partir do `DESIRED` (decisão 0100).

Substitui a consulta HTTP à API da Organization: o `StateConsumer` entrega o último `desired` de
cada Organization (`manager.desired.ipm.organization.>`) e esta projeção guarda só o necessário para
decidir o acesso, sem I/O no pedido. A API só fica pronta depois do replay inicial; o pedido que
chega logo após criar uma Organization pode, por milissegundos, ainda não a ver (consistência
eventual), e então é tratado como "não encontrada".
"""

import json
import logging
from collections.abc import Mapping
from typing import Any

from ipm_user.api.domain.access import OrganizationAccess
from ipm_user.common.contracts.envelope import EnvelopeError, read_envelope

logger = logging.getLogger(__name__)

ORGANIZATION_SUBJECT = "manager.desired.ipm.organization.>"
"""Subject do `DESIRED` de que a projeção se alimenta."""

_PRESENT = "present"


class OrganizationProjection:
    """Dono e presença de cada Organization, mantidos a partir dos eventos `desired`."""

    def __init__(self) -> None:
        self._owners: dict[str, str] = {}

    async def on_message(self, data: bytes) -> bool:
        """Aplica um evento `desired`; devolve `True` se a projeção mudou."""
        try:
            raw: Mapping[str, Any] = json.loads(data)
            envelope = read_envelope(raw)
        except (ValueError, EnvelopeError) as error:
            logger.warning("ignoring invalid organization desired message", exc_info=error)
            return False
        if (
            envelope.message_type.value != "desired"
            or envelope.module != "ipm"
            or envelope.resource_type != "organization"
        ):
            return False
        return self.apply(envelope.resource_id, envelope.data)

    def apply(self, resource_id: str, desired: Mapping[str, Any]) -> bool:
        owner = desired.get("ownerAccountId")
        before = self._owners.get(resource_id)
        if desired.get("lifecycle") == _PRESENT and isinstance(owner, str) and owner:
            self._owners[resource_id] = owner
        else:
            self._owners.pop(resource_id, None)
        return self._owners.get(resource_id) != before

    def access(self, organization_id: str, subject: str) -> OrganizationAccess:
        """`OWNED` se a Organization existe, não está sendo removida e o `subject` é o dono."""
        if self._owners.get(organization_id) == subject:
            return OrganizationAccess.OWNED
        return OrganizationAccess.NOT_OWNED
