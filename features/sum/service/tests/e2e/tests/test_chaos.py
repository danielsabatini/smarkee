"""Falhas de componentes durante o loop de ligar e desligar (resiliência; opt-in).

Derrubam contêineres reais do SUM com o `docker` e por isso só rodam com `E2E_CHAOS=1`. Cada teste
restaura o componente ao final, mesmo em caso de falha, e desliga o serviço que ligou. O contrato
esperado: o pedido aceito durante a queda não se perde (consumers duráveis) e o loop converge quando
o componente volta. Precisam de um solicitante com as roles `sum.ipm.*` (ver README).
"""

import asyncio
import os
import subprocess
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from test_conformance import SERVICE, wait_for_operation, wait_for_resource

pytestmark = pytest.mark.skipif(
    os.environ.get("E2E_CHAOS") != "1", reason="defina E2E_CHAOS=1 para derrubar contêineres"
)


def docker(*arguments: str) -> None:
    subprocess.run(["docker", *arguments], check=True, capture_output=True, timeout=60)  # noqa: S603, S607


def restart(container: str) -> None:
    docker("restart", container)


@contextmanager
def component_down(container: str) -> Generator[None]:
    docker("stop", container)
    try:
        yield
    finally:
        docker("start", container)


async def request_enable(
    api: httpx.AsyncClient, authorization: dict[str, str], created: list[str]
) -> tuple[str, str]:
    """Pede a ligação e devolve `(resourceId, operationId)` do `202`."""
    accepted = await api.post(
        "/v1/sum/services",
        json={"service": SERVICE},
        headers={**authorization, "Idempotency-Key": str(uuid.uuid7())},
    )
    assert accepted.status_code == 202, accepted.text
    resource_id = accepted.json()["resourceId"]
    created.append(resource_id)
    return resource_id, accepted.json()["operationId"]


async def disable(api: httpx.AsyncClient, authorization: dict[str, str], resource_id: str) -> None:
    """Desliga o serviço da ligação de teste e espera o loop revogar as roles."""
    current: dict[str, Any] = (
        await api.get(f"/v1/sum/services/{resource_id}", headers=authorization)
    ).json()
    removed = await api.delete(
        f"/v1/sum/services/{resource_id}",
        params={"resourceVersion": current["resourceVersion"]},
        headers=authorization,
    )
    assert removed.status_code == 202, removed.text
    await wait_for_operation(api, authorization, resource_id, removed.json()["operationId"])


async def converges_enabled(
    api: httpx.AsyncClient, authorization: dict[str, str], resource_id: str, operation_id: str
) -> None:
    await wait_for_operation(api, authorization, resource_id, operation_id)
    enabled = await wait_for_resource(
        api,
        authorization,
        resource_id,
        lambda r: r["phase"] == "Ready" and r["desired"]["lifecycle"] == "present",
    )
    assert set(enabled["desired"]["serviceRoles"]) <= set(enabled["observed"]["serviceRoles"])


async def test_requests_made_while_the_manager_is_down_are_processed_when_it_returns(
    api: httpx.AsyncClient, authorization: dict[str, str], created_resource_ids: list[str]
) -> None:
    with component_down("sum-service-manager.smarkee.internal"):
        resource_id, operation_id = await request_enable(api, authorization, created_resource_ids)
    try:
        await converges_enabled(api, authorization, resource_id, operation_id)
    finally:
        await disable(api, authorization, resource_id)


async def test_actions_made_while_the_executor_is_down_are_executed_when_it_returns(
    api: httpx.AsyncClient, authorization: dict[str, str], created_resource_ids: list[str]
) -> None:
    with component_down("sum-service-executor.smarkee.internal"):
        resource_id, operation_id = await request_enable(api, authorization, created_resource_ids)
    try:
        await converges_enabled(api, authorization, resource_id, operation_id)
    finally:
        await disable(api, authorization, resource_id)


async def test_messages_published_while_the_publisher_is_down_are_published_when_it_returns(
    api: httpx.AsyncClient, authorization: dict[str, str], created_resource_ids: list[str]
) -> None:
    with component_down("sum-service-publisher.smarkee.internal"):
        resource_id, operation_id = await request_enable(api, authorization, created_resource_ids)
    try:
        await converges_enabled(api, authorization, resource_id, operation_id)
    finally:
        await disable(api, authorization, resource_id)


async def wait_until_in_progress(
    api: httpx.AsyncClient, authorization: dict[str, str], resource_id: str, operation_id: str
) -> None:
    """Espera o Manager gravar a ligação: a Operation sai de `accepted` (reconciliação em curso)."""
    path = f"/v1/sum/services/{resource_id}/operations/{operation_id}"
    for _ in range(60):
        response = await api.get(path, headers=authorization)
        if response.status_code == 200 and response.json()["operationStatus"] != "accepted":
            return
        await asyncio.sleep(1.0)
    raise AssertionError("a Operation não saiu de `accepted` em 60 s")


async def test_the_loop_converges_after_the_reconciler_and_the_observer_restart(
    api: httpx.AsyncClient, authorization: dict[str, str], created_resource_ids: list[str]
) -> None:
    """O estado deles é um cache descartável: reiniciar no meio de uma ligação não a perde."""
    with component_down("sum-service-executor.smarkee.internal"):
        resource_id, operation_id = await request_enable(api, authorization, created_resource_ids)
        await wait_until_in_progress(api, authorization, resource_id, operation_id)
        restart("sum-service-reconciler.smarkee.internal")
        restart("sum-service-observer.smarkee.internal")
    try:
        await converges_enabled(api, authorization, resource_id, operation_id)
    finally:
        await disable(api, authorization, resource_id)
