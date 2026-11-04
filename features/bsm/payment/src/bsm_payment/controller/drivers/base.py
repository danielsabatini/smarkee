"""Contrato comum (Protocol) para drivers de gateways de pagamento externos.

Permite plugar múltiplos provedores (Mercado Pago, Stripe, Adyen, Pagar.me) mantendo o motor do
Controller e as regras de domínio agnósticos ao gateway específico.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(Exception):
    """Erro reportado pelo driver do gateway de pagamento."""

    def __init__(self, reason: str, *, retryable: bool = False, message: str = "") -> None:
        super().__init__(f"{reason}: {message}" if message else reason)
        self.reason = reason
        self.retryable = retryable
        self.message = message


@dataclass(frozen=True, slots=True)
class ProviderPaymentMethod:
    """Metadados não sensíveis retornados pelo gateway de pagamento."""

    customer_account_id: str
    display_name: str
    provider: str
    method_type: str
    status: str
    provider_customer_id: str
    provider_payment_method_id: str
    brand: str | None = None
    last_four_digits: str | None = None
    expiration_month: int | None = None
    expiration_year: int | None = None
    deletion_protection: bool = True

    def to_observed_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "customerAccountId": self.customer_account_id,
            "displayName": self.display_name,
            "provider": self.provider,
            "methodType": self.method_type,
            "status": self.status,
            "providerCustomerId": self.provider_customer_id,
            "providerPaymentMethodId": self.provider_payment_method_id,
            "deletionProtection": self.deletion_protection,
        }
        if self.brand is not None:
            data["brand"] = self.brand
        if self.last_four_digits is not None:
            data["lastFourDigits"] = self.last_four_digits
        if self.expiration_month is not None:
            data["expirationMonth"] = self.expiration_month
        if self.expiration_year is not None:
            data["expirationYear"] = self.expiration_year
        return data


class PaymentGatewayDriver(Protocol):
    """Interface que todo driver de gateway de pagamento implementa."""

    @property
    def provider_name(self) -> str: ...

    async def observe(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None = None,
    ) -> ProviderPaymentMethod | None: ...

    async def create(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
    ) -> ProviderPaymentMethod: ...

    async def update(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None = None,
    ) -> ProviderPaymentMethod: ...

    async def delete(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None = None,
    ) -> None: ...
