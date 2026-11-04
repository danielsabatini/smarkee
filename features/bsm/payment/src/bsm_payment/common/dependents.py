"""Projeção local de uso de métodos de pagamento por Billing Accounts (decisão 0100).

O `StateConsumer` entrega o último `desired` de cada Billing Account (`desired.bsm.account.>`),
e esta projeção guarda quais Billing Accounts ativas (`lifecycle = present`) estão vinculadas a
cada método de pagamento (`paymentId`).
"""

import json
import logging
from collections.abc import Mapping
from typing import Any

from bsm_payment.common.contracts.envelope import EnvelopeError, read_envelope

logger = logging.getLogger(__name__)

BILLING_ACCOUNT_SUBJECT = "desired.bsm.account.>"
"""Subject do `DESIRED` de que a projeção se alimenta."""

_MODULE = "bsm"
_RESOURCE_TYPE = "account"
_PRESENT = "present"


class BillingAccountUsageProjection:
    """Rastreia quais métodos de pagamento possuem Billing Accounts ativas vinculadas."""

    def __init__(self) -> None:
        # billing_account_id -> payment_id
        self._assignments: dict[str, str] = {}

    async def on_message(self, data: bytes) -> bool:
        """Aplica uma mensagem do `DESIRED` à projeção; devolve `True` para dar `ack`."""
        try:
            envelope = read_envelope(data)
        except (EnvelopeError, json.JSONDecodeError, ValueError) as error:
            logger.warning(
                "invalid desired message in billing account usage projection, skipping",
                extra={"error.type": type(error).__name__},
            )
            return True
        if (
            envelope.message_type != "desired"
            or envelope.module != _MODULE
            or envelope.resource_type != _RESOURCE_TYPE
        ):
            return True
        self._apply(envelope.resource_id, envelope.data)
        return True

    def _apply(self, billing_account_id: str, data: Mapping[str, Any]) -> None:
        lifecycle = data.get("lifecycle")
        payment_id = data.get("paymentId")
        if lifecycle == _PRESENT and isinstance(payment_id, str) and payment_id:
            self._assignments[billing_account_id] = payment_id
        else:
            self._assignments.pop(billing_account_id, None)

    def has_attached_billing_accounts(self, payment_id: str) -> bool:
        """Indica se alguma Billing Account ativa referencia `payment_id`."""
        return payment_id in self._assignments.values()
