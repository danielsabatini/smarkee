"""Leitura pelas views do SSOT, com o papel `ipm_user_api` (decisão 0004 e 0098)."""

from typing import Any

import psycopg
from support_api import seed_user, unique_suffix

from ipm_user.api.store.repository import SsotRepository

Connection = psycopg.AsyncConnection[Any]


async def test_user_is_read_through_the_view(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    resource_id = await seed_user(api, organization="org-" + unique_suffix())
    cleanup.append(resource_id)
    record = await repository.get_user(resource_id)

    assert record is not None
    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Pending")
    assert record.desired["roles"] == ["ipm.userViewer"]
    assert record.presence is None and record.observed is None
    assert await repository.get_user("inexistente") is None


async def test_list_filters_by_organization_and_paginates_by_resource_id(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    organization = "org-" + unique_suffix()
    ids: list[str] = []
    for _ in range(3):
        resource_id = await seed_user(api, organization=organization)
        ids.append(resource_id)
    other = await seed_user(api, organization="org-" + unique_suffix())
    cleanup.extend([*ids, other])
    ids.sort()

    first = await repository.list_users(organization_id=organization, after=None, limit=2)
    assert [item.resource_id for item in first] == ids[:2]
    rest = await repository.list_users(organization_id=organization, after=ids[1], limit=10)
    assert [item.resource_id for item in rest] == ids[2:]
