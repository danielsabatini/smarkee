"""Solicitante autenticado e as roles do projeto da plataforma (decisão 0010)."""

from dataclasses import dataclass

USER_GET = "core.user.get"
USER_DELETE = "core.user.delete"
USER_ADMIN = "core.user.admin"


@dataclass(frozen=True, slots=True)
class Principal:
    """O usuário autenticado: o `sub` do token (ID do usuário) e as roles no projeto."""

    subject: str
    roles: frozenset[str]
    access_token: str

    @property
    def is_operator(self) -> bool:
        """Operadores (`core.user.admin`) agem sobre qualquer usuário (decisão 0010)."""
        return USER_ADMIN in self.roles

    def has_role(self, role: str) -> bool:
        return role in self.roles
