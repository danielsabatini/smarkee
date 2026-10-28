"""Decisão pura de reconciliação da ligação de serviço (decisões 0033, 0079 e 0096).

Compara o estado pretendido (`desired`) com o observado (`observed`) e devolve a ação a executar
(`enable` ou `disable`), ou `None` se já convergiu. Os campos gerenciados são as permissões que a
ligação controla (`managedPermissions`): as de `servicePermissions` precisam estar com o usuário, e
as outras (por exemplo, uma que saiu do catálogo) não podem estar. A ligação desfeita não apaga os
recursos do usuário: só revoga as permissões.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DesiredState:
    lifecycle: str
    service_permissions: frozenset[str]
    managed_permissions: frozenset[str]


@dataclass(frozen=True, slots=True)
class ObservedState:
    presence: str
    service_permissions: frozenset[str] = frozenset()
    """Permissões gerenciadas que o usuário tem hoje (já limitadas às gerenciadas)."""


@dataclass(frozen=True, slots=True)
class Decision:
    operation: str
    reason: str
    fields: tuple[str, ...] = ()
    """Campos gerenciados que divergem (só os nomes, nunca os valores): diagnóstico nos logs."""


def decide(desired: DesiredState, observed: ObservedState) -> Decision | None:
    """Função pura que compara desired e observed e determina a ação necessária."""
    if observed.presence == "unknown":
        return None  # observação inconclusiva nunca autoriza ação

    managed = desired.managed_permissions | desired.service_permissions
    if desired.lifecycle == "absent":
        if observed.presence == "present" and observed.service_permissions & managed:
            return Decision(operation="disable", reason="lifecycle_absent", fields=("lifecycle",))
        return None

    if desired.lifecycle != "present":
        return None
    if observed.presence == "absent":
        return Decision(operation="enable", reason="resource_absent", fields=("lifecycle",))
    fields = tuple(
        name
        for name, differs in (
            ("servicePermissions", not desired.service_permissions <= observed.service_permissions),
            (
                "managedPermissions",
                bool(observed.service_permissions & (managed - desired.service_permissions)),
            ),
        )
        if differs
    )
    if fields:
        return Decision(operation="enable", reason="drift", fields=fields)
    return None
