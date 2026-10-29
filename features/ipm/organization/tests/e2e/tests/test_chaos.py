"""Falhas de componentes durante o loop (resiliência; opt-in).

Derrubam Deployments reais no Kubernetes com `kubectl` e por isso só rodam com `E2E_CHAOS=1`. Cada
teste restaura o componente ao final, mesmo em caso de falha. O contrato esperado: o trabalho que
chegou durante a queda não se perde (consumers duráveis e estado reconstruído da mensageria) e o
loop converge depois que o componente volta.
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
    os.environ.get("E2E_CHAOS") != "1", reason="defina E2E_CHAOS=1 para derrubar componentes"
)

CONVERGENCE_TIMEOUT_SECONDS = READY_SECONDS + 30.0


def kubectl(*arguments: str) -> None:
    subprocess.run(["kubectl", *arguments], check=True, capture_output=True, timeout=60)  # noqa: S603, S607


@contextmanager
def component_down(component: str) -> Generator[None]:
    deployment = f"ipm-organization-{component}"
    for app in ("smarkee-features-root", "feature-ipm-organization"):
        kubectl(
            "-n",
            "gitops-operator",
            "patch",
            "application",
            app,
            "--type=merge",
            "-p",
            '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":false}}}}',
        )
    try:
        kubectl("-n", "ipm", "scale", f"deployment/{deployment}", "--replicas=0")
        kubectl(
            "-n",
            "ipm",
            "wait",
            "--for=delete",
            "pod",
            "-l",
            f"app.kubernetes.io/name={deployment}",
            "--timeout=60s",
        )
        yield
    finally:
        kubectl("-n", "ipm", "scale", f"deployment/{deployment}", "--replicas=1")
        for app in ("feature-ipm-organization", "smarkee-features-root"):
            kubectl(
                "-n",
                "argocd",
                "patch",
                "application",
                app,
                "--type=merge",
                "-p",
                '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}',
            )
        kubectl("-n", "ipm", "rollout", "status", f"deployment/{deployment}", "--timeout=60s")


async def create_requested(jetstream: JetStreamContext, created: list[str], *, label: str) -> str:
    resource_id = str(uuid.uuid7())
    created.append(resource_id)
    specification = {"name": f"chaos-{label}-{uuid.uuid4().hex[:6]}", "platformAccess": "granted"}
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


@pytest.mark.parametrize("component", ["publisher", "controller"])
async def test_a_request_made_while_a_component_is_down_converges_when_it_returns(
    jetstream: JetStreamContext, created: list[str], component: str
) -> None:
    with component_down(component):
        resource_id = await create_requested(jetstream, created, label=component)
    await converges(jetstream, resource_id)
