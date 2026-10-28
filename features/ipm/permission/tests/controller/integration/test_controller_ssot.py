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
    seed_permission,
    unique_suffix,
)

from ipm_permission.controller.drivers.identity import ProviderError
from ipm_permission.controller.drivers.project_role import IdentityProjectRole
from ipm_permission.controller.engine.controller import ControllerDrivers, PermissionController
from ipm_permission.controller.settings import PermissionControllerSettings

Connection = psycopg.AsyncConnection[Any]


@dataclass
class FakeProvider:
    """Roles de projeto do Zitadel em memória. `unavailable` simula o provedor fora do ar."""

    roles: dict[str, IdentityProjectRole] = field(default_factory=lambda: {})
    unavailable: bool = False

    def _check(self) -> None:
        if self.unavailable:
            raise ProviderError("ProviderUnavailable", retryable=True)

    async def get(self, permission_name: str) -> IdentityProjectRole | None:
        self._check()
        return self.roles.get(permission_name)

    async def add_or_update_role(
        self, permission_name: str, *, display_name: str, group: str
    ) -> None:
        self._check()
        self.roles[permission_name] = IdentityProjectRole(permission_name, display_name, group)

    async def update_role(self, permission_name: str, *, display_name: str, group: str) -> None:
        self._check()
        self.roles[permission_name] = IdentityProjectRole(permission_name, display_name, group)

    async def remove_role(self, permission_name: str) -> None:
        self._check()
        self.roles.pop(permission_name, None)


def controller_of(
    pool: AsyncConnectionPool[Any], provider: FakeProvider, *, failure_limit: int = 5
) -> PermissionController:
    settings = PermissionControllerSettings()
    settings.loop.failure_limit = failure_limit
    drivers = ControllerDrivers(roles=cast("Any", provider))
    return PermissionController(cast("Any", pool), drivers, settings)


async def created(cleanup: Cleanup, api: Connection) -> str:
    resource_id = cleanup.track(f"ctl-{unique_suffix()}")
    await seed_permission(api, resource_id)
    return resource_id


async def state(connection: Connection, resource_id: str) -> Mapping[str, Any]:
    stored = await fetch_one(
        connection,
        "SELECT resource_version, phase, reconciliation, failure_count, observed_generation,"
        " desired_generation, presence FROM ipm.permission WHERE resource_id = %s",
        resource_id,
    )
    assert stored is not None
    return stored


async def outbox(reader: Connection, resource_id: str) -> list[dict[str, Any]]:
    return await fetch_all(
        reader,
        "SELECT subject, payload FROM ipm.permission_outbox WHERE resource_id = %s"
        " ORDER BY sequence",
        resource_id,
    )


async def test_creates_the_permission_and_confirms_the_generation(
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
    assert len(provider.roles) == 1
    stored = await state(api, resource_id)
    assert (stored["phase"], stored["presence"], stored["failure_count"]) == ("Ready", "present", 0)
    assert stored["observed_generation"] == stored["desired_generation"]
    sent = (await outbox(outbox_reader, resource_id))[len(before) :]
    assert [item["subject"] for item in sent] == [
        f"updated.ipm.permission.{resource_id}"
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

    async def failing_create(permission_name: str, *, display_name: str, group: str) -> None:
        raise ProviderError("ProviderUnavailable", retryable=True)

    provider.add_or_update_role = failing_create  # type: ignore[method-assign]
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
    subjects = [item["subject"].split(".")[0] for item in await outbox(outbox_reader, resource_id)]
    assert subjects.count("desired") == 1  # só o da suspensão: a admissão aqui é direta
    suspended = [
        item["payload"]
        for item in await outbox(outbox_reader, resource_id)
        if item["subject"].split(".")[0] == "desired"
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
        "UPDATE ipm.permission SET lifecycle = 'absent', desired_generation = 2,"
        " desired = jsonb_set(desired, '{lifecycle}', '\"absent\"') WHERE resource_id = %s",
        (resource_id,),
    )

    await controller.reconcile(resource_id)

    assert provider.roles == {}
    assert (
        await fetch_one(api, "SELECT 1 FROM ipm.permission WHERE resource_id = %s", resource_id)
        is None
    )
    last = (await outbox(outbox_reader, resource_id))[-1]["payload"]["data"]
    assert (last["removed"], last["phase"], last["lifecycle"]) == (True, "Deleting", "absent")
