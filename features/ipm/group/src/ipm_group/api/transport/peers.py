"""Consulta aos APIs parceiras (Organization, User, ServiceAccount) na rede interna."""

from typing import cast

import httpx

from ipm_group.api.domain.access import AccessCheckError, OrganizationAccess
from ipm_group.api.settings import PeersSettings

ORGANIZATIONS_PATH = "/v1/ipm/organizations"
USERS_PATH = "/v1/ipm/users"
SERVICEACCOUNTS_PATH = "/v1/ipm/serviceaccounts"
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404


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
            document: object = response.json()
        except ValueError:
            raise AccessCheckError(retryable=True) from None
        desired: object = (
            cast("dict[str, object]", document).get("desired")
            if isinstance(document, dict)
            else None
        )
        if not isinstance(desired, dict):
            raise AccessCheckError(retryable=True)
        lifecycle = cast("dict[str, object]", desired).get("lifecycle")
        return OrganizationAccess.OWNED if lifecycle == "present" else OrganizationAccess.NOT_OWNED


class UserPeer:
    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def get_user_organization(self, user_id: str, access_token: str) -> str | None:
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
            data: object = response.json()
            if not isinstance(data, dict):
                return None
            desired = cast("dict[str, object]", data).get("desired")
            if (
                isinstance(desired, dict)
                and cast("dict[str, object]", desired).get("lifecycle") == "present"
            ):
                org_id = cast("dict[str, object]", desired).get("organizationId")
                return str(org_id) if org_id is not None else None
        except Exception:
            return None
        return None

    async def count_users_with_group(
        self, organization_id: str, group_name: str, access_token: str
    ) -> int:
        try:
            response = await self._client.get(
                f"{self._settings.users_url}{USERS_PATH}",
                params={"organizationId": organization_id, "limit": 200},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError:
            return 0
        if response.status_code != HTTP_OK:
            return 0
        try:
            data: object = response.json()
            if not isinstance(data, dict):
                return 0
            items_raw = cast("dict[str, object]", data).get("items")
            if not isinstance(items_raw, list):
                return 0
            count = 0
            for item in cast("list[object]", items_raw):
                if not isinstance(item, dict):
                    continue
                desired = cast("dict[str, object]", item).get("desired")
                if (
                    isinstance(desired, dict)
                    and cast("dict[str, object]", desired).get("lifecycle") == "present"
                ):
                    groups_raw = cast("dict[str, object]", desired).get("groups")
                    if isinstance(groups_raw, list) and group_name in cast(
                        "list[object]", groups_raw
                    ):
                        count += 1
            return count
        except Exception:
            return 0


class ServiceAccountPeer:
    """Reconhece a service account (identidade de máquina) pelo próprio registro (decisão 0094)."""

    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def get_serviceaccount_organization(
        self, serviceaccount_id: str, access_token: str
    ) -> str | None:
        """Organization da service account, ou `None` quando o solicitante não é uma."""
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
            data: object = response.json()
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        desired = cast("dict[str, object]", data).get("desired")
        if not isinstance(desired, dict):
            return None
        fields = cast("dict[str, object]", desired)
        organization_id = fields.get("organizationId")
        if fields.get("lifecycle") != "present" or organization_id is None:
            return None
        return str(organization_id)
