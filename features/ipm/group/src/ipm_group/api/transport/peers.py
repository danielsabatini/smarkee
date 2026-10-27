"""Consulta aos APIs parceiras (Organization, User, ServiceAccount) na rede interna."""

from typing import cast

import httpx

from ipm_group.api.settings import PeersSettings

ORGANIZATIONS_PATH = "/v1/ipm/organizations"
USERS_PATH = "/v1/ipm/users"
SERVICEACCOUNTS_PATH = "/v1/ipm/serviceaccounts"
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404


class UserPeer:
    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

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
