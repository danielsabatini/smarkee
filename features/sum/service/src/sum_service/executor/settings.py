"""Configuração do Executor de `sum.service` (decisões 0015, 0032 e 0033).

Nome da variável: `SUM_SERVICE_EXECUTOR_<SEÇÃO>_<CAMPO>`. Sem default: senhas, identificadores do
Zitadel e o catálogo.
"""

from pydantic import Field

from sum_service.common.identity import IdentitySettings as CommonIdentitySettings
from sum_service.common.settings import (
    HealthSettings,
    MessagingSettings,
    RoleSettings,
    Section,
    missing_variables,
    role_config,
)


class IdentitySettings(CommonIdentitySettings):
    """Zitadel do Executor: conta `sum-service-executor` (`PROJECT_GRANT_OWNER` em `roles-ipm`)."""

    register_organization_id: str | None = None
    project_ids: dict[str, str] = Field(default_factory=dict)
    """Módulo → projeto de roles que o Executor pode conceder (decisão 0032). Hoje só `ipm`."""

    timeout_seconds: float = 10.0


class CatalogSettings(Section):
    roles: str | None = None
    """Mesmo catálogo do Manager: as roles de um serviço, para revogar ao desligar."""


class PartitionSettings(Section):
    count: int = 4
    """Partições do Stream `ACTION` (bootstrap do messaging): um consumer e um laço por partição."""


class SumServiceExecutorSettings(RoleSettings):
    model_config = role_config("executor")

    messaging: MessagingSettings = MessagingSettings()
    identity: IdentitySettings = IdentitySettings()
    catalog: CatalogSettings = CatalogSettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: SumServiceExecutorSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "SUM_SERVICE_EXECUTOR_",
        {
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "IDENTITY_REGISTER_ORGANIZATION_ID": bool(settings.identity.register_organization_id),
            "IDENTITY_PROJECT_IDS": bool(settings.identity.project_ids),
            "CATALOG_ROLES": bool(settings.catalog.roles),
        },
    )
