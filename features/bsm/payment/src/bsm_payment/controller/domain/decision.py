"""Decisão pura de reconciliação do método de pagamento (`bsm.payment`, decisão 0096).

Compara o estado pretendido (`desired`) com o estado observado (`observed`)
e devolve a ação a executar (`create`, `update`, `delete`), ou `None` se já convergido.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DesiredState:
    lifecycle: str
    display_name: str
    provider: str
    method_type: str
    deletion_protection: bool = True


@dataclass(frozen=True, slots=True)
class ObservedState:
    presence: str
    display_name: str | None = None
    provider: str | None = None
    method_type: str | None = None
    status: str | None = None
    deletion_protection: bool | None = None


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
    if observed.display_name != desired.display_name:
        fields.append("displayName")
    if observed.deletion_protection != desired.deletion_protection:
        fields.append("deletionProtection")
    return tuple(fields)
