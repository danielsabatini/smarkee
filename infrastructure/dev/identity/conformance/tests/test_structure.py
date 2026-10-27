"""Estrutura do Zitadel de dev esperada pelas decisões 0010, 0014, 0026, 0027, 0028, 0031 e 0032.

Usa só a API v2 do Zitadel (decisão 0029).

Somente leitura: usa a chave da conta `platform-bootstrap` (`CONFORMANCE_IDENTITY_KEY_FILE`) e não
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

ISSUER = os.environ.get("CONFORMANCE_IDENTITY_ISSUER", "http://ipm-dev.smarkee.com.br:8080")
BASE_URL = os.environ.get("CONFORMANCE_IDENTITY_URL", "http://localhost:8080")
HOST = os.environ.get("CONFORMANCE_IDENTITY_HOST", "ipm-dev.smarkee.com.br:8080")
KEY_FILE = os.environ.get("CONFORMANCE_IDENTITY_KEY_FILE")

# Um projeto de roles por módulo, na organização `core` (decisão 0032): as roles de ação (delegadas
# à `register` por Project Grant) e a role de operador `*.admin`, que fica fora do Grant.
ACTION_ROLES_BY_PROJECT = {
    "roles-bsm": {
        "bsm.account.create",
        "bsm.account.delete",
        "bsm.account.get",
        "bsm.account.list",
        "bsm.account.update",
    },
    "roles-core": {"core.account.delete", "core.account.get"},
    "roles-ipm": {
        "ipm.organization.create",
        "ipm.organization.delete",
        "ipm.organization.get",
        "ipm.organization.list",
        "ipm.organization.update",
        # Catálogos de permissões e roles (decisão 0083).
        "ipm.permission.get",
        "ipm.permission.list",
        # Roles `custom` da Organization (decisão 0092): `get`/`list` passam a ser delegáveis.
        "ipm.role.bind",
        "ipm.role.create",
        "ipm.role.delete",
        "ipm.role.get",
        "ipm.role.list",
        "ipm.role.update",
        # Grupos de usuários da Organization (decisão 0088).
        "ipm.group.bind",
        "ipm.group.create",
        "ipm.group.delete",
        "ipm.group.get",
        "ipm.group.list",
        "ipm.group.update",
        # Service accounts da Organization (decisão 0094).
        "ipm.serviceaccount.bind",
        "ipm.serviceaccount.create",
        "ipm.serviceaccount.delete",
        "ipm.serviceaccount.get",
        "ipm.serviceaccount.list",
        "ipm.serviceaccount.update",
        # Usuários da Organization (decisão 0077): o root as recebe pelo Grant da `register`.
        "ipm.user.bind",
        "ipm.user.create",
        "ipm.user.delete",
        "ipm.user.get",
        "ipm.user.list",
        "ipm.user.update",
    },
    "roles-sum": {
        "sum.ipm.disable",
        "sum.ipm.enable",
        "sum.ipm.get",
    },
}
ADMIN_ROLES_BY_PROJECT = {
    "roles-bsm": {"bsm.account.admin"},
    "roles-core": {"core.account.admin"},
    "roles-ipm": {
        "ipm.organization.admin",
        "ipm.permission.admin",
        "ipm.role.admin",
        "ipm.group.admin",
        "ipm.serviceaccount.admin",
        "ipm.user.admin",
    },
    "roles-sum": set[str](),
}
ACTION_ROLES = set[str]().union(*ACTION_ROLES_BY_PROJECT.values())
ADMIN_ROLES = set[str]().union(*ADMIN_ROLES_BY_PROJECT.values())
# Projetos cujo Project Grant o Executor do User administra (`PROJECT_GRANT_OWNER`, 0032 e 0082).
USER_EXECUTOR_GRANT_PROJECTS = {"roles-bsm", "roles-core", "roles-sum"}
ORGANIZATION_SERVICE = "zitadel.org.v2.OrganizationService"
PROJECT_SERVICE = "zitadel.project.v2.ProjectService"
APPLICATION_SERVICE = "zitadel.application.v2.ApplicationService"
AUTHORIZATION_SERVICE = "zitadel.authorization.v2.AuthorizationService"
PERMISSION_SERVICE = "zitadel.internal_permission.v2.InternalPermissionService"
USER_SERVICE = "zitadel.user.v2.UserService"
# Alerta antes do vencimento, para a rotação manual ter folga (`infrastructure/dev/README.md`).
KEY_EXPIRATION_WARNING = timedelta(days=90)
SERVICE_ACCOUNTS = {
    "core-account-executor",
    "core-account-observer",
    "ipm-organization-controller",
    "ipm-organization-executor",
    "ipm-organization-observer",
    "ipm-permission-executor",
    "ipm-permission-observer",
    "ipm-serviceaccount-controller",
    "ipm-serviceaccount-executor",
    "ipm-serviceaccount-observer",
    "ipm-user-executor",
    "ipm-user-observer",
    "sum-service-executor",
    "sum-service-observer",
}
# Projetos que o Executor do SUM administra (decisão 0033): `ipm`.
SUM_EXECUTOR_GRANT_PROJECTS = {"roles-ipm"}

pytestmark = pytest.mark.skipif(
    not KEY_FILE, reason="CONFORMANCE_IDENTITY_KEY_FILE não definida (chave do platform-bootstrap)"
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


@pytest.fixture(scope="module")
def operator_project_id(zitadel: Zitadel, orgs: dict[str, str]) -> str:
    """ID do projeto `roles-operator`, dono das roles `*.admin` na organização `operator`."""
    owned = projects_owned_by(zitadel, orgs["operator"])
    assert "roles-operator" in owned, "falta o projeto `roles-operator` na organização `operator`"
    return str(owned["roles-operator"]["projectId"])


def administrators(zitadel: Zitadel, resource: dict[str, Any]) -> dict[str, set[str]]:
    """Papéis de administração do recurso (administradores; o Zitadel os chamava de *members*)."""
    found = zitadel.connect(
        PERMISSION_SERVICE, "ListAdministrators", {"filters": [{"resource": resource}]}
    ).get("administrators", [])
    return {a["user"]["preferredLoginName"]: set(a["roles"]) for a in found}


def organization_administrators(zitadel: Zitadel, org_id: str) -> dict[str, set[str]]:
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


def test_the_four_organizations_exist(orgs: dict[str, str]) -> None:
    assert {"smarkee", "core", "operator", "register"} <= set(orgs)


def test_public_registration_is_off(zitadel: Zitadel) -> None:
    policy = zitadel.get("/v2/settings/login")["settings"]
    assert not policy.get("allowRegister"), "o cadastro público do Zitadel deve estar desligado"


def test_one_roles_project_per_module_and_operator_asserts_and_checks_roles(
    zitadel: Zitadel, orgs: dict[str, str]
) -> None:
    projects = projects_owned_by(zitadel, orgs["core"])
    roles_projects = {name: p for name, p in projects.items() if name.startswith("roles-")}
    assert set(roles_projects) == set(ACTION_ROLES_BY_PROJECT), (
        "um projeto de roles por módulo na core (0032)"
    )
    for name, project in roles_projects.items():
        assert project.get("projectRoleAssertion") is True, name
        assert project.get("authorizationRequired") is True, name  # `projectRoleCheck` da v1

    operator_projects = projects_owned_by(zitadel, orgs["operator"])
    assert "roles-operator" in operator_projects, "falta `roles-operator` na organização `operator`"
    operator_project = operator_projects["roles-operator"]
    assert operator_project.get("projectRoleAssertion") is True, "roles-operator"
    assert operator_project.get("authorizationRequired") is True, "roles-operator"


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
    zitadel: Zitadel, project_ids: dict[str, str], operator_project_id: str
) -> None:
    for name, project_id in project_ids.items():
        roles = zitadel.connect(PROJECT_SERVICE, "ListProjectRoles", {"projectId": project_id})[
            "projectRoles"
        ]
        assert {r["key"] for r in roles} == ACTION_ROLES_BY_PROJECT[name]
        module = name.removeprefix("roles-")
        assert all(r["key"].split(".")[0] == module for r in roles), (
            "role fora do módulo do projeto"
        )
        assert all(r.get("group") == module for r in roles)
        # O nome de exibição descreve a ação em pt-BR (por exemplo, `ipm.user.get` → "Ler usuários
        # da Organization"): nunca vazio nem a própria key, que o console já mostra ao lado.
        repeated = sorted(r["key"] for r in roles if r.get("displayName", r["key"]) == r["key"])
        assert not repeated, f"roles sem nome de exibição próprio: {repeated}"

    op_roles = zitadel.connect(
        PROJECT_SERVICE, "ListProjectRoles", {"projectId": operator_project_id}
    )["projectRoles"]
    assert {r["key"] for r in op_roles} == ADMIN_ROLES
    assert all(r["key"].endswith(".admin") for r in op_roles)
    assert all(r.get("group") == r["key"].split(".")[0] for r in op_roles)
    repeated_op = sorted(r["key"] for r in op_roles if r.get("displayName", r["key"]) == r["key"])
    assert not repeated_op, f"roles-operator sem nome de exibição próprio: {repeated_op}"


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
    zitadel: Zitadel, project_ids: dict[str, str], operator_project_id: str
) -> None:
    """As aplicações moram num projeto sem roles (0034): um projeto de roles não tem nenhuma."""
    all_projects = {**project_ids, "roles-operator": operator_project_id}
    for name, project_id in all_projects.items():
        found = zitadel.connect(
            APPLICATION_SERVICE,
            "ListApplications",
            {"filters": [{"projectIdFilter": {"projectId": project_id}}]},
        ).get("applications", [])
        assert found == [], f"{name} não deve ter aplicações: {[a['name'] for a in found]}"


def test_each_project_grant_to_register_and_operator_delegates_only_its_action_roles(
    zitadel: Zitadel, orgs: dict[str, str], project_ids: dict[str, str], operator_project_id: str
) -> None:
    grants = zitadel.connect(PROJECT_SERVICE, "ListProjectGrants")["projectGrants"]
    to_register = {
        g["projectId"]: set(g["grantedRoleKeys"])
        for g in grants
        if g["grantedOrganizationId"] == orgs["register"]
    }
    to_operator = {
        g["projectId"]: set(g["grantedRoleKeys"])
        for g in grants
        if g["grantedOrganizationId"] == orgs["operator"]
    }
    for name, project_id in project_ids.items():
        assert to_register.get(project_id) == ACTION_ROLES_BY_PROJECT[name], (
            f"o Grant de {name} para a register deve ter só as roles de ação (sem `*.admin`)"
        )
        assert to_operator.get(project_id) == ACTION_ROLES_BY_PROJECT[name], (
            f"o Grant de {name} para a operator deve ter só as roles de ação"
        )
    assert not [g for g in grants if g["projectId"] == operator_project_id], (
        "roles-operator não pode ser delegado a nenhuma outra organização"
    )


def test_service_accounts_live_in_core(zitadel: Zitadel, orgs: dict[str, str]) -> None:
    assert user_names(zitadel, orgs["core"]) >= SERVICE_ACCOUNTS
    assert not {
        n
        for n in user_names(zitadel, orgs["register"])
        if n.startswith(
            ("core-", "sum-service-", "ipm-organization-", "ipm-serviceaccount-", "ipm-user-"),
        )
    }


def test_component_service_accounts_use_opaque_bearer_tokens(
    zitadel: Zitadel, orgs: dict[str, str]
) -> None:
    """Token opaco (Bearer) nas contas de serviço dos componentes (decisão 0054): com JWT, o Zitadel
    registra um WARN a cada chamada autenticada. A API v2 omite o valor padrão, então a ausência de
    `machine.accessTokenType` significa Bearer."""
    found: list[dict[str, Any]] = zitadel.search(
        "/v2/users", {"queries": [{"organizationIdQuery": {"organizationId": orgs["core"]}}]}
    )
    machines: dict[str, dict[str, Any]] = {
        str(u["username"]): u.get("machine") or {}
        for u in found
        if u["username"] in SERVICE_ACCOUNTS
    }
    token_types = {
        name: str(machine.get("accessTokenType", "ACCESS_TOKEN_TYPE_BEARER"))
        for name, machine in machines.items()
    }
    assert set(token_types) == SERVICE_ACCOUNTS
    assert {n: t for n, t in token_types.items() if t != "ACCESS_TOKEN_TYPE_BEARER"} == {}


def test_executor_and_observer_have_roles_only_in_register(
    zitadel: Zitadel, orgs: dict[str, str]
) -> None:
    in_register = organization_administrators(zitadel, orgs["register"])
    # `ORG_USER_CREATOR` cria e remove usuários, mas não concede roles (decisão 0032).
    assert in_register.get("core-account-executor") == {"ORG_USER_CREATOR"}
    assert in_register.get("core-account-observer") == {"ORG_OWNER_VIEWER"}
    # O Observer do SUM só lê a register; o Executor do SUM não tem papel nela (só o Grant, abaixo).
    assert in_register.get("sum-service-observer") == {"ORG_OWNER_VIEWER"}
    assert "sum-service-executor" not in in_register
    # As contas da Organization têm só papel de instância (abaixo), nenhum na `register`; as do
    # User e da ServiceAccount só têm papéis nas organizações de cliente, dados pelo loop da
    # Organization (0081 e 0094).
    assert not {
        n
        for n in in_register
        if n.startswith(("ipm-organization-", "ipm-serviceaccount-", "ipm-user-"))
    }
    in_core = organization_administrators(zitadel, orgs["core"])
    assert not {
        name
        for name in in_core
        if name.startswith(
            (
                "core-account-",
                "sum-service-",
                "ipm-organization-",
                "ipm-serviceaccount-",
                "ipm-user-",
            )
        )
    }, "o Executor e o Observer não têm papel na organização core (decisão 0027)"


def test_permission_observer_reads_the_operator_organization(
    zitadel: Zitadel, orgs: dict[str, str]
) -> None:
    """O Observer de `ipm/permission` precisa de `ORG_OWNER_VIEWER` na `operator`: o Zitadel só
    devolve as roles de `roles-operator` a quem lê a organização dona do projeto. Só com
    `PROJECT_OWNER_VIEWER` a lista vem vazia e toda `*.admin` é observada como ausente (0084)."""
    in_operator = organization_administrators(zitadel, orgs["operator"])
    assert in_operator.get("ipm-permission-observer") == {"ORG_OWNER_VIEWER"}
    assert "ipm-permission-executor" not in in_operator


def test_user_executor_grants_roles_only_in_its_modules(
    zitadel: Zitadel, orgs: dict[str, str], project_ids: dict[str, str]
) -> None:
    """O isolamento do SUM: o Executor do User é `PROJECT_GRANT_OWNER` só nos Grants dos módulos
    de nível de conta (`core`, `bsm` e `sum`); no do `ipm` ele não é, e o Zitadel nega a concessão
    (decisões 0032 e 0082)."""
    for name, project_id in project_ids.items():
        owners = administrators(
            zitadel,
            {"projectGrant": {"projectId": project_id, "organizationId": orgs["register"]}},
        )
        has_role = owners.get("core-account-executor") == {"PROJECT_GRANT_OWNER"}
        assert has_role == (name in USER_EXECUTOR_GRANT_PROJECTS), name


def test_sum_executor_is_project_grant_owner_only_in_its_grants(
    zitadel: Zitadel, orgs: dict[str, str], project_ids: dict[str, str]
) -> None:
    """O Executor do SUM só concede as roles dos módulos ligáveis (`ipm`, decisão 0032): é
    `PROJECT_GRANT_OWNER` só no Grant de `roles-ipm` para a `register`."""
    for name, project_id in project_ids.items():
        owners = administrators(
            zitadel,
            {"projectGrant": {"projectId": project_id, "organizationId": orgs["register"]}},
        )
        has_role = owners.get("sum-service-executor") == {"PROJECT_GRANT_OWNER"}
        assert has_role == (name in SUM_EXECUTOR_GRANT_PROJECTS), name


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


def test_instance_administrators(zitadel: Zitadel) -> None:
    by_name = administrators(zitadel, {"instance": True})
    assert by_name.get("platform-bootstrap@smarkee.internal") == {"IAM_OWNER"}
    assert by_name.get("ipm-organization-controller") == {"IAM_ORG_MANAGER"}
    assert by_name.get("ipm-organization-executor") == {"IAM_ORG_MANAGER"}
    assert by_name.get("ipm-organization-observer") == {"IAM_OWNER_VIEWER"}
    # As contas do User e da ServiceAccount não têm papel de instância: só os da organização de
    # cliente (decisões 0077 e 0094).
    assert not {name for name in by_name if name.startswith(("ipm-user-", "ipm-serviceaccount-"))}


def operator_authorizations(
    zitadel: Zitadel, orgs: dict[str, str], project_ids: dict[str, str], operator_project_id: str
) -> dict[str, dict[str, set[str]]]:
    """Autorizações dos projetos de roles na `operator`: nome de login → projeto → roles."""
    names = {project_id: name for name, project_id in project_ids.items()}
    names[operator_project_id] = "roles-operator"
    found = zitadel.connect(
        AUTHORIZATION_SERVICE,
        "ListAuthorizations",
        {"filters": [{"organizationId": {"id": orgs["operator"]}}]},
    ).get("authorizations", [])
    result: dict[str, dict[str, set[str]]] = {}
    for item in found:
        project = names.get(item["project"]["id"])
        if project is not None:
            login = item["user"]["preferredLoginName"]
            result.setdefault(login, {})[project] = {r["key"] for r in item["roles"]}
    return result


def test_only_operators_are_authorized_in_operator_and_none_in_core(
    zitadel: Zitadel, orgs: dict[str, str], project_ids: dict[str, str], operator_project_id: str
) -> None:
    """Na `core` não há autorizações de usuários; os operadores ficam na organização `operator`,
    com `*.admin` em `roles-operator` e as roles de ação nos Grants de `roles-<módulo>`."""
    in_core = zitadel.connect(
        AUTHORIZATION_SERVICE,
        "ListAuthorizations",
        {"filters": [{"organizationId": {"id": orgs["core"]}}]},
    ).get("authorizations", [])
    assert in_core == [], f"não deve haver autorizações na core: {in_core}"

    operators = operator_authorizations(zitadel, orgs, project_ids, operator_project_id)
    assert operators, "falta a autorização do operador (`*.admin`) na organização `operator`"
    for login, by_project in operators.items():
        admin_roles = by_project.get("roles-operator", set())
        assert admin_roles and admin_roles <= ADMIN_ROLES, (
            f"{login} sem `*.admin` válido em roles-operator"
        )
        for project, roles in by_project.items():
            if project == "roles-operator":
                continue
            assert roles <= ACTION_ROLES_BY_PROJECT[project], f"{login} tem roles fora de {project}"


def test_default_operator_holds_every_role_of_each_project_with_an_admin_role(
    zitadel: Zitadel, orgs: dict[str, str], project_ids: dict[str, str], operator_project_id: str
) -> None:
    """O operador padrão (`admin@operator...`) tem todas as `*.admin` em `roles-operator` e as
    roles de ação de cada projeto que administra."""
    operators = operator_authorizations(zitadel, orgs, project_ids, operator_project_id)
    default = next(
        (r for n, r in operators.items() if n == "admin" or n.startswith("admin@operator")), None
    )
    assert default is not None, "falta a autorização do operador padrão (admin na org operator)"
    administered = {name for name, admin in ADMIN_ROLES_BY_PROJECT.items() if admin}
    assert set(default) == administered | {"roles-operator"}
    assert default["roles-operator"] == ADMIN_ROLES
    for name in administered:
        assert default[name] == ACTION_ROLES_BY_PROJECT[name], name


def test_register_has_no_project_of_its_own(zitadel: Zitadel, orgs: dict[str, str]) -> None:
    assert projects_owned_by(zitadel, orgs["register"]) == {}


# ---- desvio de configuração (decisão 0037) ----

REPOSITORY = Path(__file__).resolve().parents[5]
ENV_FILES = {
    "cli": REPOSITORY / "clients" / "cli" / ".env",
    "bsm.account": REPOSITORY / "features" / "bsm" / "account" / ".env",
    "core.account": REPOSITORY / "features" / "core" / "account" / ".env",
    "sum.service": REPOSITORY / "features" / "sum" / "service" / ".env",
    "ipm.organization": REPOSITORY / "features" / "ipm" / "organization" / ".env",
    "ipm.permission": REPOSITORY / "features" / "ipm" / "permission" / ".env",
    "ipm.role": REPOSITORY / "features" / "ipm" / "role" / ".env",
    "ipm.group": REPOSITORY / "features" / "ipm" / "group" / ".env",
    "ipm.user": REPOSITORY / "features" / "ipm" / "user" / ".env",
    "ipm.serviceaccount": REPOSITORY / "features" / "ipm" / "serviceaccount" / ".env",
}
# Variável de cada `.env` → o que ela deve apontar na instância.
EXPECTED_AUDIENCE = {
    "bsm.account": ("BSM_ACCOUNT_RECEIVER_AUTH_AUDIENCE", "roles-bsm"),
    "core.account": ("CORE_ACCOUNT_RECEIVER_AUTH_AUDIENCE", "roles-core"),
    "sum.service": ("SUM_SERVICE_RECEIVER_AUTH_AUDIENCE", "roles-sum"),
    "ipm.organization": ("IPM_ORGANIZATION_RECEIVER_AUTH_AUDIENCE", "roles-ipm"),
    "ipm.permission": ("IPM_PERMISSION_RECEIVER_AUTH_AUDIENCE", "roles-ipm"),
    "ipm.role": ("IPM_ROLE_RECEIVER_AUTH_AUDIENCE", "roles-ipm"),
    "ipm.group": ("IPM_GROUP_RECEIVER_AUTH_AUDIENCE", "roles-ipm"),
    "ipm.user": ("IPM_USER_RECEIVER_AUTH_AUDIENCE", "roles-ipm"),
    "ipm.serviceaccount": ("IPM_SERVICEACCOUNT_RECEIVER_AUTH_AUDIENCE", "roles-ipm"),
}
# Um projeto de roles só, o do próprio módulo (o Executor e o Observer do User, decisão 0077).
EXPECTED_PROJECT_ID = {
    "ipm.user": ("IPM_USER_IDENTITY_PROJECT_ID", "roles-ipm"),
    "ipm.serviceaccount": ("IPM_SERVICEACCOUNT_IDENTITY_PROJECT_ID", "roles-ipm"),
    "ipm.organization": ("IPM_ORGANIZATION_IDENTITY_PROJECT_ID", "roles-ipm"),
}
# Contas do `ipm/user` e do `ipm/serviceaccount` que o Manager da Organization prepara em cada
# Organization (decisões 0081 e 0094).
EXPECTED_ACCOUNT_IDS = {
    "ipm.organization": {
        "IPM_ORGANIZATION_USER_EXECUTOR_ACCOUNT_ID": "ipm-user-executor",
        "IPM_ORGANIZATION_USER_OBSERVER_ACCOUNT_ID": "ipm-user-observer",
        "IPM_ORGANIZATION_SERVICEACCOUNT_EXECUTOR_ACCOUNT_ID": "ipm-serviceaccount-executor",
        "IPM_ORGANIZATION_SERVICEACCOUNT_OBSERVER_ACCOUNT_ID": "ipm-serviceaccount-observer",
        "IPM_ORGANIZATION_SERVICEACCOUNT_CONTROLLER_ACCOUNT_ID": "ipm-serviceaccount-controller",
    }
}
EXPECTED_REGISTER = {
    "core.account": "CORE_ACCOUNT_IDENTITY_REGISTER_ORGANIZATION_ID",
    "sum.service": "SUM_SERVICE_IDENTITY_REGISTER_ORGANIZATION_ID",
}
EXPECTED_PROJECT_IDS = {
    "core.account": "CORE_ACCOUNT_IDENTITY_PROJECT_IDS",
    "ipm.permission": "IPM_PERMISSION_IDENTITY_PROJECT_IDS",
    "sum.service": "SUM_SERVICE_IDENTITY_PROJECT_IDS",
}
CLI_PROJECTS = {
    "SK_BSM_PROJECT_ID": "roles-bsm",
    "SK_CORE_PROJECT_ID": "roles-core",
    "SK_SUM_PROJECT_ID": "roles-sum",
    "SK_IPM_PROJECT_ID": "roles-ipm",
    "SK_OPERATOR_PROJECT_ID": "roles-operator",
}


def read_env(name: str) -> dict[str, str]:
    """Variáveis de um `.env` (aceita `export`). Sem o arquivo, o teste que o usa é pulado."""
    path = ENV_FILES[name]
    if not path.exists():
        pytest.skip(f"{path.relative_to(REPOSITORY)} não existe")
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip().removeprefix("export ")
        if text and not text.startswith("#") and "=" in text:
            key, _, value = text.partition("=")
            found[key.strip()] = value.strip().strip("\"'")
    return found


def assert_same(
    drifts: list[str], where: str, variable: str, found: str | None, expected: str
) -> None:
    """Acumula o desvio (sem repetir os valores além dos IDs, que são públicos)."""
    if found != expected:
        drifts.append(f"{where}: {variable} = {found!r}, e a instância tem {expected!r}")


def test_the_ids_in_the_env_files_match_the_instance(
    zitadel: Zitadel, orgs: dict[str, str], project_ids: dict[str, str], operator_project_id: str
) -> None:
    """Ao recriar a instância os IDs mudam; este teste aponta o `.env` que ficou desatualizado."""
    drifts: list[str] = []
    all_projects = {**project_ids, "roles-operator": operator_project_id}

    clients = projects_owned_by(zitadel, orgs["core"])["clients"]
    applications = zitadel.connect(
        APPLICATION_SERVICE,
        "ListApplications",
        {"filters": [{"projectIdFilter": {"projectId": clients["projectId"]}}]},
    )["applications"]
    client_id = {a["name"]: a for a in applications}["cli"]["oidcConfiguration"]["clientId"]
    if ENV_FILES["cli"].exists():
        cli = read_env("cli")
        assert_same(
            drifts, "clients/cli/.env", "SK_AUTH_CLIENT_ID", cli.get("SK_AUTH_CLIENT_ID"), client_id
        )
        for variable, project in CLI_PROJECTS.items():
            assert_same(
                drifts, "clients/cli/.env", variable, cli.get(variable), all_projects[project]
            )

    accounts = {
        str(u["username"]): str(u["userId"])
        for u in zitadel.search(
            "/v2/users", {"queries": [{"organizationIdQuery": {"organizationId": orgs["core"]}}]}
        )
    }
    for feature in (
        "bsm.account",
        "core.account",
        "sum.service",
        "ipm.organization",
        "ipm.permission",
        "ipm.role",
        "ipm.group",
        "ipm.user",
        "ipm.serviceaccount",
    ):
        if not ENV_FILES[feature].exists():
            continue
        values = read_env(feature)
        where = ENV_FILES[feature].relative_to(REPOSITORY).as_posix()
        variable, project = EXPECTED_AUDIENCE[feature]
        assert_same(drifts, where, variable, values.get(variable), all_projects[project])
        if feature in EXPECTED_REGISTER:
            variable = EXPECTED_REGISTER[feature]
            assert_same(drifts, where, variable, values.get(variable), orgs["register"])
        if feature in EXPECTED_PROJECT_ID:
            variable, project = EXPECTED_PROJECT_ID[feature]
            assert_same(drifts, where, variable, values.get(variable), all_projects[project])
        for variable, account in EXPECTED_ACCOUNT_IDS.get(feature, {}).items():
            assert_same(
                drifts, where, variable, values.get(variable), accounts.get(account, "(ausente)")
            )
        if feature in EXPECTED_PROJECT_IDS:
            variable = EXPECTED_PROJECT_IDS[feature]
            configured: dict[str, str] = json.loads(values.get(variable, "{}"))
            for module, project_id in configured.items():
                assert_same(
                    drifts,
                    where,
                    f"{variable}[{module}]",
                    project_id,
                    all_projects[f"roles-{module}"],
                )

    assert not drifts, "configuração desatualizada:\n" + "\n".join(drifts)
