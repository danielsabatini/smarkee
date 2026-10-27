"""Projeção local de uso de Billing Accounts por Organizations (decisões 0082 e 0100).

Substitui a consulta HTTP à API de Organization. O `StateConsumer` entrega o último `desired` de
cada Organization (`manager.desired.ipm.organization.>`), e esta projeção guarda quais Organizations
estão vinculadas a cada Billing Account. No `DELETE`, a checagem de recursos vinculados
(`ResourcesAttached`) é síncrona e em memória.
"""

import json
import logging
from collections.abc import Mapping
from typing import Any

from bsm_account.common.contracts.envelope import EnvelopeError, read_envelope

logger = logging.getLogger(__name__)

ORGANIZATION_SUBJECT = "manager.desired.ipm.organization.>"
"""Subject do `DESIRED` de que a projeção se alimenta."""

_MODULE = "ipm"
_RESOURCE_TYPE = "organization"
_PRESENT = "present"


class OrganizationUsageProjection:
    """Rastreia quais Billing Accounts possuem Organizations ativas vinculadas."""

    def __init__(self) -> None:
        # organization_id -> billing_account_id
        self._assignments: dict[str, str] = {}
        # billing_account_id -> count of organizations
        self._counts: dict[str, int] = {}

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
            or envelope.module != _MODULE
            or envelope.resource_type != _RESOURCE_TYPE
        ):
            return False
        return self.apply(envelope.resource_id, envelope.data)

    def apply(self, organization_id: str, desired: Mapping[str, Any]) -> bool:
        lifecycle = desired.get("lifecycle")
        billing_account_id = desired.get("billingAccountId")
        new_target = (
            billing_account_id
            if lifecycle == _PRESENT and isinstance(billing_account_id, str) and billing_account_id
            else None
        )

        old_target = self._assignments.get(organization_id)
        if old_target == new_target:
            return False

        if old_target is not None:
            c = self._counts.get(old_target, 0) - 1
            if c <= 0:
                self._counts.pop(old_target, None)
            else:
                self._counts[old_target] = c

        if new_target is not None:
            self._assignments[organization_id] = new_target
            self._counts[new_target] = self._counts.get(new_target, 0) + 1
        else:
            self._assignments.pop(organization_id, None)

        return True

    def has_attached_organizations(self, billing_account_id: str) -> bool:
        """`True` se alguma Organization ativa aponta para esta Billing Account."""
        return self._counts.get(billing_account_id, 0) > 0
