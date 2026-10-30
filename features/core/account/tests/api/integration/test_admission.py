"""Admissão síncrona contra o SSOT real (decisão 0098): transação, regras, outbox e idempotência."""

import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from psycopg.errors import InsufficientPrivilege
from pydantic import SecretStr
from support_api import DATABASE_HOST, DATABASE_PORT, connect, unique_suffix

from core_account.api.domain.admission import Admission
from core_account.api.domain.errors import ApiError
from core_account.api.http.admission import admit, register
from core_account.api.store.admission import SsotAdmissionStore
from core_account.common.database import open_pool
from core_account.common.settings import DatabaseSettings

Connection = psycopg.AsyncConnection[Any]
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
REQUESTER = "test-" + unique_suffix()


@pytest_asyncio.fixture
async def store(api: Connection) -> AsyncIterator[SsotAdmissionStore]:
    settings = DatabaseSettings(
        host=DATABASE_HOST,
        port=int(DATABASE_PORT),
        name="ssot",
        user="core_account_api_login",
        password=SecretStr("core_account_api_login"),
    )
    pool = await open_pool(settings, max_size=2)
    yield SsotAdmissionStore(pool)
    await pool.close()


def specification(email: str | None = None) -> dict[str, Any]:
    return {
        "givenName": "Ana",
        "familyName": "Silva",
        "email": email or f"test-account-{unique_suffix()}@example.com",
        "platformAccess": "granted",
        "platformPermissions": ["core.account.get"],
    }


def admission(
    operation: str, resource_id: str, *, key: str | None = None, **fields: Any
) -> Admission:
    digest = hashlib.sha256(f"{operation}{resource_id}{fields}".encode()).hexdigest()
    return Admission(
        operation=operation,  # type: ignore[arg-type]
        resource_id=resource_id,
        requested_by=REQUESTER,
        correlation_id=str(uuid.uuid7()),
        request_digest=digest,
        now=NOW,
        message_id=str(uuid.uuid7()),
        idempotency_key=key,
        **fields,
    )


async def outbox_of(resource_id: str) -> list[tuple[str, dict[str, Any]]]:
    """Lê o outbox com o papel de manutenção (a API só insere)."""
    maintenance = await connect("core_maintenance_login")
    try:
        cursor = await maintenance.execute(
            "SELECT subject, payload FROM core.account_outbox WHERE resource_id = %s"
            " ORDER BY created_at",
            (resource_id,),
        )
        return [(str(row[0]), dict(row[1])) for row in await cursor.fetchall()]
    finally:
        await maintenance.close()


async def test_create_writes_the_resource_and_the_desired_in_the_same_transaction(
    api: Connection, cleanup: list[str], store: SsotAdmissionStore
) -> None:
    resource_id = str(uuid.uuid7())
    cleanup.append(resource_id)

    record = await admit(store, admission("create", resource_id, specification=specification()))

    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Pending")
    assert record.observed_generation is None
    assert record.desired["deletionProtection"] is True
    cursor = await api.execute(
        "SELECT requested_by FROM core.account WHERE resource_id = %s", (resource_id,)
    )
    assert (await cursor.fetchone() or ("",))[0] == REQUESTER
    ((subject, payload),) = await outbox_of(resource_id)
    assert subject == f"desired.core.account.{resource_id}"
    assert (payload["emitter"], payload["messageType"], payload["desiredGeneration"]) == (
        "api",
        "desired",
        1,
    )
    # A API não lê o outbox nem apaga recursos (decisões 0096 e 0098).
    with pytest.raises(InsufficientPrivilege):
        await api.execute("SELECT 1 FROM core.account_outbox LIMIT 1")
    with pytest.raises(InsufficientPrivilege):
        await api.execute("DELETE FROM core.account WHERE resource_id = %s", (resource_id,))


async def test_duplicate_email_is_refused_atomically(
    api: Connection, cleanup: list[str], store: SsotAdmissionStore
) -> None:
    email = f"test-shared-{unique_suffix()}@example.com"
    first, second = str(uuid.uuid7()), str(uuid.uuid7())
    cleanup.extend([first, second])
    await admit(store, admission("create", first, specification=specification(email)))

    with pytest.raises(ApiError) as duplicate:
        await admit(store, admission("create", second, specification=specification(email)))
    assert duplicate.value.error_code == "NameInUse"
    cursor = await api.execute("SELECT 1 FROM core.account WHERE resource_id = %s", (second,))
    assert await cursor.fetchone() is None  # a recusa não deixa linha


async def test_registration_with_a_used_email_writes_nothing_and_does_not_fail(
    api: Connection, cleanup: list[str], store: SsotAdmissionStore
) -> None:
    email = f"test-shared-{unique_suffix()}@example.com"
    first, second = str(uuid.uuid7()), str(uuid.uuid7())
    cleanup.extend([first, second])
    await register(store, admission("create", first, specification=specification(email)))
    await register(store, admission("create", second, specification=specification(email)))

    cursor = await api.execute(
        "SELECT resource_id FROM core.account WHERE resource_id = ANY(%s)", ([first, second],)
    )
    assert [row[0] for row in await cursor.fetchall()] == [first]
    assert await outbox_of(second) == []


async def test_update_checks_the_version_and_increments_the_generation(
    cleanup: list[str], store: SsotAdmissionStore
) -> None:
    resource_id = str(uuid.uuid7())
    cleanup.append(resource_id)
    await admit(store, admission("create", resource_id, specification=specification()))

    updated = await admit(
        store,
        admission(
            "update", resource_id, resource_version=1, specification={"deletionProtection": False}
        ),
    )
    assert (updated.resource_version, updated.desired_generation, updated.phase) == (
        2,
        2,
        "Reconciling",
    )
    with pytest.raises(ApiError) as stale:
        await admit(
            store,
            admission(
                "update",
                resource_id,
                resource_version=1,
                specification={"deletionProtection": True},
            ),
        )
    assert stale.value.error_code == "Conflict"


async def test_delete_marks_the_account_absent_without_removing_the_row(
    api: Connection, cleanup: list[str], store: SsotAdmissionStore
) -> None:
    resource_id = str(uuid.uuid7())
    cleanup.append(resource_id)
    await admit(store, admission("create", resource_id, specification=specification()))
    await admit(
        store,
        admission(
            "update", resource_id, resource_version=1, specification={"deletionProtection": False}
        ),
    )

    deleted = await admit(store, admission("delete", resource_id, resource_version=2))

    assert (deleted.lifecycle, deleted.phase, deleted.desired_generation) == (
        "absent",
        "Deleting",
        3,
    )
    assert "email" not in deleted.desired  # sem dados pessoais
    outbox = await outbox_of(resource_id)
    assert [payload["data"]["lifecycle"] for _, payload in outbox] == [
        "present",
        "present",
        "absent",
    ]
    # Quem remove a linha é o Controller, ao convergir.
    with pytest.raises(InsufficientPrivilege):
        await api.execute("DELETE FROM core.account WHERE resource_id = %s", (resource_id,))


async def test_idempotency_key_replays_the_resource_and_rejects_other_content(
    cleanup: list[str], store: SsotAdmissionStore
) -> None:
    resource_id = str(uuid.uuid7())
    cleanup.append(resource_id)
    key = "k-" + unique_suffix()
    first = admission("create", resource_id, key=key, specification=specification())
    created = await admit(store, first)
    again = await admit(store, first)
    assert again.resource_id == created.resource_id
    assert again.desired_generation == created.desired_generation
    assert len(await outbox_of(resource_id)) == 1

    other = admission(
        "create", str(uuid.uuid7()), key=key, specification=specification("other@example.com")
    )
    with pytest.raises(ApiError) as reused:
        await admit(store, other)
    assert reused.value.error_code == "IdempotencyKeyReused"
