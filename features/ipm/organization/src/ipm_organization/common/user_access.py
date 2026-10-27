"""Preparo da Organization para os usuários dela (`userAccess`, decisão 0081). Puro: sem I/O.

A Organization nasce pronta para receber usuários do `ipm/user`, como o namespace do Kubernetes
que já vem com os RoleBindings dos controladores (referência de mercado, decisão 0071):

- **Project Grant** do projeto de permissões do `ipm` para a organização, com exatamente o catálogo
  `grantablePermission` do contrato (`schemas/ipm/definitions`): o teto do que os usuários recebem;
- **permissões de administração** das contas do `ipm/user` nela: o Executor do User com
  `ORG_USER_CREATOR` na organização e `PROJECT_GRANT_OWNER` no Grant; o Observer do User com
  `ORG_OWNER_VIEWER` na organização.

O Manager monta o `userAccess` do `desired` (o catálogo vem do contrato; as contas, da configuração
dele); o Reconciler e o próprio Manager comparam com o `observed` pelas mesmas regras daqui. O
`userAccess` só é reconciliado enquanto a organização tem acesso (`platformAccess = granted`).
"""

from collections.abc import Iterable, Mapping
from typing import Any, cast

from ipm_organization.common.contracts import generated

ORGANIZATION_USER_CREATOR = "ORG_USER_CREATOR"
PROJECT_GRANT_OWNER = "PROJECT_GRANT_OWNER"
ORGANIZATION_OWNER_VIEWER = "ORG_OWNER_VIEWER"


ADMINISTRATOR_KEY_ROLES: tuple[tuple[str, frozenset[str]], ...] = (
    ("userExecutorAccountId", frozenset({ORGANIZATION_USER_CREATOR, PROJECT_GRANT_OWNER})),
    ("userObserverAccountId", frozenset({ORGANIZATION_OWNER_VIEWER})),
    (
        "serviceaccountExecutorAccountId",
        frozenset({ORGANIZATION_USER_CREATOR, PROJECT_GRANT_OWNER}),
    ),
    ("serviceaccountObserverAccountId", frozenset({ORGANIZATION_OWNER_VIEWER})),
    (
        "serviceaccountControllerAccountId",
        frozenset({ORGANIZATION_USER_CREATOR, PROJECT_GRANT_OWNER, ORGANIZATION_OWNER_VIEWER}),
    ),
    (
        "userControllerAccountId",
        frozenset({ORGANIZATION_USER_CREATOR, PROJECT_GRANT_OWNER, ORGANIZATION_OWNER_VIEWER}),
    ),
)


def grant_catalog() -> list[str]:
    """O catálogo inicial `grantablePermission` do contrato, em ordem alfabética."""
    return sorted(permission.value for permission in generated.GrantablePermission)


def desired_user_access(
    *,
    user_executor_account_id: str | None = None,
    user_observer_account_id: str | None = None,
    serviceaccount_executor_account_id: str | None = None,
    serviceaccount_observer_account_id: str | None = None,
    serviceaccount_controller_account_id: str | None = None,
    user_controller_account_id: str | None = None,
    grant_permissions: Iterable[str] | None = None,
    administrator_accounts: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """O `userAccess` que o `desired` deve ter agora: o catálogo e as contas dos tipos.

    Suporta argumentos nomeados conhecidos e/ou registro declarativo de contas
    (Ajuste 3 do plano de evolução).
    """
    permissions = (
        sorted(set(grant_permissions)) if grant_permissions is not None else grant_catalog()
    )
    result: dict[str, Any] = {"grantPermissions": permissions}
    if user_executor_account_id is not None:
        result["userExecutorAccountId"] = user_executor_account_id
    if user_observer_account_id is not None:
        result["userObserverAccountId"] = user_observer_account_id
    if serviceaccount_executor_account_id is not None:
        result["serviceaccountExecutorAccountId"] = serviceaccount_executor_account_id
    if serviceaccount_observer_account_id is not None:
        result["serviceaccountObserverAccountId"] = serviceaccount_observer_account_id
    if serviceaccount_controller_account_id is not None:
        result["serviceaccountControllerAccountId"] = serviceaccount_controller_account_id
    if user_controller_account_id is not None:
        result["userControllerAccountId"] = user_controller_account_id

    if administrator_accounts:
        declared: list[dict[str, Any]] = [
            {"accountId": acc, "permissions": sorted(perms)}
            for acc, perms in administrator_accounts.items()
        ]
        result["administratorAccounts"] = declared

    return result


def required_administrators(
    user_access: Mapping[str, Any],
    extra_declarative_accounts: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, frozenset[str]]:
    """Conta → permissões de administração que ela precisa ter, somando a organização e o Grant.

    Avalia as chaves padrão conhecidas e registros declarativos (Ajuste 3).
    """
    required: dict[str, set[str]] = {}

    for key, perms in ADMINISTRATOR_KEY_ROLES:
        account_id = user_access.get(key)
        if account_id:
            required.setdefault(str(account_id), set()).update(perms)

    # Contas declarativas embutidas no próprio documento
    for item in cast("list[object]", user_access.get("administratorAccounts") or []):
        if isinstance(item, Mapping):
            entry = cast("Mapping[str, Any]", item)
            acc = entry.get("accountId")
            declared = entry.get("permissions")
            if acc and isinstance(declared, list):
                items = cast("list[object]", declared)
                required.setdefault(str(acc), set()).update(str(p) for p in items)

    # Contas declarativas fornecidas externamente (ex.: catálogo ou configuração dinâmica)
    if extra_declarative_accounts:
        for acc, perms in extra_declarative_accounts.items():
            required.setdefault(str(acc), set()).update(str(p) for p in perms)

    return {account: frozenset(permissions) for account, permissions in required.items()}


def is_managed(desired: Mapping[str, Any]) -> bool:
    """`True` quando o `desired` pede o preparo: tem `userAccess` e a organização tem acesso."""
    return desired.get("userAccess") is not None and desired.get("platformAccess") != "revoked"


def converged(desired_user_access: Mapping[str, Any], observed_user_access: object) -> bool:
    """O `observed` tem o Grant com exatamente o catálogo e cada conta com as permissões exigidas.

    Permissões a mais numa conta (ou outras contas) não contam como divergência: o Executor só
    acrescenta o que falta e não retira permissões que a plataforma não gerencia.
    """
    if not isinstance(observed_user_access, Mapping):
        return False
    observed: Mapping[str, Any] = observed_user_access  # pyright: ignore[reportUnknownVariableType]
    grant_permissions = observed.get("grantPermissions")
    if grant_permissions is None or sorted(grant_permissions) != sorted(
        desired_user_access["grantPermissions"]
    ):
        return False
    held = observed_administrators(observed)
    return all(
        permissions <= held.get(account, frozenset())
        for account, permissions in required_administrators(desired_user_access).items()
    )


def observed_administrators(observed_user_access: Mapping[str, Any]) -> dict[str, frozenset[str]]:
    """Conta → permissões lidas do provedor, a partir da lista `administrators` do `observed`."""
    held: dict[str, frozenset[str]] = {}
    for item in cast("list[object]", observed_user_access.get("administrators") or []):
        if not isinstance(item, Mapping):
            continue
        entry = cast("Mapping[str, Any]", item)
        if "accountId" in entry:
            permissions = cast("list[object]", entry.get("permissions") or [])
            held[str(entry["accountId"])] = frozenset(str(permission) for permission in permissions)
    return held
