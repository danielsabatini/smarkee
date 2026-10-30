"""Falhas de componentes durante o loop (resiliência; opt-in).

Derrubam Deployments reais no Kubernetes com `kubectl` e por isso só rodam com `E2E_CHAOS=1`. Cada
teste restaura o componente ao final, mesmo em caso de falha. O contrato esperado: o trabalho que
chegou durante a queda não se perde (outbox e consumers duráveis) e o loop converge depois que o
componente volta.
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
    os.environ.get("E2E_CHAOS") != "1", reason="defina E2E_CHAOS=1 para derrubar componentes"
)

CONVERGENCE_TIMEOUT_SECONDS = 90.0


def kubectl(*arguments: str) -> None:
    subprocess.run(["kubectl", *arguments], check=True, capture_output=True, timeout=60)  # noqa: S603, S607


@contextmanager
def component_down(deployment: str) -> Generator[None]:
    for app in ("smarkee-features-root", "feature-core-account"):
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
        kubectl("-n", "core", "scale", f"deployment/{deployment}", "--replicas=0")
        kubectl(
            "-n",
            "core",
            "wait",
            "--for=delete",
            "pod",
            "-l",
            f"app.kubernetes.io/name={deployment}",
            "--timeout=60s",
        )
        yield
    finally:
        kubectl("-n", "core", "scale", f"deployment/{deployment}", "--replicas=1")
        for app in ("feature-core-account", "smarkee-features-root"):
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
        kubectl("-n", "core", "rollout", "status", f"deployment/{deployment}", "--timeout=60s")


async def register_and_expect_ready(
    api: httpx.AsyncClient, jetstream: JetStreamContext, created: list[str], *, label: str
) -> str:
    body = {
        "givenName": "Caos",
        "familyName": label,
        "email": f"test-chaos-{label}-{uuid.uuid4().hex[:8]}@example.com",
    }
    response = await api.post("/v1/core/accounts", json=body)
    assert response.status_code == 202
    resource_id = response.json()["resourceId"]
    created.append(resource_id)
    return resource_id


async def converges(jetstream: JetStreamContext, resource_id: str) -> None:
    await wait_for(
        jetstream,
        "UPDATED",
        f"updated.core.account.{resource_id}",
        lambda m: m["data"]["phase"] == "Ready",
        timeout=CONVERGENCE_TIMEOUT_SECONDS,
    )


async def test_accounts_registered_while_the_controller_is_down_converge_when_it_returns(
    api: httpx.AsyncClient, jetstream: JetStreamContext, created: list[str]
) -> None:
    with component_down("core-account-controller"):
        resource_id = await register_and_expect_ready(api, jetstream, created, label="controller")
    await converges(jetstream, resource_id)


async def test_messages_published_while_the_publisher_is_down_are_published_when_it_returns(
    api: httpx.AsyncClient, jetstream: JetStreamContext, created: list[str]
) -> None:
    with component_down("core-account-publisher"):
        resource_id = await register_and_expect_ready(api, jetstream, created, label="publisher")
    await converges(jetstream, resource_id)
