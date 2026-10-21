"""Conformidade de ipm.user pela rede: o gateway e o Receiver recusam quem não se autentica."""

import httpx
from contracts import assert_valid


async def test_missing_token_is_401_with_the_error_contract(api: httpx.AsyncClient) -> None:
    response = await api.get("/v1/ipm/users", params={"organizationId": "org-1"})
    assert response.status_code == 401
    assert_valid("common/api-error.v1.schema.json", response.json())
    assert response.json()["errorCode"] == "Unauthorized"


async def test_invalid_token_is_401(api: httpx.AsyncClient) -> None:
    response = await api.post(
        "/v1/ipm/users",
        json={"organizationId": "org-1", "givenName": "A", "familyName": "B", "email": "a@x.com"},
        headers={"Authorization": "Bearer invalido"},
    )
    assert response.status_code == 401
