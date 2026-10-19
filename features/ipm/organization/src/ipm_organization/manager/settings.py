"""Configuração do Manager de Organization (decisões 0015, 0019 e 0063).

Ordem: variável de ambiente → default (seções comuns em `common/settings.py`).

Nome da variável: `IPM_ORGANIZATION_MANAGER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_ORGANIZATION_MANAGER_NATS_URL` (`docs/SCHEMA.md` §8.3). As senhas não têm default.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from ipm_organization.common.settings import DatabaseSettings as CommonDatabaseSettings
from ipm_organization.common.settings import (
    HealthSettings,
    NatsSettings,
    Section,
    missing_variables,
)


class DatabaseSettings(CommonDatabaseSettings):
    user: str = "ipm_organization_manager_login"
    """Papel de login do Manager do tipo (`docs/POSTGRESQL.md` §14.2)."""


class LoopSettings(Section):
    failure_limit: int = 5
    """Falhas por geração antes de `Failed` (`schemas/ipm/organization/desired`, `failureLimit`)."""


class OrganizationManagerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IPM_ORGANIZATION_MANAGER_",
        # IPM_ORGANIZATION_MANAGER_NATS_URL → nats.url: separa somente a seção do campo.
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    database: DatabaseSettings = DatabaseSettings()
    nats: NatsSettings = NatsSettings()
    loop: LoopSettings = LoopSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: OrganizationManagerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_ORGANIZATION_MANAGER_",
        {
            "NATS_PASSWORD": settings.nats.password is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
