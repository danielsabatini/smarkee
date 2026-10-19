"""Configuração do Reconciler de `sum.service` (decisões 0015 e 0033).

Nome da variável: `SUM_SERVICE_RECONCILER_<SEÇÃO>_<CAMPO>`. Os parâmetros do loop vêm do
contrato `desired` (`x-resourceParameters`). Só a senha do NATS não tem default.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from sum_service.common.settings import (
    HealthSettings,
    Section,
    StateNatsSettings,
    missing_variables,
)


class LoopSettings(Section):
    """Parâmetros do loop (`x-resourceParameters` do `desired`, decisão 0033)."""

    observation_interval_seconds: int = 300
    observation_validity_seconds: int = 600
    action_deadline_seconds: int = 120
    failure_limit: int = 5
    failure_backoff_seconds: int = 30
    failure_backoff_maximum_seconds: int = 600
    reevaluation_interval_seconds: int = 15
    """Período da reavaliação periódica de todos os recursos (com jitter)."""

    reevaluation_jitter: float = 0.2


class SumServiceReconcilerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUM_SERVICE_RECONCILER_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    nats: StateNatsSettings = StateNatsSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()


def missing_required(settings: SumServiceReconcilerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "SUM_SERVICE_RECONCILER_",
        {
            "NATS_PASSWORD": settings.nats.password is not None,
        },
    )
