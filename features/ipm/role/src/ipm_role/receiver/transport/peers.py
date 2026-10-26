"""Consulta aos Receivers parceiros (Organization, User, Group, ServiceAccount; 0092 e 0094).

Todas as consultas usam o token do solicitante (decisão 0040): o parceiro autoriza como se o
próprio solicitante perguntasse. Na dúvida, a resposta é erro (`AccessCheckError`), nunca "não".
"""

from typing import Any, cast

import httpx

from ipm_role.receiver.domain.access import AccessCheckError, OrganizationAccess
from ipm_role.receiver.settings import PeersSettings

ORGANIZATIONS_PATH = "/v1/ipm/organizations"
USERS_PATH = "/v1/ipm/users"
GROUPS_PATH = "/v1/ipm/groups"
SERVICEACCOUNTS_PATH = "/v1/ipm/serviceaccounts"
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
PAGE_SIZE = 200
MAXIMUM_PAGES = 50
"""Teto de páginas lidas ao procurar uso de uma Role; acima dele, o resultado é "não confirmado"."""


def _desired_of(document: object) -> dict[str, Any] | None:
    if not isinstance(document, dict):
        return None
    desired = cast("dict[str, Any]", document).get("desired")
    return cast("dict[str, Any]", desired) if isinstance(desired, dict) else None


class OrganizationPeer:
    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def access(self, organization_id: str, access_token: str) -> OrganizationAccess:
        try:
            response = await self._client.get(
                f"{self._settings.organizations_url}{ORGANIZATIONS_PATH}/{organization_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError:
            raise AccessCheckError(retryable=True) from None
        if response.status_code in (HTTP_NOT_FOUND, HTTP_FORBIDDEN):
            return OrganizationAccess.NOT_OWNED
        if response.status_code == HTTP_UNAUTHORIZED:
            raise AccessCheckError(retryable=False)
        if response.status_code != HTTP_OK:
            raise AccessCheckError(retryable=True)
        try:
            desired = _desired_of(response.json())
        except ValueError:
            raise AccessCheckError(retryable=True) from None
        if desired is None:
            raise AccessCheckError(retryable=True)
        return (
            OrganizationAccess.OWNED
            if desired.get("lifecycle") == "present"
            else OrganizationAccess.NOT_OWNED
        )


class UserPeer:
    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def get_user_organization(self, user_id: str, access_token: str) -> str | None:
        """Organization do próprio solicitante (todo usuário lê o próprio registro)."""
        try:
            response = await self._client.get(
                f"{self._settings.users_url}{USERS_PATH}/{user_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError:
            return None
        if response.status_code != HTTP_OK:
            return None
        try:
            desired = _desired_of(response.json())
        except ValueError:
            return None
        if desired is None or desired.get("lifecycle") != "present":
            return None
        organization_id = desired.get("organizationId")
        return str(organization_id) if organization_id is not None else None

    async def get_serviceaccount_organization(
        self, serviceaccount_id: str, access_token: str
    ) -> str | None:
        """Organization da service account solicitante (lê o próprio registro; decisão 0094)."""
        try:
            response = await self._client.get(
                f"{self._settings.serviceaccounts_url}{SERVICEACCOUNTS_PATH}/{serviceaccount_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError:
            return None
        if response.status_code != HTTP_OK:
            return None
        try:
            desired = _desired_of(response.json())
        except ValueError:
            return None
        if desired is None or desired.get("lifecycle") != "present":
            return None
        organization_id = desired.get("organizationId")
        return str(organization_id) if organization_id is not None else None


class RoleUsagePeer:
    """Informa se usuário, grupo ou service account usa uma Role (`ResourcesAttached`)."""

    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def role_in_use(self, organization_id: str, role_name: str, access_token: str) -> bool:
        for base_url, path in (
            (self._settings.users_url, USERS_PATH),
            (self._settings.groups_url, GROUPS_PATH),
            (self._settings.serviceaccounts_url, SERVICEACCOUNTS_PATH),
        ):
            if await self._listing_uses_role(
                f"{base_url}{path}", organization_id, role_name, access_token
            ):
                return True
        return False

    async def _listing_uses_role(
        self, url: str, organization_id: str, role_name: str, access_token: str
    ) -> bool:
        cursor: str | None = None
        for _ in range(MAXIMUM_PAGES):
            params: dict[str, str | int] = {"organizationId": organization_id, "limit": PAGE_SIZE}
            if cursor is not None:
                params["cursor"] = cursor
            try:
                response = await self._client.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=self._settings.timeout_seconds,
                )
            except httpx.HTTPError:
                raise AccessCheckError(retryable=True) from None
            if response.status_code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
                raise AccessCheckError(retryable=False)
            if response.status_code != HTTP_OK:
                raise AccessCheckError(retryable=True)
            try:
                document: object = response.json()
            except ValueError:
                raise AccessCheckError(retryable=True) from None
            if not isinstance(document, dict):
                raise AccessCheckError(retryable=True)
            body = cast("dict[str, Any]", document)
            items = body.get("items")
            if not isinstance(items, list):
                raise AccessCheckError(retryable=True)
            for item in cast("list[object]", items):
                desired = _desired_of(item)
                if desired is None or desired.get("lifecycle") != "present":
                    continue
                roles = desired.get("roles")
                if isinstance(roles, list) and role_name in cast("list[object]", roles):
                    return True
            next_cursor = body.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                return False
            cursor = next_cursor
        raise AccessCheckError(retryable=True)
