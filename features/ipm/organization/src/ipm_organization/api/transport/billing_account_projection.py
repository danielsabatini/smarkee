"""Projeção local de Billing Accounts: dono e presença, a partir do stream `DESIRED` (decisão 0100).

Substitui a consulta HTTP ao BSM (`bsm/account`). O `StateConsumer` entrega o último `desired` de
cada Billing Account (`manager.desired.bsm.account.>`) e esta projeção guarda em memória quais
contas estão `present` e a quem pertencem (`ownerAccountId`).
"""

import json
import logging
from collections.abc import Mapping
from typing import Any

from ipm_organization.common.contracts.envelope import EnvelopeError, read_envelope

logger = logging.getLogger(__name__)

BILLING_ACCOUNT_SUBJECT = "manager.desired.bsm.account.>"
"""Subject do `DESIRED` de que a projeção se alimenta."""

_MODULE = "bsm"
_RESOURCE_TYPE = "account"
_PRESENT = "present"


class BillingAccountProjection:
    """Mapeamento de billing_account_id -> owner_account_id mantido a partir do stream `DESIRED`."""

    def __init__(self) -> None:
        self._accounts: dict[str, str] = {}

    async def on_message(self, data: bytes) -> bool:
        """Aplica um evento `desired`; devolve `True` se a projeção mudou."""
        try:
            raw: Mapping[str, Any] = json.loads(data)
            envelope = read_envelope(raw)
        except (ValueError, EnvelopeError) as error:
            logger.warning("ignoring invalid billing account desired message", exc_info=error)
            return False
        if (
            envelope.message_type.value != "desired"
            or envelope.module != _MODULE
            or envelope.resource_type != _RESOURCE_TYPE
        ):
            return False
        return self.apply(envelope.resource_id, envelope.data)

    def apply(self, resource_id: str, desired: Mapping[str, Any]) -> bool:
        owner = desired.get("ownerAccountId")
        before = self._accounts.get(resource_id)
        if desired.get("lifecycle") == _PRESENT and isinstance(owner, str) and owner:
            self._accounts[resource_id] = owner
        else:
            self._accounts.pop(resource_id, None)
        return self._accounts.get(resource_id) != before

    def is_ready_billing_account(self, billing_account_id: str, owner_account_id: str) -> bool:
        """`True` se a Billing Account existe, está presente e pertence ao solicitante."""
        return self._accounts.get(billing_account_id) == owner_account_id
