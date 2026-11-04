"""Projeção local de métodos de pagamento (`bsm.payment`) via `DESIRED` (decisão 0100).

O `StateConsumer` entrega o último `desired` de cada método de pagamento (`desired.bsm.payment.>`)
e esta projeção guarda em memória quais métodos estão ativos (`lifecycle = present`,
`reconciliation = active`) e a qual Customer Account pertencem (`customerAccountId`).
"""

import json
import logging
from collections.abc import Mapping
from typing import Any

from bsm_account.common.contracts.envelope import EnvelopeError, read_envelope

logger = logging.getLogger(__name__)

PAYMENT_SUBJECT = "desired.bsm.payment.>"
"""Subject do `DESIRED` de que a projeção se alimenta."""

_MODULE = "bsm"
_RESOURCE_TYPE = "payment"
_PRESENT = "present"


class PaymentProjection:
    """Mapeamento de `payment_id -> customer_account_id` mantido a partir do stream `DESIRED`."""

    def __init__(self) -> None:
        self._payments: dict[str, str] = {}

    async def on_message(self, data: bytes) -> bool:
        """Aplica um evento `desired`; devolve `True` para dar `ack`."""
        try:
            raw: Mapping[str, Any] = json.loads(data)
            envelope = read_envelope(raw)
        except (ValueError, EnvelopeError) as error:
            logger.warning("ignoring invalid payment desired message", exc_info=error)
            return True
        if (
            envelope.message_type.value != "desired"
            or envelope.module != _MODULE
            or envelope.resource_type != _RESOURCE_TYPE
        ):
            return True
        self.apply(envelope.resource_id, envelope.data)
        return True

    def apply(self, payment_id: str, desired: Mapping[str, Any]) -> bool:
        customer = desired.get("customerAccountId") or desired.get("ownerAccountId")
        reconciliation = desired.get("reconciliation", "active")
        before = self._payments.get(payment_id)
        if (
            desired.get("lifecycle") == _PRESENT
            and reconciliation != "suspended"
            and isinstance(customer, str)
            and customer
        ):
            self._payments[payment_id] = customer
        else:
            self._payments.pop(payment_id, None)
        return self._payments.get(payment_id) != before

    def is_active_payment(self, payment_id: str, customer_account_id: str) -> bool:
        """`True` se o método de pagamento existe, está ativo e pertence à Customer Account."""
        return self._payments.get(payment_id) == customer_account_id
