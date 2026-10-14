"""Estrutura do Zitadel de dev esperada pelas decisões 0010, 0014, 0026, 0027 e 0028.

Somente leitura: usa a chave da conta `platform-bootstrap` (`CONFORMANCE_ZITADEL_KEY_FILE`) e não
altera nada.
Sem a chave, os testes são pulados. A estrutura é criada à mão (ver `infrastructure/dev/README.md`);
estes testes dizem se ela está como o desenho manda.
"""

import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import jwt
import pytest

ISSUER = os.environ.get("CONFORMANCE_ZITADEL_ISSUER", "http://ipm-dev.smarkee.com.br:8080")
BASE_URL = os.environ.get("CONFORMANCE_ZITADEL_URL", "http://localhost:8080")
HOST = os.environ.get("CONFORMANCE_ZITADEL_HOST", "ipm-dev.smarkee.com.br:8080")
KEY_FILE = os.environ.get("CONFORMANCE_ZITADEL_KEY_FILE")

ACTION_ROLES = {
    "core.user.delete",
    "core.user.get",
    "ipm.organization.create",
    "ipm.organization.delete",
    "ipm.organization.get",
    "ipm.organization.list",
    "ipm.organization.update",
}
ADMIN_ROLES = {"core.user.admin", "ipm.organization.admin"}
SERVICE_ACCOUNTS = {"core-user-executor", "core-user-observer", "core-organization-executor"}

pytestmark = pytest.mark.skipif(
    not KEY_FILE, reason="CONFORMANCE_ZITADEL_KEY_FILE não definida (chave do platform-bootstrap)"
)


class Zitadel:
    """Cliente mínimo da API de gestão, só para leitura."""

    def __init__(self, key: dict[str, str]) -> None:
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": key["userId"],
                "sub": key["userId"],
                "aud": ISSUER,
                "iat": now,
                "exp": now + 300,
            },
            key["key"],
            algorithm="RS256",
            headers={"kid": key["keyId"]},
        )
        self._client = httpx.Client(base_url=BASE_URL, headers={"Host": HOST}, timeout=20)
        response = self._client.post(
            "/oauth/v2/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "scope": "openid urn:zitadel:iam:org:project:id:zitadel:aud",
                "assertion": assertion,
            },
        )
        response.raise_for_status()
        self._client.headers["Authorization"] = "Bearer " + response.json()["access_token"]

    def search(
        self, path: str, body: dict[str, Any] | None = None, org: str | None = None
    ) -> list[Any]:
        headers = {"x-zitadel-orgid": org} if org else {}
        response = self._client.post(path, json=body or {}, headers=headers)
        response.raise_for_status()
        return cast("list[Any]", response.json().get("result") or [])

    def get(self, path: str) -> dict[str, Any]:
        response = self._client.get(path)
        response.raise_for_status()
        return cast("dict[str, Any]", response.json())

    def close(self) -> None:
        self._client.close()


@pytest.fixture(scope="module")
def zitadel() -> Iterator[Zitadel]:
    client = Zitadel(json.loads(Path(cast("str", KEY_FILE)).read_text(encoding="utf-8")))
    yield client
    client.close()


@pytest.fixture(scope="module")
def orgs(zitadel: Zitadel) -> dict[str, str]:
    return {org["name"]: org["id"] for org in zitadel.search("/admin/v1/orgs/_search")}


@pytest.fixture(scope="module")
def project_id(zitadel: Zitadel, orgs: dict[str, str]) -> str:
    projects = zitadel.search("/management/v1/projects/_search", org=orgs["core"])
    return next(p["id"] for p in projects if p["name"] == "roles")


def members(zitadel: Zitadel, org_id: str) -> dict[str, set[str]]:
    found = zitadel.search("/management/v1/orgs/me/members/_search", org=org_id)
    return {m.get("preferredLoginName") or m["userId"]: set(m["roles"]) for m in found}


def user_names(zitadel: Zitadel, org_id: str) -> set[str]:
    return {u["userName"] for u in zitadel.search("/management/v1/users/_search", org=org_id)}


def test_the_three_organizations_exist(orgs: dict[str, str]) -> None:
    assert {"smarkee", "core", "register"} <= set(orgs)


def test_public_registration_is_off(zitadel: Zitadel) -> None:
    policy = zitadel.get("/admin/v1/policies/login")["policy"]
    assert not policy.get("allowRegister"), "o cadastro público do Zitadel deve estar desligado"


def test_roles_project_asserts_and_checks_roles(zitadel: Zitadel, orgs: dict[str, str]) -> None:
    projects = {
        p["name"]: p for p in zitadel.search("/management/v1/projects/_search", org=orgs["core"])
    }
    assert "roles" in projects and "smarkee" not in projects
    assert projects["roles"].get("projectRoleAssertion") is True
    assert projects["roles"].get("projectRoleCheck") is True


def test_roles_follow_the_naming_standard_and_group_by_module(
    zitadel: Zitadel, orgs: dict[str, str], project_id: str
) -> None:
    roles = zitadel.search(f"/management/v1/projects/{project_id}/roles/_search", org=orgs["core"])
    assert {r["key"] for r in roles} == ACTION_ROLES | ADMIN_ROLES
    assert all(r.get("group") == r["key"].split(".")[0] for r in roles)


def test_cli_application_is_a_public_native_client_with_jwt(
    zitadel: Zitadel, orgs: dict[str, str], project_id: str
) -> None:
    apps = {
        a["name"]: a
        for a in zitadel.search(
            f"/management/v1/projects/{project_id}/apps/_search", org=orgs["core"]
        )
    }
    config = apps["cli"]["oidcConfig"]
    assert config["appType"] == "OIDC_APP_TYPE_NATIVE"
    assert config["authMethodType"] == "OIDC_AUTH_METHOD_TYPE_NONE"  # cliente público (PKCE)
    assert config["accessTokenType"] == "OIDC_TOKEN_TYPE_JWT"
    assert config["accessTokenRoleAssertion"] is True and config["idTokenRoleAssertion"] is True
    assert config["responseTypes"] == ["OIDC_RESPONSE_TYPE_CODE"]
    assert set(config["grantTypes"]) == {
        "OIDC_GRANT_TYPE_AUTHORIZATION_CODE",
        "OIDC_GRANT_TYPE_REFRESH_TOKEN",
    }
    assert config["redirectUris"] == ["http://127.0.0.1/callback"]


def test_project_grant_to_register_delegates_only_the_action_roles(
    zitadel: Zitadel, orgs: dict[str, str], project_id: str
) -> None:
    grants = zitadel.search(
        f"/management/v1/projects/{project_id}/grants/_search", org=orgs["core"]
    )
    to_register = [g for g in grants if g["grantedOrgId"] == orgs["register"]]
    assert len(to_register) == 1
    assert set(to_register[0]["grantedRoleKeys"]) == ACTION_ROLES  # sem as roles *.admin


def test_service_accounts_live_in_core(zitadel: Zitadel, orgs: dict[str, str]) -> None:
    assert user_names(zitadel, orgs["core"]) >= SERVICE_ACCOUNTS
    assert not {n for n in user_names(zitadel, orgs["register"]) if n.startswith("core-")}


def test_executor_and_observer_have_roles_only_in_register(
    zitadel: Zitadel, orgs: dict[str, str]
) -> None:
    in_register = members(zitadel, orgs["register"])
    assert in_register.get("core-user-executor") == {"ORG_USER_MANAGER"}
    assert in_register.get("core-user-observer") == {"ORG_OWNER_VIEWER"}
    in_core = members(zitadel, orgs["core"])
    assert not {name for name in in_core if name.startswith("core-user-")}, (
        "o Executor e o Observer do User não têm papel na organização core (decisão 0027)"
    )


def test_instance_members(zitadel: Zitadel) -> None:
    found = zitadel.search("/admin/v1/members/_search")
    by_name = {m.get("preferredLoginName") or m["userId"]: set(m["roles"]) for m in found}
    assert by_name.get("platform-bootstrap@smarkee.internal") == {"IAM_OWNER"}
    assert by_name.get("core-organization-executor") == {"IAM_ORG_MANAGER"}


def test_only_operators_are_authorized_in_core(
    zitadel: Zitadel, orgs: dict[str, str], project_id: str
) -> None:
    grants = zitadel.search(
        "/management/v1/users/grants/_search",
        {"queries": [{"projectIdQuery": {"projectId": project_id}}]},
        org=orgs["core"],
    )
    assert grants, "falta a autorização do operador (`*.admin`) no projeto roles"
    for grant in grants:
        assert set(grant["roleKeys"]) <= ADMIN_ROLES, (
            f"{grant.get('userName')} tem roles de ação na core; elas valem na register "
            "(decisão 0027)"
        )


def test_register_has_no_project_of_its_own(zitadel: Zitadel, orgs: dict[str, str]) -> None:
    assert zitadel.search("/management/v1/projects/_search", org=orgs["register"]) == []
