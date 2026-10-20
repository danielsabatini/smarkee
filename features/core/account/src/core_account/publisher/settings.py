"""Configuração do Publisher de `core.account` (decisões 0015 e 0019).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `CORE_ACCOUNT_PUBLISHER_<SEÇÃO>_<CAMPO>`, por exemplo
`CORE_ACCOUNT_PUBLISHER_MESSAGING_URL`.
As senhas não têm default.
"""

from core_account.common.settings import (
    DatabaseSettings,
    HealthSettings,
    MessagingSettings,
    RoleSettings,
    missing_variables,
    role_config,
)


class CoreAccountPublisherSettings(RoleSettings):
    model_config = role_config("publisher")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: CoreAccountPublisherSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "CORE_ACCOUNT_PUBLISHER_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_HOST": settings.database.host is not None,
            "DATABASE_PORT": settings.database.port is not None,
            "DATABASE_NAME": settings.database.name is not None,
            "DATABASE_USER": settings.database.user is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
