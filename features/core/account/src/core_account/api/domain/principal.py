"""Solicitante autenticado e as permissões do projeto de permissões da plataforma."""

from dataclasses import dataclass

ACCOUNT_GET = "core.account.get"
ACCOUNT_DELETE = "core.account.delete"
ACCOUNT_ADMIN = "core.account.admin"


@dataclass(frozen=True, slots=True)
class Principal:
    """O usuário autenticado: o `sub` do token (ID do usuário) e as permissões no projeto."""

    subject: str
    permissions: frozenset[str]
    access_token: str

    @property
    def is_operator(self) -> bool:
        """Operadores agem em qualquer Account."""
        return ACCOUNT_ADMIN in self.permissions

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions
