"""Leitura pelas views do SSOT, com o papel `bsm_payment_api` (decisões 0004 e 0098)."""

from typing import Any

import psycopg
from support_api import seed_payment, unique_suffix

from bsm_payment.api.store.repository import SsotRepository

Connection = psycopg.AsyncConnection[Any]


async def test_payment_is_read_through_the_view(
    api_conn: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    resource_id = await seed_payment(
        api_conn, owner="repo-owner", display_name="Repo " + unique_suffix()
    )
    cleanup.append(resource_id)
    record = await repository.get_payment(resource_id)

    assert record is not None
    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Pending")
    assert record.desired["ownerAccountId"] == "repo-owner"
    assert record.presence is None and record.observed is None
    assert await repository.get_payment("inexistente") is None


async def test_list_filters_by_owner_and_paginates_by_resource_id(
    api_conn: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    owner = "owner-" + unique_suffix()
    first = await seed_payment(api_conn, owner=owner, display_name="A " + unique_suffix())
    second = await seed_payment(api_conn, owner=owner, display_name="B " + unique_suffix())
    other = await seed_payment(api_conn, owner="outro-" + unique_suffix())
    cleanup.extend([first, second, other])
    expected = sorted([first, second])

    page_one = await repository.list_payments(owner=owner, after=None, limit=1)
    page_two = await repository.list_payments(owner=owner, after=page_one[0].resource_id, limit=1)
    page_three = await repository.list_payments(owner=owner, after=page_two[0].resource_id, limit=1)

    assert [r.resource_id for r in page_one] == [expected[0]]
    assert [r.resource_id for r in page_two] == [expected[1]]
    assert page_three == []
