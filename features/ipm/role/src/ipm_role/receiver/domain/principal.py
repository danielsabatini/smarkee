"""Solicitante autenticado e as permissões do projeto da plataforma (`roles-ipm`, decisões 0083
e 0092)."""

from dataclasses import dataclass

ROLE_GET = "ipm.role.get"
ROLE_LIST = "ipm.role.list"
ROLE_CREATE = "ipm.role.create"
ROLE_UPDATE = "ipm.role.update"
ROLE_DELETE = "ipm.role.delete"
ROLE_BIND = "ipm.role.bind"
"""Definir ou alterar as permissões de uma Role (semântica do RBAC do Kubernetes)."""

ROLE_ADMIN = "ipm.role.admin"


@dataclass(frozen=True, slots=True)
class Principal:
    """O usuário autenticado: o `sub` do token (ID do usuário) e as permissões no projeto."""

    subject: str
    permissions: frozenset[str]
    access_token: str

    @property
    def is_operator(self) -> bool:
        """Operadores (`ipm.role.admin`) gerenciam qualquer Role em qualquer Organization."""
        return ROLE_ADMIN in self.permissions

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions or self.is_operator
