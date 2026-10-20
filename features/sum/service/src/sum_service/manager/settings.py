"""Configuração do Manager de `sum.service` (decisões 0015, 0019 e 0033).

Precedência: CLI → ambiente → config.toml → segredos → default (`common/settings.py`).

Nome da variável: `SUM_SERVICE_MANAGER_<SEÇÃO>_<CAMPO>`, por exemplo
`SUM_SERVICE_MANAGER_MESSAGING_URL`. As senhas e o catálogo não têm default.
"""

from sum_service.common.settings import (
    DatabaseSettings,
    HealthSettings,
    MessagingSettings,
    RoleSettings,
    Section,
    missing_variables,
    role_config,
)


class CatalogSettings(Section):
    roles: str | None = None
    """Catálogo serviço → roles em JSON, por exemplo `{"ipm": ["ipm.organization.get"]}`.
    Sem default: o Manager não sobe sem um catálogo (decisão 0033)."""


class SumServiceManagerSettings(RoleSettings):
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
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_USER": settings.database.user is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
            "CATALOG_ROLES": bool(settings.catalog.roles),
        },
    )
