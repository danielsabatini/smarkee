"""Leitura pelas views do SSOT, com o papel `ipm_permission_api` (decisão 0004 e 0098)."""

from typing import Any

import psycopg
from support_api import seed_permission, unique_suffix

from ipm_permission.api.store.repository import SsotRepository

Connection = psycopg.AsyncConnection[Any]


async def test_permission_is_read_through_the_view(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    resource_id = await seed_permission(
        api, requester="repo-requester", name="repo-" + unique_suffix()
    )
    cleanup.append(resource_id)
    record = await repository.get_permission(resource_id)

    assert record is not None
    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Pending")
    assert record.desired["description"] == "Permission de teste"
    assert record.presence is None and record.observed is None
    assert await repository.get_permission("inexistente") is None


async def test_list_paginates_by_resource_id(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    ids = [
        await seed_permission(api, requester="lister", name="l." + unique_suffix() + ".get")
        for _ in range(3)
    ]
    cleanup.extend(ids)
    ids.sort()

    everything = await repository.list_permissions(after=None, limit=1000)
    listed = [item.resource_id for item in everything]
    assert set(ids) <= set(listed)
    assert listed == sorted(listed)
    after = await repository.list_permissions(after=ids[0], limit=1000)
    assert ids[0] not in {item.resource_id for item in after}
    assert set(ids[1:]) <= {item.resource_id for item in after}
    assert len(await repository.list_permissions(after=None, limit=2)) == 2
