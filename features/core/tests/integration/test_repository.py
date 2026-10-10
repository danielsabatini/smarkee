"""Leitura da API pelas views do SSOT, com os papéis `core_*_api` (decisão 0004)."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest_asyncio
from pydantic import SecretStr
from support import (
    DATABASE_HOST,
    DATABASE_PORT,
    DEFAULT_DIGEST,
    Cleanup,
    requested_message,
    unique_suffix,
)

from core.api.repository import PostgresRepository
from core.database import open_pool
from core.manager.kinds import ORGANIZATION, USER
from core.manager.requested import RequestedHandler
from core.settings import DatabaseSettings

Connection = psycopg.AsyncConnection[Any]
handler = RequestedHandler()


@pytest_asyncio.fixture
async def repository(database_available: None) -> AsyncIterator[PostgresRepository]:
    settings = DatabaseSettings(
        host=DATABASE_HOST,
        port=int(DATABASE_PORT),
        organization_api_password=SecretStr("core_organization_api_login"),
        user_api_password=SecretStr("core_user_api_login"),
    )
    pools = {
        "organization": await open_pool(settings, "organization_api", max_size=2),
        "user": await open_pool(settings, "user_api", max_size=2),
    }
    yield PostgresRepository(pools)
    for pool in pools.values():
        await pool.close()


async def create_organization(
    cleanup: Cleanup, manager: Connection, *, owner: str, name: str | None = None
) -> tuple[str, str]:
    resource_id, operation_id = cleanup.track(str(uuid.uuid7())), str(uuid.uuid7())
    await handler.handle(
        manager,
        ORGANIZATION,
        requested_message(
            resource_type="organization",
            resource_id=resource_id,
            operation="create",
            requested_by=owner,
            data={
                "operationId": operation_id,
                "requestDigest": DEFAULT_DIGEST,
                "specification": {
                    "name": name or "repo-" + unique_suffix(),
                    "platformAccess": "granted",
                },
            },
        ),
    )
    return resource_id, operation_id


async def test_organization_is_read_through_the_view(
    cleanup: Cleanup, organization_manager: Connection, repository: PostgresRepository
) -> None:
    resource_id, _ = await create_organization(cleanup, organization_manager, owner="repo-owner")
    record = await repository.get_resource("organization", resource_id)

    assert record is not None
    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Pending")
    assert record.desired["ownerUserId"] == "repo-owner"
    assert record.presence is None and record.observed is None
    assert await repository.get_resource("organization", "inexistente") is None


async def test_list_filters_by_owner_and_paginates_by_resource_id(
    cleanup: Cleanup, organization_manager: Connection, repository: PostgresRepository
) -> None:
    owner = "list-" + unique_suffix()
    ids = sorted(
        [
            (await create_organization(cleanup, organization_manager, owner=owner))[0]
            for _ in range(3)
        ]
    )
    await create_organization(cleanup, organization_manager, owner="other-" + unique_suffix())

    first = await repository.list_organizations(owner=owner, after=None, limit=2)
    assert [item.resource_id for item in first] == ids[:2]
    rest = await repository.list_organizations(owner=owner, after=ids[1], limit=10)
    assert [item.resource_id for item in rest] == ids[2:]
    assert await repository.count_organizations_owned_by(owner) == 3
    everything = await repository.list_organizations(owner=None, after=None, limit=1000)
    assert set(ids) <= {item.resource_id for item in everything}


async def test_operation_is_found_with_requester_in_the_right_type(
    cleanup: Cleanup,
    organization_manager: Connection,
    user_manager: Connection,
    repository: PostgresRepository,
) -> None:
    _, organization_operation = await create_organization(
        cleanup, organization_manager, owner="op-owner"
    )
    found = await repository.find_operation(organization_operation)
    assert found is not None
    assert (found.resource_type, found.requested_by, found.operation_status) == (
        "organization",
        "op-owner",
        "accepted",
    )

    user_id, user_operation = cleanup.track(str(uuid.uuid7())), str(uuid.uuid7())
    await handler.handle(
        user_manager,
        USER,
        requested_message(
            resource_type="user",
            resource_id=user_id,
            operation="create",
            requested_by="anonymous",
            data={
                "operationId": user_operation,
                "requestDigest": DEFAULT_DIGEST,
                "specification": {
                    "givenName": "Ana",
                    "familyName": "Souza",
                    "email": f"repo.{unique_suffix()}@example.com",
                },
            },
        ),
    )
    by_any_type = await repository.find_operation(user_operation)
    assert by_any_type is not None and by_any_type.resource_type == "user"
    assert by_any_type.requested_by == "anonymous"
    assert await repository.find_operation(user_operation, resource_type="organization") is None
    assert (await repository.get_resource("user", user_id)) is not None
    assert await repository.find_operation("inexistente") is None
