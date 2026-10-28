"""Admissão síncrona contra o SSOT real (decisão 0098): transação, regras, outbox e idempotência."""

import hashlib
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from psycopg.errors import InsufficientPrivilege
from pydantic import SecretStr
from support_api import DATABASE_HOST, DATABASE_PORT, connect, seed_link, unique_suffix

from sum_service.api.domain.admission import Admission
from sum_service.api.domain.errors import ApiError
from sum_service.api.http.admission import Rules, admit
from sum_service.api.store.admission import SsotAdmissionStore
from sum_service.common.database import open_pool
from sum_service.common.settings import DatabaseSettings

Connection = psycopg.AsyncConnection[Any]
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
CATALOG = {"ipm": ("ipm.organization.get", "ipm.organization.create")}


@pytest_asyncio.fixture
async def store(api: Connection) -> AsyncIterator[SsotAdmissionStore]:
    settings = DatabaseSettings(
        host=DATABASE_HOST,
        port=int(DATABASE_PORT),
        name="ssot",
        user="sum_service_api_login",
        password=SecretStr("sum_service_api_login"),
    )
    pool = await open_pool(settings, max_size=2)
    yield SsotAdmissionStore(pool)
    await pool.close()


def refuse(code: str) -> Callable[..., None]:
    def refusal(*_: Any) -> None:
        raise ApiError(HTTPStatus.CONFLICT, code, "recusado")

    return refusal


def accept(*_: Any) -> None:
    return


RULES = Rules(catalog=CATALOG, before_enable=accept, before_disable=accept)


def admission(
    operation: str,
    requester: str,
    *,
    resource_id: str | None = None,
    key: str | None = None,
    **fields: Any,
) -> Admission:
    resource_id = resource_id or str(uuid.uuid7())
    digest = hashlib.sha256(f"{operation}{requester}{resource_id}{fields}".encode()).hexdigest()
    return Admission(
        operation=operation,  # type: ignore[arg-type]
        resource_id=resource_id,
        requested_by=requester,
        correlation_id=str(uuid.uuid7()),
        request_digest=digest,
        now=NOW,
        message_id=str(uuid.uuid7()),
        idempotency_key=key,
        **fields,
    )


def new_owner() -> str:
    return "test-" + unique_suffix()


async def outbox_of(resource_id: str) -> list[tuple[str, dict[str, Any]]]:
    """Lê o outbox com o papel de manutenção (a API só insere)."""
    maintenance = await connect("sum_service_maintenance_login")
    try:
        cursor = await maintenance.execute(
            "SELECT subject, payload FROM sum.service_outbox WHERE resource_id = %s"
            " ORDER BY created_at",
            (resource_id,),
        )
        return [(str(row[0]), dict(row[1])) for row in await cursor.fetchall()]
    finally:
        await maintenance.close()


async def test_enable_writes_the_link_and_the_desired_in_the_same_transaction(
    api: Connection, cleanup: list[str], store: SsotAdmissionStore
) -> None:
    owner = new_owner()
    record = await admit(store, admission("create", owner, service="ipm"), RULES)
    cleanup.append(record.resource_id)

    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Pending")
    assert record.observed_generation is None
    assert record.desired["ownerAccountId"] == owner
    assert record.desired["servicePermissions"] == list(CATALOG["ipm"])
    cursor = await api.execute(
        "SELECT requested_by, owner_account_id, service FROM sum.service WHERE resource_id = %s",
        (record.resource_id,),
    )
    assert await cursor.fetchone() == (owner, owner, "ipm")
    ((subject, payload),) = await outbox_of(record.resource_id)
    assert subject == f"desired.sum.service.{record.resource_id}"
    assert (payload["emitter"], payload["messageType"], payload["desiredGeneration"]) == (
        "api",
        "desired",
        1,
    )
    # A API não lê o outbox nem apaga recursos (decisões 0096 e 0098).
    with pytest.raises(InsufficientPrivilege):
        await api.execute("SELECT 1 FROM sum.service_outbox LIMIT 1")
    with pytest.raises(InsufficientPrivilege):
        await api.execute("DELETE FROM sum.service WHERE resource_id = %s", (record.resource_id,))


async def test_enabling_an_enabled_service_is_refused_atomically(
    api: Connection, cleanup: list[str], store: SsotAdmissionStore
) -> None:
    owner = new_owner()
    first = await admit(store, admission("create", owner, service="ipm"), RULES)
    cleanup.append(first.resource_id)

    with pytest.raises(ApiError) as duplicate:
        await admit(store, admission("create", owner, service="ipm"), RULES)

    assert duplicate.value.error_code == "AlreadyEnabled"
    cursor = await api.execute(
        "SELECT count(*) FROM sum.service WHERE owner_account_id = %s", (owner,)
    )
    assert await cursor.fetchone() == (1,)
    assert len(await outbox_of(first.resource_id)) == 1


async def test_a_refused_precondition_leaves_no_row(
    api: Connection, store: SsotAdmissionStore
) -> None:
    owner = new_owner()
    rules = Rules(
        catalog=CATALOG, before_enable=refuse("BillingAccountRequired"), before_disable=accept
    )
    with pytest.raises(ApiError) as refused:
        await admit(store, admission("create", owner, service="ipm"), rules)
    assert refused.value.error_code == "BillingAccountRequired"
    cursor = await api.execute(
        "SELECT count(*) FROM sum.service WHERE owner_account_id = %s", (owner,)
    )
    assert await cursor.fetchone() == (0,)


async def test_a_service_outside_the_catalog_is_refused(
    api: Connection, store: SsotAdmissionStore
) -> None:
    owner = new_owner()
    with pytest.raises(ApiError) as refused:
        await admit(store, admission("create", owner, service="zzz"), RULES)
    assert refused.value.error_code == "ServiceNotAvailable"
    cursor = await api.execute(
        "SELECT count(*) FROM sum.service WHERE owner_account_id = %s", (owner,)
    )
    assert await cursor.fetchone() == (0,)


async def test_disable_marks_the_link_absent_without_removing_the_row(
    api: Connection, cleanup: list[str], store: SsotAdmissionStore
) -> None:
    owner = new_owner()
    enabled = await admit(store, admission("create", owner, service="ipm"), RULES)
    cleanup.append(enabled.resource_id)

    disabled = await admit(
        store,
        admission("delete", owner, resource_id=enabled.resource_id, resource_version=1),
        RULES,
    )

    assert (disabled.lifecycle, disabled.phase, disabled.desired_generation) == (
        "absent",
        "Deleting",
        2,
    )
    assert disabled.desired["servicePermissions"] == []
    outbox = await outbox_of(enabled.resource_id)
    assert [payload["data"]["lifecycle"] for _, payload in outbox] == ["present", "absent"]
    # Quem remove a linha é a remoção da conta, pelo Controller (decisão 0044).
    with pytest.raises(InsufficientPrivilege):
        await api.execute("DELETE FROM sum.service WHERE resource_id = %s", (enabled.resource_id,))


async def test_enabling_again_reuses_the_row_with_a_new_generation(
    api: Connection, cleanup: list[str], store: SsotAdmissionStore
) -> None:
    owner = new_owner()
    resource_id = await seed_link(api, owner=owner, lifecycle="absent")
    cleanup.append(resource_id)

    record = await admit(store, admission("create", owner, service="ipm"), RULES)

    assert record.resource_id == resource_id
    assert (record.lifecycle, record.desired_generation) == ("present", 2)
    cursor = await api.execute(
        "SELECT count(*) FROM sum.service WHERE owner_account_id = %s", (owner,)
    )
    assert await cursor.fetchone() == (1,)


async def test_disable_checks_the_owner_the_version_and_the_precondition(
    cleanup: list[str], store: SsotAdmissionStore
) -> None:
    owner = new_owner()
    enabled = await admit(store, admission("create", owner, service="ipm"), RULES)
    cleanup.append(enabled.resource_id)
    resource_id = enabled.resource_id

    with pytest.raises(ApiError) as other:
        await admit(
            store,
            admission("delete", new_owner(), resource_id=resource_id, resource_version=1),
            RULES,
        )
    assert other.value.error_code == "NotFound"

    with pytest.raises(ApiError) as stale:
        await admit(
            store, admission("delete", owner, resource_id=resource_id, resource_version=9), RULES
        )
    assert stale.value.error_code == "Conflict"

    blocked = Rules(
        catalog=CATALOG, before_enable=accept, before_disable=refuse("ResourcesAttached")
    )
    with pytest.raises(ApiError) as attached:
        await admit(
            store,
            admission("delete", owner, resource_id=resource_id, resource_version=1),
            blocked,
        )
    assert attached.value.error_code == "ResourcesAttached"
    assert len(await outbox_of(resource_id)) == 1  # nada novo foi gravado


async def test_repeating_the_disable_of_a_disabled_link_writes_nothing(
    api: Connection, cleanup: list[str], store: SsotAdmissionStore
) -> None:
    owner = new_owner()
    resource_id = await seed_link(api, owner=owner, lifecycle="absent")
    cleanup.append(resource_id)

    record = await admit(
        store, admission("delete", owner, resource_id=resource_id, resource_version=1), RULES
    )

    assert (record.lifecycle, record.desired_generation) == ("absent", 1)
    assert await outbox_of(resource_id) == []


async def test_idempotency_key_replays_the_link_and_rejects_other_content(
    cleanup: list[str], store: SsotAdmissionStore
) -> None:
    owner = new_owner()
    key = "k-" + unique_suffix()
    first = admission("create", owner, key=key, service="ipm")
    created = await admit(store, first, RULES)
    cleanup.append(created.resource_id)
    again = await admit(store, first, RULES)
    assert again.resource_id == created.resource_id
    assert again.desired_generation == created.desired_generation
    assert len(await outbox_of(created.resource_id)) == 1

    other = admission("create", owner, key=key, service="bsm")
    with pytest.raises(ApiError) as reused:
        await admit(store, other, RULES)
    assert reused.value.error_code == "IdempotencyKeyReused"
