"""Concessão e revogação das roles de um serviço no Zitadel (decisões 0032 e 0033).

`enable` garante que o usuário tem as roles pedidas em cada projeto do módulo delas. `disable`
tira só essas roles e mantém as demais (o usuário pode ter roles de outros serviços). Quando uma
autorização fica sem roles, ela é removida. Repetir qualquer um dos dois não muda nada.
Compõe os drivers de `executor/drivers/`; não chama o provedor direto.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from sum_service.executor.domain.identity import Grant


class Authorizations(Protocol):
    """Driver da autorização nos projetos de roles (`executor/drivers/authorization.py`)."""

    def project_of(self, role: str) -> str: ...
    async def grants(self, user_id: str) -> list[Grant]: ...
    async def create_grant(self, user_id: str, project_id: str, roles: list[str]) -> None: ...
    async def update_grant(self, grant_id: str, roles: list[str]) -> None: ...
    async def remove_grant(self, grant_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de escrita que as operações do serviço usam."""

    authorizations: Authorizations


def _by_project(granter: Authorizations, roles: Iterable[str]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for role in roles:
        grouped.setdefault(granter.project_of(role), set()).add(role)
    return grouped


async def enable(granter: Authorizations, user_id: str, roles: Iterable[str]) -> None:
    """O usuário passa a ter as roles, em cada projeto do módulo delas."""
    wanted_by_project = _by_project(granter, roles)
    grants = await granter.grants(user_id)
    for project_id, wanted in sorted(wanted_by_project.items()):
        current = next((grant for grant in grants if grant.project_id == project_id), None)
        if current is not None and wanted <= current.roles:
            continue
        if current is None:
            await granter.create_grant(user_id, project_id, sorted(wanted))
        else:
            await granter.update_grant(current.grant_id, sorted(current.roles | wanted))


async def disable(granter: Authorizations, user_id: str, roles: Iterable[str]) -> None:
    """Tira as roles pedidas e mantém as demais. Autorização sem roles restantes é removida."""
    unwanted_by_project = _by_project(granter, roles)
    grants = await granter.grants(user_id)
    for grant in grants:
        unwanted = unwanted_by_project.get(grant.project_id)
        if not unwanted or not (unwanted & grant.roles):
            continue
        remaining = grant.roles - unwanted
        if remaining:
            await granter.update_grant(grant.grant_id, sorted(remaining))
        else:
            await granter.remove_grant(grant.grant_id)
