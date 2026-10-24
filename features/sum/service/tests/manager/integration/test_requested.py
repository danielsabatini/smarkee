"""Testes de integração do tratamento de `requested` contra o SSOT de `sum.service`.

Requer o banco de dev já migrado (`0001` e `0002`) e o papel do Manager, por
`SUM_MANAGER_TEST_DATABASE_URL`. Sem a variável, os testes são pulados. Cada teste roda numa
transação que termina em `rollback`: nada persiste no banco.
"""

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

import psycopg
import pytest
from psycopg.rows import dict_row

from sum_service.common.service_rules import parse_catalog
from sum_service.manager.handlers.requested import Duplicate, Recorded, RequestedHandler

DATABASE_URL = os.environ.get("SUM_MANAGER_TEST_DATABASE_URL")
CATALOG = parse_catalog('{"ipm": ["ipm.organization.get", "ipm.organization.list"]}')
DIGEST = "a" * 64

pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="SUM_MANAGER_TEST_DATABASE_URL não definida"
)


@pytest.fixture
async def conn() -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    assert DATABASE_URL is not None
    connection: psycopg.AsyncConnection[Any] = await psycopg.AsyncConnection.connect(
        DATABASE_URL, row_factory=cast(Any, dict_row)
    )
    yield connection
    await connection.rollback()
    await connection.close()


def ids() -> dict[str, str]:
    """Identificadores novos: o dono é um UUID, e a operação nunca se repete entre testes."""
    return {
        "owner": str(uuid.uuid7()),
        "operation": str(uuid.uuid7()),
        "message": str(uuid.uuid7()),
    }


async def create(
    conn: psycopg.AsyncConnection[Any],
    owner: str,
    operation: str,
    service: str = "ipm",
    resource_id: str | None = None,
) -> Any:
    return await RequestedHandler(catalog=CATALOG).create(
        conn,
        operation_id=operation,
        request_digest=DIGEST,
        requested_by=owner,
        correlation_id=str(uuid.uuid7()),
        requested_message_id=str(uuid.uuid7()),
        resource_id=resource_id or str(uuid.uuid7()),
        owner_account_id=owner,
        service=service,
    )


async def delete(
    conn: psycopg.AsyncConnection[Any],
    resource_id: str,
    version: str,
    operation: str,
    requested_by: str,
) -> Any:
    return await RequestedHandler(catalog=CATALOG).delete(
        conn,
        operation_id=operation,
        request_digest=DIGEST,
        requested_by=requested_by,
        correlation_id=str(uuid.uuid7()),
        requested_message_id=str(uuid.uuid7()),
        resource_id=resource_id,
        expected_version=version,
    )


async def link_row(conn: psycopg.AsyncConnection[Any], resource_id: str) -> dict[str, Any]:
    cur = await conn.execute(
        "SELECT lifecycle, desired_generation, resource_version, desired FROM sum.service "
        "WHERE resource_id = %s",
        (resource_id,),
    )
    row = await cur.fetchone()
    assert row is not None
    return row


async def test_create_is_accepted_and_writes_the_link_the_operation_and_the_outbox(
    conn: psycopg.AsyncConnection[Any],
) -> None:
    v = ids()
    outcome = await create(conn, v["owner"], v["operation"])
    assert isinstance(outcome, Recorded) and outcome.status == "accepted"
    row = await link_row(conn, outcome.resource_id or "")
    assert (row["lifecycle"], row["desired_generation"], row["resource_version"]) == (
        "present",
        1,
        1,
    )
    assert row["desired"]["servicePermissions"] == ["ipm.organization.get", "ipm.organization.list"]


async def test_the_outbox_message_is_the_desired_envelope_read_by_the_maintenance_role() -> None:
    """O Manager não lê o outbox (só grava). Este teste grava de verdade, lê com o papel de
    manutenção e limpa o que criou: a leitura precisa ver a transação já confirmada."""
    assert DATABASE_URL is not None
    maintenance_url = os.environ.get("SUM_MANAGER_TEST_MAINTENANCE_URL")
    if maintenance_url is None:
        pytest.skip("SUM_MANAGER_TEST_MAINTENANCE_URL não definida")
    v = ids()
    writer = await psycopg.AsyncConnection.connect(DATABASE_URL, row_factory=cast(Any, dict_row))
    reader = await psycopg.AsyncConnection.connect(maintenance_url, row_factory=cast(Any, dict_row))
    resource_id: str | None = None
    try:
        outcome = await create(writer, v["owner"], v["operation"])
        await writer.commit()
        resource_id = outcome.resource_id if isinstance(outcome, Recorded) else None
        cur = await reader.execute(
            "SELECT payload FROM sum.service_outbox WHERE resource_id = %s", (resource_id,)
        )
        message = (await cur.fetchone())["payload"]  # type: ignore[index]
        assert message["messageType"] == "desired"
        assert message["module"] == "sum" and message["resourceType"] == "service"
        assert message["data"]["lifecycle"] == "present"
        assert "publishedAt" not in message  # o Publisher preenche ao publicar
    finally:
        # Operações e mensagens são de retenção: a limpeza delas é do papel de manutenção.
        await reader.execute(
            "DELETE FROM sum.service_outbox WHERE resource_id = %s", (resource_id,)
        )
        await reader.execute(
            "DELETE FROM sum.service_operation WHERE requested_by = %s", (v["owner"],)
        )
        await reader.commit()
        await writer.execute("DELETE FROM sum.service WHERE owner_account_id = %s", (v["owner"],))
        await writer.commit()
        await reader.close()
        await writer.close()


async def test_a_second_active_link_for_the_same_pair_is_rejected_with_the_existing_id(
    conn: psycopg.AsyncConnection[Any],
) -> None:
    v = ids()
    first = await create(conn, v["owner"], v["operation"])
    second = await create(conn, v["owner"], str(uuid.uuid7()))
    assert isinstance(second, Recorded) and second.reason == "already_exists"
    assert second.existing_resource_id == first.resource_id  # type: ignore[union-attr]


async def test_a_redelivered_operation_is_a_duplicate_and_writes_nothing_again(
    conn: psycopg.AsyncConnection[Any],
) -> None:
    v = ids()
    await create(conn, v["owner"], v["operation"])
    again = await create(conn, v["owner"], v["operation"])
    assert again == Duplicate(v["operation"])
    cur = await conn.execute(
        "SELECT count(*) AS n FROM sum.service WHERE owner_account_id = %s", (v["owner"],)
    )
    assert (await cur.fetchone())["n"] == 1  # type: ignore[index]


async def test_a_service_outside_the_catalog_is_rejected_and_keeps_the_receiver_id(
    conn: psycopg.AsyncConnection[Any],
) -> None:
    v = ids()
    resource_id = str(uuid.uuid7())
    outcome = await RequestedHandler(catalog=CATALOG).create(
        conn,
        operation_id=v["operation"],
        request_digest=DIGEST,
        requested_by=v["owner"],
        correlation_id=str(uuid.uuid7()),
        requested_message_id=str(uuid.uuid7()),
        resource_id=resource_id,
        owner_account_id=v["owner"],
        service="sum",
    )
    assert isinstance(outcome, Recorded) and outcome.reason == "service_unavailable"
    cur = await conn.execute(
        "SELECT resource_id, operation_status FROM sum.service_operation WHERE operation_id = %s",
        (v["operation"],),
    )
    row = await cur.fetchone()
    assert row == {"resource_id": resource_id, "operation_status": "rejected"}


async def test_delete_with_the_current_version_disables_and_bumps_generation_and_version(
    conn: psycopg.AsyncConnection[Any],
) -> None:
    v = ids()
    created = await create(conn, v["owner"], v["operation"])
    resource_id = created.resource_id or ""  # type: ignore[union-attr]
    removal = str(uuid.uuid7())
    outcome = await delete(conn, resource_id, "1", removal, v["owner"])
    assert isinstance(outcome, Recorded) and outcome.status == "accepted"
    row = await link_row(conn, resource_id)
    assert (row["lifecycle"], row["desired_generation"], row["resource_version"]) == (
        "absent",
        2,
        2,
    )
    assert row["desired"]["servicePermissions"] == []


async def test_delete_with_an_outdated_version_is_a_conflict_and_changes_nothing(
    conn: psycopg.AsyncConnection[Any],
) -> None:
    v = ids()
    created = await create(conn, v["owner"], v["operation"])
    resource_id = created.resource_id or ""  # type: ignore[union-attr]
    outcome = await delete(conn, resource_id, "9", str(uuid.uuid7()), v["owner"])
    assert isinstance(outcome, Recorded) and outcome.reason == "conflict"
    row = await link_row(conn, resource_id)
    assert row["lifecycle"] == "present"


async def test_enabling_a_disabled_pair_again_reuses_the_same_resource(
    conn: psycopg.AsyncConnection[Any],
) -> None:
    v = ids()
    created = await create(conn, v["owner"], v["operation"])
    resource_id = created.resource_id or ""  # type: ignore[union-attr]
    await delete(conn, resource_id, "1", str(uuid.uuid7()), v["owner"])
    again = await create(conn, v["owner"], str(uuid.uuid7()), resource_id=resource_id)
    assert isinstance(again, Recorded) and again.status == "accepted"
    assert again.resource_id == resource_id
    row = await link_row(conn, resource_id)
    # Geração 1 (ligar), 2 (desligar), 3 (ligar de novo); a versão acompanha.
    assert (row["lifecycle"], row["desired_generation"], row["resource_version"]) == (
        "present",
        3,
        3,
    )
    assert row["desired"]["servicePermissions"] != []
    cur = await conn.execute(
        "SELECT count(*) AS n FROM sum.service WHERE owner_account_id = %s", (v["owner"],)
    )
    assert (await cur.fetchone())["n"] == 1  # type: ignore[index]  # um recurso por par


async def test_reusing_an_active_resource_is_rejected_as_already_exists(
    conn: psycopg.AsyncConnection[Any],
) -> None:
    v = ids()
    created = await create(conn, v["owner"], v["operation"])
    resource_id = created.resource_id or ""  # type: ignore[union-attr]
    again = await create(conn, v["owner"], str(uuid.uuid7()), resource_id=resource_id)
    assert isinstance(again, Recorded) and again.reason == "already_exists"
    assert again.existing_resource_id == resource_id


async def test_reusing_the_resource_of_another_owner_is_a_conflict_and_changes_nothing(
    conn: psycopg.AsyncConnection[Any],
) -> None:
    v = ids()
    created = await create(conn, v["owner"], v["operation"])
    resource_id = created.resource_id or ""  # type: ignore[union-attr]
    await delete(conn, resource_id, "1", str(uuid.uuid7()), v["owner"])
    stranger = str(uuid.uuid7())
    outcome = await create(conn, stranger, str(uuid.uuid7()), resource_id=resource_id)
    assert isinstance(outcome, Recorded) and outcome.reason == "conflict"
    row = await link_row(conn, resource_id)
    assert (row["lifecycle"], row["desired_generation"]) == ("absent", 2)
