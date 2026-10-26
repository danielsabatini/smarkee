"""Regras de acesso do usuário da Organization, sem I/O (decisões 0077 e 0083).

- **Escopo:** o operador age em qualquer Organization; o dono dela (o root, confirmado pelo
  Receiver da Organization) e os usuários dela (confirmados pelo próprio registro no SSOT do tipo)
  agem só nela.
- **Catálogo:** só as permissões do catálogo `grantablePermission` (o Project Grant de toda
  Organization, decisão 0081) podem ser atribuídas.
- **`bind`:** atribuir ou retirar permissões exige explicitamente `ipm.user.bind` (ou ser o dono da
  Organization / operador, decisão 0083). Sem `bind`, o solicitante só pode criar usuário sem
  permissões (`[]`) ou manter inalteradas as permissões atuais.
"""

from collections.abc import Iterable
from enum import StrEnum

from ipm_user.common.catalog import AccessCatalog, default_grantable_permissions


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


def outside_catalog(
    permissions: Iterable[str], *, catalog: AccessCatalog | None = None
) -> list[str]:
    """Permissões pedidas fora do catálogo delegável à Organization, em ordem alfabética."""
    allowed = (
        catalog.grantable_permissions if catalog is not None else default_grantable_permissions()
    )
    return sorted(permission for permission in set(permissions) if permission not in allowed)


def outside_roles_catalog(
    roles: Iterable[str], *, organization_id: str, catalog: AccessCatalog | None = None
) -> list[str]:
    """Roles pedidas inexistentes na Organization ou não delegáveis a ela (0083, 0092)."""
    active_catalog = catalog if catalog is not None else AccessCatalog()
    return sorted(
        role for role in set(roles) if not active_catalog.is_role_grantable(role, organization_id)
    )


def binding_allowed(
    current: Iterable[str],
    requested: Iterable[str],
    requester_permissions: Iterable[str],
    *,
    can_bind: bool,
) -> bool:
    """`True` se quem pede pode levar o usuário de `current` para `requested`.

    Com `bind`, qualquer mudança dentro do catálogo é permitida. Sem `bind`, nenhuma permissão pode
    ser acrescentada ou retirada (`set(current) == set(requested)`).
    """
    _ = requester_permissions
    if can_bind:
        return True
    return set(current) == set(requested)
