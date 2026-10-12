"""Falhas de componentes durante o loop (resiliência; opt-in).

Derrubam contêineres reais com o `docker` e por isso só rodam com `E2E_CHAOS=1`. Cada teste
restaura o componente ao final, mesmo em caso de falha. O contrato esperado: o trabalho que chegou
durante a queda não se perde (consumers duráveis) e o loop converge depois que o componente volta.
"""

import os
import subprocess
import uuid
from collections.abc import Generator
from contextlib import contextmanager

import httpx
import pytest
from nats.js import JetStreamContext
from test_conformance import wait_for

pytestmark = pytest.mark.skipif(
    os.environ.get("E2E_CHAOS") != "1", reason="defina E2E_CHAOS=1 para derrubar contêineres"
)

CONVERGENCE_TIMEOUT_SECONDS = 90.0


def docker(*arguments: str) -> None:
    subprocess.run(["docker", *arguments], check=True, capture_output=True, timeout=60)  # noqa: S603, S607


@contextmanager
def component_down(container: str) -> Generator[None]:
    docker("stop", container)
    try:
        yield
    finally:
        docker("start", container)


async def register_and_expect_ready(
    api: httpx.AsyncClient, jetstream: JetStreamContext, created: list[str], *, label: str
) -> str:
    body = {
        "givenName": "Caos",
        "familyName": label,
        "email": f"chaos.{label}.{uuid.uuid4().hex[:8]}@example.com",
    }
    response = await api.post("/v1/users", json=body)
    assert response.status_code == 202
    resource_id = response.json()["resourceId"]
    created.append(resource_id)
    return resource_id


async def converges(jetstream: JetStreamContext, resource_id: str) -> None:
    await wait_for(
        jetstream,
        "UPDATED",
        f"manager.updated.core.user.{resource_id}.changed",
        lambda m: m["data"]["phase"] == "Ready",
        timeout=CONVERGENCE_TIMEOUT_SECONDS,
    )


async def test_requests_made_while_the_manager_is_down_are_processed_when_it_returns(
    api: httpx.AsyncClient, jetstream: JetStreamContext, created: list[str]
) -> None:
    with component_down("core-user-manager.smarkee.internal"):
        resource_id = await register_and_expect_ready(api, jetstream, created, label="manager")
    await converges(jetstream, resource_id)


async def test_actions_made_while_the_executor_is_down_are_executed_when_it_returns(
    api: httpx.AsyncClient, jetstream: JetStreamContext, created: list[str]
) -> None:
    with component_down("core-user-executor.smarkee.internal"):
        resource_id = await register_and_expect_ready(api, jetstream, created, label="executor")
    await converges(jetstream, resource_id)


async def test_messages_published_while_the_publisher_is_down_are_published_when_it_returns(
    api: httpx.AsyncClient, jetstream: JetStreamContext, created: list[str]
) -> None:
    with component_down("core-user-publisher.smarkee.internal"):
        resource_id = await register_and_expect_ready(api, jetstream, created, label="publisher")
    await converges(jetstream, resource_id)
