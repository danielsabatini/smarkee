"""Configuração do Manager de Organization (decisões 0015, 0019 e 0063).

Ordem: variável de ambiente → default (seções comuns em `common/settings.py`).

Nome da variável: `IPM_ORGANIZATION_MANAGER_<SEÇÃO>_<CAMPO>`, por exemplo
`IPM_ORGANIZATION_MANAGER_MESSAGING_URL` (`docs/SCHEMA.md` §8.3). As senhas não têm default.
"""

from pydantic_settings import BaseSettings

from ipm_organization.common.settings import DatabaseSettings as CommonDatabaseSettings
from ipm_organization.common.settings import (
    HealthSettings,
    MessagingSettings,
    Section,
    missing_variables,
    role_config,
)


class DatabaseSettings(CommonDatabaseSettings):
    user: str = "ipm_organization_manager_login"
    """Papel de login do Manager do tipo (`docs/POSTGRESQL.md` §14.2)."""


class LoopSettings(Section):
    failure_limit: int = 5
    """Falhas por geração antes de `Failed` (`schemas/ipm/organization/desired`, `failureLimit`)."""


class OrganizationManagerSettings(BaseSettings):
    model_config = role_config("manager")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    loop: LoopSettings = LoopSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: OrganizationManagerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_ORGANIZATION_MANAGER_",
        {
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
        },
    )
