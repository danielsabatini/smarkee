"""Resultado de uma observação: mapeia o Zitadel para o contrato `observed` da Organization."""

from dataclasses import dataclass
from typing import Any, Protocol

from ipm_organization.observer.domain.identity import IdentityOrganization, ProviderError

_STATE = {
    "ORGANIZATION_STATE_ACTIVE": "active",
    "ORGANIZATION_STATE_INACTIVE": "inactive",
}


class Organizations(Protocol):
    """Driver de leitura da organização (`observer/drivers/organization.py`)."""

    async def get_organization(self, organization_id: str) -> IdentityOrganization | None: ...


class Metadata(Protocol):
    """Driver de leitura do metadado do provedor (`observer/drivers/metadata.py`)."""

    async def get_value(self, owner_id: str, key: str) -> str | None: ...


class UserAccess(Protocol):
    """Driver de leitura do Grant e das permissões (`observer/drivers/user_access.py`)."""

    async def grant_permissions(self, organization_id: str) -> list[str] | None: ...

    async def administrators(
        self, organization_id: str, *, with_grant: bool
    ) -> dict[str, frozenset[str]]: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de leitura que a observação usa: espelho dos drivers de escrita do Executor."""

    organizations: Organizations
    metadata: Metadata
    user_access: UserAccess


@dataclass(frozen=True, slots=True)
class Observation:
    presence: str
    """`present`, `absent` ou `unknown`."""

    data: dict[str, Any]


async def observe(drivers: Drivers, organization_id: str) -> Observation:
    """Lê a organização. Qualquer falha de leitura é `unknown`, nunca `absent`.

    `platformAccess` é `granted` quando a organização está ativa e `revoked` quando está
    desativada (`.decisions/0038`). Um estado que o contrato não conhece é inconclusivo
    (`unknown`), e não um valor inventado. Quem compara com o `desired` é o Reconciler.
    """
    try:
        organization = await drivers.organizations.get_organization(organization_id)
        if organization is None:
            return Observation("absent", {})
        protection = await drivers.metadata.get_value(organization_id, DELETION_PROTECTION_KEY)
        user_access = await observe_user_access(drivers.user_access, organization_id)
    except ProviderError:
        return Observation("unknown", {})
    state = _STATE.get(organization.state)
    if state is None:
        return Observation("unknown", {})
    return Observation(
        "present",
        {
            "name": organization.name,
            "platformAccess": "granted" if state == "active" else "revoked",
            "organizationState": state,
            **deletion_protection(protection),
            "userAccess": user_access,
        },
    )


async def observe_user_access(driver: UserAccess, organization_id: str) -> dict[str, Any]:
    """O Project Grant e as permissões de administração, no formato do `observed` (decisão 0081).

    Sem Grant, `grantPermissions` fica fora (ausente ≠ vazio) e só as permissões na organização
    são lidas.
    """
    permissions = await driver.grant_permissions(organization_id)
    held = await driver.administrators(organization_id, with_grant=permissions is not None)
    observed: dict[str, Any] = {
        "administrators": [
            {"accountId": account, "permissions": sorted(held[account])} for account in sorted(held)
        ]
    }
    if permissions is not None:
        observed["grantPermissions"] = permissions
    return observed


DELETION_PROTECTION_KEY = "deletionProtection"
_PROTECTION = {"true": True, "false": False}


def deletion_protection(value: str | None) -> dict[str, bool]:
    """O campo `deletionProtection` do `observed`, a partir do metadado (decisão 0074).

    Metadado ausente ou com outro valor fica fora do `observed`: o Reconciler o vê como divergência
    e o Executor o regrava. Não se inventa um valor que o provedor não tem.
    """
    protected = _PROTECTION.get(value or "")
    return {} if protected is None else {"deletionProtection": protected}


def log_identifiers(resource_id: str) -> dict[str, str]:
    """Identificadores de negócio extras nos logs de cada observação (decisão 0061).

    Gancho que o motor do Observer (template, perfil `loop-engines`) chama. O recurso é a própria
    Organization: o `resourceId` é também o `organization_id`.
    """
    return {"organization_id": resource_id}
