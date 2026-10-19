"""Configuração do Manager de `sum.service` (decisões 0015, 0019 e 0033).

Ordem: variável de ambiente → default. Não há arquivo de configuração: o componente roda em
contêiner, e os segredos entram por variável (ou arquivo montado), nunca no código.

Nome da variável: `SUM_SERVICE_MANAGER_<SEÇÃO>_<CAMPO>`, por exemplo
`SUM_SERVICE_MANAGER_MESSAGING_URL`. As senhas e o catálogo não têm default.
"""

from pydantic_settings import BaseSettings

from sum_service.common.settings import DatabaseSettings as CommonDatabaseSettings
from sum_service.common.settings import (
    HealthSettings,
    MessagingSettings,
    Section,
    missing_variables,
    role_config,
)


class DatabaseSettings(CommonDatabaseSettings):
    user: str = "sum_service_manager_login"
    """Papel de login do Manager do tipo (`infrastructure/dev/database/bootstrap/sum.sql`)."""


class CatalogSettings(Section):
    roles: str | None = None
    """Catálogo serviço → roles em JSON, por exemplo `{"ipm": ["ipm.organization.get"]}`.
    Sem default: o Manager não sobe sem um catálogo (decisão 0033)."""


class SumServiceManagerSettings(BaseSettings):
    model_config = role_config("manager")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    catalog: CatalogSettings = CatalogSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: SumServiceManagerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "SUM_SERVICE_MANAGER_",
        {
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
            "CATALOG_ROLES": bool(settings.catalog.roles),
        },
    )
