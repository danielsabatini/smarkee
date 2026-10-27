"""Regras de acesso de Roles `custom` da Organization, sem I/O (decisão 0092).

- **Escopo:** o operador age em qualquer Organization; o dono dela (o root, confirmado pelo
  API da Organization) e os usuários dela (confirmados pelo API de User) agem só nela.
- **Teto:** uma Role `custom` só contém permissões delegáveis à Organization (`grantable`).
- **`bind`:** definir ou alterar as `permissions` exige `ipm.role.bind` (ou ser o dono da
  Organization / operador).
"""

from collections.abc import Iterable
from enum import StrEnum


class OrganizationAccess(StrEnum):
    """Resposta do API da Organization para o solicitante."""

    OWNED = "owned"
    """A Organization existe, não está sendo removida e o solicitante é o dono (ou operador)."""

    NOT_OWNED = "not_owned"
    """Não existe, está sendo removida ou é de outro dono."""


class AccessCheckError(Exception):
    """Algo que a API precisa confirmar nos parceiros não pôde ser confirmado.

    Na dúvida, o pedido não segue. `retryable = False` indica que o solicitante não pode fazer a
    consulta (token recusado); `True`, que o parceiro está indisponível.
    """

    def __init__(self, *, retryable: bool) -> None:
        super().__init__("access could not be verified")
        self.retryable = retryable


def permissions_changed(current: Iterable[str], requested: Iterable[str]) -> bool:
    """`True` se o conjunto de permissões pedido difere do atual."""
    return set(current) != set(requested)
