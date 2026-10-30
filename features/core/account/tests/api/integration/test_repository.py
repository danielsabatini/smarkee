"""Leitura pelas views do SSOT, com o papel `core_account_api` (decisões 0004 e 0098)."""

from typing import Any

import psycopg
from support_api import seed_account, unique_suffix

from core_account.api.store.repository import SsotRepository

Connection = psycopg.AsyncConnection[Any]


async def test_account_is_read_through_the_view(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    resource_id = await seed_account(api, email=f"test-repo-{unique_suffix()}@example.com")
    cleanup.append(resource_id)
    record = await repository.get_account(resource_id)

    assert record is not None
    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Pending")
    assert record.observed_generation is None
    assert record.desired["platformAccess"] == "granted"
    assert record.presence is None and record.observed is None
    assert await repository.get_account("inexistente") is None
