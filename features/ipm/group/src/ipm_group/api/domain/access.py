"""Regras de acesso de Grupos da Organization, sem I/O (decisões 0085 e 0088).

- **Escopo:** o operador age em qualquer Organization; o dono dela (o root, confirmado pela
  API da Organization) e os usuários dela (confirmados pelo próprio registro no SSOT do tipo)
  agem só nela.
- **Catálogo:** só as roles do catálogo (delegáveis à Organization) podem ser atribuídas.
- **`bind`:** atribuir ou retirar roles exige explicitamente `ipm.group.bind` (ou ser o dono da
  Organization / operador). Sem `bind`, o solicitante só pode criar grupo sem roles (`[]`) ou
  manter inalteradas as roles atuais.
"""

from collections.abc import Iterable
from enum import StrEnum

from ipm_group.common.catalog import RolesCatalog


class OrganizationAccess(StrEnum):
    """Resposta da API da Organization para o solicitante."""

    OWNED = "owned"
    """A Organization existe, não está sendo removida e o solicitante é o dono (ou operador)."""

    NOT_OWNED = "not_owned"
    """Não existe, está sendo removida ou é de outro dono."""


class AccessCheckError(Exception):
    """O dono da Organization não pôde ser confirmado. Na dúvida, o pedido não segue."""

    def __init__(self, *, retryable: bool) -> None:
        super().__init__("organization access could not be verified")
        self.retryable = retryable


def outside_roles_catalog(
    roles: Iterable[str], *, organization_id: str, catalog: RolesCatalog | None = None
) -> list[str]:
    """Roles pedidas que não existem para a Organization (predefinidas ou `custom` dela)."""
    active_catalog = catalog if catalog is not None else RolesCatalog()
    return active_catalog.outside_catalog(roles, organization_id)


def binding_allowed(
    current: Iterable[str],
    requested: Iterable[str],
    requester_permissions: Iterable[str],
    *,
    can_bind: bool,
) -> bool:
    """`True` se quem pede pode levar o grupo de `current` para `requested`."""
    _ = requester_permissions
    if can_bind:
        return True
    return set(current) == set(requested)
