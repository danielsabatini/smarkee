"""Controller contra o SSOT real (decisão 0096): fases, outbox, suspensão e remoção do dono.

O provedor (Zitadel) é simulado em memória; o banco é o real, com o papel de login do Controller.
Os testes com banco falso não pegam violação de CHECK, `GRANT` faltando nem SQL inválido.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

import psycopg
from psycopg_pool import AsyncConnectionPool
from support_controller import (
    PERMISSIONS,
    Cleanup,
    fetch_all,
    fetch_one,
    seed_link,
    unique_suffix,
)

from sum_service.controller.drivers.authorization import Grant
from sum_service.controller.drivers.identity import ProviderError
from sum_service.controller.engine.account_removed import AccountRemovedHandler
from sum_service.controller.engine.controller import ControllerDrivers, ServiceController
from sum_service.controller.settings import SumServiceControllerSettings

Connection = psycopg.AsyncConnection[Any]
PROJECT = "p-ipm"


@dataclass
class FakeProvider:
    """Usuários e autorizações do Zitadel em memória.

    `unavailable` simula o provedor fora do ar; `missing` são os usuários que o Zitadel não tem.
    """

    missing: set[str] = field(default_factory=lambda: set())
    grants_by_user: dict[str, list[Grant]] = field(default_factory=lambda: {})
    unavailable: bool = False
    failing_grants: bool = False

    def _check(self) -> None:
        if self.unavailable:
            raise ProviderError("ProviderUnavailable", retryable=True)

    # UserDriver
    async def exists(self, user_id: str) -> bool:
        self._check()
        return user_id not in self.missing

    # AuthorizationDriver
    def project_of(self, permission: str) -> str:
        return PROJECT

    async def grants(self, user_id: str) -> list[Grant]:
        self._check()
        return list(self.grants_by_user.get(user_id, []))

    async def create_grant(self, user_id: str, project_id: str, permissions: list[str]) -> None:
        self._check()
        if self.failing_grants:
            raise ProviderError("ProviderUnavailable", retryable=True)
        self.grants_by_user.setdefault(user_id, []).append(
            Grant(f"g-{user_id}", project_id, frozenset(permissions))
        )

    async def update_grant(self, grant_id: str, permissions: list[str]) -> None:
        self._check()
        for user_id, grants in self.grants_by_user.items():
            self.grants_by_user[user_id] = [
                Grant(g.grant_id, g.project_id, frozenset(permissions))
                if g.grant_id == grant_id
                else g
                for g in grants
            ]

    async def remove_grant(self, grant_id: str) -> None:
        self._check()
        for user_id, grants in self.grants_by_user.items():
            self.grants_by_user[user_id] = [g for g in grants if g.grant_id != grant_id]


def controller_of(
    pool: AsyncConnectionPool[Any], provider: FakeProvider, *, failure_limit: int = 5
) -> ServiceController:
    settings = SumServiceControllerSettings()
    settings.loop.failure_limit = failure_limit
    drivers = ControllerDrivers(users=cast("Any", provider), authorizations=cast("Any", provider))
    return ServiceController(cast("Any", pool), drivers, settings)


async def created(
    cleanup: Cleanup, api: Connection, *, lifecycle: str = "present"
) -> tuple[str, str]:
    """Cria uma ligação; devolve `(resource_id, dono)`."""
    resource_id = cleanup.track(f"ctl-{unique_suffix()}")
    owner = f"own-{unique_suffix()}"
    await seed_link(api, resource_id, owner=owner, lifecycle=lifecycle)
    return resource_id, owner


def held(provider: FakeProvider, owner: str) -> set[str]:
    return {p for g in provider.grants_by_user.get(owner, []) for p in g.permissions}


async def state(connection: Connection, resource_id: str) -> Mapping[str, Any]:
    stored = await fetch_one(
        connection,
        "SELECT resource_version, phase, reconciliation, failure_count, observed_generation,"
        " desired_generation, presence FROM sum.service WHERE resource_id = %s",
        resource_id,
    )
    assert stored is not None
    return stored


async def outbox(reader: Connection, resource_id: str) -> list[dict[str, Any]]:
    return await fetch_all(
        reader,
        "SELECT subject, payload FROM sum.service_outbox WHERE resource_id = %s ORDER BY sequence",
        resource_id,
    )


async def test_enables_the_link_and_confirms_the_generation(
    cleanup: Cleanup,
    api: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id, owner = await created(cleanup, api)
    provider = FakeProvider()
    controller = controller_of(controller_pool, provider)
    before = await outbox(outbox_reader, resource_id)

    retry = await controller.reconcile(resource_id)

    assert retry is False
    assert held(provider, owner) == set(PERMISSIONS)
    stored = await state(api, resource_id)
    assert (stored["phase"], stored["presence"], stored["failure_count"]) == ("Ready", "present", 0)
    assert stored["observed_generation"] == stored["desired_generation"]
    sent = (await outbox(outbox_reader, resource_id))[len(before) :]
    assert [item["subject"] for item in sent] == [f"updated.sum.service.{resource_id}"]
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
    resource_id, _ = await created(cleanup, api)
    controller = controller_of(controller_pool, FakeProvider())
    await controller.reconcile(resource_id)
    version = (await state(api, resource_id))["resource_version"]
    messages = len(await outbox(outbox_reader, resource_id))

    await controller.reconcile(resource_id)

    assert (await state(api, resource_id))["resource_version"] == version
    assert len(await outbox(outbox_reader, resource_id)) == messages


async def test_drift_in_the_provider_is_corrected(
    cleanup: Cleanup,
    api: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id, owner = await created(cleanup, api)
    provider = FakeProvider()
    controller = controller_of(controller_pool, provider)
    await controller.reconcile(resource_id)
    provider.grants_by_user[owner] = []  # alguém revogou as permissões no provedor

    await controller.reconcile(resource_id)

    assert held(provider, owner) == set(PERMISSIONS)
    assert (await state(api, resource_id))["phase"] == "Ready"


async def test_disabling_revokes_the_permissions_and_keeps_the_row(
    cleanup: Cleanup,
    api: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id, owner = await created(cleanup, api)
    provider = FakeProvider()
    controller = controller_of(controller_pool, provider)
    await controller.reconcile(resource_id)
    await api.execute(
        "UPDATE sum.service SET lifecycle = 'absent', desired_generation = 2,"
        " desired = jsonb_set(jsonb_set(desired, '{lifecycle}', '\"absent\"'),"
        " '{servicePermissions}', '[]') WHERE resource_id = %s",
        (resource_id,),
    )

    await controller.reconcile(resource_id)

    assert held(provider, owner) == set()
    stored = await state(api, resource_id)  # a linha continua (decisão 0033)
    assert (stored["phase"], stored["observed_generation"]) == ("Ready", 2)
    last = (await outbox(outbox_reader, resource_id))[-1]["payload"]["data"]
    assert last["lifecycle"] == "absent" and "removed" not in last


async def test_a_missing_owner_keeps_the_enabled_link_reconciling(
    cleanup: Cleanup,
    api: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id, owner = await created(cleanup, api)
    provider = FakeProvider(missing={owner})
    controller = controller_of(controller_pool, provider)

    assert await controller.reconcile(resource_id) is True

    stored = await state(api, resource_id)
    assert (stored["phase"], stored["presence"]) == ("Reconciling", "absent")


async def test_an_unavailable_provider_counts_failures_and_suspends_at_the_limit(
    cleanup: Cleanup,
    api: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id, _ = await created(cleanup, api)
    provider = FakeProvider(unavailable=True)
    controller = controller_of(controller_pool, provider, failure_limit=2)

    # Provedor fora do ar: a observação é inconclusiva, não é falha de ação, e nada é contado.
    await controller.reconcile(resource_id)
    assert (await state(api, resource_id))["failure_count"] == 0

    # Observa, mas toda ação falha: cada ciclo conta uma falha.
    provider.unavailable = False
    provider.failing_grants = True
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
    assert len(desired) == 1  # só o da suspensão: a admissão aqui é direta
    assert desired[0]["data"]["reconciliation"] == "suspended"
    assert desired[0]["desiredGeneration"] == stored["desired_generation"]

    # Suspenso: o Controller não age mais.
    assert await controller.reconcile(resource_id) is False
    assert (await state(api, resource_id))["failure_count"] == 2


async def test_the_removal_of_the_account_deletes_only_its_links(
    cleanup: Cleanup,
    api: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    removed_id, removed_owner = await created(cleanup, api, lifecycle="absent")
    kept_id, _ = await created(cleanup, api, lifecycle="absent")
    message = (
        b'{"messageId":"0198a4a0-0000-7000-8000-000000000001","schemaVersion":"1.0",'
        b'"messageType":"updated","emitter":"controller","module":"core","resourceType":"account",'
        b'"resourceId":"' + removed_owner.encode() + b'","operation":"changed",'
        b'"desiredGeneration":1,"requestedBy":"x","correlationId":"c","causationId":"c",'
        b'"occurredAt":"2026-10-28T12:00:00Z","publishedAt":"2026-10-28T12:00:01Z","data":{"removed":true}}'
    )

    assert await AccountRemovedHandler(controller_pool).on_message(message) == removed_owner
    assert await AccountRemovedHandler(controller_pool).on_message(message) == removed_owner

    assert (
        await fetch_one(api, "SELECT 1 FROM sum.service WHERE resource_id = %s", removed_id) is None
    )
    assert await fetch_one(api, "SELECT 1 FROM sum.service WHERE resource_id = %s", kept_id)
