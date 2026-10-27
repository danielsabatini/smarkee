"""Fixtures dos testes de integração: PostgreSQL de desenvolvimento, com os papéis reais.

Requer a stack de dev no ar (`infrastructure/dev`, `docker compose up -d` e a migração de
`ipm-serviceaccount`). Sem o banco acessível, os testes são pulados. Os testes usam
identificadores únicos e removem o que criam. As credenciais são as triviais de desenvolvimento
(cada papel de login tem senha igual ao nome, `infrastructure/dev/README.md`).
"""

from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from support_publisher import Cleanup, connect


@pytest_asyncio.fixture
async def database_available() -> None:
    try:
        connection = await connect("ipm_serviceaccount_publisher_login")
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL de dev indisponível: {error}")
    await connection.close()


@pytest_asyncio.fixture
async def cleanup(database_available: None) -> AsyncIterator[Cleanup]:
    tracker = Cleanup()
    yield tracker
    controller = await connect("ipm_serviceaccount_controller_login")
    maintenance = await connect("ipm_maintenance_login")
    try:
        await controller.execute(
            "DELETE FROM ipm.serviceaccount WHERE resource_id = ANY(%s)", (tracker.resource_ids,)
        )
        await maintenance.execute(
            "DELETE FROM ipm.serviceaccount_outbox WHERE resource_id = ANY(%s)",
            (tracker.resource_ids,),
        )
    finally:
        await controller.close()
        await maintenance.close()


@pytest_asyncio.fixture
async def api_writer(
    database_available: None,
) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    connection = await connect("ipm_serviceaccount_api_login")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def outbox_reader(database_available: None) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """Papel de leitura do outbox do tipo (a API só insere nele)."""
    connection = await connect("ipm_serviceaccount_publisher_login")
    yield connection
    await connection.close()
