"""Solicitante autenticado e as permissões do projeto do módulo (`roles-bsm`)."""

from dataclasses import dataclass

ACCOUNT_CREATE = "bsm.account.create"
ACCOUNT_GET = "bsm.account.get"
ACCOUNT_LIST = "bsm.account.list"
ACCOUNT_UPDATE = "bsm.account.update"
ACCOUNT_DELETE = "bsm.account.delete"
ACCOUNT_ADMIN = "bsm.account.admin"


@dataclass(frozen=True, slots=True)
class Principal:
    """O usuário autenticado: o `sub` do token (ID do usuário) e as permissões no projeto."""

    subject: str
    permissions: frozenset[str]
    access_token: str

    @property
    def is_operator(self) -> bool:
        """Operadores agem em qualquer Billing Account."""
        return ACCOUNT_ADMIN in self.permissions

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions
