"""Solicitante autenticado e as roles do projeto do módulo (`roles-bsm`)."""

from dataclasses import dataclass

ACCOUNT_CREATE = "bsm.account.create"
ACCOUNT_GET = "bsm.account.get"
ACCOUNT_LIST = "bsm.account.list"
ACCOUNT_UPDATE = "bsm.account.update"
ACCOUNT_DELETE = "bsm.account.delete"
ACCOUNT_ADMIN = "bsm.account.admin"


@dataclass(frozen=True, slots=True)
class Principal:
    """O usuário autenticado: o `sub` do token (ID do usuário) e as roles no projeto."""

    subject: str
    roles: frozenset[str]
    access_token: str

    @property
    def is_operator(self) -> bool:
        """Operadores agem em qualquer Billing Account."""
        return ACCOUNT_ADMIN in self.roles

    def has_role(self, role: str) -> bool:
        return role in self.roles
