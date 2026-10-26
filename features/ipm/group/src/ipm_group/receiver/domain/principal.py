"""Solicitante autenticado e as permissões de Grupo (`roles-ipm`, decisões 0085 e 0088)."""

from dataclasses import dataclass

GROUP_GET = "ipm.group.get"
GROUP_LIST = "ipm.group.list"
GROUP_CREATE = "ipm.group.create"
GROUP_UPDATE = "ipm.group.update"
GROUP_DELETE = "ipm.group.delete"
GROUP_BIND = "ipm.group.bind"
GROUP_ADMIN = "ipm.group.admin"


@dataclass(frozen=True, slots=True)
class Principal:
    """O usuário autenticado: o `sub` do token (ID do usuário) e as permissões no projeto."""

    subject: str
    permissions: frozenset[str]
    access_token: str

    @property
    def is_operator(self) -> bool:
        """Operadores (`ipm.group.admin`) gerenciam qualquer Grupo em qualquer Organization."""
        return GROUP_ADMIN in self.permissions

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions or self.is_operator
