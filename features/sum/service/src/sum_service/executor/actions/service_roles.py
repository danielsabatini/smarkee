"""Concessão e revogação das permissões de um serviço no Zitadel (decisões 0032 e 0033).

`enable` garante que o usuário tem as permissões pedidas em cada projeto do módulo delas. `disable`
tira só essas permissões e mantém as demais (o usuário pode ter permissões de outros serviços).
Quando uma autorização fica sem permissões, ela é removida. Repetir qualquer um dos dois não muda
nada. Compõe os drivers de `executor/drivers/`; não chama o provedor direto.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from sum_service.executor.domain.identity import Grant


class Authorizations(Protocol):
    """Driver da autorização nos projetos (`executor/drivers/authorization.py`)."""

    def project_of(self, permission: str) -> str: ...
    async def grants(self, user_id: str) -> list[Grant]: ...
    async def create_grant(self, user_id: str, project_id: str, permissions: list[str]) -> None: ...
    async def update_grant(self, grant_id: str, permissions: list[str]) -> None: ...
    async def remove_grant(self, grant_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de escrita que as operações do serviço usam."""

    authorizations: Authorizations


def _by_project(granter: Authorizations, permissions: Iterable[str]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for permission in permissions:
        grouped.setdefault(granter.project_of(permission), set()).add(permission)
    return grouped


async def enable(granter: Authorizations, user_id: str, permissions: Iterable[str]) -> None:
    """O usuário passa a ter as permissões, em cada projeto do módulo delas."""
    wanted_by_project = _by_project(granter, permissions)
    grants = await granter.grants(user_id)
    for project_id, wanted in sorted(wanted_by_project.items()):
        current = next((grant for grant in grants if grant.project_id == project_id), None)
        if current is not None and wanted <= current.permissions:
            continue
        if current is None:
            await granter.create_grant(user_id, project_id, sorted(wanted))
        else:
            await granter.update_grant(current.grant_id, sorted(current.permissions | wanted))


async def disable(granter: Authorizations, user_id: str, permissions: Iterable[str]) -> None:
    """Tira as permissões pedidas e mantém as demais; remove a autorização que ficar vazia."""
    unwanted_by_project = _by_project(granter, permissions)
    grants = await granter.grants(user_id)
    for grant in grants:
        unwanted = unwanted_by_project.get(grant.project_id)
        if not unwanted or not (unwanted & grant.permissions):
            continue
        remaining = grant.permissions - unwanted
        if remaining:
            await granter.update_grant(grant.grant_id, sorted(remaining))
        else:
            await granter.remove_grant(grant.grant_id)
