"""Leitura do Receiver pelas views do SSOT, com o papel `core_user_receiver` (decisão 0004)."""

from typing import Any

import psycopg
from support import seed_user, unique_suffix

from core_user_receiver.store.repository import PostgresRepository

Connection = psycopg.AsyncConnection[Any]


async def test_user_is_read_through_the_view(
    manager: Connection, cleanup: list[str], repository: PostgresRepository
) -> None:
    resource_id, _ = await seed_user(manager, email=f"repo.{unique_suffix()}@example.com")
    cleanup.append(resource_id)
    record = await repository.get_user(resource_id)

    assert record is not None
    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Pending")
    assert record.desired["platformAccess"] == "granted"
    assert record.presence is None and record.observed is None
    assert await repository.get_user("inexistente") is None


async def test_operation_is_found_with_the_requester(
    manager: Connection, cleanup: list[str], repository: PostgresRepository
) -> None:
    resource_id, operation_id = await seed_user(manager, email=f"op.{unique_suffix()}@example.com")
    cleanup.append(resource_id)
    found = await repository.find_operation(operation_id)
    assert found is not None
    assert (found.resource_id, found.requested_by, found.operation_status) == (
        resource_id,
        "anonymous",
        "accepted",
    )
    assert await repository.find_operation("inexistente") is None
