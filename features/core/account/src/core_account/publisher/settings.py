"""Configuração do Publisher de Account (decisões 0015, 0019 e 0063).

Ordem: variável de ambiente → default (seções comuns em `common/settings.py`).

Nome da variável: `CORE_ACCOUNT_PUBLISHER_<SEÇÃO>_<CAMPO>`, por exemplo
`CORE_ACCOUNT_PUBLISHER_NATS_URL` (`docs/SCHEMA.md` §8.3). As senhas não têm default.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from core_account.common.settings import DatabaseSettings as CommonDatabaseSettings
from core_account.common.settings import (
    HealthSettings,
    MessagingSettings,
    missing_variables,
)


class DatabaseSettings(CommonDatabaseSettings):
    user: str = "core_account_publisher_login"
    """Papel de login do Publisher: lê o outbox e marca `published_at` (`POSTGRESQL.md` §14.2)."""


class AccountPublisherSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CORE_ACCOUNT_PUBLISHER_",
        # CORE_ACCOUNT_PUBLISHER_NATS_URL → nats.url: separa somente a seção do campo.
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    database: DatabaseSettings = DatabaseSettings()
    nats: MessagingSettings = MessagingSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: AccountPublisherSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "CORE_ACCOUNT_PUBLISHER_",
        {
            "NATS_PASSWORD": settings.nats.password is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
