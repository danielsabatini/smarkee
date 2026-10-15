"""Estrutura do Zitadel de dev esperada pelas decisões 0010, 0014, 0026, 0027 e 0028.

Usa só a API v2 do Zitadel (decisão 0029).

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
ORGANIZATION_SERVICE = "zitadel.org.v2.OrganizationService"
PROJECT_SERVICE = "zitadel.project.v2.ProjectService"
APPLICATION_SERVICE = "zitadel.application.v2.ApplicationService"
AUTHORIZATION_SERVICE = "zitadel.authorization.v2.AuthorizationService"
PERMISSION_SERVICE = "zitadel.internal_permission.v2.InternalPermissionService"
ADMIN_ROLES = {"core.user.admin", "ipm.organization.admin"}
SERVICE_ACCOUNTS = {"core-user-executor", "core-user-observer", "core-organization-executor"}

pytestmark = pytest.mark.skipif(
    not KEY_FILE, reason="CONFORMANCE_ZITADEL_KEY_FILE não definida (chave do platform-bootstrap)"
)


class Zitadel:
    """Cliente mínimo da API do Zitadel, só para leitura."""

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
        self._client = httpx.Client(
            base_url=BASE_URL, headers={"Host": HOST, "Connect-Protocol-Version": "1"}, timeout=20
        )
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

    def connect(self, service: str, method: str, body: dict[str, Any] | None = None) -> Any:
        """Chamada Connect da API v2 (`POST /<serviço>/<método>`), já em JSON."""
        response = self._client.post(f"/{service}/{method}", json=body or {})
        response.raise_for_status()
        return response.json()

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
    found = zitadel.connect(ORGANIZATION_SERVICE, "ListOrganizations")["result"]
    return {org["name"]: org["id"] for org in found}


def projects_owned_by(zitadel: Zitadel, org_id: str) -> dict[str, dict[str, Any]]:
    """Projetos da organização. A listagem por organização também traz os projetos delegados a ela
    (Project Grant); aqui ficam só os que ela possui."""
    found = zitadel.connect(
        PROJECT_SERVICE,
        "ListProjects",
        {"filters": [{"organizationIdFilter": {"organizationId": org_id}}]},
    ).get("projects", [])
    return {p["name"]: p for p in found if p["organizationId"] == org_id}


@pytest.fixture(scope="module")
def project_id(zitadel: Zitadel, orgs: dict[str, str]) -> str:
    return projects_owned_by(zitadel, orgs["core"])["roles"]["projectId"]


def administrators(zitadel: Zitadel, resource: dict[str, Any]) -> dict[str, set[str]]:
    """Papéis de administração (membros) do recurso: a instância ou uma organização."""
    found = zitadel.connect(
        PERMISSION_SERVICE, "ListAdministrators", {"filters": [{"resource": resource}]}
    ).get("administrators", [])
    return {a["user"]["preferredLoginName"]: set(a["roles"]) for a in found}


def members(zitadel: Zitadel, org_id: str) -> dict[str, set[str]]:
    return administrators(zitadel, {"organizationId": org_id})


def user_names(zitadel: Zitadel, org_id: str) -> set[str]:
    found = zitadel.search(
        "/v2/users", {"queries": [{"organizationIdQuery": {"organizationId": org_id}}]}
    )
    return {u["username"] for u in found}


def test_the_three_organizations_exist(orgs: dict[str, str]) -> None:
    assert {"smarkee", "core", "register"} <= set(orgs)


def test_public_registration_is_off(zitadel: Zitadel) -> None:
    policy = zitadel.get("/v2/settings/login")["settings"]
    assert not policy.get("allowRegister"), "o cadastro público do Zitadel deve estar desligado"


def test_roles_project_asserts_and_checks_roles(zitadel: Zitadel, orgs: dict[str, str]) -> None:
    projects = projects_owned_by(zitadel, orgs["core"])
    assert "roles" in projects and "smarkee" not in projects
    assert projects["roles"].get("projectRoleAssertion") is True
    assert projects["roles"].get("authorizationRequired") is True  # `projectRoleCheck` da v1


def test_roles_follow_the_naming_standard_and_group_by_module(
    zitadel: Zitadel, orgs: dict[str, str], project_id: str
) -> None:
    roles = zitadel.connect(PROJECT_SERVICE, "ListProjectRoles", {"projectId": project_id})[
        "projectRoles"
    ]
    assert {r["key"] for r in roles} == ACTION_ROLES | ADMIN_ROLES
    assert all(r.get("group") == r["key"].split(".")[0] for r in roles)


def test_cli_application_is_a_public_native_client_with_jwt(
    zitadel: Zitadel, orgs: dict[str, str], project_id: str
) -> None:
    found = zitadel.connect(
        APPLICATION_SERVICE,
        "ListApplications",
        {"filters": [{"projectIdFilter": {"projectId": project_id}}]},
    )["applications"]
    config = {a["name"]: a for a in found}["cli"]["oidcConfiguration"]
    assert config["applicationType"] == "OIDC_APP_TYPE_NATIVE"
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
    grants = zitadel.connect(PROJECT_SERVICE, "ListProjectGrants")["projectGrants"]
    to_register = [
        g
        for g in grants
        if g["projectId"] == project_id and g["grantedOrganizationId"] == orgs["register"]
    ]
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
    by_name = administrators(zitadel, {"instance": True})
    assert by_name.get("platform-bootstrap@smarkee.internal") == {"IAM_OWNER"}
    assert by_name.get("core-organization-executor") == {"IAM_ORG_MANAGER"}


def operator_authorizations(
    zitadel: Zitadel, orgs: dict[str, str], project_id: str
) -> dict[str, set[str]]:
    """Autorizações do projeto `roles` na `core`: nome de login → roles."""
    found = zitadel.connect(
        AUTHORIZATION_SERVICE,
        "ListAuthorizations",
        {"filters": [{"projectId": {"id": project_id}}, {"organizationId": {"id": orgs["core"]}}]},
    ).get("authorizations", [])
    return {g["user"]["preferredLoginName"]: {r["key"] for r in g["roles"]} for g in found}


def test_only_operators_are_authorized_in_core(
    zitadel: Zitadel, orgs: dict[str, str], project_id: str
) -> None:
    """Na `core` só há operadores: cada autorização tem uma role `*.admin` (o escopo) e, além
    dela, as roles de ação que o operador exerce (decisão 0031). Usuários cadastrados são
    autorizados na `register`, pelo Project Grant, e nunca recebem `*.admin`."""
    operators = operator_authorizations(zitadel, orgs, project_id)
    assert operators, "falta a autorização do operador (`*.admin`) no projeto roles"
    for name, roles in operators.items():
        assert roles & ADMIN_ROLES, f"{name} está na core sem nenhuma role `*.admin`"
        assert roles <= ACTION_ROLES | ADMIN_ROLES, f"{name} tem roles fora do conjunto conhecido"


def test_default_operator_holds_every_role(
    zitadel: Zitadel, orgs: dict[str, str], project_id: str
) -> None:
    """O operador padrão tem `*.admin` e as roles de ação: o Receiver exige as duas coisas
    (o que pode fazer e em quais recursos). Role de ação nova sem concessão aparece aqui."""
    operators = operator_authorizations(zitadel, orgs, project_id)
    default = next((r for n, r in operators.items() if n.startswith("admin@smarkee")), None)
    assert default is not None, "falta a autorização do operador padrão (admin@smarkee)"
    assert default == ACTION_ROLES | ADMIN_ROLES


def test_register_has_no_project_of_its_own(zitadel: Zitadel, orgs: dict[str, str]) -> None:
    assert projects_owned_by(zitadel, orgs["register"]) == {}
