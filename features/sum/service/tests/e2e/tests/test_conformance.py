"""Conformidade de sum.service: Receiver e SSOT pela rede, contra os schemas de `schemas/`."""

import asyncio
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from contracts import assert_valid

SCHEMAS_DIRECTORY = "sum/service"
# Cada exemplo valida contra o schema de mesmo nome (`.example.json` -> `.v1.schema.json`).
EXAMPLES = (
    "api-create-request",
    "desired",
    "observed",
    "requested-create",
    "requested-delete",
    "resource",
)
SERVICE = "ipm"
LOOP_TIMEOUT_SECONDS = 90.0
POLL_INTERVAL_SECONDS = 1.0


# ---------------------------------------------------------------------- contratos (sem serviços)


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_is_valid_against_its_schema(name: str) -> None:
    schema_root = Path(__file__).resolve().parents[6] / "schemas" / SCHEMAS_DIRECTORY
    example = json.loads((schema_root / f"{name}.example.json").read_text(encoding="utf-8"))
    assert_valid(f"{SCHEMAS_DIRECTORY}/{name}.v1.schema.json", example)


# ---------------------------------------------------------------------- Receiver (HTTP)


async def test_missing_token_is_401_with_the_error_contract(api: httpx.AsyncClient) -> None:
    response = await api.get("/v1/sum/services")
    assert response.status_code == 401
    assert_valid("common/api-error.v1.schema.json", response.json())
    assert response.json()["errorCode"] == "Unauthorized"


async def test_invalid_token_is_401(api: httpx.AsyncClient) -> None:
    response = await api.get("/v1/sum/services", headers={"Authorization": "Bearer invalido"})
    assert response.status_code == 401


async def test_create_without_service_is_400_with_the_error_contract(
    api: httpx.AsyncClient, authorization: dict[str, str]
) -> None:
    response = await api.post("/v1/sum/services", json={}, headers=authorization)
    assert response.status_code == 400
    assert_valid("common/api-error.v1.schema.json", response.json())
    assert response.json()["errorCode"] == "ValidationFailed"


# ---------------------------------------------------------------------- loop completo


async def wait_for_operation(
    api: httpx.AsyncClient, headers: dict[str, str], resource_id: str, operation_id: str
) -> dict[str, Any]:
    """Acompanha a Operation até `completed`. Falha se ela falhar ou o prazo acabar.

    A Operation existe desde o `202`; é por ela que o cliente sabe quando o pedido terminou.
    """
    deadline = asyncio.get_running_loop().time() + LOOP_TIMEOUT_SECONDS
    path = f"/v1/sum/services/{resource_id}/operations/{operation_id}"
    while True:
        response = await api.get(path, headers=headers)
        # `404` até o Manager gravar a Operation (`docs/RESOURCE-CONTROL-LOOP.md`, §6.1.1).
        if response.status_code == 404 and asyncio.get_running_loop().time() <= deadline:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue
        assert response.status_code == 200, response.text
        operation = response.json()
        assert_valid("common/operation.v1.schema.json", operation)
        assert operation["operationStatus"] != "failed", operation
        if operation["operationStatus"] == "completed":
            return operation
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"operação não concluída em {LOOP_TIMEOUT_SECONDS}s: {operation}")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def wait_for_resource(
    api: httpx.AsyncClient,
    headers: dict[str, str],
    resource_id: str,
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    """Lê a ligação até o predicado valer, ou falha com o último estado observado."""
    deadline = asyncio.get_running_loop().time() + LOOP_TIMEOUT_SECONDS
    while True:
        response = await api.get(f"/v1/sum/services/{resource_id}", headers=headers)
        assert response.status_code == 200, response.text
        resource = response.json()
        if predicate(resource):
            return resource
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"condição não atendida em {LOOP_TIMEOUT_SECONDS}s: {resource}")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def test_enable_then_disable_runs_the_whole_loop(
    api: httpx.AsyncClient,
    authorization: dict[str, str],
    created_resource_ids: list[str],
) -> None:
    """Ligar e desligar `ipm` pela API: Manager, Publisher, Reconciler, Executor e Observer reais.

    Exige a stack do SUM no ar e um solicitante com `sum.ipm.enable`, `sum.ipm.disable` e
    `sum.ipm.get` (ver README). Não deixa o serviço ligado ao final.
    """
    # 1. Ligar: 202 com o contrato de aceite.
    accepted = await api.post(
        "/v1/sum/services",
        json={"service": SERVICE},
        headers={**authorization, "Idempotency-Key": str(uuid.uuid7())},
    )
    assert accepted.status_code == 202, accepted.text
    assert_valid("common/api-accepted-response.v1.schema.json", accepted.json())
    resource_id = accepted.json()["resourceId"]
    created_resource_ids.append(resource_id)
    await wait_for_operation(api, authorization, resource_id, accepted.json()["operationId"])

    # 2. O loop converge: fase Ready, com as roles do serviço observadas no Zitadel.
    enabled = await wait_for_resource(
        api,
        authorization,
        resource_id,
        lambda r: r["phase"] == "Ready" and r["desired"]["lifecycle"] == "present",
    )
    assert_valid("sum/service/resource.v1.schema.json", enabled)
    assert enabled["desired"]["service"] == SERVICE
    assert set(enabled["desired"]["serviceRoles"]) <= set(enabled["observed"]["serviceRoles"])

    # 3. A ligação aparece na listagem do solicitante.
    listed = await api.get("/v1/sum/services", headers=authorization)
    assert listed.status_code == 200
    assert_valid("sum/service/api-list-response.v1.schema.json", listed.json())
    assert resource_id in [item["resourceId"] for item in listed.json()["items"]]

    # 4. Ligar o mesmo serviço de novo é recusado: a unicidade do par ativo é do Manager/SSOT.
    duplicate = await api.post("/v1/sum/services", json={"service": SERVICE}, headers=authorization)
    assert duplicate.status_code == 409, duplicate.text
    assert_valid("common/api-error.v1.schema.json", duplicate.json())

    # 5. Desligar com a versão lida: 202, e o loop revoga as roles.
    version = enabled["resourceVersion"]
    removed = await api.delete(
        f"/v1/sum/services/{resource_id}",
        params={"resourceVersion": version},
        headers=authorization,
    )
    assert removed.status_code == 202, removed.text
    assert_valid("common/api-accepted-response.v1.schema.json", removed.json())
    await wait_for_operation(api, authorization, resource_id, removed.json()["operationId"])

    disabled = await wait_for_resource(
        api,
        authorization,
        resource_id,
        lambda r: r["phase"] == "Ready" and r["desired"]["lifecycle"] == "absent",
    )
    assert disabled["observed"]["serviceRoles"] == []

    # 6. Ligar de novo reaproveita o mesmo recurso: o par tem uma linha só (decisão 0033).
    again = await api.post("/v1/sum/services", json={"service": SERVICE}, headers=authorization)
    assert again.status_code == 202, again.text
    assert again.json()["resourceId"] == resource_id
    await wait_for_operation(api, authorization, resource_id, again.json()["operationId"])
    reenabled = await wait_for_resource(
        api,
        authorization,
        resource_id,
        lambda r: r["phase"] == "Ready" and r["desired"]["lifecycle"] == "present",
    )
    assert reenabled["desiredGeneration"] == disabled["desiredGeneration"] + 1
    listed_again = await api.get("/v1/sum/services", headers=authorization)
    assert [i["resourceId"] for i in listed_again.json()["items"]].count(resource_id) == 1

    # 7. Desliga de novo: o teste termina desligado (a limpeza não apaga ligação ativa).
    final = await api.delete(
        f"/v1/sum/services/{resource_id}",
        params={"resourceVersion": reenabled["resourceVersion"]},
        headers=authorization,
    )
    assert final.status_code == 202, final.text
    await wait_for_operation(api, authorization, resource_id, final.json()["operationId"])
    await wait_for_resource(
        api,
        authorization,
        resource_id,
        lambda r: r["phase"] == "Ready" and r["desired"]["lifecycle"] == "absent",
    )
