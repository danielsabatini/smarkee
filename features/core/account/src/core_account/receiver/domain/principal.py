"""Solicitante autenticado e as roles do projeto da plataforma (decisão 0010)."""

from dataclasses import dataclass

ACCOUNT_GET = "core.account.get"
ACCOUNT_DELETE = "core.account.delete"
ACCOUNT_ADMIN = "core.account.admin"


@dataclass(frozen=True, slots=True)
class Principal:
    """O usuário autenticado: o `sub` do token (ID do usuário) e as roles no projeto."""

    subject: str
    roles: frozenset[str]
    access_token: str

    @property
    def is_operator(self) -> bool:
        """Operadores (`core.account.admin`) agem sobre qualquer usuário (decisão 0010)."""
        return ACCOUNT_ADMIN in self.roles

    def has_role(self, role: str) -> bool:
        return role in self.roles
