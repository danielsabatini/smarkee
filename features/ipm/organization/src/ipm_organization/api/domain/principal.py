"""Solicitante autenticado e as permissões do projeto da plataforma (decisão 0010)."""

from dataclasses import dataclass

ORGANIZATION_CREATE = "ipm.organization.create"
ORGANIZATION_GET = "ipm.organization.get"
ORGANIZATION_LIST = "ipm.organization.list"
ORGANIZATION_UPDATE = "ipm.organization.update"
ORGANIZATION_DELETE = "ipm.organization.delete"
ORGANIZATION_OPERATE = "ipm.organization.operate"
ORGANIZATION_ADMIN = "ipm.organization.admin"  # retrocompatibilidade transitória


@dataclass(frozen=True, slots=True)
class Principal:
    """O usuário autenticado: o `sub` do token (ID do usuário) e as permissões no projeto."""

    subject: str
    permissions: frozenset[str]
    access_token: str

    @property
    def is_operator(self) -> bool:
        """Operadores agem em qualquer Organization e não têm cota (decisão 0010)."""
        return ORGANIZATION_OPERATE in self.permissions or ORGANIZATION_ADMIN in self.permissions

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions
