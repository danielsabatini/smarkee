"""Leitura pelas views do SSOT, com o papel `ipm_organization_api` (decisão 0004 e 0098)."""

from typing import Any

import psycopg
from support_api import seed_organization, unique_suffix

from ipm_organization.api.store.repository import SsotRepository

Connection = psycopg.AsyncConnection[Any]


async def test_organization_is_read_through_the_view(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    resource_id = await seed_organization(api, owner="repo-owner", name="repo-" + unique_suffix())
    cleanup.append(resource_id)
    record = await repository.get_organization(resource_id)

    assert record is not None
    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Pending")
    assert record.desired["ownerAccountId"] == "repo-owner"
    assert record.presence is None and record.observed is None
    assert await repository.get_organization("inexistente") is None


async def test_list_filters_by_owner_and_paginates_by_resource_id(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    owner = "list-" + unique_suffix()
    ids: list[str] = []
    for _ in range(3):
        resource_id = await seed_organization(api, owner=owner, name="l-" + unique_suffix())
        ids.append(resource_id)
    other = await seed_organization(
        api, owner="other-" + unique_suffix(), name="o-" + unique_suffix()
    )
    cleanup.extend([*ids, other])
    ids.sort()

    first = await repository.list_organizations(owner=owner, after=None, limit=2)
    assert [item.resource_id for item in first] == ids[:2]
    rest = await repository.list_organizations(owner=owner, after=ids[1], limit=10)
    assert [item.resource_id for item in rest] == ids[2:]
    assert await repository.count_organizations_owned_by(owner) == 3
    everything = await repository.list_organizations(owner=None, after=None, limit=1000)
    assert set(ids) <= {item.resource_id for item in everything}
