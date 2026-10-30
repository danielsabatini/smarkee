"""Solicitante autenticado e as permissões do projeto da plataforma (`roles-ipm`, decisão 0083)."""

from dataclasses import dataclass

PERMISSION_GET = "ipm.permission.get"
PERMISSION_LIST = "ipm.permission.list"
PERMISSION_OPERATE = "ipm.permission.operate"
PERMISSION_ADMIN = "ipm.permission.admin"  # retrocompatibilidade transitória


@dataclass(frozen=True, slots=True)
class Principal:
    """O usuário autenticado: o `sub` do token (ID do usuário) e as permissões no projeto."""

    subject: str
    permissions: frozenset[str]
    access_token: str

    @property
    def is_operator(self) -> bool:
        """Operadores (`ipm.permission.operate`) gerenciam e leem qualquer Permission."""
        return PERMISSION_OPERATE in self.permissions or PERMISSION_ADMIN in self.permissions

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions or self.is_operator
