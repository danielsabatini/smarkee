"""Controller contra o SSOT real (decisão 0096): fases, Operations, outbox e suspensão.

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
    requested_message,
    ssot,
    unique_suffix,
)

from ipm_user.controller.drivers.authorization import Authorization
from ipm_user.controller.drivers.identity import ProviderError
from ipm_user.controller.drivers.user import IdentityUser
from ipm_user.controller.engine.controller import (
    ControllerDrivers,
    UserController,
)
from ipm_user.controller.settings import UserControllerSettings
from ipm_user.manager.domain.kind import USER
from ipm_user.manager.handlers.requested import RequestedHandler

Connection = psycopg.AsyncConnection[Any]


@dataclass
class FakeProvider:
    """Usuários, autorizações e metadados do Zitadel em memória.

    `unavailable` simula o provedor fora do ar.
    """

    users: dict[str, IdentityUser] = field(default_factory=lambda: {})
    authorizations: dict[str, Authorization] = field(default_factory=lambda: {})
    metadata: dict[tuple[str, str], str] = field(default_factory=lambda: {})
    unavailable: bool = False

    def _check(self) -> None:
        if self.unavailable:
            raise ProviderError("ProviderUnavailable", retryable=True)

    # UserDriver
    async def get_user(self, user_id: str) -> IdentityUser | None:
        self._check()
        return self.users.get(user_id)

    async def create_user(
        self,
        user_id: str,
        *,
        organization_id: str,
        given_name: str,
        family_name: str,
        email: str,
    ) -> bool:
        self._check()
        if user_id in self.users:
            return False
        self.users[user_id] = IdentityUser(
            email=email,
            organization_id=organization_id,
            state="USER_STATE_ACTIVE",
            email_verified=True,
            password_set=True,
        )
        return True

    async def delete_user(self, user_id: str) -> None:
        self._check()
        self.users.pop(user_id, None)
        self.authorizations.pop(user_id, None)

    # AuthorizationDriver
    async def authorization(self, user_id: str, organization_id: str) -> Authorization | None:
        self._check()
        return self.authorizations.get(user_id)

    async def granted_permissions(self, user_id: str) -> set[str]:
        self._check()
        found = self.authorizations.get(user_id)
        return set(found.permissions) if found else set()

    async def create(self, user_id: str, organization_id: str, permissions: list[str]) -> None:
        self._check()
        self.authorizations[user_id] = Authorization(f"auth-{user_id}", frozenset(permissions))

    async def update(self, authorization_id: str, permissions: list[str]) -> None:
        self._check()
        for user_id, found in self.authorizations.items():
            if found.authorization_id == authorization_id:
                self.authorizations[user_id] = Authorization(
                    authorization_id, frozenset(permissions)
                )

    async def remove(self, authorization_id: str) -> None:
        self._check()
        for user_id in [
            user_id
            for user_id, found in self.authorizations.items()
            if found.authorization_id == authorization_id
        ]:
            del self.authorizations[user_id]

    # MetadataDriver
    async def get_value(self, owner_id: str, key: str) -> str | None:
        self._check()
        return self.metadata.get((owner_id, key))

    async def set_value(self, owner_id: str, key: str, value: str) -> None:
        self._check()
        self.metadata[(owner_id, key)] = value


def controller_of(
    pool: AsyncConnectionPool[Any], provider: FakeProvider, *, failure_limit: int = 5
) -> UserController:
    settings = UserControllerSettings()
    settings.loop.failure_limit = failure_limit
    drivers = ControllerDrivers(
        users=cast("Any", provider),
        authorizations=cast("Any", provider),
        metadata=cast("Any", provider),
    )
    return UserController(cast("Any", pool), drivers, settings)


async def created(cleanup: Cleanup, manager: Connection) -> str:
    message = requested_message(cleanup.track(f"ctl-{unique_suffix()}"))
    await RequestedHandler().handle(ssot(manager), USER, message)
    return str(message["resourceId"])


async def state(connection: Connection, resource_id: str) -> Mapping[str, Any]:
    stored = await fetch_one(
        connection,
        "SELECT resource_version, phase, reconciliation, failure_count, observed_generation,"
        " desired_generation, presence FROM ipm.user WHERE resource_id = %s",
        resource_id,
    )
    assert stored is not None
    return stored


async def operations(connection: Connection, resource_id: str) -> list[str]:
    rows = await fetch_all(
        connection,
        "SELECT operation_status FROM ipm.user_operation WHERE resource_id = %s"
        " ORDER BY created_at",
        resource_id,
    )
    return [item["operation_status"] for item in rows]


async def outbox(reader: Connection, resource_id: str) -> list[dict[str, Any]]:
    return await fetch_all(
        reader,
        "SELECT subject, payload FROM ipm.user_outbox WHERE resource_id = %s ORDER BY sequence",
        resource_id,
    )


async def test_creates_the_user_and_confirms_the_generation(
    cleanup: Cleanup,
    manager: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id = await created(cleanup, manager)
    provider = FakeProvider()
    controller = controller_of(controller_pool, provider)
    before = await outbox(outbox_reader, resource_id)

    retry = await controller.reconcile(resource_id)

    assert retry is False
    assert resource_id in provider.users
    stored = await state(manager, resource_id)
    assert (stored["phase"], stored["presence"], stored["failure_count"]) == ("Ready", "present", 0)
    assert stored["observed_generation"] == stored["desired_generation"]
    assert await operations(manager, resource_id) == ["completed"]
    sent = (await outbox(outbox_reader, resource_id))[len(before) :]
    assert [item["subject"] for item in sent] == [f"manager.updated.ipm.user.{resource_id}.changed"]
    data = sent[0]["payload"]["data"]
    assert (data["phase"], data["resourceVersion"]) == ("Ready", str(stored["resource_version"]))
    assert data["observedGeneration"] == data["desiredGeneration"]
    assert sent[0]["payload"]["correlationId"]


async def test_a_reevaluation_without_news_keeps_the_version_and_emits_nothing(
    cleanup: Cleanup,
    manager: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id = await created(cleanup, manager)
    controller = controller_of(controller_pool, FakeProvider())
    await controller.reconcile(resource_id)
    version = (await state(manager, resource_id))["resource_version"]
    messages = len(await outbox(outbox_reader, resource_id))

    await controller.reconcile(resource_id)

    assert (await state(manager, resource_id))["resource_version"] == version
    assert len(await outbox(outbox_reader, resource_id)) == messages


async def test_an_unavailable_provider_counts_failures_and_suspends_at_the_limit(
    cleanup: Cleanup,
    manager: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id = await created(cleanup, manager)
    provider = FakeProvider(unavailable=True)
    controller = controller_of(controller_pool, provider, failure_limit=2)

    # Provedor fora do ar: a observação é inconclusiva, não é falha de ação, e nada é contado.
    with contextlib.suppress(ProviderError):
        await controller.reconcile(resource_id)
    assert (await state(manager, resource_id))["failure_count"] == 0

    # Observa, mas toda ação falha: cada ciclo conta uma falha.
    provider.unavailable = False

    async def failing_create(
        user_id: str, *, organization_id: str, given_name: str, family_name: str, email: str
    ) -> bool:
        raise ProviderError("ProviderUnavailable", retryable=True)

    provider.create_user = failing_create  # type: ignore[method-assign]
    assert await controller.reconcile(resource_id) is True
    first = await state(manager, resource_id)
    assert (first["phase"], first["failure_count"], first["reconciliation"]) == (
        "Reconciling",
        1,
        "active",
    )

    assert await controller.reconcile(resource_id) is False
    stored = await state(manager, resource_id)
    assert (stored["phase"], stored["failure_count"], stored["reconciliation"]) == (
        "Failed",
        2,
        "suspended",
    )
    assert await operations(manager, resource_id) == ["failed"]
    subjects = [item["subject"].split(".")[1] for item in await outbox(outbox_reader, resource_id)]
    assert subjects.count("desired") == 2  # o do pedido e o suspenso
    suspended = [
        item["payload"]
        for item in await outbox(outbox_reader, resource_id)
        if item["subject"].split(".")[1] == "desired"
    ][-1]
    assert suspended["data"]["reconciliation"] == "suspended"
    assert suspended["desiredGeneration"] == stored["desired_generation"]

    # Suspenso: o Controller não age mais.
    assert await controller.reconcile(resource_id) is False
    assert (await state(manager, resource_id))["failure_count"] == 2


async def test_removal_deletes_the_record_and_emits_removed(
    cleanup: Cleanup,
    manager: Connection,
    outbox_reader: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id = await created(cleanup, manager)
    provider = FakeProvider()
    controller = controller_of(controller_pool, provider)
    await controller.reconcile(resource_id)
    await manager.execute(
        "UPDATE ipm.user SET lifecycle = 'absent', desired_generation = 2,"
        " desired = jsonb_set(desired, '{lifecycle}', '\"absent\"') WHERE resource_id = %s",
        (resource_id,),
    )

    await controller.reconcile(resource_id)

    assert resource_id not in provider.users
    assert (
        await fetch_one(manager, "SELECT 1 FROM ipm.user WHERE resource_id = %s", resource_id)
        is None
    )
    assert await operations(manager, resource_id) == ["completed"]
    last = (await outbox(outbox_reader, resource_id))[-1]["payload"]["data"]
    assert (last["removed"], last["phase"], last["lifecycle"]) == (True, "Deleting", "absent")


async def test_an_open_operation_of_an_older_generation_becomes_superseded(
    cleanup: Cleanup,
    manager: Connection,
    controller_pool: AsyncConnectionPool[Any],
) -> None:
    resource_id = await created(cleanup, manager)
    await manager.execute(
        "UPDATE ipm.user SET desired_generation = 2 WHERE resource_id = %s",
        (resource_id,),
    )
    await manager.execute(
        "INSERT INTO ipm.user_operation (operation_id, resource_id, operation_type,"
        " desired_generation, requested_by, correlation_id, request_digest, operation_status)"
        " VALUES (%s, %s, 'update', 2, 'owner-1', 'corr-2', %s, 'accepted')",
        (f"op-{unique_suffix()}", resource_id, "0" * 64),
    )

    await controller_of(controller_pool, FakeProvider()).reconcile(resource_id)

    assert sorted(await operations(manager, resource_id)) == ["completed", "superseded"]
