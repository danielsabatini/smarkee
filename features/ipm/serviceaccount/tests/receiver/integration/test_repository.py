"""Leitura pelas views do SSOT, com o papel `ipm_serviceaccount.receiver` (decisão 0004)."""

from typing import Any

import psycopg
from support_receiver import seed_serviceaccount, unique_suffix

from ipm_serviceaccount.receiver.store.repository import SsotRepository

Connection = psycopg.AsyncConnection[Any]


async def test_serviceaccount_is_read_through_the_view(
    manager: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    resource_id, _ = await seed_serviceaccount(manager, organization="org-" + unique_suffix())
    cleanup.append(resource_id)
    record = await repository.get_serviceaccount(resource_id)

    assert record is not None
    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Pending")
    assert record.desired["roles"] == ["ipm.serviceaccountViewer"]
    assert record.presence is None and record.observed is None
    assert await repository.get_serviceaccount("inexistente") is None


async def test_list_and_count_filter_by_organization_and_paginate_by_resource_id(
    manager: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    organization = "org-" + unique_suffix()
    ids: list[str] = []
    for _ in range(3):
        resource_id, _ = await seed_serviceaccount(manager, organization=organization)
        ids.append(resource_id)
    other, _ = await seed_serviceaccount(manager, organization="org-" + unique_suffix())
    cleanup.extend([*ids, other])
    ids.sort()

    first = await repository.list_serviceaccounts(organization_id=organization, after=None, limit=2)
    assert [item.resource_id for item in first] == ids[:2]
    rest = await repository.list_serviceaccounts(
        organization_id=organization, after=ids[1], limit=10
    )
    assert [item.resource_id for item in rest] == ids[2:]
    assert await repository.count_serviceaccounts_in(organization) == 3


async def test_operation_is_found_with_the_requester(
    manager: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    resource_id, operation_id = await seed_serviceaccount(
        manager, organization="org-" + unique_suffix(), requested_by="op-owner"
    )
    cleanup.append(resource_id)
    found = await repository.find_operation(operation_id)
    assert found is not None
    assert (found.resource_id, found.requested_by, found.operation_status) == (
        resource_id,
        "op-owner",
        "accepted",
    )
    assert await repository.find_operation("inexistente") is None
