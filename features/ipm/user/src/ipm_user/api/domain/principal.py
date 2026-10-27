"""Solicitante autenticado e as permissões do tipo no projeto `roles-ipm` (decisões 0028 e 0077)."""

from dataclasses import dataclass

USER_CREATE = "ipm.user.create"
USER_GET = "ipm.user.get"
USER_LIST = "ipm.user.list"
USER_UPDATE = "ipm.user.update"
USER_DELETE = "ipm.user.delete"
USER_BIND = "ipm.user.bind"
"""Atribuir ou retirar permissões que o solicitante não tem (semântica do RBAC do Kubernetes)."""

USER_ADMIN = "ipm.user.admin"


@dataclass(frozen=True, slots=True)
class Principal:
    """O usuário autenticado: o `sub` do token (ID do usuário) e as permissões no projeto."""

    subject: str
    permissions: frozenset[str]
    access_token: str

    @property
    def is_operator(self) -> bool:
        """Operadores agem em qualquer Organization e não têm cota (decisão 0031)."""
        return USER_ADMIN in self.permissions

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions
