"""Driver do gateway de pagamento Mercado Pago (`provider = "mercadopago"`).

Suporta dois modos de operação:
- `simulation_mode = True`: simula o cofre de clientes e cartões do Mercado Pago de forma
  determinística e sem rede externa (padrão de dev/CI local). Tokens iniciados por `tok_invalid`,
  `tok_fail` ou `invalid_` são recusados com `InvalidPaymentToken`.
- `simulation_mode = False`: opera contra a API v1 de Customers & Cards do Mercado Pago
  (`https://api.mercadopago.com/v1/customers`) via `MercadoPagoHttpClient`.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, cast

from bsm_payment.controller.drivers.base import ProviderError, ProviderPaymentMethod
from bsm_payment.controller.drivers.mercadopago.client import MercadoPagoHttpClient

_INVALID_TOKEN_PREFIXES = ("tok_invalid", "tok_fail", "invalid_")
_LAST_FOUR_DIGITS_RE = re.compile(r"([0-9]{4})$")


def _validate_simulated_token(token: str) -> None:
    lowered = token.lower()
    if any(lowered.startswith(prefix) for prefix in _INVALID_TOKEN_PREFIXES):
        raise ProviderError(
            "InvalidPaymentToken",
            retryable=False,
            message="Token de pagamento recusado pelo gateway Mercado Pago.",
        )


def _infer_card_metadata(
    method_type: str, token: str
) -> tuple[str, str | None, int | None, int | None]:
    if method_type in ("pix", "boleto"):
        return method_type, None, None, None
    lowered = token.lower()
    if "master" in lowered:
        brand = "master"
    elif "amex" in lowered:
        brand = "amex"
    elif "elo" in lowered:
        brand = "elo"
    else:
        brand = "visa"
    match = _LAST_FOUR_DIGITS_RE.search(token)
    last_four = match.group(1) if match else "4242"
    return brand, last_four, 12, 2030


def _customer_email(customer_account_id: str) -> str:
    return f"{customer_account_id}@customers.smarkee.com.br"


class MercadoPagoDriver:
    """Implementação de `PaymentGatewayDriver` para o Mercado Pago."""

    def __init__(
        self,
        http_client: MercadoPagoHttpClient | None = None,
        *,
        simulation_mode: bool = True,
    ) -> None:
        self._http_client = http_client
        self._simulation_mode = simulation_mode
        self._simulated: dict[str, ProviderPaymentMethod] = {}
        self._deleted: set[str] = set()

    @property
    def provider_name(self) -> str:
        return "mercadopago"

    async def observe(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None = None,
    ) -> ProviderPaymentMethod | None:
        if self._simulation_mode:
            return self._observe_simulated(
                resource_id, desired=desired, previous_observed=previous_observed
            )
        return await self._observe_remote(
            resource_id, desired=desired, previous_observed=previous_observed
        )

    async def create(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
    ) -> ProviderPaymentMethod:
        if self._simulation_mode:
            return self._create_simulated(resource_id, desired=desired)
        return await self._create_remote(resource_id, desired=desired)

    async def update(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None = None,
    ) -> ProviderPaymentMethod:
        if self._simulation_mode:
            return self._update_simulated(
                resource_id, desired=desired, previous_observed=previous_observed
            )
        return await self._update_remote(
            resource_id, desired=desired, previous_observed=previous_observed
        )

    async def delete(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None = None,
    ) -> None:
        if self._simulation_mode:
            self._delete_simulated(resource_id)
            return
        await self._delete_remote(resource_id, desired=desired, previous_observed=previous_observed)

    # ------------------------------------------------------------------ modo simulado (dev/CI)

    def _observe_simulated(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None,
    ) -> ProviderPaymentMethod | None:
        if resource_id in self._deleted:
            return None
        existing = self._simulated.get(resource_id)
        if existing is not None:
            return existing
        if previous_observed and previous_observed.get("providerPaymentMethodId"):
            hydrated = ProviderPaymentMethod(
                customer_account_id=str(
                    previous_observed.get("customerAccountId")
                    or desired.get("customerAccountId")
                    or desired["ownerAccountId"]
                ),
                display_name=str(
                    previous_observed.get("displayName") or desired.get("displayName", "")
                ),
                provider="mercadopago",
                method_type=str(
                    previous_observed.get("methodType") or desired.get("methodType", "credit_card")
                ),
                status=str(previous_observed.get("status") or "active"),
                provider_customer_id=str(previous_observed["providerCustomerId"]),
                provider_payment_method_id=str(previous_observed["providerPaymentMethodId"]),
                brand=(
                    str(previous_observed["brand"])
                    if previous_observed.get("brand") is not None
                    else None
                ),
                last_four_digits=(
                    str(previous_observed["lastFourDigits"])
                    if previous_observed.get("lastFourDigits") is not None
                    else None
                ),
                expiration_month=(
                    int(previous_observed["expirationMonth"])
                    if previous_observed.get("expirationMonth") is not None
                    else None
                ),
                expiration_year=(
                    int(previous_observed["expirationYear"])
                    if previous_observed.get("expirationYear") is not None
                    else None
                ),
                deletion_protection=previous_observed.get("deletionProtection", True) is not False,
            )
            self._simulated[resource_id] = hydrated
            return hydrated
        return None

    def _create_simulated(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
    ) -> ProviderPaymentMethod:
        token = str(desired.get("providerToken", ""))
        _validate_simulated_token(token)
        customer_account_id = str(desired.get("customerAccountId") or desired["ownerAccountId"])
        method_type = str(desired.get("methodType", "credit_card"))
        brand, last_four, exp_month, exp_year = _infer_card_metadata(method_type, token)
        record = ProviderPaymentMethod(
            customer_account_id=customer_account_id,
            display_name=str(desired["displayName"]),
            provider="mercadopago",
            method_type=method_type,
            status="active",
            provider_customer_id=f"mp-cust-{customer_account_id[:8]}",
            provider_payment_method_id=f"mp-pm-{resource_id[:8]}",
            brand=brand,
            last_four_digits=last_four,
            expiration_month=exp_month,
            expiration_year=exp_year,
            deletion_protection=desired.get("deletionProtection", True) is not False,
        )
        self._deleted.discard(resource_id)
        self._simulated[resource_id] = record
        return record

    def _update_simulated(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None,
    ) -> ProviderPaymentMethod:
        current = self._observe_simulated(
            resource_id, desired=desired, previous_observed=previous_observed
        )
        if current is None:
            raise ProviderError(
                "PaymentMethodNotFound",
                retryable=False,
                message="Método de pagamento não encontrado no gateway.",
            )
        updated = replace(
            current,
            display_name=str(desired["displayName"]),
            deletion_protection=desired.get("deletionProtection", True) is not False,
        )
        self._simulated[resource_id] = updated
        return updated

    def _delete_simulated(self, resource_id: str) -> None:
        self._simulated.pop(resource_id, None)
        self._deleted.add(resource_id)

    # ------------------------------------------------------------------ modo real HTTP (API v1)

    def _require_client(self) -> MercadoPagoHttpClient:
        if self._http_client is None:
            raise ProviderError(
                "ProviderMisconfigured",
                retryable=False,
                message="MercadoPagoHttpClient é obrigatório quando simulation_mode=False.",
            )
        return self._http_client

    async def _observe_remote(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None,
    ) -> ProviderPaymentMethod | None:
        client = self._require_client()
        customer_account_id = str(desired.get("customerAccountId") or desired["ownerAccountId"])
        provider_customer_id = (
            str(previous_observed["providerCustomerId"])
            if previous_observed and previous_observed.get("providerCustomerId")
            else None
        )
        provider_pm_id = (
            str(previous_observed["providerPaymentMethodId"])
            if previous_observed and previous_observed.get("providerPaymentMethodId")
            else None
        )

        customer = (
            await client.get_customer(provider_customer_id)
            if provider_customer_id
            else await client.search_customer_by_email(_customer_email(customer_account_id))
        )
        if customer is None or not customer.get("id"):
            return None

        customer_id = str(customer["id"])
        metadata = cast("dict[str, Any]", customer.get("metadata") or {})
        payments_meta = cast("dict[str, Any]", metadata.get("smarkee_payments") or {})
        entry_meta = cast("dict[str, Any]", payments_meta.get(resource_id) or {})

        card_id = provider_pm_id or str(entry_meta.get("card_id") or "")
        if not card_id:
            return None

        method_type = str(desired.get("methodType", "credit_card"))
        display_name = str(entry_meta.get("display_name") or desired.get("displayName", ""))
        deletion_protection = entry_meta.get("deletion_protection", True) is not False

        if method_type in ("pix", "boleto"):
            return ProviderPaymentMethod(
                customer_account_id=customer_account_id,
                display_name=display_name,
                provider="mercadopago",
                method_type=method_type,
                status="active",
                provider_customer_id=customer_id,
                provider_payment_method_id=card_id,
                brand=method_type,
                deletion_protection=deletion_protection,
            )

        card = await client.get_card(customer_id, card_id)
        if card is None or not card.get("id"):
            return None

        pm_info = cast("dict[str, Any]", card.get("payment_method") or {})
        brand = str(pm_info.get("id") or "visa").lower()
        last_four = (
            str(card["last_four_digits"]) if card.get("last_four_digits") is not None else None
        )
        exp_month = (
            int(card["expiration_month"]) if card.get("expiration_month") is not None else None
        )
        exp_year = int(card["expiration_year"]) if card.get("expiration_year") is not None else None

        return ProviderPaymentMethod(
            customer_account_id=customer_account_id,
            display_name=display_name,
            provider="mercadopago",
            method_type=method_type,
            status="active",
            provider_customer_id=customer_id,
            provider_payment_method_id=str(card["id"]),
            brand=brand,
            last_four_digits=last_four,
            expiration_month=exp_month,
            expiration_year=exp_year,
            deletion_protection=deletion_protection,
        )

    async def _create_remote(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
    ) -> ProviderPaymentMethod:
        client = self._require_client()
        customer_account_id = str(desired.get("customerAccountId") or desired["ownerAccountId"])
        email = _customer_email(customer_account_id)
        customer = await client.search_customer_by_email(email)
        if customer is None or not customer.get("id"):
            customer = await client.create_customer(
                email=email,
                description=f"Smarkee Customer {customer_account_id}",
                metadata={"smarkee_customer_account_id": customer_account_id},
                idempotency_key=f"cust-{customer_account_id}",
            )
        customer_id = str(customer["id"])
        method_type = str(desired.get("methodType", "credit_card"))
        token = str(desired["providerToken"])
        display_name = str(desired["displayName"])
        deletion_protection = desired.get("deletionProtection", True) is not False

        if method_type in ("pix", "boleto"):
            card_id = f"mp-{method_type}-{resource_id[:8]}"
            brand: str | None = method_type
            last_four: str | None = None
            exp_month: int | None = None
            exp_year: int | None = None
        else:
            card = await client.create_card(
                customer_id,
                token=token,
                idempotency_key=f"card-{resource_id}",
            )
            card_id = str(card["id"])
            pm_info = cast("dict[str, Any]", card.get("payment_method") or {})
            brand = str(pm_info.get("id") or "visa").lower()
            last_four = (
                str(card["last_four_digits"]) if card.get("last_four_digits") is not None else None
            )
            exp_month = (
                int(card["expiration_month"]) if card.get("expiration_month") is not None else None
            )
            exp_year = (
                int(card["expiration_year"]) if card.get("expiration_year") is not None else None
            )

        metadata = dict(cast("dict[str, Any]", customer.get("metadata") or {}))
        payments_meta = dict(cast("dict[str, Any]", metadata.get("smarkee_payments") or {}))
        payments_meta[resource_id] = {
            "card_id": card_id,
            "display_name": display_name,
            "deletion_protection": deletion_protection,
        }
        metadata["smarkee_payments"] = payments_meta
        await client.update_customer_metadata(
            customer_id,
            metadata=metadata,
            idempotency_key=f"meta-create-{resource_id}",
        )
        return ProviderPaymentMethod(
            customer_account_id=customer_account_id,
            display_name=display_name,
            provider="mercadopago",
            method_type=method_type,
            status="active",
            provider_customer_id=customer_id,
            provider_payment_method_id=card_id,
            brand=brand,
            last_four_digits=last_four,
            expiration_month=exp_month,
            expiration_year=exp_year,
            deletion_protection=deletion_protection,
        )

    async def _update_remote(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None,
    ) -> ProviderPaymentMethod:
        client = self._require_client()
        current = await self._observe_remote(
            resource_id, desired=desired, previous_observed=previous_observed
        )
        if current is None:
            raise ProviderError(
                "PaymentMethodNotFound",
                retryable=False,
                message="Método de pagamento não encontrado no Mercado Pago.",
            )
        customer = await client.get_customer(current.provider_customer_id)
        metadata = dict(cast("dict[str, Any]", (customer or {}).get("metadata") or {}))
        payments_meta = dict(cast("dict[str, Any]", metadata.get("smarkee_payments") or {}))
        display_name = str(desired["displayName"])
        deletion_protection = desired.get("deletionProtection", True) is not False
        payments_meta[resource_id] = {
            "card_id": current.provider_payment_method_id,
            "display_name": display_name,
            "deletion_protection": deletion_protection,
        }
        metadata["smarkee_payments"] = payments_meta
        digest = hashlib.sha256(
            f"{resource_id}:{display_name}:{deletion_protection}".encode()
        ).hexdigest()[:16]
        await client.update_customer_metadata(
            current.provider_customer_id,
            metadata=metadata,
            idempotency_key=f"meta-update-{resource_id}-{digest}",
        )
        return replace(
            current,
            display_name=display_name,
            deletion_protection=deletion_protection,
        )

    async def _delete_remote(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None,
    ) -> None:
        client = self._require_client()
        current = await self._observe_remote(
            resource_id, desired=desired, previous_observed=previous_observed
        )
        if current is None:
            return
        if current.method_type not in ("pix", "boleto"):
            await client.delete_card(
                current.provider_customer_id,
                current.provider_payment_method_id,
                idempotency_key=f"del-card-{resource_id}",
            )
        customer = await client.get_customer(current.provider_customer_id)
        if customer is not None:
            metadata = dict(cast("dict[str, Any]", customer.get("metadata") or {}))
            payments_meta = dict(cast("dict[str, Any]", metadata.get("smarkee_payments") or {}))
            payments_meta.pop(resource_id, None)
            metadata["smarkee_payments"] = payments_meta
            await client.update_customer_metadata(
                current.provider_customer_id,
                metadata=metadata,
                idempotency_key=f"meta-del-{resource_id}",
            )
