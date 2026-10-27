"""Decisão pura de reconciliação do usuário da Organization (decisão 0096).

Compara o estado pretendido (`desired`) com o observado (`observed`) e devolve a ação a executar
(`create`, `update`, `delete`), ou `None` se já convergiu. Os campos gerenciados são `lifecycle`,
`permissions` (as efetivas, do catálogo; decisão 0097) e `deletionProtection` (decisões 0074 e
0077). Dados pessoais e Organization são imutáveis e definidos na criação.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DesiredState:
    lifecycle: str
    permissions: frozenset[str]
    deletion_protection: bool = False
    """Proteção contra exclusão desejada; sem o campo, desligada (decisão 0077)."""


@dataclass(frozen=True, slots=True)
class ObservedState:
    presence: str
    permissions: frozenset[str] = frozenset()
    deletion_protection: bool | None = None
    """Proteção lida do metadado do provedor; `None` quando ele não existe (decisão 0074)."""


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

    if desired.lifecycle == "absent":
        if observed.presence == "present":
            return Decision(operation="delete", reason="lifecycle_absent", fields=("lifecycle",))
        return None

    if desired.lifecycle != "present":
        return None
    if observed.presence == "absent":
        return Decision(operation="create", reason="resource_absent", fields=("lifecycle",))
    fields = tuple(
        name
        for name, differs in (
            ("permissions", observed.permissions != desired.permissions),
            ("deletionProtection", observed.deletion_protection != desired.deletion_protection),
        )
        if differs
    )
    if fields:
        return Decision(operation="update", reason="drift", fields=fields)
    return None
