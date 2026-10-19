"""Configuração do Publisher de `@@DOTTED@@` (decisões 0015 e 0019).

Ordem: variável de ambiente → default. Nome da variável:
`@@UPPER@@_PUBLISHER_<SEÇÃO>_<CAMPO>`, por exemplo
`@@UPPER@@_PUBLISHER_MESSAGING_URL`.
As senhas não têm default.
"""

from pydantic_settings import BaseSettings

from @@PACKAGE@@.common.settings import DatabaseSettings as CommonDatabaseSettings
from @@PACKAGE@@.common.settings import (
    HealthSettings,
    MessagingSettings,
    missing_variables,
    role_config,
)


class DatabaseSettings(CommonDatabaseSettings):
    user: str = "@@PACKAGE@@_publisher_login"
    """Papel de login do Publisher (lê o outbox e marca `published_at`)."""


class @@CLASS@@PublisherSettings(BaseSettings):
    model_config = role_config("publisher")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: @@CLASS@@PublisherSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "@@UPPER@@_PUBLISHER_",
        {
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
