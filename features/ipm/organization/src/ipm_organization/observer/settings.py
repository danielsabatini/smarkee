"""Configuração do Observer de Organization (decisões 0015 e 0063).

Ordem: variável de ambiente → default. Nome da variável:
`IPM_ORGANIZATION_OBSERVER_<SEÇÃO>_<CAMPO>`, por exemplo `IPM_ORGANIZATION_OBSERVER_NATS_URL`
(`docs/SCHEMA.md` §8.3). Sem default: a senha do NATS. O Observer
não acessa o SSOT e só **lê** o Zitadel (conta `ipm-organization-observer`, somente leitura).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from ipm_organization.common.identity import IdentitySettings
from ipm_organization.common.settings import (
    HealthSettings,
    Section,
    StateMessagingSettings,
    missing_variables,
)


class PartitionSettings(Section):
    index: int = 0
    count: int = 1
    """Partição por `resourceId`: a instância observa só `hash mod count == index`."""


class LoopSettings(Section):
    observation_interval_seconds: int = 300
    """`observationInterval` (PT5M) de `schemas/ipm/organization/desired`."""

    observation_jitter: float = 0.2
    maximum_concurrent_reads: int = 4
    """Leituras simultâneas no Zitadel: limita a pressão sobre o provedor."""


class OrganizationObserverSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IPM_ORGANIZATION_OBSERVER_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    nats: StateMessagingSettings = StateMessagingSettings()
    zitadel: IdentitySettings = IdentitySettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()


def missing_required(settings: OrganizationObserverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_ORGANIZATION_OBSERVER_",
        {
            "NATS_PASSWORD": settings.nats.password is not None,
        },
    )
