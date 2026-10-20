"""Configuração do Reconciler de `sum.service` (decisões 0015 e 0033).

Nome da variável: `SUM_SERVICE_RECONCILER_<SEÇÃO>_<CAMPO>`. Os parâmetros do loop vêm do
contrato `desired` (`x-resourceParameters`). Só a senha do NATS não tem default.
"""

from sum_service.common.settings import (
    HealthSettings,
    RoleSettings,
    Section,
    StateMessagingSettings,
    missing_variables,
    role_config,
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


class SumServiceReconcilerSettings(RoleSettings):
    model_config = role_config("reconciler")

    messaging: StateMessagingSettings = StateMessagingSettings()
    health: HealthSettings = HealthSettings()
    loop: LoopSettings = LoopSettings()


def missing_required(settings: SumServiceReconcilerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "SUM_SERVICE_RECONCILER_",
        {
            "MESSAGING_URL": settings.messaging.url is not None,
            "MESSAGING_USER": settings.messaging.user is not None,
            "MESSAGING_PASSWORD": settings.messaging.password is not None,
        },
    )
