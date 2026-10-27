"""Decisão pura de reconciliação da Permission (decisões 0083 e 0096).

Compara o estado pretendido (`desired`) com o observado (`observed`) e devolve a ação a executar
(`create`, `update`, `delete`), ou `None` se já convergido ou se a observação foi inconclusiva.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DesiredState:
    lifecycle: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class ObservedState:
    presence: str
    name: str | None = None
    description: str | None = None
    group: str | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    operation: str
    reason: str
    fields: tuple[str, ...] = ()


def module_of(permission_name: str) -> str:
    """Extrai o módulo (`<módulo>`) da chave `<módulo>.<tipo>.<ação>`."""
    return permission_name.split(".", 1)[0]


def decide(desired: DesiredState, observed: ObservedState) -> Decision | None:
    """Função pura que compara desired e observed e determina a ação necessária."""
    if observed.presence == "unknown":
        return None  # observação inconclusiva nunca autoriza ação

    if desired.lifecycle == "absent":
        if observed.presence == "present":
            return Decision("delete", "lifecycle_absent", ("lifecycle",))
        return None

    if observed.presence == "absent":
        return Decision("create", "resource_absent", ("lifecycle",))
    fields = _drift_fields(desired, observed)
    if fields:
        return Decision("update", "drift", fields)
    return None


def _drift_fields(desired: DesiredState, observed: ObservedState) -> tuple[str, ...]:
    return tuple(
        field
        for field, differs in (
            ("name", observed.name != desired.name),
            ("description", observed.description != desired.description),
            ("group", observed.group != module_of(desired.name)),
        )
        if differs
    )
