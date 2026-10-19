"""Configuração do Publisher de Organization (decisões 0015, 0019 e 0063).

Ordem: variável de ambiente → default (seções comuns em `common/settings.py`).

Nome da variável: `IPM_ORGANIZATION_PUBLISHER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_ORGANIZATION_PUBLISHER_NATS_URL` (`docs/SCHEMA.md` §8.3). As senhas não têm default.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from ipm_organization.common.settings import DatabaseSettings as CommonDatabaseSettings
from ipm_organization.common.settings import (
    HealthSettings,
    NatsSettings,
    missing_variables,
)


class DatabaseSettings(CommonDatabaseSettings):
    user: str = "ipm_organization_publisher_login"
    """Papel de login do Publisher: lê o outbox e marca `published_at` (`POSTGRESQL.md` §14.2)."""


class OrganizationPublisherSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IPM_ORGANIZATION_PUBLISHER_",
        # IPM_ORGANIZATION_PUBLISHER_NATS_URL → nats.url: separa somente a seção do campo.
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    database: DatabaseSettings = DatabaseSettings()
    nats: NatsSettings = NatsSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: OrganizationPublisherSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_ORGANIZATION_PUBLISHER_",
        {
            "NATS_PASSWORD": settings.nats.password is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
