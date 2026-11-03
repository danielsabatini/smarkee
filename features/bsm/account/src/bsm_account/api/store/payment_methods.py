"""Leitura local em disco das formas de pagamento por Customer Account (decisão 0082).

Consulta um arquivo JSON local validado pelo contrato `BillingAccountPaymentMethods`
(`schemas/bsm/account/payment-methods.v1.schema.json`). Se o arquivo não existir, nenhuma conta tem
forma de pagamento ativa (a criação de Billing Account `paid` é recusada com `409
PaymentMethodRequired`).
"""

import json
from pathlib import Path

from pydantic import ValidationError

from bsm_account.api.domain.errors import unavailable
from bsm_account.common.contracts import generated


class FilePaymentMethodVerifier:
    """Verifica no arquivo local se a Customer Account tem forma de pagamento `active`."""

    def __init__(self, path: Path | None) -> None:
        self._path = path

    def has_active_payment_method(self, customer_account_id: str) -> bool:
        if self._path is None or not self._path.exists():
            return False
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            registry = generated.BillingAccountPaymentMethods.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as error:
            raise unavailable(
                "Não foi possível consultar o registro de formas de pagamento. Tente de novo."
            ) from error
        return any(
            record.customer_account_id == customer_account_id
            and record.status == generated.Status.active
            for record in registry.accounts
        )
