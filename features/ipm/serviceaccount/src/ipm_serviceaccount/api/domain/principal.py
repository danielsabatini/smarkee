"""Solicitante autenticado e as permissões do tipo no projeto `roles-ipm` (decisões 0028 e 0094)."""

from dataclasses import dataclass

SERVICEACCOUNT_CREATE = "ipm.serviceaccount.create"
SERVICEACCOUNT_GET = "ipm.serviceaccount.get"
SERVICEACCOUNT_LIST = "ipm.serviceaccount.list"
SERVICEACCOUNT_UPDATE = "ipm.serviceaccount.update"
SERVICEACCOUNT_DELETE = "ipm.serviceaccount.delete"
SERVICEACCOUNT_BIND = "ipm.serviceaccount.bind"
"""Atribuir ou retirar permissões que o solicitante não tem (semântica do RBAC do Kubernetes)."""

SERVICEACCOUNT_ADMIN = "ipm.serviceaccount.admin"  # retrocompatibilidade transitória
SERVICEACCOUNT_OPERATE = "ipm.serviceaccount.operate"


@dataclass(frozen=True, slots=True)
class Principal:
    """O solicitante autenticado: o `sub` do token e as permissões dele no projeto."""

    subject: str
    permissions: frozenset[str]
    access_token: str

    @property
    def is_operator(self) -> bool:
        """Operadores agem em qualquer Organization e não têm cota (decisão 0031 e 0104)."""
        return (
            SERVICEACCOUNT_OPERATE in self.permissions or SERVICEACCOUNT_ADMIN in self.permissions
        )

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions
