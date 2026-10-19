"""Configuração do Executor de `sum.service` (decisões 0015, 0032 e 0033).

Nome da variável: `SUM_SERVICE_EXECUTOR_<SEÇÃO>_<CAMPO>`. Sem default: senhas, identificadores do
Zitadel e o catálogo.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from sum_service.common.identity import IdentitySettings as CommonIdentitySettings
from sum_service.common.settings import (
    HealthSettings,
    MessagingSettings,
    Section,
    missing_variables,
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


class SumServiceExecutorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUM_SERVICE_EXECUTOR_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    nats: MessagingSettings = MessagingSettings()
    zitadel: IdentitySettings = IdentitySettings()
    catalog: CatalogSettings = CatalogSettings()
    partition: PartitionSettings = PartitionSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: SumServiceExecutorSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "SUM_SERVICE_EXECUTOR_",
        {
            "NATS_PASSWORD": settings.nats.password is not None,
            "ZITADEL_REGISTER_ORGANIZATION_ID": bool(settings.zitadel.register_organization_id),
            "ZITADEL_PROJECT_IDS": bool(settings.zitadel.project_ids),
            "CATALOG_ROLES": bool(settings.catalog.roles),
        },
    )
