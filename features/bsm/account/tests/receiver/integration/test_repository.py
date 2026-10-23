"""Leitura pelas views do SSOT, com o papel `bsm_account.receiver` (decisão 0004)."""

from typing import Any

import psycopg
from support_receiver import seed_account, unique_suffix

from bsm_account.receiver.store.repository import SsotRepository

Connection = psycopg.AsyncConnection[Any]


async def test_account_is_read_through_the_view(
    manager: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    resource_id, _ = await seed_account(
        manager, owner="repo-owner", display_name="Repo " + unique_suffix()
    )
    cleanup.append(resource_id)
    record = await repository.get_account(resource_id)

    assert record is not None
    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Pending")
    assert record.desired["ownerAccountId"] == "repo-owner"
    assert record.presence is None and record.observed is None
    assert await repository.get_account("inexistente") is None


async def test_list_filters_by_owner_and_paginates_by_resource_id(
    manager: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    owner = "list-" + unique_suffix()
    ids: list[str] = []
    for _ in range(3):
        resource_id, _ = await seed_account(
            manager, owner=owner, display_name="L " + unique_suffix()
        )
        ids.append(resource_id)
    other, _ = await seed_account(
        manager, owner="other-" + unique_suffix(), display_name="O " + unique_suffix()
    )
    cleanup.extend([*ids, other])
    ids.sort()

    first = await repository.list_accounts(owner=owner, after=None, limit=2)
    assert [item.resource_id for item in first] == ids[:2]
    rest = await repository.list_accounts(owner=owner, after=ids[1], limit=10)
    assert [item.resource_id for item in rest] == ids[2:]
    everything = await repository.list_accounts(owner=None, after=None, limit=1000)
    assert set(ids) <= {item.resource_id for item in everything}


async def test_operation_is_found_with_the_requester(
    manager: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    resource_id, operation_id = await seed_account(
        manager, owner="op-owner", display_name="Op " + unique_suffix()
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
