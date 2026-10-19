"""Configuração do Publisher de `core.account` (decisões 0015 e 0019).

Ordem: variável de ambiente → default. Nome da variável:
`CORE_ACCOUNT_PUBLISHER_<SEÇÃO>_<CAMPO>`, por exemplo
`CORE_ACCOUNT_PUBLISHER_MESSAGING_URL`.
As senhas não têm default.
"""

from pydantic_settings import BaseSettings

from core_account.common.settings import DatabaseSettings as CommonDatabaseSettings
from core_account.common.settings import (
    HealthSettings,
    MessagingSettings,
    missing_variables,
    role_config,
)


class DatabaseSettings(CommonDatabaseSettings):
    user: str = "core_account_publisher_login"
    """Papel de login do Publisher (lê o outbox e marca `published_at`)."""


class CoreAccountPublisherSettings(BaseSettings):
    model_config = role_config("publisher")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: CoreAccountPublisherSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "CORE_ACCOUNT_PUBLISHER_",
        {
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
