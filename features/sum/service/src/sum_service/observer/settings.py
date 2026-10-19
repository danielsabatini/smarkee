"""Configuração do Observer de `sum.service` (decisões 0015 e 0033).

Nome da variável: `SUM_SERVICE_OBSERVER_<SEÇÃO>_<CAMPO>`. Sem default: identificadores do
Zitadel.
"""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from sum_service.common.identity import IdentitySettings as CommonIdentitySettings
from sum_service.common.settings import (
    HealthSettings,
    Section,
    StateMessagingSettings,
    missing_variables,
)


class IdentitySettings(CommonIdentitySettings):
    """Zitadel do Observer: conta `sum-service-observer` (somente leitura)."""

    register_organization_id: str | None = None
    project_ids: dict[str, str] = Field(default_factory=dict)
    """Módulo → projeto de roles que o Observer lê (decisão 0032)."""


class CatalogSettings(Section):
    roles: str | None = None
    """Mesmo catálogo do Manager (serviço → roles), para observar só as roles de cada serviço."""


class PartitionSettings(Section):
    index: int = Field(default=0, ge=0)
    count: int = Field(default=1, ge=1)
    """Partição por `resourceId`: a instância observa só `hash mod count == index`."""

    @model_validator(mode="after")
    def _index_is_inside_the_count(self) -> PartitionSettings:
        if self.index >= self.count:
            raise ValueError("a partição (index) deve ser menor que a quantidade (count)")
        return self


class LoopSettings(Section):
    observation_interval_seconds: int = 300
    """Intervalo da observação periódica (`observationInterval` do `desired`)."""

    observation_jitter: float = 0.2
    """Fração de variação do intervalo, para as instâncias não observarem todas ao mesmo tempo."""


class SumServiceObserverSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUM_SERVICE_OBSERVER_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    zitadel: IdentitySettings = IdentitySettings()
    nats: StateMessagingSettings = StateMessagingSettings()
    catalog: CatalogSettings = CatalogSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()
    partition: PartitionSettings = PartitionSettings()


def missing_required(settings: SumServiceObserverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "SUM_SERVICE_OBSERVER_",
        {
            "NATS_PASSWORD": settings.nats.password is not None,
            "ZITADEL_REGISTER_ORGANIZATION_ID": bool(settings.zitadel.register_organization_id),
            "ZITADEL_PROJECT_IDS": bool(settings.zitadel.project_ids),
            "CATALOG_ROLES": bool(settings.catalog.roles),
        },
    )
