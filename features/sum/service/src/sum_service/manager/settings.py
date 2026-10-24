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
    permissions: str | None = None
    """Catálogo serviço → permissões em JSON, por exemplo `{"ipm": ["ipm.organization.get"]}`.
    Sem default: o Manager não sobe sem um catálogo (decisão 0033)."""


class LoopSettings(Section):
    failure_limit: int = 5
    """Falhas por geração antes de `Failed` e da suspensão (`schemas/sum/service/desired`,
    `failureLimit`; decisão 0080)."""

    progress_deadline_seconds: int = 300
    """Prazo para a geração convergir antes de `Failed` com `ProgressDeadlineExceeded`
    (`schemas/sum/service/desired`, `progressDeadline`; decisões 0078 e 0080)."""


class SumServiceManagerSettings(RoleSettings):
    model_config = role_config("manager")

    database: DatabaseSettings = DatabaseSettings()
    messaging: MessagingSettings = MessagingSettings()
    catalog: CatalogSettings = CatalogSettings()
    loop: LoopSettings = LoopSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: SumServiceManagerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "SUM_SERVICE_MANAGER_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "DATABASE_HOST": settings.database.host is not None,
            "DATABASE_PORT": settings.database.port is not None,
            "DATABASE_NAME": settings.database.name is not None,
            "DATABASE_USER": settings.database.user is not None,
            "DATABASE_PASSWORD": settings.database.password is not None,
            "CATALOG_PERMISSIONS": bool(settings.catalog.permissions),
        },
    )
