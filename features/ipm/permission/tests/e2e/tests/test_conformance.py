"""Conformidade de ipm.permission pela rede: a API recusa quem não autentica ou envia lixo."""

import httpx
from contracts import assert_valid


async def test_missing_token_is_401_with_the_error_contract(api: httpx.AsyncClient) -> None:
    response = await api.get("/v1/ipm/permissions")
    assert response.status_code == 401
    assert_valid("common/api-error.v1.schema.json", response.json())
    assert response.json()["errorCode"] == "Unauthorized"


async def test_invalid_token_is_401(api: httpx.AsyncClient) -> None:
    response = await api.get("/v1/ipm/permissions", headers={"Authorization": "Bearer invalido"})
    assert response.status_code == 401


async def test_unknown_body_field_is_400(api: httpx.AsyncClient, headers: dict[str, str]) -> None:
    response = await api.post(
        "/v1/ipm/permissions",
        json={"name": "bsm.e2e.ok", "description": "Descrição válida", "unknownField": "x"},
        headers=headers,
    )
    assert response.status_code == 400
    assert_valid("common/api-error.v1.schema.json", response.json())
