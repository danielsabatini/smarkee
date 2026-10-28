"""Leitura pelas views do SSOT, com o papel `sum_service_api` (decisões 0004 e 0098)."""

from typing import Any

import psycopg
from support_api import seed_link, unique_suffix

from sum_service.api.store.repository import SsotRepository

Connection = psycopg.AsyncConnection[Any]


async def test_a_link_is_read_through_the_view(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    resource_id = await seed_link(api, owner=f"owner-{unique_suffix()}")
    cleanup.append(resource_id)
    record = await repository.get_service(resource_id)

    assert record is not None
    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Pending")
    assert record.observed_generation is None
    assert record.desired["service"] == "ipm"
    assert record.presence is None and record.observed is None
    assert await repository.get_service("inexistente") is None


async def test_the_links_of_an_owner_are_listed_in_a_stable_order(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    owner = f"owner-{unique_suffix()}"
    cleanup.extend(
        [
            await seed_link(api, owner=owner, service="ipm"),
            await seed_link(api, owner=owner, service="bsm"),
            await seed_link(api, owner=f"other-{unique_suffix()}", service="ipm"),
        ]
    )

    records = await repository.services_of(owner)

    assert sorted(record.desired["service"] for record in records) == ["bsm", "ipm"]
    assert [record.resource_id for record in records] == sorted(
        record.resource_id for record in records
    )
