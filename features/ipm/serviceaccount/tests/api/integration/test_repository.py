"""Leitura pelas views do SSOT, com o papel `ipm_serviceaccount_api` (decisões 0004 e 0098)."""

from typing import Any

import psycopg
from support_api import seed_serviceaccount, unique_suffix

from ipm_serviceaccount.api.store.repository import SsotRepository

Connection = psycopg.AsyncConnection[Any]


async def test_serviceaccount_is_read_through_the_view(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    resource_id = await seed_serviceaccount(api, organization="org-" + unique_suffix())
    cleanup.append(resource_id)
    record = await repository.get_serviceaccount(resource_id)

    assert record is not None
    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Pending")
    assert record.observed_generation is None
    assert record.desired["roles"] == ["ipm.serviceaccountViewer"]
    assert record.presence is None and record.observed is None
    assert await repository.get_serviceaccount("inexistente") is None


async def test_list_filters_by_organization_and_paginates_by_resource_id(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    organization = "org-" + unique_suffix()
    ids = [await seed_serviceaccount(api, organization=organization) for _ in range(3)]
    other = await seed_serviceaccount(api, organization="org-" + unique_suffix())
    cleanup.extend([*ids, other])
    ids.sort()

    first = await repository.list_serviceaccounts(organization_id=organization, after=None, limit=2)
    assert [item.resource_id for item in first] == ids[:2]
    rest = await repository.list_serviceaccounts(
        organization_id=organization, after=ids[1], limit=10
    )
    assert [item.resource_id for item in rest] == ids[2:]
