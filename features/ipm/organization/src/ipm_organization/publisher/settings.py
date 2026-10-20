"""Configuração do Publisher de `ipm.organization` (decisões 0015 e 0019).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).
Nome da variável: `IPM_ORGANIZATION_PUBLISHER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_ORGANIZATION_PUBLISHER_MESSAGING_URL`.
As senhas não têm default.
"""

from ipm_organization.common.settings import DatabaseSettings as CommonDatabaseSettings
from ipm_organization.common.settings import (
    HealthSettings,
    MessagingSettings,
    RoleSettings,
    missing_variables,
    role_config,
)


class DatabaseSettings(CommonDatabaseSettings):
    user: str = "ipm_organization_publisher_login"
    """Papel de login do Publisher (lê o outbox e marca `published_at`)."""


class IpmOrganizationPublisherSettings(RoleSettings):
    model_config = role_config("publisher")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: IpmOrganizationPublisherSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_ORGANIZATION_PUBLISHER_",
        {
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
