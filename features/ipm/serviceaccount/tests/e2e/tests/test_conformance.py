"""Conformidade de ipm.serviceaccount pela rede: gateway e Receiver recusam quem não autentica."""

import httpx
from contracts import assert_valid


async def test_missing_token_is_401_with_the_error_contract(api: httpx.AsyncClient) -> None:
    response = await api.get("/v1/ipm/serviceaccounts", params={"organizationId": "org-1"})
    assert response.status_code == 401
    assert_valid("common/api-error.v1.schema.json", response.json())
    assert response.json()["errorCode"] == "Unauthorized"


async def test_invalid_token_is_401(api: httpx.AsyncClient) -> None:
    response = await api.post(
        "/v1/ipm/serviceaccounts",
        json={"organizationId": "org-1", "name": "ci-deploy", "keys": []},
        headers={"Authorization": "Bearer invalido"},
    )
    assert response.status_code == 401
