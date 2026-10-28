"""Conformidade de sum.service pela rede: gateway, API síncrona e SSOT (decisão 0098).

A API admite a escrita na requisição (`201` na ligação, `202` no desligamento, ambos com o
recurso); o Controller converge o Zitadel depois. O teste acompanha a convergência lendo o recurso
pela API, e valida exemplos e respostas contra os JSON Schemas de `schemas/`.
"""

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
    "api-list-response",
    "desired",
    "observed",
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


# ---------------------------------------------------------------------- API (HTTP)


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


def is_enabled(resource: dict[str, Any]) -> bool:
    """Ligação convergida: a observação confirma a geração e o `desired` é `present`."""
    return (
        resource["phase"] == "Ready"
        and resource["desired"]["lifecycle"] == "present"
        and resource.get("observedGeneration") == resource["desiredGeneration"]
    )


def is_disabled(resource: dict[str, Any]) -> bool:
    return (
        resource["phase"] == "Ready"
        and resource["desired"]["lifecycle"] == "absent"
        and resource.get("observedGeneration") == resource["desiredGeneration"]
    )


async def test_enable_then_disable_runs_the_whole_loop(
    api: httpx.AsyncClient,
    authorization: dict[str, str],
    created_resource_ids: list[str],
) -> None:
    """Ligar e desligar `ipm` pela API, com API, Publisher e Controller reais.

    Exige a stack do SUM no ar e um solicitante com conta de cobrança (`BillingAccountRequired`) e
    com `sum.ipm.enable`, `sum.ipm.disable` e `sum.ipm.get` (ver README). Não deixa o serviço ligado
    ao final.
    """
    # 1. Ligar: 201 com o recurso (sem Operation).
    created = await api.post(
        "/v1/sum/services",
        json={"service": SERVICE},
        headers={**authorization, "Idempotency-Key": str(uuid.uuid7())},
    )
    assert created.status_code == 201, created.text
    assert_valid("sum/service/resource.v1.schema.json", created.json())
    resource_id = created.json()["resourceId"]
    created_resource_ids.append(resource_id)

    # 2. O Controller converge: fase Ready, com as permissões do serviço observadas no Zitadel.
    enabled = await wait_for_resource(api, authorization, resource_id, is_enabled)
    assert_valid("sum/service/resource.v1.schema.json", enabled)
    assert enabled["desired"]["service"] == SERVICE
    assert set(enabled["desired"]["servicePermissions"]) <= set(
        enabled["observed"]["servicePermissions"]
    )

    # 3. A ligação aparece na listagem do solicitante.
    listed = await api.get("/v1/sum/services", headers=authorization)
    assert listed.status_code == 200
    assert_valid("sum/service/api-list-response.v1.schema.json", listed.json())
    assert resource_id in [item["resourceId"] for item in listed.json()["items"]]

    # 4. Ligar o mesmo serviço de novo é recusado: a unicidade do par ativo é do SSOT.
    duplicate = await api.post("/v1/sum/services", json={"service": SERVICE}, headers=authorization)
    assert duplicate.status_code == 409, duplicate.text
    assert_valid("common/api-error.v1.schema.json", duplicate.json())
    assert duplicate.json()["errorCode"] == "AlreadyEnabled"

    # 5. Desligar com a versão lida: 202 com o recurso, e o Controller revoga as permissões.
    removed = await api.delete(
        f"/v1/sum/services/{resource_id}",
        params={"resourceVersion": enabled["resourceVersion"]},
        headers=authorization,
    )
    assert removed.status_code == 202, removed.text
    assert_valid("sum/service/resource.v1.schema.json", removed.json())
    disabled = await wait_for_resource(api, authorization, resource_id, is_disabled)
    assert disabled["observed"]["servicePermissions"] == []

    # 6. Ligar de novo reaproveita o mesmo recurso: o par tem uma linha só (decisão 0033).
    again = await api.post("/v1/sum/services", json={"service": SERVICE}, headers=authorization)
    assert again.status_code == 201, again.text
    assert again.json()["resourceId"] == resource_id
    reenabled = await wait_for_resource(api, authorization, resource_id, is_enabled)
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
    await wait_for_resource(api, authorization, resource_id, is_disabled)
