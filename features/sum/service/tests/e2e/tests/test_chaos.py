"""Falhas de componentes durante a ligação de um serviço (resiliência; opt-in).

Derrubam Deployments reais do SUM no Kubernetes com `kubectl` e por isso só rodam com `E2E_CHAOS=1`.
Cada teste restaura o componente ao final, mesmo em caso de falha, e desliga o serviço que ligou. O
contrato esperado: a ligação admitida durante a queda não se perde (outbox e consumers duráveis) e
converge quando o componente volta. Precisam de um solicitante com as permissões `sum.ipm.*` (ver
README).
"""

import os
import subprocess
import uuid
from collections.abc import Generator
from contextlib import contextmanager

import httpx
import pytest
from test_conformance import SERVICE, is_disabled, is_enabled, wait_for_resource

pytestmark = pytest.mark.skipif(
    os.environ.get("E2E_CHAOS") != "1", reason="defina E2E_CHAOS=1 para derrubar componentes"
)


def kubectl(*arguments: str) -> None:
    subprocess.run(["kubectl", *arguments], check=True, capture_output=True, timeout=60)  # noqa: S603, S607


def restart(deployment: str) -> None:
    kubectl("-n", "sum", "rollout", "restart", f"deployment/{deployment}")
    kubectl("-n", "sum", "rollout", "status", f"deployment/{deployment}", "--timeout=60s")


@contextmanager
def component_down(deployment: str) -> Generator[None]:
    for app in ("smarkee-features-root", "feature-sum-service"):
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
        kubectl("-n", "sum", "scale", f"deployment/{deployment}", "--replicas=0")
        kubectl(
            "-n",
            "sum",
            "wait",
            "--for=delete",
            "pod",
            "-l",
            f"app.kubernetes.io/name={deployment}",
            "--timeout=60s",
        )
        yield
    finally:
        kubectl("-n", "sum", "scale", f"deployment/{deployment}", "--replicas=1")
        for app in ("feature-sum-service", "smarkee-features-root"):
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
        kubectl("-n", "sum", "rollout", "status", f"deployment/{deployment}", "--timeout=60s")


async def request_enable(
    api: httpx.AsyncClient, authorization: dict[str, str], created: list[str]
) -> str:
    """Pede a ligação e devolve o `resourceId` do `201`."""
    response = await api.post(
        "/v1/sum/services",
        json={"service": SERVICE},
        headers={**authorization, "Idempotency-Key": str(uuid.uuid7())},
    )
    assert response.status_code == 201, response.text
    resource_id = response.json()["resourceId"]
    created.append(resource_id)
    return resource_id


async def disable(api: httpx.AsyncClient, authorization: dict[str, str], resource_id: str) -> None:
    """Desliga o serviço da ligação de teste e espera o Controller revogar as permissões."""
    current = (await api.get(f"/v1/sum/services/{resource_id}", headers=authorization)).json()
    removed = await api.delete(
        f"/v1/sum/services/{resource_id}",
        params={"resourceVersion": current["resourceVersion"]},
        headers=authorization,
    )
    assert removed.status_code == 202, removed.text
    await wait_for_resource(api, authorization, resource_id, is_disabled)


async def converges_enabled(
    api: httpx.AsyncClient, authorization: dict[str, str], resource_id: str
) -> None:
    enabled = await wait_for_resource(api, authorization, resource_id, is_enabled)
    assert set(enabled["desired"]["servicePermissions"]) <= set(
        enabled["observed"]["servicePermissions"]
    )


async def test_links_made_while_the_controller_is_down_converge_when_it_returns(
    api: httpx.AsyncClient, authorization: dict[str, str], created_resource_ids: list[str]
) -> None:
    with component_down("sum-service-controller"):
        resource_id = await request_enable(api, authorization, created_resource_ids)
    try:
        await converges_enabled(api, authorization, resource_id)
    finally:
        await disable(api, authorization, resource_id)


async def test_messages_published_while_the_publisher_is_down_are_published_when_it_returns(
    api: httpx.AsyncClient, authorization: dict[str, str], created_resource_ids: list[str]
) -> None:
    with component_down("sum-service-publisher"):
        resource_id = await request_enable(api, authorization, created_resource_ids)
    try:
        await converges_enabled(api, authorization, resource_id)
    finally:
        await disable(api, authorization, resource_id)


async def test_the_link_converges_after_the_controller_restarts_mid_reconciliation(
    api: httpx.AsyncClient, authorization: dict[str, str], created_resource_ids: list[str]
) -> None:
    """O estado do Controller é um cache descartável: reiniciar no meio não perde a ligação."""
    resource_id = await request_enable(api, authorization, created_resource_ids)
    restart("sum-service-controller")
    try:
        await converges_enabled(api, authorization, resource_id)
    finally:
        await disable(api, authorization, resource_id)
