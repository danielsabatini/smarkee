"""Fixtures: cliente HTTP do gateway e limpeza dos dados de teste no SSOT de `sum.service`."""

import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
import psycopg
import pytest
import pytest_asyncio

API_URL = os.environ.get("CONFORMANCE_API_URL", "http://localhost:8080")
API_HOST = os.environ.get("CONFORMANCE_API_HOST", "api-dev.smarkee.com.br")
ACCESS_TOKEN = os.environ.get("CONFORMANCE_ACCESS_TOKEN")
# Conexões dos papéis de dev do SSOT. Sem elas, a limpeza no banco é pulada e o teste informa isso.
MANAGER_DATABASE_URL = os.environ.get("CONFORMANCE_SUM_MANAGER_DATABASE_URL")
MAINTENANCE_DATABASE_URL = os.environ.get("CONFORMANCE_SUM_MAINTENANCE_DATABASE_URL")


@pytest_asyncio.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url=API_URL,
        headers={"Host": API_HOST},
        timeout=10.0,
    ) as client:
        yield client


@pytest.fixture
def authorization() -> dict[str, str]:
    """Cabeçalho com o token de um solicitante com as roles `sum.ipm.*` (ver README)."""
    if ACCESS_TOKEN is None:
        pytest.skip("CONFORMANCE_ACCESS_TOKEN não definida")
    return {"Authorization": f"Bearer {ACCESS_TOKEN}"}


@pytest_asyncio.fixture
async def created_resource_ids() -> AsyncIterator[list[str]]:
    """Identificadores das ligações criadas pelo teste, limpos do SSOT ao final."""
    resource_ids: list[str] = []
    yield resource_ids
    if resource_ids:
        await _cleanup_database(resource_ids)


async def _cleanup_database(resource_ids: list[str]) -> None:
    """Remove as linhas de teste, mas só as de ligações já desligadas pela API (`absent`).

    Apagar uma ligação ainda `present` deixaria o Zitadel e o Reconciler com uma ligação sem
    linha no SSOT (um órfão que falha para sempre). Por isso ela é mantida e o teste falha.
    """
    if MANAGER_DATABASE_URL is None or MAINTENANCE_DATABASE_URL is None:
        return  # sem os papéis de dev: a limpeza é opcional e as linhas ficam como estão
    manager: psycopg.AsyncConnection[Any] = await psycopg.AsyncConnection.connect(
        MANAGER_DATABASE_URL, autocommit=True
    )
    maintenance: psycopg.AsyncConnection[Any] = await psycopg.AsyncConnection.connect(
        MAINTENANCE_DATABASE_URL, autocommit=True
    )
    try:
        cursor = await manager.execute(
            "SELECT resource_id FROM sum.service "
            "WHERE resource_id = ANY(%s) AND lifecycle = 'present'",
            (resource_ids,),
        )
        still_present = [str(row[0]) for row in await cursor.fetchall()]
        if still_present:
            raise AssertionError(
                f"ligação(ões) ainda ligada(s) no fim do teste: {still_present}. "
                "Desligue pela API antes de limpar; não apague a linha à mão."
            )
        removable = list(resource_ids)
        # A ligação (papel do Manager) é apagada por último: é a raiz das outras linhas.
        for table in ("service_outbox", "service_operation", "service_action_result"):
            await maintenance.execute(
                f"DELETE FROM sum.{table} WHERE resource_id = ANY(%s)",  # noqa: S608 (tabela fixa)
                (removable,),
            )
        await manager.execute(
            "DELETE FROM sum.service WHERE resource_id = ANY(%s) AND lifecycle = 'absent'",
            (removable,),
        )
    finally:
        await manager.close()
        await maintenance.close()
