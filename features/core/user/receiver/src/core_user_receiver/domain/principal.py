"""Solicitante autenticado e as roles do projeto da plataforma (decisão 0010)."""

from dataclasses import dataclass

USER_GET = "user.get"
USER_DELETE = "user.delete"
PLATFORM_ADMIN = "platform.admin"


@dataclass(frozen=True, slots=True)
class Principal:
    """O usuário autenticado: o `sub` do token (ID do usuário) e as roles no projeto."""

    subject: str
    roles: frozenset[str]
    access_token: str

    @property
    def is_operator(self) -> bool:
        """Operadores (`platform.admin`) agem sobre qualquer usuário (decisão 0010)."""
        return PLATFORM_ADMIN in self.roles

    def has_role(self, role: str) -> bool:
        return role in self.roles
