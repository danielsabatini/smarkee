"""Leitura pelas views do SSOT, com o papel `ipm_role_api` (decisões 0004 e 0098)."""

from typing import Any

import psycopg
from support_api import seed_role, unique_suffix

from ipm_role.api.store.repository import SsotRepository

Connection = psycopg.AsyncConnection[Any]


async def test_role_is_read_through_the_view(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    resource_id = await seed_role(api, organization="org-" + unique_suffix())
    cleanup.append(resource_id)
    record = await repository.get_role(resource_id)

    assert record is not None
    assert (record.resource_version, record.desired_generation, record.phase) == (1, 1, "Ready")
    assert record.observed_generation == 1
    assert record.desired["permissions"] == ["ipm.user.get"]
    assert await repository.get_role("inexistente") is None


async def test_list_returns_predefined_plus_the_organization_and_paginates(
    api: Connection, cleanup: list[str], repository: SsotRepository
) -> None:
    organization = "org-" + unique_suffix()
    ids = [await seed_role(api, organization=organization) for _ in range(3)]
    other = await seed_role(api, organization="org-" + unique_suffix())
    cleanup.extend([*ids, other])

    everything = await repository.list_roles(organization_id=organization, after=None, limit=1000)
    listed = {item.resource_id for item in everything}
    assert set(ids) <= listed
    assert other not in listed  # nunca a Role de outra Organization
    # As predefinidas (`core`) são visíveis a todos.
    assert any(item.desired.get("organizationId") == "core" for item in everything)

    ordered = sorted(ids)
    page = await repository.list_roles(organization_id=organization, after=ordered[0], limit=1000)
    assert ordered[0] not in {item.resource_id for item in page}
