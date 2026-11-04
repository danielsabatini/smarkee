"""Testes unitários do driver Mercado Pago (`simulation_mode` e HTTP v1 via `MockTransport`)."""

from typing import Any

import httpx
import pytest

from bsm_payment.controller.drivers.base import ProviderError
from bsm_payment.controller.drivers.mercadopago.client import MercadoPagoHttpClient
from bsm_payment.controller.drivers.mercadopago.driver import MercadoPagoDriver
from bsm_payment.controller.drivers.registry import DriverRegistry

DESIRED: dict[str, Any] = {
    "lifecycle": "present",
    "customerAccountId": "cust-0001",
    "displayName": "Visa Corporativo Final 4242",
    "provider": "mercadopago",
    "methodType": "credit_card",
    "providerToken": "tok_test_apro_4242",
    "deletionProtection": True,
    "ownerAccountId": "cust-0001",
}


async def test_simulated_driver_create_observe_update_delete_and_hydration() -> None:
    driver = MercadoPagoDriver(simulation_mode=True)
    registry = DriverRegistry([driver])
    assert registry.get("mercadopago") is driver

    with pytest.raises(ProviderError) as exc_info:
        registry.get("stripe")
    assert exc_info.value.reason == "UnsupportedProvider"

    # Antes de criar, observe retorna None
    assert await driver.observe("pm-1", desired=DESIRED) is None

    # Cria o método de pagamento
    created = await driver.create("pm-1", desired=DESIRED)
    assert created.status == "active"
    assert created.brand == "visa"
    assert created.last_four_digits == "4242"
    assert created.provider_customer_id == "mp-cust-cust-000"
    assert created.provider_payment_method_id == "mp-pm-pm-1"

    observed = await driver.observe("pm-1", desired=DESIRED)
    assert observed == created

    # Update de displayName e deletionProtection
    updated_desired = {
        **DESIRED,
        "displayName": "Visa Renomeado",
        "deletionProtection": False,
    }
    updated = await driver.update("pm-1", desired=updated_desired)
    assert updated.display_name == "Visa Renomeado"
    assert updated.deletion_protection is False

    # Hidratação em nova instância do driver a partir de previous_observed
    fresh_driver = MercadoPagoDriver(simulation_mode=True)
    hydrated = await fresh_driver.observe(
        "pm-1",
        desired=updated_desired,
        previous_observed=updated.to_observed_data(),
    )
    assert hydrated is not None
    assert hydrated.display_name == "Visa Renomeado"
    assert hydrated.provider_payment_method_id == "mp-pm-pm-1"

    # Delete remove do driver
    await fresh_driver.delete(
        "pm-1",
        desired={**updated_desired, "lifecycle": "absent"},
        previous_observed=updated.to_observed_data(),
    )
    assert (
        await fresh_driver.observe(
            "pm-1",
            desired={**updated_desired, "lifecycle": "absent"},
            previous_observed=updated.to_observed_data(),
        )
        is None
    )


async def test_simulated_driver_rejects_invalid_token() -> None:
    driver = MercadoPagoDriver(simulation_mode=True)
    with pytest.raises(ProviderError) as exc_info:
        await driver.create(
            "pm-bad",
            desired={**DESIRED, "providerToken": "tok_invalid_0000"},
        )
    assert exc_info.value.reason == "InvalidPaymentToken"
    assert exc_info.value.retryable is False


async def test_remote_driver_against_mercadopago_customers_and_cards_api() -> None:
    customers: dict[str, dict[str, Any]] = {}
    cards: dict[tuple[str, str], dict[str, Any]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer TEST-mp-token"
        path = request.url.path
        if request.method == "GET" and path == "/v1/customers/search":
            email = request.url.params.get("email")
            found = [c for c in customers.values() if c.get("email") == email]
            return httpx.Response(200, json={"results": found})
        if request.method == "POST" and path == "/v1/customers":
            import json

            body = json.loads(request.content)
            cid = "mp-cust-100"
            customers[cid] = {"id": cid, **body}
            return httpx.Response(201, json=customers[cid])
        if request.method == "GET" and path.startswith("/v1/customers/") and "/cards/" not in path:
            cid = path.rsplit("/", 1)[-1]
            if cid not in customers:
                return httpx.Response(404, json={"message": "not found"})
            return httpx.Response(200, json=customers[cid])
        if request.method == "PUT" and path.startswith("/v1/customers/"):
            import json

            cid = path.rsplit("/", 1)[-1]
            body = json.loads(request.content)
            customers[cid]["metadata"] = body.get("metadata", {})
            return httpx.Response(200, json=customers[cid])
        if request.method == "POST" and path.endswith("/cards"):
            cid = path.split("/")[3]
            card_id = "mp-card-999"
            card = {
                "id": card_id,
                "last_four_digits": "4242",
                "expiration_month": 11,
                "expiration_year": 2029,
                "payment_method": {"id": "visa"},
            }
            cards[(cid, card_id)] = card
            return httpx.Response(201, json=card)
        if request.method == "GET" and "/cards/" in path:
            parts = path.split("/")
            cid, card_id = parts[3], parts[5]
            card = cards.get((cid, card_id))
            if card is None:
                return httpx.Response(404, json={"message": "card not found"})
            return httpx.Response(200, json=card)
        if request.method == "DELETE" and "/cards/" in path:
            parts = path.split("/")
            cid, card_id = parts[3], parts[5]
            cards.pop((cid, card_id), None)
            return httpx.Response(200, json={"id": card_id})
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as async_client:
        mp_client = MercadoPagoHttpClient(
            base_url="https://api.mercadopago.com",
            access_token="TEST-mp-token",
            client=async_client,
        )
        driver = MercadoPagoDriver(mp_client, simulation_mode=False)

        assert await driver.observe("pm-remote-1", desired=DESIRED) is None
        created = await driver.create("pm-remote-1", desired=DESIRED)
        assert created.provider_customer_id == "mp-cust-100"
        assert created.provider_payment_method_id == "mp-card-999"
        assert created.brand == "visa"
        assert created.last_four_digits == "4242"

        observed = await driver.observe(
            "pm-remote-1",
            desired=DESIRED,
            previous_observed=created.to_observed_data(),
        )
        assert observed is not None
        assert observed.display_name == "Visa Corporativo Final 4242"

        updated = await driver.update(
            "pm-remote-1",
            desired={**DESIRED, "displayName": "Novo Cartão", "deletionProtection": False},
            previous_observed=created.to_observed_data(),
        )
        assert updated.display_name == "Novo Cartão"
        assert updated.deletion_protection is False

        await driver.delete(
            "pm-remote-1",
            desired={**DESIRED, "lifecycle": "absent", "deletionProtection": False},
            previous_observed=updated.to_observed_data(),
        )
        assert (
            await driver.observe(
                "pm-remote-1",
                desired={**DESIRED, "lifecycle": "absent"},
                previous_observed=updated.to_observed_data(),
            )
            is None
        )
