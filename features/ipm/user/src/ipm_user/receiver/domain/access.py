"""Regras de acesso do usuário da Organization, sem I/O (decisão 0077).

- **Escopo:** o operador age em qualquer Organization; o dono dela (o root, confirmado pelo
  Receiver da Organization) e os usuários dela (confirmados pelo próprio registro no SSOT do tipo)
  agem só nela.
- **Catálogo:** só as permissões do catálogo `grantablePermission` (o Project Grant de toda
  Organization, decisão 0081) podem ser atribuídas.
- **`bind`:** sem `ipm.user.bind`, quem pede só atribui ou retira permissões que ele mesmo tem,
  como o RBAC do Kubernetes (referência de mercado, decisão 0071).
"""

from collections.abc import Iterable
from enum import StrEnum

from ipm_user.common.contracts import generated


class OrganizationAccess(StrEnum):
    """Resposta do Receiver da Organization para o solicitante."""

    OWNED = "owned"
    """A Organization existe, não está sendo removida e o solicitante é o dono (ou operador)."""

    NOT_OWNED = "not_owned"
    """Não existe, está sendo removida ou é de outro dono."""


class AccessCheckError(Exception):
    """O dono da Organization não pôde ser confirmado. Na dúvida, o pedido não segue."""

    def __init__(self, *, retryable: bool) -> None:
        super().__init__("organization access could not be verified")
        self.retryable = retryable


def outside_catalog(permissions: Iterable[str]) -> list[str]:
    """Permissões pedidas fora do catálogo `grantablePermission`, em ordem alfabética.

    O catálogo é contrato (`schemas/ipm/user/definitions`, decisão 0081), e não configuração: é o
    mesmo que o Manager da Organization grava no Project Grant de cada Organization.
    """
    allowed = {permission.value for permission in generated.GrantablePermission}
    return sorted(permission for permission in set(permissions) if permission not in allowed)


def binding_allowed(
    current: Iterable[str],
    requested: Iterable[str],
    requester_permissions: Iterable[str],
    *,
    can_bind: bool,
) -> bool:
    """`True` se quem pede pode levar o usuário de `current` para `requested`.

    Com `bind`, qualquer mudança dentro do catálogo. Sem ele, cada permissão acrescentada ou
    retirada precisa estar entre as permissões de quem pede (nunca concede mais do que tem).
    """
    if can_bind:
        return True
    changed = set(current) ^ set(requested)
    return changed <= set(requester_permissions)
