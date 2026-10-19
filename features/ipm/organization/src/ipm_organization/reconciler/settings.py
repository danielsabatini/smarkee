"""Configuração do Reconciler de Organization (decisões 0015 e 0063).

Ordem: variável de ambiente → default. Nome da variável:
`IPM_ORGANIZATION_RECONCILER_<SEÇÃO>_<CAMPO>`, por exemplo `IPM_ORGANIZATION_RECONCILER_NATS_URL`
(`docs/SCHEMA.md` §8.3). A senha do NATS não tem default. O Reconciler não acessa o SSOT.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from ipm_organization.common.settings import (
    HealthSettings,
    Section,
    StateNatsSettings,
    missing_variables,
)


class LoopSettings(Section):
    """Parâmetros do loop do tipo (`x-resourceParameters` de `schemas/ipm/organization/desired`)."""

    observation_validity_seconds: int = 600
    """`observationValidity` (PT10M): idade máxima de um `observed` para decidir."""

    action_deadline_seconds: int = 120
    """`actionDeadline` (PT2M): prazo da `action` pendente e da espera pela observação causada."""

    reevaluation_interval_seconds: int = 30
    """Período da reavaliação periódica de todos os recursos (com jitter)."""

    reevaluation_jitter: float = 0.2
    failure_backoff_seconds: int = 5
    """Atraso após o primeiro `failed`; dobra a cada falha seguida, até o máximo."""

    failure_backoff_maximum_seconds: int = 300


class OrganizationReconcilerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IPM_ORGANIZATION_RECONCILER_",
        env_nested_delimiter="_",
        env_nested_max_split=1,
        extra="forbid",
    )

    nats: StateNatsSettings = StateNatsSettings()
    loop: LoopSettings = LoopSettings()
    health: HealthSettings = HealthSettings()


def missing_required(settings: OrganizationReconcilerSettings) -> list[str]:
    """Nomes das variáveis obrigatórias (sem default) que não foram informadas."""
    return missing_variables(
        "IPM_ORGANIZATION_RECONCILER_", {"NATS_PASSWORD": settings.nats.password is not None}
    )
