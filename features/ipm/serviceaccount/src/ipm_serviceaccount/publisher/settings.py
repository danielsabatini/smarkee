"""Configuração do Publisher de `ipm.serviceaccount` (decisões 0015 e 0019).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `IPM_SERVICEACCOUNT_PUBLISHER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_SERVICEACCOUNT_PUBLISHER_MESSAGING_URL`.
As senhas não têm default.
"""

from ipm_serviceaccount.common.settings import (
    DatabaseSettings,
    HealthSettings,
    MessagingSettings,
    RoleSettings,
    missing_variables,
    role_config,
)


class IpmServiceaccountPublisherSettings(RoleSettings):
    model_config = role_config("publisher")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: IpmServiceaccountPublisherSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_SERVICEACCOUNT_PUBLISHER_",
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
