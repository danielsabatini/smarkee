"""Decisão pura de reconciliação da Account (decisões 0014 e 0096).

Compara o estado pretendido (`desired`) com o observado (`observed`) e devolve a ação a executar
(`create`, `update`, `delete`), ou `None` se já convergiu. Os campos gerenciados são `lifecycle`,
`platformAccess`, `platformPermissions` e `deletionProtection` (decisão 0074). As permissões
desejadas precisam estar contidas nas observadas: a mais não é divergência. Dados pessoais são
imutáveis e definidos na criação.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DesiredState:
    lifecycle: str
    platform_access: str
    platform_permissions: frozenset[str]
    deletion_protection: bool = True
    """Proteção contra exclusão desejada; sem o campo, vale protegido (decisão 0043)."""
    resend_requested_at: str | None = None


@dataclass(frozen=True, slots=True)
class ObservedState:
    presence: str
    platform_access: str | None = None
    platform_permissions: frozenset[str] = frozenset()
    deletion_protection: bool | None = None
    """Proteção lida do metadado do provedor; `None` quando ele não existe (decisão 0074)."""
    email_verified: bool = False
    last_resend_at: str | None = None



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
            ("platformAccess", observed.platform_access != desired.platform_access),
            (
                "platformPermissions",
                not desired.platform_permissions <= observed.platform_permissions,
            ),
            ("deletionProtection", observed.deletion_protection != desired.deletion_protection),
            (
                "resendRequestedAt",
                bool(
                    desired.resend_requested_at
                    and not observed.email_verified
                    and observed.last_resend_at != desired.resend_requested_at
                ),
            ),
        )
        if differs
    )
    if fields:
        return Decision(operation="update", reason="drift", fields=fields)
    return None
