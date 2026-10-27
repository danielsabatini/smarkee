"""Controller contra o SSOT real (decisão 0096): fases, outbox e suspensão.

O provedor (Zitadel) é simulado em memória; o banco é o real, com o papel de login do Controller.
Os testes com banco falso não pegam violação de CHECK, `GRANT` faltando nem SQL inválido.
"""

import contextlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

import psycopg
from psycopg_pool import AsyncConnectionPool
from support_controller import (
    Cleanup,
    fetch_all,
    fetch_one,
    seed_organization,
    unique_suffix,
)

from ipm_organization.controller.drivers.identity import ProviderError
from ipm_organization.controller.drivers.organization import IdentityOrganization
from ipm_organization.controller.engine.controller import ControllerDrivers, OrganizationController
from ipm_organization.controller.settings import OrganizationControllerSettings

Connection = psycopg.AsyncConnection[Any]


@dataclass
class FakeProvider:
    """Organizações do Zitadel em memória. `unavailable` simula o provedor fora do ar."""

    organizations: dict[str, IdentityOrganization] = field(default_factory=lambda: {})
    protection: dict[str, str] = field(default_factory=lambda: {})
    unavailable: bool = False

    def _check(self) -> None:
        if self.unavailable:
            raise ProviderError("ProviderUnavailable", retryable=True)

    # OrganizationDriver
    async def get_organization(self, organization_id: str) -> IdentityOrganization | None:
        self._check()
        return self.organizations.get(organization_id)

    async def create_organization(self, organization_id: str, *, name: str) -> bool:
        self._check()
        if organization_id in self.organizations:
            return False
        self.organizations[organization_id] = IdentityOrganization(name=name, active=True)
        return True

    async def rename_organization(self, organization_id: str, *, name: str) -> None:
        self._check()
        self.organizations[organization_id] = IdentityOrganization(name=name, active=True)

    async def activate_organization(self, organization_id: str) -> None:
        self._check()

    async def deactivate_organization(self, organization_id: str) -> None:
        self._check()

    async def delete_organization(self, organization_id: str) -> None:
        self._check()
        self.organizations.pop(organization_id, None)

    # MetadataDriver
    async def get_value(self, owner_id: str, key: str) -> str | None:
        self._check()
        return self.protection.get(owner_id)

    async def set_value(self, owner_id: str, key: str, value: str) -> None:
        self._check()
        self.protection[owner_id] = value

    # UserAccessDriver
    async def grant_permissions(self, organization_id: str) -> list[str] | None:
        return None

    async def list_administrators(self, organization_id: str, *, with_grant: bool) -> list[Any]:
        return []


def controller_of(
    pool: AsyncConnectionPool[Any], provider: FakeProvider, *, failure_limit: int = 5
) -> OrganizationController:
    settings = OrganizationControllerSettings()
    settings.loop.failure_limit = failure_limit
    drivers = ControllerDrivers(
        organizations=cast("Any", provider),
        metadata=cast("Any", provider),
        user_access=cast("Any", provider),
    )
    return OrganizationController(cast("Any", pool), drivers, settings)


async def created(cleanup: Cleanup, api: Connection) -> str:
    resource_id = cleanup.track(f"ctl-{unique_suffix()}")
    await seed_organization(api, resource_id)
    return resource_id


async def state(connection: Connection, resource_id: str) -> Mapping[str, Any]:
    stored = await fetch_one(
        connection,
        "SELECT resource_version, phase, reconciliation, failure_count, observed_generation,"
        " desired_generation, presence FROM ipm.organization WHERE resource_id = %s",
        resource_id,
    )
    assert stored is not None
    return stored


async def outbox(reader: Connection, resource_id: str) -> list[dict[str, Any]]:
    return await fetch_all(
        reader,
        "SELECT subject, payload FROM ipm.organization_outbox WHERE resource_id = %s"
        " ORDER BY sequence",
        resource_id,
    )


async def test_creates_the_organization_and_confirms_the_generation(
    cleanup: Cleanup,
    api: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id = await created(cleanup, api)
    provider = FakeProvider()
    controller = controller_of(controller_pool, provider)
    before = await outbox(outbox_reader, resource_id)

    retry = await controller.reconcile(resource_id)

    assert retry is False
    assert resource_id in provider.organizations
    stored = await state(api, resource_id)
    assert (stored["phase"], stored["presence"], stored["failure_count"]) == ("Ready", "present", 0)
    assert stored["observed_generation"] == stored["desired_generation"]
    sent = (await outbox(outbox_reader, resource_id))[len(before) :]
    assert [item["subject"] for item in sent] == [
        f"manager.updated.ipm.organization.{resource_id}.changed"
    ]
    data = sent[0]["payload"]["data"]
    assert (data["phase"], data["resourceVersion"]) == ("Ready", str(stored["resource_version"]))
    assert data["observedGeneration"] == data["desiredGeneration"]
    assert sent[0]["payload"]["correlationId"]


async def test_a_reevaluation_without_news_keeps_the_version_and_emits_nothing(
    cleanup: Cleanup,
    api: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id = await created(cleanup, api)
    controller = controller_of(controller_pool, FakeProvider())
    await controller.reconcile(resource_id)
    version = (await state(api, resource_id))["resource_version"]
    messages = len(await outbox(outbox_reader, resource_id))

    await controller.reconcile(resource_id)

    assert (await state(api, resource_id))["resource_version"] == version
    assert len(await outbox(outbox_reader, resource_id)) == messages


async def test_an_unavailable_provider_counts_failures_and_suspends_at_the_limit(
    cleanup: Cleanup,
    api: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id = await created(cleanup, api)
    provider = FakeProvider(unavailable=True)
    controller = controller_of(controller_pool, provider, failure_limit=2)

    # Provedor fora do ar: a observação é inconclusiva, não é falha de ação, e nada é contado.
    with contextlib.suppress(ProviderError):
        await controller.reconcile(resource_id)
    assert (await state(api, resource_id))["failure_count"] == 0

    # Observa, mas toda ação falha: cada ciclo conta uma falha.
    provider.unavailable = False

    async def failing_create(organization_id: str, *, name: str) -> bool:
        raise ProviderError("ProviderUnavailable", retryable=True)

    provider.create_organization = failing_create  # type: ignore[method-assign]
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
    subjects = [item["subject"].split(".")[1] for item in await outbox(outbox_reader, resource_id)]
    assert subjects.count("desired") == 1  # só o da suspensão: a admissão aqui é direta
    suspended = [
        item["payload"]
        for item in await outbox(outbox_reader, resource_id)
        if item["subject"].split(".")[1] == "desired"
    ][-1]
    assert suspended["data"]["reconciliation"] == "suspended"
    assert suspended["desiredGeneration"] == stored["desired_generation"]

    # Suspenso: o Controller não age mais.
    assert await controller.reconcile(resource_id) is False
    assert (await state(api, resource_id))["failure_count"] == 2


async def test_removal_deletes_the_record_and_emits_removed(
    cleanup: Cleanup,
    api: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id = await created(cleanup, api)
    provider = FakeProvider()
    controller = controller_of(controller_pool, provider)
    await controller.reconcile(resource_id)
    await api.execute(
        "UPDATE ipm.organization SET lifecycle = 'absent', desired_generation = 2,"
        " desired = jsonb_set(desired, '{lifecycle}', '\"absent\"') WHERE resource_id = %s",
        (resource_id,),
    )

    await controller.reconcile(resource_id)

    assert resource_id not in provider.organizations
    assert (
        await fetch_one(api, "SELECT 1 FROM ipm.organization WHERE resource_id = %s", resource_id)
        is None
    )
    last = (await outbox(outbox_reader, resource_id))[-1]["payload"]["data"]
    assert (last["removed"], last["phase"], last["lifecycle"]) == (True, "Deleting", "absent")
