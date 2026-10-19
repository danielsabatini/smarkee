"""Configuração do Publisher de `sum.service` (decisões 0015 e 0019).

Ordem: variável de ambiente → default. Nome da variável: `SUM_SERVICE_PUBLISHER_<SEÇÃO>_<CAMPO>`,
por exemplo `SUM_SERVICE_PUBLISHER_NATS_URL`. As senhas não têm default.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from sum_service.common.settings import DatabaseSettings as CommonDatabaseSettings
from sum_service.common.settings import (
    HealthSettings,
    NatsSettings,
    missing_variables,
)


class DatabaseSettings(CommonDatabaseSettings):
    user: str = "sum_service_publisher_login"
    """Papel de login do Publisher (lê o outbox e marca `published_at`)."""


class SumServicePublisherSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUM_SERVICE_PUBLISHER_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    database: DatabaseSettings = DatabaseSettings()
    nats: NatsSettings = NatsSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: SumServicePublisherSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "SUM_SERVICE_PUBLISHER_",
        {
            "NATS_PASSWORD": settings.nats.password is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
