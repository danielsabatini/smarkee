"""Leitura pelas views do SSOT, com o papel `ipm_group_api` (decisões 0004 e 0098)."""

from typing import Any

import psycopg
from support_api import seed_group, unique_suffix

from ipm_group.api.store.repository import SsotRepository

Connection = psycopg.AsyncConnection[Any]


async def test_role_is_read_through_the_view(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    resource_id = await seed_group(api, organization="org-" + unique_suffix())
    cleanup.append(resource_id)
    record = await repository.get_group(resource_id)

    assert record is not None
    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Ready")
    assert record.observed_generation == 1
    assert record.desired["roles"] == ["ipm.userViewer"]
    assert await repository.get_group("inexistente") is None


async def test_list_returns_only_the_organization_and_paginates(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    organization = "org-" + unique_suffix()
    ids = [await seed_group(api, organization=organization) for _ in range(3)]
    other = await seed_group(api, organization="org-" + unique_suffix())
    cleanup.extend([*ids, other])

    everything = await repository.list_groups(organization_id=organization, after=None, limit=1000)
    listed = {item.resource_id for item in everything}
    assert listed == set(ids)  # nunca o Grupo de outra Organization

    ordered = sorted(ids)
    page = await repository.list_groups(organization_id=organization, after=ordered[0], limit=1000)
    assert [item.resource_id for item in page] == ordered[1:]
