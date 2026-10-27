"""Decisão pura de reconciliação da Organization (decisão 0096).

Compara o estado pretendido (`desired`) com o estado observado (`observed`)
e devolve a ação a executar (`create`, `update`, `delete`), ou `None` se já convergido.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ipm_organization.common import user_access as access


@dataclass(frozen=True, slots=True)
class DesiredState:
    lifecycle: str
    name: str
    platform_access: str
    deletion_protection: bool = True
    user_access: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ObservedState:
    presence: str
    name: str | None = None
    platform_access: str | None = None
    deletion_protection: bool | None = None
    user_access: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    operation: str
    reason: str
    fields: tuple[str, ...] = ()


def decide(desired: DesiredState, observed: ObservedState) -> Decision | None:
    """Função pura que compara desired e observed e determina a ação necessária."""
    if observed.presence == "unknown":
        return None

    if desired.lifecycle == "present":
        if observed.presence == "absent":
            return Decision(
                operation="create",
                reason="resource_absent",
                fields=("lifecycle",),
            )
        fields = _drift_fields(desired, observed)
        if fields:
            return Decision(
                operation="update",
                reason="drift",
                fields=fields,
            )
        return None

    if desired.lifecycle == "absent":
        if observed.presence == "present":
            return Decision(
                operation="delete",
                reason="lifecycle_absent",
                fields=("lifecycle",),
            )
        return None

    return None


def _drift_fields(desired: DesiredState, observed: ObservedState) -> tuple[str, ...]:
    fields: list[str] = []
    if observed.name != desired.name:
        fields.append("name")
    if observed.platform_access != desired.platform_access:
        fields.append("platformAccess")
    if observed.deletion_protection != desired.deletion_protection:
        fields.append("deletionProtection")
    if _user_access_differs(desired, observed):
        fields.append("userAccess")
    return tuple(fields)


def _user_access_differs(desired: DesiredState, observed: ObservedState) -> bool:
    if desired.user_access is None or desired.platform_access == "revoked":
        return False
    return not access.converged(desired.user_access, observed.user_access)
