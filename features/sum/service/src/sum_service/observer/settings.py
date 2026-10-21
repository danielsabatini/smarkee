"""Configuração do Observer de `sum.service` (decisões 0015 e 0033).

Nome da variável: `SUM_SERVICE_OBSERVER_<SEÇÃO>_<CAMPO>`. Sem default: identificadores do
Zitadel.
"""

from pydantic import Field, model_validator

from sum_service.common.identity import IdentitySettings as CommonIdentitySettings
from sum_service.common.settings import (
    HealthSettings,
    RoleSettings,
    Section,
    StateMessagingSettings,
    missing_variables,
    role_config,
)


class IdentitySettings(CommonIdentitySettings):
    """Zitadel do Observer: conta `sum-service-observer` (somente leitura)."""

    register_organization_id: str | None = None
    project_ids: dict[str, str] = Field(default_factory=dict)
    """Módulo → projeto de roles que o Observer lê (decisão 0032)."""


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


class SumServiceObserverSettings(RoleSettings):
    model_config = role_config("observer")

    identity: IdentitySettings = IdentitySettings()
    messaging: StateMessagingSettings = StateMessagingSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()
    partition: PartitionSettings = PartitionSettings()


def missing_required(settings: SumServiceObserverSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "SUM_SERVICE_OBSERVER_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
            "IDENTITY_REGISTER_ORGANIZATION_ID": bool(settings.identity.register_organization_id),
            "IDENTITY_PROJECT_IDS": bool(settings.identity.project_ids),
        },
    )
