"""Leitura pelas views do SSOT, com o papel `bsm_account_api` (decisões 0004 e 0098)."""

from typing import Any

import psycopg
from support_api import seed_account, unique_suffix

from bsm_account.api.store.repository import SsotRepository

Connection = psycopg.AsyncConnection[Any]


async def test_account_is_read_through_the_view(
    api_conn: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    resource_id = await seed_account(
        api_conn, owner="repo-owner", display_name="Repo " + unique_suffix()
    )
    cleanup.append(resource_id)
    record = await repository.get_account(resource_id)

    assert record is not None
    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Ready")
    assert record.desired["ownerAccountId"] == "repo-owner"
    assert record.presence is None and record.observed is None
    assert await repository.get_account("inexistente") is None


async def test_list_filters_by_owner_and_paginates_by_resource_id(
    api_conn: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    owner = "list-" + unique_suffix()
    ids: list[str] = []
    for _ in range(3):
        resource_id = await seed_account(
            api_conn, owner=owner, display_name="L " + unique_suffix()
        )
        ids.append(resource_id)
    other = await seed_account(
        api_conn, owner="other-" + unique_suffix(), display_name="O " + unique_suffix()
    )
    cleanup.extend([*ids, other])
    ids.sort()

    first = await repository.list_accounts(owner=owner, after=None, limit=2)
    assert [item.resource_id for item in first] == ids[:2]
    rest = await repository.list_accounts(owner=owner, after=ids[1], limit=10)
    assert [item.resource_id for item in rest] == ids[2:]
    everything = await repository.list_accounts(owner=None, after=None, limit=1000)
    assert set(ids) <= {item.resource_id for item in everything}
