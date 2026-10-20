"""Configuração do Publisher de `sum.service` (decisões 0015 e 0019).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `SUM_SERVICE_PUBLISHER_<SEÇÃO>_<CAMPO>`, por exemplo
`SUM_SERVICE_PUBLISHER_MESSAGING_URL`.
As senhas não têm default.
"""

from sum_service.common.settings import DatabaseSettings as CommonDatabaseSettings
from sum_service.common.settings import (
    HealthSettings,
    MessagingSettings,
    RoleSettings,
    missing_variables,
    role_config,
)


class DatabaseSettings(CommonDatabaseSettings):
    user: str = "sum_service_publisher_login"
    """Papel de login do Publisher (lê o outbox e marca `published_at`)."""


class SumServicePublisherSettings(RoleSettings):
    model_config = role_config("publisher")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: SumServicePublisherSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "SUM_SERVICE_PUBLISHER_",
        {
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
