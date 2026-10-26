"""Falhas de componentes durante o loop (resiliência; opt-in).

Derrubam contêineres reais com o `docker` e por isso só rodam com `E2E_CHAOS=1`. Cada teste
restaura o componente ao final, mesmo em caso de falha.
"""

import os
import subprocess
import uuid
from collections.abc import Generator
from contextlib import contextmanager

import pytest
from nats.js import JetStreamContext
from test_loop import READY_SECONDS, request, send, wait_for

pytestmark = pytest.mark.skipif(
    os.environ.get("E2E_CHAOS") != "1", reason="defina E2E_CHAOS=1 para derrubar contêineres"
)

CONVERGENCE_TIMEOUT_SECONDS = READY_SECONDS + 30.0


def docker(*arguments: str) -> None:
    subprocess.run(["docker", *arguments], check=True, capture_output=True, timeout=60)  # noqa: S603, S607


@contextmanager
def component_down(component: str) -> Generator[None]:
    container = f"ipm-role-{component}.smarkee.internal"
    docker("stop", container)
    try:
        yield
    finally:
        docker("start", container)


async def create_requested(jetstream: JetStreamContext, created: list[str], *, label: str) -> str:
    resource_id = str(uuid.uuid7())
    created.append(resource_id)
    specification = {
        "organizationId": "test-org",
        "name": f"test.chaos{uuid.uuid4().hex[:6]}",
        "description": f"Chaos {label} test",
        "permissions": ["ipm.permission.get"],
    }
    await send(jetstream, request(resource_id, "create", {"specification": specification}))
    return resource_id


async def converges(jetstream: JetStreamContext, resource_id: str) -> None:
    await wait_for(
        jetstream,
        "updated",
        resource_id,
        lambda m: m["data"]["phase"] == "Ready",
        timeout=CONVERGENCE_TIMEOUT_SECONDS,
    )


@pytest.mark.parametrize(
    "component", ["manager", "publisher", "reconciler", "observer", "executor"]
)
async def test_a_request_made_while_a_component_is_down_converges_when_it_returns(
    jetstream: JetStreamContext, created: list[str], component: str
) -> None:
    with component_down(component):
        resource_id = await create_requested(jetstream, created, label=component)
    await converges(jetstream, resource_id)
