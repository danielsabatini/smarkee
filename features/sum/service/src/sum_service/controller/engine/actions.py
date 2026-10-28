"""Execução idempotente da ligação de serviço no Zitadel (decisões 0032, 0033 e 0096).

`enable` garante que o usuário tem as permissões desejadas, em cada projeto do módulo delas, e
revoga as que a ligação controla e já não deseja. `disable` tira só as permissões que a ligação
controla e mantém as demais (o usuário pode ter permissões de outros serviços); a autorização que
ficar vazia é removida. Repetir qualquer um dos dois não muda nada. Compõe os drivers; não chama o
provedor direto.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from sum_service.controller.domain.convergence import managed_permissions, permissions_of
from sum_service.controller.drivers.authorization import AuthorizationDriver


class ActionFailedError(Exception):
    def __init__(self, reason: str, *, retryable: bool = False, message: str = "") -> None:
        super().__init__(f"{reason}: {message}" if message else reason)
        self.reason = reason
        self.retryable = retryable
        self.message = message


async def execute(
    operation: str,
    user_id: str,
    desired: Mapping[str, Any],
    *,
    authorizations: AuthorizationDriver,
) -> None:
    wanted = permissions_of(desired.get("servicePermissions"))
    managed = managed_permissions(desired) | wanted
    match operation:
        case "enable":
            await _enable(authorizations, user_id, wanted)
            await _disable(authorizations, user_id, managed - wanted)
        case "disable":
            await _disable(authorizations, user_id, managed)
        case _:
            raise ActionFailedError("Rejected", retryable=False, message="unsupported operation")


def _by_project(
    authorizations: AuthorizationDriver, permissions: Iterable[str]
) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for permission in permissions:
        grouped.setdefault(authorizations.project_of(permission), set()).add(permission)
    return grouped


async def _enable(
    authorizations: AuthorizationDriver, user_id: str, permissions: Iterable[str]
) -> None:
    """O usuário passa a ter as permissões, em cada projeto do módulo delas."""
    wanted_by_project = _by_project(authorizations, permissions)
    if not wanted_by_project:
        return
    grants = await authorizations.grants(user_id)
    for project_id, wanted in sorted(wanted_by_project.items()):
        current = next((grant for grant in grants if grant.project_id == project_id), None)
        if current is not None and wanted <= current.permissions:
            continue
        if current is None:
            await authorizations.create_grant(user_id, project_id, sorted(wanted))
        else:
            await authorizations.update_grant(
                current.grant_id, sorted(current.permissions | wanted)
            )


async def _disable(
    authorizations: AuthorizationDriver, user_id: str, permissions: Iterable[str]
) -> None:
    """Tira as permissões pedidas e mantém as demais; remove a autorização que ficar vazia."""
    unwanted_by_project = _by_project(authorizations, permissions)
    if not unwanted_by_project:
        return
    for grant in await authorizations.grants(user_id):
        unwanted = unwanted_by_project.get(grant.project_id)
        if not unwanted or not unwanted & grant.permissions:
            continue
        remaining = grant.permissions - unwanted
        if remaining:
            await authorizations.update_grant(grant.grant_id, sorted(remaining))
        else:
            await authorizations.remove_grant(grant.grant_id)
