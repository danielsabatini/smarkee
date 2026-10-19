"""Resultado de uma observação: mapeia o Zitadel para o contrato `observed` da Organization."""

from dataclasses import dataclass
from typing import Any, Protocol

from ipm_organization.observer.domain.identity import IdentityOrganization, ProviderError

_STATE = {
    "ORGANIZATION_STATE_ACTIVE": "active",
    "ORGANIZATION_STATE_INACTIVE": "inactive",
}


class Reader(Protocol):
    """Leitura do provedor de identidade (implementada por `IdentityReader`)."""

    async def get_organization(self, organization_id: str) -> IdentityOrganization | None: ...


@dataclass(frozen=True, slots=True)
class Observation:
    presence: str
    """`present`, `absent` ou `unknown`."""

    data: dict[str, Any]


async def observe(reader: Reader, organization_id: str) -> Observation:
    """Lê a organização. Qualquer falha de leitura é `unknown`, nunca `absent`.

    `platformAccess` é `granted` quando a organização está ativa e `revoked` quando está
    desativada (`.decisions/0038`). Um estado que o contrato não conhece é inconclusivo
    (`unknown`), e não um valor inventado. Quem compara com o `desired` é o Reconciler.
    """
    try:
        organization = await reader.get_organization(organization_id)
    except ProviderError:
        return Observation("unknown", {})
    if organization is None:
        return Observation("absent", {})
    state = _STATE.get(organization.state)
    if state is None:
        return Observation("unknown", {})
    return Observation(
        "present",
        {
            "name": organization.name,
            "platformAccess": "granted" if state == "active" else "revoked",
            "organizationState": state,
        },
    )
