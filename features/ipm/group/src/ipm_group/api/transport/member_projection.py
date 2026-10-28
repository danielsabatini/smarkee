"""Projeção local do pertencimento: a Organization de cada usuário e service account (decisão 0100).

Substitui a consulta HTTP às APIs de User e de ServiceAccount. O `StateConsumer` entrega o último
`desired` de cada recurso (`manager.desired.ipm.user.>` e `manager.desired.ipm.serviceaccount.>`) e
esta projeção guarda só a Organization de quem está `present`; quem está sendo removido deixa de
pertencer. Pedido que chegue milissegundos após a criação do membro pode ainda não o ver
(consistência eventual) e então é tratado como "não é membro".
"""

import json
import logging
from collections.abc import Mapping
from typing import Any

from ipm_group.common.contracts.envelope import EnvelopeError, read_envelope

logger = logging.getLogger(__name__)

USER_SUBJECT = "desired.ipm.user.>"
SERVICEACCOUNT_SUBJECT = "desired.ipm.serviceaccount.>"
"""Subjects do `DESIRED` de que a projeção se alimenta."""

_MEMBER_TYPES = frozenset({"user", "serviceaccount"})
_PRESENT = "present"


class MemberProjection:
    """Organization de cada usuário e service account, mantida a partir dos eventos `desired`."""

    def __init__(self) -> None:
        self._organizations: dict[str, str] = {}

    async def on_message(self, data: bytes) -> bool:
        """Aplica um evento `desired`; devolve `True` se a projeção mudou."""
        try:
            raw: Mapping[str, Any] = json.loads(data)
            envelope = read_envelope(raw)
        except (ValueError, EnvelopeError) as error:
            logger.warning("ignoring invalid member desired message", exc_info=error)
            return False
        if (
            envelope.message_type.value != "desired"
            or envelope.module != "ipm"
            or envelope.resource_type not in _MEMBER_TYPES
        ):
            return False
        return self.apply(envelope.resource_id, envelope.data)

    def apply(self, resource_id: str, desired: Mapping[str, Any]) -> bool:
        organization_id = desired.get("organizationId")
        before = self._organizations.get(resource_id)
        if desired.get("lifecycle") == _PRESENT and isinstance(organization_id, str):
            self._organizations[resource_id] = organization_id
        else:
            self._organizations.pop(resource_id, None)
        return self._organizations.get(resource_id) != before

    def organization_of(self, subject: str) -> str | None:
        """Organization do usuário ou da service account `subject`; `None` se não é membro."""
        return self._organizations.get(subject)
