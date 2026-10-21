"""Preparo da Organization para os usuários dela (`userAccess`, decisão 0081). Puro: sem I/O.

A Organization nasce pronta para receber usuários do `ipm/user`, como o namespace do Kubernetes
que já vem com os RoleBindings dos controladores (referência de mercado, decisão 0071):

- **Project Grant** do projeto de roles do `ipm` para a organização, com exatamente o catálogo
  `grantableRole` do contrato (`schemas/ipm/definitions`): o teto do que os usuários recebem;
- **papéis de administração** das contas do `ipm/user` nela: o Executor do User com
  `ORG_USER_CREATOR` na organização e `PROJECT_GRANT_OWNER` no Grant; o Observer do User com
  `ORG_OWNER_VIEWER` na organização.

O Manager monta o `userAccess` do `desired` (o catálogo vem do contrato; as contas, da configuração
dele); o Reconciler e o próprio Manager comparam com o `observed` pelas mesmas regras daqui. O
`userAccess` só é reconciliado enquanto a organização tem acesso (`platformAccess = granted`).
"""

from collections.abc import Mapping
from typing import Any, cast

from ipm_organization.common.contracts import generated

ORGANIZATION_USER_CREATOR = "ORG_USER_CREATOR"
PROJECT_GRANT_OWNER = "PROJECT_GRANT_OWNER"
ORGANIZATION_OWNER_VIEWER = "ORG_OWNER_VIEWER"


def grant_catalog() -> list[str]:
    """O catálogo `grantableRole` do contrato, em ordem alfabética."""
    return sorted(role.value for role in generated.GrantableRole)


def desired_user_access(
    *, user_executor_account_id: str, user_observer_account_id: str
) -> dict[str, Any]:
    """O `userAccess` que o `desired` deve ter agora: o catálogo e as contas do `ipm/user`."""
    return {
        "grantRoles": grant_catalog(),
        "userExecutorAccountId": user_executor_account_id,
        "userObserverAccountId": user_observer_account_id,
    }


def required_administrators(user_access: Mapping[str, Any]) -> dict[str, frozenset[str]]:
    """Conta → papéis que ela precisa ter, somando a organização e o Grant."""
    executor = str(user_access["userExecutorAccountId"])
    observer = str(user_access["userObserverAccountId"])
    required: dict[str, set[str]] = {
        executor: {ORGANIZATION_USER_CREATOR, PROJECT_GRANT_OWNER},
    }
    required.setdefault(observer, set()).add(ORGANIZATION_OWNER_VIEWER)
    return {account: frozenset(roles) for account, roles in required.items()}


def is_managed(desired: Mapping[str, Any]) -> bool:
    """`True` quando o `desired` pede o preparo: tem `userAccess` e a organização tem acesso."""
    return desired.get("userAccess") is not None and desired.get("platformAccess") != "revoked"


def converged(desired_user_access: Mapping[str, Any], observed_user_access: object) -> bool:
    """O `observed` tem o Grant com exatamente o catálogo e cada conta com os papéis exigidos.

    Papéis a mais numa conta (ou outras contas) não contam como divergência: o Executor só
    acrescenta o que falta e não retira papéis que a plataforma não gerencia.
    """
    if not isinstance(observed_user_access, Mapping):
        return False
    observed: Mapping[str, Any] = observed_user_access  # pyright: ignore[reportUnknownVariableType]
    grant_roles = observed.get("grantRoles")
    if grant_roles is None or sorted(grant_roles) != sorted(desired_user_access["grantRoles"]):
        return False
    held = observed_administrators(observed)
    return all(
        roles <= held.get(account, frozenset())
        for account, roles in required_administrators(desired_user_access).items()
    )


def observed_administrators(observed_user_access: Mapping[str, Any]) -> dict[str, frozenset[str]]:
    """Conta → papéis lidos do provedor, a partir da lista `administrators` do `observed`."""
    held: dict[str, frozenset[str]] = {}
    for item in cast("list[object]", observed_user_access.get("administrators") or []):
        if not isinstance(item, Mapping):
            continue
        entry = cast("Mapping[str, Any]", item)
        if "accountId" in entry:
            roles = cast("list[object]", entry.get("roles") or [])
            held[str(entry["accountId"])] = frozenset(str(role) for role in roles)
    return held
