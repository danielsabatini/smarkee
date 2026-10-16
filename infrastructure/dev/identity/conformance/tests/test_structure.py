"""Estrutura do Zitadel de dev esperada pelas decisões 0010, 0014, 0026, 0027, 0028, 0031 e 0032.

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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import jwt
import pytest

ISSUER = os.environ.get("CONFORMANCE_ZITADEL_ISSUER", "http://ipm-dev.smarkee.com.br:8080")
BASE_URL = os.environ.get("CONFORMANCE_ZITADEL_URL", "http://localhost:8080")
HOST = os.environ.get("CONFORMANCE_ZITADEL_HOST", "ipm-dev.smarkee.com.br:8080")
KEY_FILE = os.environ.get("CONFORMANCE_ZITADEL_KEY_FILE")

# Um projeto de roles por módulo, na organização `core` (decisão 0032): as roles de ação (delegadas
# à `register` por Project Grant) e a role de operador `*.admin`, que fica fora do Grant.
ACTION_ROLES_BY_PROJECT = {
    "roles-core": {"core.user.delete", "core.user.get"},
    "roles-ipm": {
        "ipm.organization.create",
        "ipm.organization.delete",
        "ipm.organization.get",
        "ipm.organization.list",
        "ipm.organization.update",
    },
    "roles-sum": {"sum.ipm.disable", "sum.ipm.enable", "sum.ipm.get"},
}
ADMIN_ROLES_BY_PROJECT = {
    "roles-core": {"core.user.admin"},
    "roles-ipm": {"ipm.organization.admin"},
    "roles-sum": set[str](),
}
ACTION_ROLES = set[str]().union(*ACTION_ROLES_BY_PROJECT.values())
ADMIN_ROLES = set[str]().union(*ADMIN_ROLES_BY_PROJECT.values())
# Projetos cujo Project Grant o Executor do User administra (`PROJECT_GRANT_OWNER`).
USER_EXECUTOR_GRANT_PROJECTS = {"roles-core", "roles-sum"}
ORGANIZATION_SERVICE = "zitadel.org.v2.OrganizationService"
PROJECT_SERVICE = "zitadel.project.v2.ProjectService"
APPLICATION_SERVICE = "zitadel.application.v2.ApplicationService"
AUTHORIZATION_SERVICE = "zitadel.authorization.v2.AuthorizationService"
PERMISSION_SERVICE = "zitadel.internal_permission.v2.InternalPermissionService"
USER_SERVICE = "zitadel.user.v2.UserService"
# Alerta antes do vencimento, para a rotação manual ter folga (`infrastructure/dev/README.md`).
KEY_EXPIRATION_WARNING = timedelta(days=90)
SERVICE_ACCOUNTS = {
    "core-user-executor",
    "core-user-observer",
    "ipm-organization-executor",
    "ipm-organization-observer",
    "sum-service-executor",
    "sum-service-observer",
}
# Projeto que o Executor do SUM administra (decisão 0033): só o do `ipm`, nenhum outro módulo.
SUM_EXECUTOR_GRANT_PROJECT = "roles-ipm"

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
def project_ids(zitadel: Zitadel, orgs: dict[str, str]) -> dict[str, str]:
    """Nome → ID dos projetos de roles da `core` (`roles-<módulo>`, sem o projeto `clients`)."""
    owned = projects_owned_by(zitadel, orgs["core"])
    return {name: p["projectId"] for name, p in owned.items() if name.startswith("roles-")}


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


def test_the_access_token_lives_at_most_15_minutes(zitadel: Zitadel) -> None:
    """Uma revogação de role vale em até 15 minutos (decisão 0033).

    Leitura pela Admin API v1: não existe API v2 para as configurações de OIDC (exceção da seção
    24.2 do `AGENTS.md`, registrada na decisão 0033).
    """
    settings = zitadel.get("/admin/v1/settings/oidc")["settings"]
    assert settings["accessTokenLifetime"] == "900s", settings["accessTokenLifetime"]


def test_the_three_organizations_exist(orgs: dict[str, str]) -> None:
    assert {"smarkee", "core", "register"} <= set(orgs)


def test_public_registration_is_off(zitadel: Zitadel) -> None:
    policy = zitadel.get("/v2/settings/login")["settings"]
    assert not policy.get("allowRegister"), "o cadastro público do Zitadel deve estar desligado"


def test_one_roles_project_per_module_asserts_and_checks_roles(
    zitadel: Zitadel, orgs: dict[str, str]
) -> None:
    projects = projects_owned_by(zitadel, orgs["core"])
    roles_projects = {name: p for name, p in projects.items() if name.startswith("roles-")}
    assert set(roles_projects) == set(ACTION_ROLES_BY_PROJECT), (
        "um projeto de roles por módulo (0032)"
    )
    for name, project in roles_projects.items():
        assert project.get("projectRoleAssertion") is True, name
        assert project.get("authorizationRequired") is True, name  # `projectRoleCheck` da v1


def test_the_clients_project_has_no_roles_and_does_not_require_one_to_sign_in(
    zitadel: Zitadel, orgs: dict[str, str]
) -> None:
    """A aplicação do `sk` mora num projeto sem roles (decisão 0034).

    Com ela dentro de um projeto de roles, o Zitadel só põe no token as roles desse projeto, e o
    token não valeria nos Receivers dos outros módulos. Sem roles no projeto, a verificação de
    role na autenticação (`authorizationRequired`) precisa estar desligada: ninguém teria role nele.
    """
    projects = projects_owned_by(zitadel, orgs["core"])
    assert "clients" in projects, "o projeto `clients` da core (decisão 0034)"
    project = projects["clients"]
    assert not project.get("authorizationRequired")  # a API v2 omite o valor falso
    roles = zitadel.connect(
        PROJECT_SERVICE, "ListProjectRoles", {"projectId": project["projectId"]}
    )
    assert roles.get("projectRoles", []) == []
    grants = zitadel.connect(PROJECT_SERVICE, "ListProjectGrants").get("projectGrants", [])
    assert not [g for g in grants if g["projectId"] == project["projectId"]]


def test_roles_follow_the_naming_standard_and_group_by_module(
    zitadel: Zitadel, project_ids: dict[str, str]
) -> None:
    for name, project_id in project_ids.items():
        roles = zitadel.connect(PROJECT_SERVICE, "ListProjectRoles", {"projectId": project_id})[
            "projectRoles"
        ]
        assert {r["key"] for r in roles} == ACTION_ROLES_BY_PROJECT[name] | ADMIN_ROLES_BY_PROJECT[
            name
        ]
        module = name.removeprefix("roles-")
        assert all(r["key"].split(".")[0] == module for r in roles), (
            "role fora do módulo do projeto"
        )
        assert all(r.get("group") == module for r in roles)


def test_cli_application_is_a_public_native_client_with_jwt(
    zitadel: Zitadel, orgs: dict[str, str]
) -> None:
    clients = projects_owned_by(zitadel, orgs["core"])["clients"]
    found = zitadel.connect(
        APPLICATION_SERVICE,
        "ListApplications",
        {"filters": [{"projectIdFilter": {"projectId": clients["projectId"]}}]},
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


def test_no_roles_project_holds_an_application(
    zitadel: Zitadel, project_ids: dict[str, str]
) -> None:
    """As aplicações moram no `clients` (decisão 0034): um projeto de roles não tem nenhuma."""
    for name, project_id in project_ids.items():
        found = zitadel.connect(
            APPLICATION_SERVICE,
            "ListApplications",
            {"filters": [{"projectIdFilter": {"projectId": project_id}}]},
        ).get("applications", [])
        assert found == [], f"{name} não deve ter aplicações: {[a['name'] for a in found]}"


def test_each_project_grant_to_register_delegates_only_its_action_roles(
    zitadel: Zitadel, orgs: dict[str, str], project_ids: dict[str, str]
) -> None:
    grants = zitadel.connect(PROJECT_SERVICE, "ListProjectGrants")["projectGrants"]
    to_register = {
        g["projectId"]: set(g["grantedRoleKeys"])
        for g in grants
        if g["grantedOrganizationId"] == orgs["register"]
    }
    for name, project_id in project_ids.items():
        assert to_register.get(project_id) == ACTION_ROLES_BY_PROJECT[name], (
            f"o Grant de {name} para a register deve ter só as roles de ação (sem `*.admin`)"
        )


def test_service_accounts_live_in_core(zitadel: Zitadel, orgs: dict[str, str]) -> None:
    assert user_names(zitadel, orgs["core"]) >= SERVICE_ACCOUNTS
    assert not {
        n
        for n in user_names(zitadel, orgs["register"])
        if n.startswith(("core-", "sum-service-", "ipm-organization-"))
    }


def test_executor_and_observer_have_roles_only_in_register(
    zitadel: Zitadel, orgs: dict[str, str]
) -> None:
    in_register = members(zitadel, orgs["register"])
    # `ORG_USER_CREATOR` cria e remove usuários, mas não concede roles (decisão 0032).
    assert in_register.get("core-user-executor") == {"ORG_USER_CREATOR"}
    assert in_register.get("core-user-observer") == {"ORG_OWNER_VIEWER"}
    # O Observer do SUM só lê a register; o Executor do SUM não tem papel nela (só o Grant, abaixo).
    assert in_register.get("sum-service-observer") == {"ORG_OWNER_VIEWER"}
    assert "sum-service-executor" not in in_register
    # As contas da Organization têm só papel de instância (abaixo), nenhum na `register`.
    assert not {n for n in in_register if n.startswith("ipm-organization-")}
    in_core = members(zitadel, orgs["core"])
    assert not {
        name
        for name in in_core
        if name.startswith(("core-user-", "sum-service-", "ipm-organization-"))
    }, "o Executor e o Observer não têm papel na organização core (decisão 0027)"


def test_user_executor_grants_roles_only_in_its_modules(
    zitadel: Zitadel, orgs: dict[str, str], project_ids: dict[str, str]
) -> None:
    """O isolamento do SUM: o Executor do User é `PROJECT_GRANT_OWNER` só nos Grants dos módulos
    `core` e `sum`; no do `ipm` ele não é, e o Zitadel nega a concessão (decisão 0032)."""
    for name, project_id in project_ids.items():
        owners = administrators(
            zitadel,
            {"projectGrant": {"projectId": project_id, "organizationId": orgs["register"]}},
        )
        has_role = owners.get("core-user-executor") == {"PROJECT_GRANT_OWNER"}
        assert has_role == (name in USER_EXECUTOR_GRANT_PROJECTS), name


def test_sum_executor_is_project_grant_owner_only_in_the_ipm_grant(
    zitadel: Zitadel, orgs: dict[str, str], project_ids: dict[str, str]
) -> None:
    """O Executor do SUM só concede as roles do `ipm` (decisão 0032): é `PROJECT_GRANT_OWNER` só
    no Grant de `roles-ipm` para a `register`, e em nenhum outro projeto."""
    for name, project_id in project_ids.items():
        owners = administrators(
            zitadel,
            {"projectGrant": {"projectId": project_id, "organizationId": orgs["register"]}},
        )
        has_role = owners.get("sum-service-executor") == {"PROJECT_GRANT_OWNER"}
        assert has_role == (name == SUM_EXECUTOR_GRANT_PROJECT), name


def test_service_account_keys_exist_and_are_not_close_to_expiry(
    zitadel: Zitadel, orgs: dict[str, str]
) -> None:
    """Cada conta de serviço tem chave, e nenhuma vence em menos de `KEY_EXPIRATION_WARNING`.

    A rotação é manual (`infrastructure/dev/README.md`, "Rotação das chaves"): este teste é o aviso.
    """
    names = {
        u["userId"]: u["username"]
        for u in zitadel.search(
            "/v2/users", {"queries": [{"organizationIdQuery": {"organizationId": orgs["core"]}}]}
        )
    }
    keys = zitadel.connect(USER_SERVICE, "ListKeys", {}).get("result", [])
    by_account: dict[str, list[datetime]] = {name: [] for name in SERVICE_ACCOUNTS}
    for key in keys:
        name = names.get(key["userId"])
        if name in by_account:
            by_account[name].append(
                datetime.fromisoformat(key["expirationDate"].replace("Z", "+00:00"))
            )
    limit = datetime.now(UTC) + KEY_EXPIRATION_WARNING
    for name, expirations in by_account.items():
        assert expirations, f"{name} não tem chave"
        assert max(expirations) > limit, f"chave de {name} vence antes de {limit.date()}"


def test_instance_members(zitadel: Zitadel) -> None:
    by_name = administrators(zitadel, {"instance": True})
    assert by_name.get("platform-bootstrap@smarkee.internal") == {"IAM_OWNER"}
    assert by_name.get("ipm-organization-executor") == {"IAM_ORG_MANAGER"}
    assert by_name.get("ipm-organization-observer") == {"IAM_OWNER_VIEWER"}


def operator_authorizations(
    zitadel: Zitadel, orgs: dict[str, str], project_ids: dict[str, str]
) -> dict[str, dict[str, set[str]]]:
    """Autorizações dos projetos de roles na `core`: nome de login → projeto → roles."""
    names = {project_id: name for name, project_id in project_ids.items()}
    found = zitadel.connect(
        AUTHORIZATION_SERVICE,
        "ListAuthorizations",
        {"filters": [{"organizationId": {"id": orgs["core"]}}]},
    ).get("authorizations", [])
    result: dict[str, dict[str, set[str]]] = {}
    for item in found:
        project = names.get(item["project"]["id"])
        if project is not None:
            login = item["user"]["preferredLoginName"]
            result.setdefault(login, {})[project] = {r["key"] for r in item["roles"]}
    return result


def test_only_operators_are_authorized_in_core(
    zitadel: Zitadel, orgs: dict[str, str], project_ids: dict[str, str]
) -> None:
    """Na `core` só há operadores: cada autorização tem a role `*.admin` do projeto (escopo) e,
    além dela, as roles de ação que o operador exerce (decisão 0031). Usuários cadastrados são
    autorizados na `register`, pelo Project Grant, e nunca recebem `*.admin`."""
    operators = operator_authorizations(zitadel, orgs, project_ids)
    assert operators, "falta a autorização do operador (`*.admin`)"
    for login, by_project in operators.items():
        for project, roles in by_project.items():
            assert roles & ADMIN_ROLES_BY_PROJECT[project], f"{login} sem `*.admin` em {project}"
            known = ACTION_ROLES_BY_PROJECT[project] | ADMIN_ROLES_BY_PROJECT[project]
            assert roles <= known, f"{login} tem roles fora de {project}"


def test_default_operator_holds_every_role_of_each_project_with_an_admin_role(
    zitadel: Zitadel, orgs: dict[str, str], project_ids: dict[str, str]
) -> None:
    """O operador padrão tem `*.admin` e as roles de ação de cada projeto que administra: o
    Receiver exige as duas coisas (o que pode fazer e em quais recursos)."""
    operators = operator_authorizations(zitadel, orgs, project_ids)
    default = next((r for n, r in operators.items() if n.startswith("admin@smarkee")), None)
    assert default is not None, "falta a autorização do operador padrão (admin@smarkee)"
    administered = {name for name, admin in ADMIN_ROLES_BY_PROJECT.items() if admin}
    assert set(default) == administered
    for name in administered:
        assert default[name] == ACTION_ROLES_BY_PROJECT[name] | ADMIN_ROLES_BY_PROJECT[name], name


def test_register_has_no_project_of_its_own(zitadel: Zitadel, orgs: dict[str, str]) -> None:
    assert projects_owned_by(zitadel, orgs["register"]) == {}
