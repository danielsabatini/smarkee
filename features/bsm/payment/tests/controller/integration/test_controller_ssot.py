"""Controller de `bsm.payment` contra o SSOT real (decisão 0096)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

import psycopg
from psycopg_pool import AsyncConnectionPool
from support_controller import (
    Cleanup,
    fetch_all,
    fetch_one,
    seed_payment,
    unique_suffix,
)

from bsm_payment.controller.drivers.base import ProviderError, ProviderPaymentMethod
from bsm_payment.controller.drivers.registry import DriverRegistry
from bsm_payment.controller.engine.controller import PaymentController
from bsm_payment.controller.settings import LoopSettings

Connection = psycopg.AsyncConnection[Any]


@dataclass
class FakeGatewayDriver:
    """Gateway de pagamento (Mercado Pago) em memória para os testes de integração SSOT."""

    provider_name: str = "mercadopago"
    cards: dict[str, ProviderPaymentMethod] = field(default_factory=lambda: {})
    unavailable: bool = False
    failing_create: bool = False

    def _check(self) -> None:
        if self.unavailable:
            raise ProviderError("ProviderUnavailable", retryable=True)

    async def observe(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None = None,
    ) -> ProviderPaymentMethod | None:
        self._check()
        return self.cards.get(resource_id)

    async def create(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
    ) -> ProviderPaymentMethod:
        self._check()
        if self.failing_create:
            raise ProviderError("GatewayError", retryable=True)
        customer_account_id = str(desired.get("customerAccountId", "cust-1"))
        method = ProviderPaymentMethod(
            customer_account_id=customer_account_id,
            display_name=str(desired.get("displayName", "Visa")),
            provider="mercadopago",
            method_type=str(desired.get("methodType", "credit_card")),
            status="active",
            provider_customer_id=f"mp_cust_{customer_account_id}",
            provider_payment_method_id=f"mp_card_{resource_id[:8]}",
            brand="visa",
            last_four_digits="4242",
            expiration_month=12,
            expiration_year=2030,
            deletion_protection=desired.get("deletionProtection", True) is not False,
        )
        self.cards[resource_id] = method
        return method

    async def update(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None = None,
    ) -> ProviderPaymentMethod:
        return await self.create(resource_id, desired=desired)

    async def delete(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        previous_observed: Mapping[str, Any] | None = None,
    ) -> None:
        self._check()
        self.cards.pop(resource_id, None)


def controller_of(
    pool: AsyncConnectionPool[Any],
    driver: FakeGatewayDriver,
    *,
    failure_limit: int = 5,
) -> PaymentController:
    registry = DriverRegistry([driver])
    loop_settings = LoopSettings(failure_limit=failure_limit)
    return PaymentController(cast("Any", pool), registry, loop_settings=loop_settings)


async def created(
    cleanup: Cleanup, api: Connection, *, lifecycle: str = "present"
) -> tuple[str, str]:
    resource_id = cleanup.track(f"ctl-{unique_suffix()}")
    owner = f"own-{unique_suffix()}"
    await seed_payment(api, resource_id, owner=owner, lifecycle=lifecycle)
    return resource_id, owner


async def state(connection: Connection, resource_id: str) -> Mapping[str, Any]:
    stored = await fetch_one(
        connection,
        "SELECT resource_version, phase, reconciliation, failure_count, observed_generation,"
        " desired_generation, presence, observed FROM bsm.payment WHERE resource_id = %s",
        resource_id,
    )
    assert stored is not None
    return stored


async def outbox(reader: Connection, resource_id: str) -> list[dict[str, Any]]:
    return await fetch_all(
        reader,
        "SELECT subject, payload FROM bsm.payment_outbox WHERE resource_id = %s ORDER BY sequence",
        resource_id,
    )


async def test_registers_payment_method_and_confirms_generation(
    cleanup: Cleanup,
    api: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id, _ = await created(cleanup, api)
    driver = FakeGatewayDriver()
    controller = controller_of(controller_pool, driver)
    before = await outbox(outbox_reader, resource_id)

    retry = await controller.reconcile(resource_id)

    assert retry is False
    stored = await state(api, resource_id)
    assert (stored["phase"], stored["presence"], stored["failure_count"]) == ("Ready", "present", 0)
    assert stored["observed_generation"] == stored["desired_generation"]
    assert stored["observed"]["brand"] == "visa"
    assert stored["observed"]["lastFourDigits"] == "4242"

    sent = (await outbox(outbox_reader, resource_id))[len(before) :]
    assert [item["subject"] for item in sent] == [f"updated.bsm.payment.{resource_id}"]
    data = sent[0]["payload"]["data"]
    assert (data["phase"], data["resourceVersion"]) == ("Ready", str(stored["resource_version"]))
    assert data["observedGeneration"] == data["desiredGeneration"]


async def test_reevaluation_without_drift_keeps_version_and_emits_nothing(
    cleanup: Cleanup,
    api: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id, _ = await created(cleanup, api)
    driver = FakeGatewayDriver()
    controller = controller_of(controller_pool, driver)
    await controller.reconcile(resource_id)
    version = (await state(api, resource_id))["resource_version"]
    messages = len(await outbox(outbox_reader, resource_id))

    await controller.reconcile(resource_id)

    assert (await state(api, resource_id))["resource_version"] == version
    assert len(await outbox(outbox_reader, resource_id)) == messages


async def test_deletion_removes_from_gateway_and_deletes_row_from_ssot(
    cleanup: Cleanup,
    api: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id, _ = await created(cleanup, api)
    driver = FakeGatewayDriver()
    controller = controller_of(controller_pool, driver)
    await controller.reconcile(resource_id)
    assert len(driver.cards) == 1

    await api.execute(
        "UPDATE bsm.payment SET lifecycle = 'absent', phase = 'Deleting', desired_generation = 2,"
        " desired = jsonb_set(desired, '{lifecycle}', '\"absent\"') WHERE resource_id = %s",
        (resource_id,),
    )

    await controller.reconcile(resource_id)

    assert len(driver.cards) == 0
    assert (
        await fetch_one(api, "SELECT 1 FROM bsm.payment WHERE resource_id = %s", resource_id)
        is None
    )
    last = (await outbox(outbox_reader, resource_id))[-1]["payload"]["data"]
    assert last.get("removed") is True


async def test_unavailable_provider_counts_failures_and_suspends_at_limit(
    cleanup: Cleanup,
    api: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id, _ = await created(cleanup, api)
    driver = FakeGatewayDriver(failing_create=True)
    controller = controller_of(controller_pool, driver, failure_limit=2)

    assert await controller.reconcile(resource_id) is True
    first = await state(api, resource_id)
    assert (first["phase"], first["failure_count"], first["reconciliation"]) == (
        "Reconciling",
        1,
        "active",
    )

    assert await controller.reconcile(resource_id) is False
    stored = await state(api, resource_id)
    assert (stored["phase"], stored["failure_count"], stored["reconciliation"]) == (
        "Failed",
        2,
        "suspended",
    )
    sent = await outbox(outbox_reader, resource_id)
    desired = [item["payload"] for item in sent if item["subject"].split(".")[0] == "desired"]
    assert len(desired) == 1
    assert desired[0]["data"]["reconciliation"] == "suspended"

    assert await controller.reconcile(resource_id) is False
    assert (await state(api, resource_id))["failure_count"] == 2
