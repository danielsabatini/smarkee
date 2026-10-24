"""Solicitante autenticado e as permissões do projeto `roles-sum` (decisões 0028 e 0033).

As permissões de um serviço seguem `sum.<serviço>.<ação>`: o segundo segmento é o serviço
(decisão 0028). A ação é `enable`, `disable` ou `get`. Não há curinga: a permissão exata é conferida.
"""

from dataclasses import dataclass

ACTION_ENABLE = "enable"
ACTION_DISABLE = "disable"
ACTION_GET = "get"


def service_permission(service: str, action: str) -> str:
    return f"sum.{service}.{action}"


@dataclass(frozen=True, slots=True)
class Principal:
    """O usuário autenticado: o `sub` do token (ID do usuário) e as permissões no projeto `roles-sum`."""

    subject: str
    permissions: frozenset[str]
    access_token: str

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions
