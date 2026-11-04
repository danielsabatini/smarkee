"""Cliente HTTP assíncrono para a API v1 de Customers & Cards do Mercado Pago."""

from collections.abc import Mapping
from typing import Any, cast

import httpx

from bsm_payment.controller.drivers.base import ProviderError


class MercadoPagoHttpClient:
    """Comunicação HTTP com `https://api.mercadopago.com/v1/customers`."""

    def __init__(
        self,
        *,
        base_url: str,
        access_token: str | None,
        client: httpx.AsyncClient,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._access_token = access_token or ""
        self._client = client

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        url = f"{self._base_url}{path}"
        try:
            response = await self._client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=self._headers(idempotency_key=idempotency_key),
            )
        except httpx.HTTPError as error:
            raise ProviderError(
                "ProviderUnavailable",
                retryable=True,
                message=f"Falha de comunicação com o Mercado Pago: {type(error).__name__}",
            ) from error

        if allow_not_found and response.status_code == 404:
            return None
        if response.status_code in (401, 403):
            raise ProviderError(
                "ProviderAuthenticationFailed",
                retryable=False,
                message=f"Credencial recusada pelo Mercado Pago (HTTP {response.status_code}).",
            )
        if response.status_code in (400, 404, 422):
            raise ProviderError(
                "InvalidPaymentToken",
                retryable=False,
                message=f"Requisição recusada pelo Mercado Pago (HTTP {response.status_code}).",
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderError(
                "ProviderUnavailable",
                retryable=True,
                message=(
                    f"Mercado Pago indisponível ou limitando taxa (HTTP {response.status_code})."
                ),
            )
        if response.status_code >= 400:
            raise ProviderError(
                "ProviderRejected",
                retryable=False,
                message=f"Erro inesperado do Mercado Pago (HTTP {response.status_code}).",
            )
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderError(
                "ProviderUnavailable",
                retryable=True,
                message="Resposta JSON inválida do Mercado Pago.",
            ) from error
        return cast("dict[str, Any]", payload) if isinstance(payload, dict) else {}

    async def search_customer_by_email(self, email: str) -> dict[str, Any] | None:
        data = await self._request("GET", "/v1/customers/search", params={"email": email})
        if not data:
            return None
        results = data.get("results")
        if isinstance(results, list) and results:
            first: object = results[0]  # pyright: ignore[reportUnknownVariableType]
            if isinstance(first, dict):
                return cast("dict[str, Any]", first)
        return None

    async def get_customer(self, customer_id: str) -> dict[str, Any] | None:
        return await self._request(
            "GET",
            f"/v1/customers/{customer_id}",
            allow_not_found=True,
        )

    async def create_customer(
        self,
        *,
        email: str,
        description: str,
        metadata: Mapping[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        result = await self._request(
            "POST",
            "/v1/customers",
            json_body={
                "email": email,
                "description": description,
                "metadata": dict(metadata),
            },
            idempotency_key=idempotency_key,
        )
        return result or {}

    async def update_customer_metadata(
        self,
        customer_id: str,
        *,
        metadata: Mapping[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        result = await self._request(
            "PUT",
            f"/v1/customers/{customer_id}",
            json_body={"metadata": dict(metadata)},
            idempotency_key=idempotency_key,
        )
        return result or {}

    async def get_card(self, customer_id: str, card_id: str) -> dict[str, Any] | None:
        return await self._request(
            "GET",
            f"/v1/customers/{customer_id}/cards/{card_id}",
            allow_not_found=True,
        )

    async def create_card(
        self,
        customer_id: str,
        *,
        token: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        result = await self._request(
            "POST",
            f"/v1/customers/{customer_id}/cards",
            json_body={"token": token},
            idempotency_key=idempotency_key,
        )
        return result or {}

    async def delete_card(
        self,
        customer_id: str,
        card_id: str,
        *,
        idempotency_key: str,
    ) -> None:
        await self._request(
            "DELETE",
            f"/v1/customers/{customer_id}/cards/{card_id}",
            idempotency_key=idempotency_key,
            allow_not_found=True,
        )
