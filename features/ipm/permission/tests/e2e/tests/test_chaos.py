"""Falhas de componentes durante o loop (resiliência; opt-in).

Derrubam Deployments reais no Kubernetes com `kubectl` e por isso só rodam com `E2E_CHAOS=1`. Cada
teste restaura o componente ao final, mesmo em caso de falha.
"""

import os
import subprocess
import uuid
from collections.abc import Generator
from contextlib import contextmanager

import httpx
import pytest
from test_loop import COLLECTION, READY_SECONDS, converged, resource_where

pytestmark = pytest.mark.skipif(
    os.environ.get("E2E_CHAOS") != "1", reason="defina E2E_CHAOS=1 para derrubar componentes"
)

CONVERGENCE_TIMEOUT_SECONDS = READY_SECONDS + 30.0


def kubectl(*arguments: str) -> None:
    subprocess.run(["kubectl", *arguments], check=True, capture_output=True, timeout=60)  # noqa: S603, S607


@contextmanager
def component_down(component: str) -> Generator[None]:
    deployment = f"ipm-permission-{component}"
    for app in ("smarkee-features-root", "feature-ipm-permission"):
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
        for app in ("feature-ipm-permission", "smarkee-features-root"):
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


async def create_requested(
    api: httpx.AsyncClient, headers: dict[str, str], created: list[str], *, label: str
) -> str:
    response = await api.post(
        COLLECTION,
        json={
            "name": f"bsm.chaos.c{uuid.uuid4().hex[:5]}",
            "description": f"Chaos {label} test",
            "grantable": True,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    resource_id = str(response.json()["resourceId"])
    created.append(resource_id)
    return resource_id


@pytest.mark.parametrize("component", ["publisher", "controller"])
async def test_a_permission_created_while_a_component_is_down_converges_when_it_returns(
    api: httpx.AsyncClient, headers: dict[str, str], created: list[str], component: str
) -> None:
    # A API grava o recurso e o outbox na mesma transação: o Publisher entrega ao voltar e o
    # Controller reconcilia o que ficou pendente (Informer e reavaliação periódica).
    with component_down(component):
        resource_id = await create_requested(api, headers, created, label=component)
    await resource_where(api, headers, resource_id, converged, timeout=CONVERGENCE_TIMEOUT_SECONDS)
